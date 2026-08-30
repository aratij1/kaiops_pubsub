from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message, RobustChannel, RobustConnection, RobustExchange, RobustQueue

from common.config import Settings
from common.logging import get_logger
from common.message_processing import ProcessedMessageCache, extract_message_identity, processing_cancelled
from common.resilience import CircuitBreaker, CircuitOpenError
from common.telemetry import DEAD_LETTER_EVENTS, QUEUE_AGE, QUEUE_DEPTH
from opentelemetry import propagate, trace

logger = get_logger(__name__)

# aio_pika's RobustConnection/RobustExchange retry a broken broker connection
# internally rather than raising promptly, so a publish() call can stall for a
# long time during an outage instead of failing fast. Bound each publish
# attempt and count timeouts/errors toward the breaker so a sustained outage
# fails new publishes immediately instead of piling up stalled callers.
_PUBLISH_TIMEOUT_SECONDS = 10.0


def _is_transient_handler_error(error: str) -> bool:
    normalized = str(error or "").strip().lower()
    return any(
        marker in normalized
        for marker in (
            "can't connect to mysql server",
            "connection refused",
            "connection reset",
            "connection timed out",
            "temporary failure in name resolution",
            "name or service not known",
            "server has gone away",
            "lost connection to mysql",
            "circuit breaker open",
            "tool circuit open",
            "timeout",
            "timed out",
        )
    )


def normalize_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: normalize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_payload(item) for item in value]
    return value


class RabbitMQProducer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: RobustConnection | None = None
        self._channels: list[RobustChannel] = []
        self._exchanges: list[RobustExchange] = []
        self._next_exchange_index = 0
        self._publish_breaker = CircuitBreaker()

    async def start(self) -> None:
        if self._connection is not None:
            return
        attempts = max(1, int(self._settings.rabbitmq_startup_attempts or 1))
        retry_seconds = max(0.1, float(self._settings.rabbitmq_startup_retry_seconds or 0.1))
        pool_size = max(1, int(self._settings.rabbitmq_publisher_channel_pool_size or 1))
        for attempt in range(1, attempts + 1):
            try:
                self._connection = await aio_pika.connect_robust(self._settings.rabbitmq_url)
                for _ in range(pool_size):
                    channel = await self._connection.channel()
                    exchange = await channel.declare_exchange(
                        self._settings.rabbitmq_exchange,
                        ExchangeType.TOPIC,
                        durable=True,
                    )
                    self._channels.append(channel)
                    self._exchanges.append(exchange)
                logger.info(
                    "connected rabbitmq producer",
                    extra={
                        "url": self._settings.rabbitmq_url,
                        "exchange": self._settings.rabbitmq_exchange,
                        "channel_pool_size": pool_size,
                    },
                )
                return
            except Exception:
                await self.stop()
                logger.warning(
                    "rabbitmq producer connect retry",
                    extra={
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "retry_seconds": retry_seconds,
                    },
                    exc_info=True,
                )
                if attempt < attempts:
                    await asyncio.sleep(retry_seconds)
        raise RuntimeError("rabbitmq producer failed to connect after retries")

    async def stop(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._channels = []
        self._exchanges = []
        self._next_exchange_index = 0

    def _next_exchange(self) -> RobustExchange:
        # Plain round-robin: a single int increment between awaits is not
        # preemptible in one asyncio event loop, so no lock is needed here.
        exchange = self._exchanges[self._next_exchange_index % len(self._exchanges)]
        self._next_exchange_index += 1
        return exchange

    async def publish(self, topic: str, event: dict[str, Any] | Any, key: str | None = None) -> None:
        if not self._exchanges:
            logger.info("rabbitmq producer unavailable; event logged", extra={"topic": topic, "payload": normalize_payload(event)})
            return
        if not self._publish_breaker.allow():
            raise CircuitOpenError("rabbitmq publish circuit breaker open: broker appears unreachable")
        payload = normalize_payload(event)
        envelope = {
            "topic": topic,
            "key": key,
            "payload": payload,
            "produced_at": datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps(envelope, default=str).encode("utf-8")
        routing_key = topic
        trace_headers: dict[str, str] = {}
        propagate.inject(trace_headers)
        try:
            await asyncio.wait_for(
                self._next_exchange().publish(
                    Message(
                        body,
                        content_type="application/json",
                        delivery_mode=DeliveryMode.PERSISTENT,
                        type=topic,
                        app_id="kaiops",
                        headers=trace_headers,
                    ),
                    routing_key=routing_key,
                ),
                timeout=_PUBLISH_TIMEOUT_SECONDS,
            )
        except Exception:
            self._publish_breaker.record_failure()
            raise
        else:
            self._publish_breaker.record_success()


class RabbitMQConsumer:
    def __init__(self, settings: Settings, topic: str) -> None:
        self._settings = settings
        self._topic = topic
        self._connection: RobustConnection | None = None
        self._channel: RobustChannel | None = None
        self._exchange: RobustExchange | None = None
        self._queue: RobustQueue | None = None
        self._dlq_routing_key: str | None = None

    async def start(self) -> None:
        if self._connection is not None:
            return
        attempts = max(1, int(self._settings.rabbitmq_startup_attempts or 1))
        retry_seconds = max(0.1, float(self._settings.rabbitmq_startup_retry_seconds or 0.1))
        for attempt in range(1, attempts + 1):
            try:
                self._connection = await aio_pika.connect_robust(self._settings.rabbitmq_url)
                self._channel = await self._connection.channel()
                # Bound how many unacked messages the broker will push to this
                # consumer at once. Without this, a channel drop mid-backlog can
                # leave thousands of delivered-but-unacked messages that all fail
                # to nack together (a single ExceptionGroup with one sub-exception
                # per message), and total in-flight work per consumer is otherwise
                # unbounded.
                await self._channel.set_qos(prefetch_count=self._settings.rabbitmq_consumer_prefetch_count)
                self._exchange = await self._channel.declare_exchange(
                    self._settings.rabbitmq_exchange,
                    ExchangeType.TOPIC,
                    durable=True,
                )
                queue_name = f"{self._settings.rabbitmq_queue_prefix}.{self._settings.service_name}.{self._topic}"
                self._queue = await self._channel.declare_queue(queue_name, durable=True)
                declaration = getattr(self._queue, "declaration_result", None)
                if declaration is not None:
                    QUEUE_DEPTH.labels("rabbitmq", queue_name).set(float(getattr(declaration, "message_count", 0) or 0))
                await self._queue.bind(self._exchange, routing_key=self._topic)
                self._dlq_routing_key = f"{self._topic}{self._settings.rabbitmq_dlq_suffix}"
                dlq_queue_name = f"{queue_name}.dlq"
                dlq_queue = await self._channel.declare_queue(dlq_queue_name, durable=True)
                await dlq_queue.bind(self._exchange, routing_key=self._dlq_routing_key)
                logger.info(
                    "connected rabbitmq consumer",
                    extra={
                        "topic": self._topic,
                        "queue": queue_name,
                        "dlq_queue": dlq_queue_name,
                        "exchange": self._settings.rabbitmq_exchange,
                    },
                )
                return
            except Exception:
                await self.stop()
                logger.warning(
                    "rabbitmq consumer connect retry",
                    extra={
                        "topic": self._topic,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "retry_seconds": retry_seconds,
                    },
                    exc_info=True,
                )
                if attempt < attempts:
                    await asyncio.sleep(retry_seconds)
        raise RuntimeError(f"rabbitmq consumer failed to connect after retries for topic {self._topic}")

    async def stop(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._exchange = None
        self._queue = None
        self._dlq_routing_key = None

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        if self._queue is None:
            while True:
                await asyncio.sleep(3600)
        else:
            async with self._queue.iterator() as iterator:
                async for message in iterator:
                    async with message.process(requeue=False):
                        try:
                            decoded = json.loads(message.body.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            logger.warning("failed to decode rabbitmq message", extra={"topic": self._topic})
                            continue
                        payload = decoded.get("payload") if isinstance(decoded, dict) else None
                        if isinstance(payload, dict):
                            yield payload


async def consume_forever(
    consumer: RabbitMQConsumer,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
    failure_handler: Callable[[dict[str, Any], str], Awaitable[None]] | None = None,
) -> None:
    processed_cache = ProcessedMessageCache()
    while True:
        try:
            await consumer.start()
            if consumer._queue is None:
                await asyncio.sleep(1)
                continue

            async with consumer._queue.iterator() as iterator:
                async for message in iterator:
                    try:
                        decoded = json.loads(message.body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        logger.warning("failed to decode rabbitmq message", extra={"topic": consumer._topic})
                        await message.ack()
                        continue

                    payload = decoded.get("payload") if isinstance(decoded, dict) else None
                    if not isinstance(payload, dict):
                        await message.ack()
                        continue

                    identity = extract_message_identity(payload)
                    if await processing_cancelled(consumer._settings, payload):
                        logger.warning("cancelled alert removed from rabbitmq processing", extra={"topic": consumer._topic, "message_identity": identity})
                        await message.ack()
                        continue
                    if processed_cache.contains(identity):
                        logger.info("skipping duplicate rabbitmq message", extra={"topic": consumer._topic, "message_identity": identity})
                        await message.ack()
                        continue

                    attempts = 0
                    max_retries = max(0, int(consumer._settings.rabbitmq_consumer_max_retries or 0))
                    success = False
                    dlq_published = False

                    last_error = ""
                    produced_at = decoded.get("produced_at") if isinstance(decoded, dict) else None
                    if produced_at:
                        try:
                            produced = datetime.fromisoformat(str(produced_at).replace("Z", "+00:00"))
                            QUEUE_AGE.labels("rabbitmq", consumer._topic).observe(max(0.0, (datetime.now(timezone.utc) - produced).total_seconds()))
                        except (TypeError, ValueError):
                            pass
                    parent_context = propagate.extract(dict(getattr(message, "headers", None) or {}))
                    while attempts <= max_retries:
                        try:
                            with trace.get_tracer("kaiops.rabbitmq").start_as_current_span("rabbitmq.consume", context=parent_context) as span:
                                span.set_attribute("messaging.system", "rabbitmq")
                                span.set_attribute("messaging.destination.name", consumer._topic)
                                await asyncio.wait_for(handler(payload), timeout=consumer._settings.rabbitmq_handler_timeout_seconds)
                            success = True
                            processed_cache.mark(identity)
                            break
                        except Exception as exc:
                            # Includes asyncio.TimeoutError: without a bound here a
                            # single hung downstream call could block this consumer
                            # (and its whole prefetch batch) indefinitely.
                            last_error = str(exc) or exc.__class__.__name__
                            attempts += 1
                            if attempts > max_retries:
                                break
                            await asyncio.sleep(min(2**attempts, 5))

                    if success:
                        await message.ack()
                        continue

                    logger.error(
                        "failed to process rabbitmq message: topic=%s identity=%s attempts=%s error=%s",
                        consumer._topic,
                        identity,
                        attempts,
                        last_error,
                        extra={
                            "topic": consumer._topic,
                            "attempts": attempts,
                            "max_retries": max_retries,
                            "error": last_error,
                            "message_identity": identity,
                        },
                    )
                    if (
                        consumer._settings.rabbitmq_transient_requeue_enabled
                        and _is_transient_handler_error(last_error)
                    ):
                        logger.warning(
                            "requeueing rabbitmq message after transient dependency failure: topic=%s identity=%s error=%s",
                            consumer._topic,
                            identity,
                            last_error,
                        )
                        await asyncio.sleep(min(5.0, max(1.0, float(attempts))))
                        await message.nack(requeue=True)
                        continue
                    if consumer._exchange is not None and consumer._dlq_routing_key:
                        try:
                            if failure_handler is not None:
                                try:
                                    await failure_handler(payload, last_error or "handler_failed")
                                except Exception:
                                    logger.exception(
                                        "failed to persist rabbitmq terminal handler state",
                                        extra={"topic": consumer._topic, "message_identity": identity},
                                    )
                            envelope = {
                                "failed_topic": consumer._topic,
                                "payload": payload,
                                "error": last_error or "handler_failed",
                                "attempts": attempts,
                                "failed_at": datetime.now(timezone.utc).isoformat(),
                            }
                            await consumer._exchange.publish(
                                Message(
                                    json.dumps(envelope, default=str).encode("utf-8"),
                                    content_type="application/json",
                                    delivery_mode=DeliveryMode.PERSISTENT,
                                    type=consumer._dlq_routing_key,
                                    app_id="kaiops",
                                ),
                                routing_key=consumer._dlq_routing_key,
                            )
                            processed_cache.mark(identity)
                            dlq_published = True
                            DEAD_LETTER_EVENTS.labels("rabbitmq", consumer._topic, "handler_failed").inc()
                        except Exception:
                            logger.exception(
                                "failed to publish rabbitmq dlq message",
                                extra={"topic": consumer._topic, "dlq": consumer._dlq_routing_key},
                            )
                    if dlq_published:
                        await message.ack()
                        continue

                    await message.nack(requeue=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("rabbitmq consumer loop crashed; restarting", extra={"topic": consumer._topic})
            try:
                await consumer.stop()
            except Exception:
                logger.exception("rabbitmq consumer stop failed", extra={"topic": consumer._topic})
            await asyncio.sleep(1)
