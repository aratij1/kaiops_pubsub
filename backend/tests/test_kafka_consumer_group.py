"""Every service used to share the literal Kafka consumer group id "kaiops"
(common/config.py's kafka_group_id default), so any one service's consumer
joining/leaving triggered a group-wide rebalance for every other service,
regardless of which topic they actually cared about (confirmed live: a
consumer group stuck cycling through 12+ generations within an hour, ending
up with zero partitions assigned most of the time). group_id now isolates
each (service_name, topic) pair, mirroring RabbitMQ's existing
`{prefix}.{service_name}.{topic}` queue-naming convention.
"""

from __future__ import annotations

from typing import Any

import pytest

from common.config import Settings
from common.kafka import KafkaConsumer


class _FakeAIOKafkaConsumer:
    last_kwargs: dict[str, Any] | None = None

    def __init__(self, *topics: str, **kwargs: Any) -> None:
        self.topics = topics
        self.kwargs = kwargs
        _FakeAIOKafkaConsumer.last_kwargs = kwargs

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_aiokafka_consumer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("common.kafka.AIOKafkaConsumer", _FakeAIOKafkaConsumer)
    yield


async def test_group_id_is_isolated_per_service_and_topic() -> None:
    settings_a = Settings(SERVICE_NAME="alert-intelligence")
    consumer_a = KafkaConsumer(settings_a, "raw-alerts")
    await consumer_a.start()
    group_id_a = _FakeAIOKafkaConsumer.last_kwargs["group_id"]

    settings_b = Settings(SERVICE_NAME="orchestrator")
    consumer_b = KafkaConsumer(settings_b, "enriched-alerts")
    await consumer_b.start()
    group_id_b = _FakeAIOKafkaConsumer.last_kwargs["group_id"]

    assert group_id_a != group_id_b
    assert group_id_a == "kaiops.alert-intelligence.raw-alerts"
    assert group_id_b == "kaiops.orchestrator.enriched-alerts"


async def test_group_id_preserves_configured_prefix() -> None:
    settings = Settings(SERVICE_NAME="notification-service", KAFKA_GROUP_ID="custom-prefix")
    consumer = KafkaConsumer(settings, "resolution-events")
    await consumer.start()

    assert _FakeAIOKafkaConsumer.last_kwargs["group_id"] == "custom-prefix.notification-service.resolution-events"


async def test_same_service_different_topics_get_different_groups() -> None:
    settings = Settings(SERVICE_NAME="notification-service")

    await KafkaConsumer(settings, "raw-alerts").start()
    group_raw = _FakeAIOKafkaConsumer.last_kwargs["group_id"]

    await KafkaConsumer(settings, "resolution-events").start()
    group_resolution = _FakeAIOKafkaConsumer.last_kwargs["group_id"]

    assert group_raw != group_resolution
