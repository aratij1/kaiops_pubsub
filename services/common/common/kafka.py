from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic import BaseModel

from common.config import Settings
from common.logging import get_logger
from common.resilience import retry_async

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


def normalize_payload(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: normalize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_payload(item) for item in value]
    return value


class KafkaProducer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        if not self._settings.kafka_enabled:
            return
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            value_serializer=lambda value: json.dumps(value, default=str).encode("utf-8"),
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def publish(self, topic: str, event: BaseModel | dict[str, Any], key: str | None = None) -> None:
        payload = normalize_payload(event)
        if self._producer is None:
            logger.info("kafka disabled; event logged", extra={"topic": topic, "payload": payload})
            return

        async def send() -> None:
            assert self._producer is not None
            await self._producer.send_and_wait(topic, payload, key=key.encode("utf-8") if key else None)

        await retry_async(send)


class KafkaConsumer:
    def __init__(self, settings: Settings, topic: str) -> None:
        self._settings = settings
        self._topic = topic
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self) -> None:
        if not self._settings.kafka_enabled:
            return
        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=self._settings.kafka_group_id,
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
            enable_auto_commit=True,
        )
        await self._consumer.start()

    async def stop(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        if self._consumer is None:
            while True:
                await asyncio.sleep(3600)
        else:
            async for message in self._consumer:
                yield message.value


async def consume_forever(
    consumer: KafkaConsumer,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    await consumer.start()
    async for message in consumer.messages():
        try:
            await handler(message)
        except Exception:
            logger.exception("failed to process kafka message", extra={"topic": consumer._topic})
