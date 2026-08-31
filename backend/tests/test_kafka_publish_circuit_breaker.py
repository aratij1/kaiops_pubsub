"""KafkaProducer.publish already retries a transient send failure via
retry_async. This adds a circuit breaker on top so a sustained broker outage
fails new publishes immediately instead of eating a full retry backoff on
every message.
"""

from __future__ import annotations

import pytest
from common.config import Settings
from common.kafka import KafkaProducer
from common.resilience import CircuitOpenError


class _FailingKafkaProducer:
    async def send_and_wait(self, _topic, _payload, key=None) -> None:  # noqa: ANN001
        raise ConnectionError("broker unreachable")


@pytest.mark.asyncio
async def test_publish_opens_circuit_after_repeated_send_failures() -> None:
    producer = KafkaProducer(Settings())
    producer._producer = _FailingKafkaProducer()
    producer._publish_breaker.failure_threshold = 1

    with pytest.raises(ConnectionError):
        await producer.publish("some-topic", {"hello": "world"})

    # Second attempt must fail fast on the breaker, not retry against the broker.
    with pytest.raises(CircuitOpenError):
        await producer.publish("some-topic", {"hello": "world"})
