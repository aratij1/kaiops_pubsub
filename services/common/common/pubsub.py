from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from common.config import Settings
from common.logging import get_logger
from common.resilience import retry_async

logger = get_logger(__name__)


def normalize_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: normalize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_payload(item) for item in value]
    return value


def _full_topic_name(settings: Settings, topic: str) -> str:
    prefix = str(settings.gcp_pubsub_topic_prefix or "kaiops").strip() or "kaiops"
    return f"{prefix}-{topic}".replace("_", "-")


class PubSubProducer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._project_id = str(settings.gcp_project_id or "").strip()
        self._client: Any | None = None

    async def start(self) -> None:
        if not self._settings.gcp_pubsub_enabled or not self._project_id:
            return
        from google.cloud import pubsub_v1

        self._client = pubsub_v1.PublisherClient()
        logger.info("connected pubsub producer", extra={"project": self._project_id})

    async def stop(self) -> None:
        self._client = None

    async def publish(self, topic: str, event: Any, key: str | None = None) -> None:
        payload = normalize_payload(event)
        if self._client is None:
            logger.info("pubsub producer unavailable; event logged", extra={"topic": topic, "payload": payload})
            return

        topic_path = self._client.topic_path(self._project_id, _full_topic_name(self._settings, topic))
        data = json.dumps(payload, default=str).encode("utf-8")

        async def send() -> None:
            def send_sync() -> None:
                kwargs: dict[str, Any] = {"ordering_key": key} if key else {}
                future = self._client.publish(topic_path, data=data, **kwargs)
                future.result(timeout=10)

            await asyncio.to_thread(send_sync)

        await retry_async(send)


class PubSubConsumer:
    def __init__(self, settings: Settings, topic: str) -> None:
        self._settings = settings
        self._topic = topic
        self._project_id = str(settings.gcp_project_id or "").strip()
        self._publisher_client: Any | None = None
        self._subscriber_client: Any | None = None
        self._subscription_path: str | None = None
        self._dlq_topic_path: str | None = None

    async def start(self) -> None:
        if not self._settings.gcp_pubsub_enabled or not self._project_id:
            return
        from google.api_core.exceptions import AlreadyExists
        from google.cloud import pubsub_v1

        last_error: Exception | None = None
        for attempt in range(1, self._settings.gcp_pubsub_startup_attempts + 1):
            publisher_client = pubsub_v1.PublisherClient()
            subscriber_client = pubsub_v1.SubscriberClient()
            topic_name = _full_topic_name(self._settings, self._topic)
            topic_path = publisher_client.topic_path(self._project_id, topic_name)
            dlq_topic_name = f"{topic_name}{self._settings.gcp_pubsub_dlq_suffix}"
            dlq_topic_path = publisher_client.topic_path(self._project_id, dlq_topic_name)
            subscription_name = f"{self._settings.gcp_pubsub_subscription_prefix}-{self._settings.service_name}-{topic_name}"
            subscription_path = subscriber_client.subscription_path(self._project_id, subscription_name)

            def ensure_resources() -> None:
                for path in (topic_path, dlq_topic_path):
                    try:
                        publisher_client.create_topic(request={"name": path})
                    except AlreadyExists:
                        pass
                try:
                    subscriber_client.create_subscription(request={"name": subscription_path, "topic": topic_path})
                except AlreadyExists:
                    pass

            try:
                await asyncio.to_thread(ensure_resources)
                self._publisher_client = publisher_client
                self._subscriber_client = subscriber_client
                self._subscription_path = subscription_path
                self._dlq_topic_path = dlq_topic_path
                logger.info(
                    "connected pubsub consumer",
                    extra={"topic": self._topic, "subscription": subscription_name},
                )
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "pubsub consumer not ready; retrying",
                    extra={
                        "topic": self._topic,
                        "attempt": attempt,
                        "attempts": self._settings.gcp_pubsub_startup_attempts,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(self._settings.gcp_pubsub_startup_retry_seconds)
        assert last_error is not None
        raise last_error

    async def stop(self) -> None:
        self._publisher_client = None
        self._subscriber_client = None
        self._subscription_path = None
        self._dlq_topic_path = None

    async def pull(self, max_messages: int | None = None) -> list[Any]:
        if self._subscriber_client is None or self._subscription_path is None:
            return []

        def pull_sync() -> list[Any]:
            response = self._subscriber_client.pull(
                request={
                    "subscription": self._subscription_path,
                    "max_messages": max_messages or self._settings.gcp_pubsub_pull_max_messages,
                },
                timeout=30,
            )
            return list(response.received_messages)

        return await asyncio.to_thread(pull_sync)

    async def ack(self, ack_ids: list[str]) -> None:
        if self._subscriber_client is None or self._subscription_path is None or not ack_ids:
            return

        def ack_sync() -> None:
            self._subscriber_client.acknowledge(request={"subscription": self._subscription_path, "ack_ids": ack_ids})

        await asyncio.to_thread(ack_sync)

    async def publish_dlq(self, envelope: dict[str, Any]) -> None:
        if self._publisher_client is None or self._dlq_topic_path is None:
            return
        data = json.dumps(envelope, default=str).encode("utf-8")

        def publish_sync() -> None:
            future = self._publisher_client.publish(self._dlq_topic_path, data=data)
            future.result(timeout=10)

        await asyncio.to_thread(publish_sync)

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        if self._subscriber_client is None:
            while True:
                await asyncio.sleep(3600)
        else:
            while True:
                received = await self.pull()
                if not received:
                    await asyncio.sleep(1)
                    continue
                ack_ids = []
                for message in received:
                    ack_ids.append(message.ack_id)
                    try:
                        payload = json.loads(message.message.data.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if isinstance(payload, dict):
                        yield payload
                await self.ack(ack_ids)


async def consume_forever(
    consumer: PubSubConsumer,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    await consumer.start()
    if consumer._subscriber_client is None:
        while True:
            await asyncio.sleep(3600)

    try:
        while True:
            received = await consumer.pull()
            if not received:
                await asyncio.sleep(1)
                continue

            ack_ids: list[str] = []
            for message in received:
                ack_ids.append(message.ack_id)
                try:
                    payload = json.loads(message.message.data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.warning("failed to decode pubsub message", extra={"topic": consumer._topic})
                    continue
                if not isinstance(payload, dict):
                    continue

                attempts = 0
                max_retries = max(0, int(consumer._settings.gcp_pubsub_consumer_max_retries or 0))
                success = False
                while attempts <= max_retries:
                    try:
                        await handler(payload)
                        success = True
                        break
                    except Exception:
                        attempts += 1
                        if attempts > max_retries:
                            break
                        await asyncio.sleep(min(2**attempts, 5))

                if not success:
                    logger.error(
                        "failed to process pubsub message",
                        extra={"topic": consumer._topic, "attempts": attempts, "max_retries": max_retries},
                    )
                    try:
                        await consumer.publish_dlq(
                            {
                                "failed_topic": consumer._topic,
                                "payload": payload,
                                "error": "handler_failed",
                                "attempts": attempts,
                                "failed_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    except Exception:
                        logger.exception("failed to publish pubsub dlq message", extra={"topic": consumer._topic})

            await consumer.ack(ack_ids)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("pubsub consumer loop crashed", extra={"topic": consumer._topic})
        raise
