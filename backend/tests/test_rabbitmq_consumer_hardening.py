"""RabbitMQConsumer previously never bounded prefetch (a channel drop mid-backlog
could leave thousands of delivered-but-unacked messages that all fail to nack
together) and consume_forever never bounded a single handler's runtime (a hung
downstream call could block a consumer indefinitely). Both are now bounded and
configurable.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from common.config import Settings
from common.rabbitmq import RabbitMQConsumer, _is_transient_handler_error, consume_forever


def test_transient_dependency_errors_are_requeueable() -> None:
    assert _is_transient_handler_error("Can't connect to MySQL server on 'mysql'")
    assert _is_transient_handler_error("Temporary failure in name resolution")
    assert _is_transient_handler_error("request timed out")
    assert not _is_transient_handler_error("context field is required")


class _FakeQueue:
    def __init__(self, name: str) -> None:
        self.name = name
        self.bind_calls: list[tuple[object, str]] = []

    async def bind(self, exchange: object, routing_key: str) -> None:
        self.bind_calls.append((exchange, routing_key))


class _FakeChannel:
    def __init__(self) -> None:
        self.qos_calls: list[int] = []
        self.declared_queues: list[_FakeQueue] = []

    async def set_qos(self, prefetch_count: int) -> None:
        self.qos_calls.append(prefetch_count)

    async def declare_exchange(self, _name: str, _exchange_type, durable: bool = True) -> object:
        return object()

    async def declare_queue(self, name: str, durable: bool = True) -> _FakeQueue:
        queue = _FakeQueue(name)
        self.declared_queues.append(queue)
        return queue


class _FakeConnection:
    def __init__(self) -> None:
        self.channel_obj = _FakeChannel()

    async def channel(self) -> _FakeChannel:
        return self.channel_obj

    async def close(self) -> None:
        return None


@pytest.fixture
def fake_connection(monkeypatch: pytest.MonkeyPatch) -> _FakeConnection:
    connection = _FakeConnection()

    async def fake_connect_robust(_url: str) -> _FakeConnection:
        return connection

    monkeypatch.setattr("common.rabbitmq.aio_pika.connect_robust", fake_connect_robust)
    return connection


async def test_start_sets_configured_prefetch(fake_connection: _FakeConnection) -> None:
    settings = Settings(RABBITMQ_CONSUMER_PREFETCH_COUNT=7)
    consumer = RabbitMQConsumer(settings, "raw-alerts")

    await consumer.start()

    assert fake_connection.channel_obj.qos_calls == [7]


async def test_start_defaults_prefetch_to_ten(fake_connection: _FakeConnection) -> None:
    consumer = RabbitMQConsumer(Settings(), "raw-alerts")

    await consumer.start()

    assert fake_connection.channel_obj.qos_calls == [10]


class _FakeMessage:
    def __init__(self, body: bytes, headers: dict | None = None) -> None:
        self.body = body
        self.type = None
        self.headers = headers or {}
        self.acked = 0
        self.nacked: list[bool] = []

    async def ack(self) -> None:
        self.acked += 1

    async def nack(self, requeue: bool = True) -> None:
        self.nacked.append(requeue)


class _FakeExchange:
    def __init__(self) -> None:
        self.published: list[tuple[object, str]] = []

    async def publish(self, message: object, routing_key: str) -> None:
        self.published.append((message, routing_key))


class _FakeIterator:
    """Yields queued messages once, then parks forever (simulating an idle
    queue) so the test can cancel the consumer task deterministically instead
    of racing a fixed sleep."""

    def __init__(self, messages: list[_FakeMessage], parked: asyncio.Event) -> None:
        self._messages = messages
        self._parked = parked

    def __aiter__(self) -> "_FakeIterator":
        return self

    async def __anext__(self) -> _FakeMessage:
        if self._messages:
            return self._messages.pop(0)
        await self._parked.wait()
        raise StopAsyncIteration


class _FakeIteratorCtx:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self._messages = messages
        self.parked = asyncio.Event()

    def __call__(self) -> "_FakeIteratorCtx":
        return self

    async def __aenter__(self) -> _FakeIterator:
        return _FakeIterator(self._messages, self.parked)

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeConsumerQueue:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self._ctx = _FakeIteratorCtx(messages)

    def iterator(self) -> _FakeIteratorCtx:
        return self._ctx


async def test_hung_handler_times_out_and_requeues_via_republish_instead_of_blocking_forever() -> None:
    # A bare handler timeout is inherently ambiguous (could be a slow
    # downstream dependency) so it's always requeue-eligible regardless of
    # RABBITMQ_TRANSIENT_REQUEUE_ENABLED. Requeue happens via a republished
    # copy (not native nack(requeue=True), which redelivers the original
    # message unchanged) so a redelivery counter can travel with it.
    settings = Settings(RABBITMQ_HANDLER_TIMEOUT_SECONDS=0.05, RABBITMQ_CONSUMER_MAX_RETRIES=0)
    consumer = RabbitMQConsumer(settings, "raw-alerts")
    consumer._connection = object()  # bypass real start(): already "connected"
    exchange = _FakeExchange()
    consumer._exchange = exchange
    consumer._dlq_routing_key = "raw-alerts.dlq"

    message = _FakeMessage(json.dumps({"payload": {"id": "evt-1"}}).encode("utf-8"))
    consumer._queue = _FakeConsumerQueue([message])

    async def hanging_handler(_payload: dict) -> None:
        await asyncio.sleep(10)  # far longer than the configured timeout

    task = asyncio.create_task(consume_forever(consumer, hanging_handler))
    try:
        for _ in range(200):
            if message.acked or exchange.published:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("handler timeout never resulted in a requeue republish")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # Original delivery is ack'd (removed from the queue) and a fresh copy
    # carrying an incremented redelivery counter is republished in its place.
    assert message.acked == 1
    assert message.nacked == []
    assert len(exchange.published) == 1
    republished_message, routing_key = exchange.published[0]
    assert routing_key == "raw-alerts"
    assert republished_message.headers.get("x-kaiops-requeue-count") == 1


async def test_hung_handler_exceeding_max_redeliveries_is_poisoned() -> None:
    settings = Settings(
        RABBITMQ_HANDLER_TIMEOUT_SECONDS=0.05,
        RABBITMQ_CONSUMER_MAX_RETRIES=0,
        RABBITMQ_TRANSIENT_REQUEUE_MAX_REDELIVERIES=1,
    )
    consumer = RabbitMQConsumer(settings, "raw-alerts")
    consumer._connection = object()
    exchange = _FakeExchange()
    consumer._exchange = exchange
    consumer._dlq_routing_key = "raw-alerts.dlq"

    # Simulate a message already redelivered once (at the configured max).
    message = _FakeMessage(
        json.dumps({"payload": {"id": "evt-1"}}).encode("utf-8"),
        headers={"x-kaiops-requeue-count": 1},
    )
    consumer._queue = _FakeConsumerQueue([message])

    async def hanging_handler(_payload: dict) -> None:
        await asyncio.sleep(10)

    task = asyncio.create_task(consume_forever(consumer, hanging_handler))
    try:
        for _ in range(200):
            if message.nacked or message.acked:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("message stuck past max redeliveries never resolved")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # Past the redelivery cap: routed to DLQ (published) and ack'd, not
    # requeued again — the loop is bounded even under a persistent failure.
    assert len(exchange.published) == 1
    dlq_message, routing_key = exchange.published[0]
    assert routing_key == "raw-alerts.dlq"
    assert message.acked == 1
    assert message.nacked == []


async def test_consume_forever_bounded_concurrency() -> None:
    settings = Settings(RABBITMQ_MAX_CONCURRENT_HANDLERS=2, RABBITMQ_CONSUMER_MAX_RETRIES=0)
    consumer = RabbitMQConsumer(settings, "raw-alerts")
    consumer._connection = object()
    consumer._exchange = None
    consumer._dlq_routing_key = None

    m1 = _FakeMessage(json.dumps({"payload": {"id": "evt-1"}}).encode("utf-8"))
    m2 = _FakeMessage(json.dumps({"payload": {"id": "evt-2"}}).encode("utf-8"))
    m3 = _FakeMessage(json.dumps({"payload": {"id": "evt-3"}}).encode("utf-8"))
    m4 = _FakeMessage(json.dumps({"payload": {"id": "evt-4"}}).encode("utf-8"))
    consumer._queue = _FakeConsumerQueue([m1, m2, m3, m4])

    active_count = 0
    max_seen_active = 0
    lock = asyncio.Lock()

    async def handler(_payload: dict) -> None:
        nonlocal active_count, max_seen_active
        async with lock:
            active_count += 1
            if active_count > max_seen_active:
                max_seen_active = active_count
        await asyncio.sleep(0.05)
        async with lock:
            active_count -= 1

    task = asyncio.create_task(consume_forever(consumer, handler))
    try:
        await asyncio.sleep(0.2)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert max_seen_active <= 2
    assert max_seen_active > 0


async def test_consume_forever_stale_message_discard() -> None:
    settings = Settings(RABBITMQ_MAX_MESSAGE_AGE_SECONDS=10.0, RABBITMQ_CONSUMER_MAX_RETRIES=0)
    consumer = RabbitMQConsumer(settings, "raw-alerts")
    consumer._connection = object()
    consumer._exchange = None
    consumer._dlq_routing_key = None

    from datetime import datetime, timezone, timedelta
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    m_stale = _FakeMessage(json.dumps({
        "produced_at": stale_time,
        "payload": {"id": "evt-stale"}
    }).encode("utf-8"))

    fresh_time = datetime.now(timezone.utc).isoformat()
    m_fresh = _FakeMessage(json.dumps({
        "produced_at": fresh_time,
        "payload": {"id": "evt-fresh"}
    }).encode("utf-8"))

    consumer._queue = _FakeConsumerQueue([m_stale, m_fresh])

    processed_ids = []
    async def handler(payload: dict) -> None:
        processed_ids.append(payload.get("id"))

    task = asyncio.create_task(consume_forever(consumer, handler))
    try:
        await asyncio.sleep(0.1)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert m_stale.acked == 1
    assert "evt-fresh" in processed_ids
    assert "evt-stale" not in processed_ids


async def test_consume_forever_dlq_failure_prevents_infinite_requeue() -> None:
    settings = Settings(RABBITMQ_CONSUMER_MAX_RETRIES=0)
    consumer = RabbitMQConsumer(settings, "raw-alerts")
    consumer._connection = object()
    
    class _FailingExchange:
        async def publish(self, *args, **kwargs) -> None:
            raise RuntimeError("failing to publish to DLQ exchange")
            
    consumer._exchange = _FailingExchange()
    consumer._dlq_routing_key = "raw-alerts.dlq"

    m = _FakeMessage(json.dumps({"payload": {"id": "evt-failure"}}).encode("utf-8"))
    consumer._queue = _FakeConsumerQueue([m])

    async def failing_handler(_payload: dict) -> None:
        raise ValueError("processing failed")

    task = asyncio.create_task(consume_forever(consumer, failing_handler))
    try:
        await asyncio.sleep(0.1)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert m.nacked == [False]

