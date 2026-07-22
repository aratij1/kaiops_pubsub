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
from common.message_processing import ProcessedMessageCache, extract_message_identity

logger = get_logger(__name__)


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
        self._channel: RobustChannel | None = None
        self._exchange: RobustExchange | None = None

    async def start(self) -> None:
        if self._connection is not None:
            return
        attempts = max(1, int(self._settings.rabbitmq_startup_attempts or 1))
        retry_seconds = max(0.1, float(self._settings.rabbitmq_startup_retry_seconds or 0.1))
        for attempt in range(1, attempts + 1):
            try:
                self._connection = await aio_pika.connect_robust(self._settings.rabbitmq_url)
                self._channel = await self._connection.channel()
                self._exchange = await self._channel.declare_exchange(
                    self._settings.rabbitmq_exchange,
                    ExchangeType.TOPIC,
                    durable=True,
                )
                logger.info(
                    "connected rabbitmq producer",
                    extra={"url": self._settings.rabbitmq_url, "exchange": self._settings.rabbitmq_exchange},
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
        self._channel = None
        self._exchange = None

    async def publish(self, topic: str, event: dict[str, Any] | Any, key: str | None = None) -> None:
        if self._exchange is None:
            logger.info("rabbitmq producer unavailable; event logged", extra={"topic": topic, "payload": normalize_payload(event)})
            return
        payload = normalize_payload(event)
        envelope = {
            "topic": topic,
            "key": key,
            "payload": payload,
        }
        body = json.dumps(envelope, default=str).encode("utf-8")
        routing_key = topic
        await self._exchange.publish(
            Message(
                body,
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                type=topic,
                app_id="kaiops",
            ),
            routing_key=routing_key,
        )


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
                self._exchange = await self._channel.declare_exchange(
                    self._settings.rabbitmq_exchange,
                    ExchangeType.TOPIC,
                    durable=True,
                )
                queue_name = f"{self._settings.rabbitmq_queue_prefix}.{self._settings.service_name}.{self._topic}"
                self._queue = await self._channel.declare_queue(queue_name, durable=True)
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
                    if processed_cache.contains(identity):
                        logger.info("skipping duplicate rabbitmq message", extra={"topic": consumer._topic, "message_identity": identity})
                        await message.ack()
                        continue

                    attempts = 0
                    max_retries = max(0, int(consumer._settings.rabbitmq_consumer_max_retries or 0))
                    success = False
                    dlq_published = False

                    last_error = ""
                    while attempts <= max_retries:
                        try:
                            await handler(payload)
                            success = True
                            processed_cache.mark(identity)
                            break
                        except Exception as exc:
                            last_error = str(exc) or exc.__class__.__name__
                            attempts += 1
                            if attempts > max_retries:
                                break
                            await asyncio.sleep(min(2**attempts, 5))

                    if success:
                        await message.ack()
                        continue

                    logger.error(
                        "failed to process rabbitmq message",
                        extra={
                            "topic": consumer._topic,
                            "attempts": attempts,
                            "max_retries": max_retries,
                            "error": last_error,
                            "message_identity": identity,
                        },
                    )
                    if consumer._exchange is not None and consumer._dlq_routing_key:
                        try:
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
