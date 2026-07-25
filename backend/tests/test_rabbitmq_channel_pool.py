"""RabbitMQProducer now opens a small pool of channels/exchanges instead of
one shared channel per process, round-robining publishes across them for
higher parallel publish throughput under a 10k-alert burst. Since routing_key
is always the topic (never the `key=` argument), round-robining introduces no
ordering regression to guard against here.
"""

from __future__ import annotations

import pytest

from common.config import Settings
from common.rabbitmq import RabbitMQProducer


class _FakeExchange:
    def __init__(self) -> None:
        self.publish_calls = 0

    async def publish(self, _message, routing_key) -> None:  # noqa: ANN001
        self.publish_calls += 1


class _FakeChannel:
    def __init__(self, exchange: _FakeExchange) -> None:
        self._exchange = exchange

    async def declare_exchange(self, _name, _exchange_type, durable=True):  # noqa: ANN001
        return self._exchange


class _FakeConnection:
    def __init__(self) -> None:
        self.channels_created = 0

    async def channel(self) -> _FakeChannel:
        self.channels_created += 1
        return _FakeChannel(_FakeExchange())

    async def close(self) -> None:
        return None


@pytest.fixture
def fake_connection(monkeypatch: pytest.MonkeyPatch) -> _FakeConnection:
    connection = _FakeConnection()

    async def fake_connect_robust(_url):  # noqa: ANN001
        return connection

    monkeypatch.setattr("common.rabbitmq.aio_pika.connect_robust", fake_connect_robust)
    return connection


async def test_start_creates_configured_channel_pool_size(fake_connection: _FakeConnection) -> None:
    settings = Settings(RABBITMQ_PUBLISHER_CHANNEL_POOL_SIZE=3)
    producer = RabbitMQProducer(settings)

    await producer.start()

    assert fake_connection.channels_created == 3
    assert len(producer._channels) == 3
    assert len(producer._exchanges) == 3


async def test_start_defaults_to_pool_size_four(fake_connection: _FakeConnection) -> None:
    producer = RabbitMQProducer(Settings())

    await producer.start()

    assert fake_connection.channels_created == 4


async def test_publish_round_robins_across_channels(fake_connection: _FakeConnection) -> None:
    settings = Settings(RABBITMQ_PUBLISHER_CHANNEL_POOL_SIZE=3)
    producer = RabbitMQProducer(settings)
    await producer.start()

    for _ in range(9):
        await producer.publish("some-topic", {"hello": "world"})

    counts = sorted(exchange.publish_calls for exchange in producer._exchanges)
    assert counts == [3, 3, 3]


async def test_publish_without_start_logs_and_does_not_raise() -> None:
    producer = RabbitMQProducer(Settings())
    # start() was never called, so there are no exchanges yet.
    await producer.publish("some-topic", {"hello": "world"})
