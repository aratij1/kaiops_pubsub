from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Stats:
    requested: int = 0
    success: int = 0
    failed: int = 0
    # Per-request wall-clock latency in milliseconds, one entry per completed
    # attempt (success or failure). Acceptance-count alone doesn't prove an
    # SLO; this is what lets the run report p50/p95/p99.
    latencies_ms: list[float] = field(default_factory=list)


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, round(pct / 100.0 * (len(sorted_values) - 1))))
    return sorted_values[index]


async def post_alert(client: httpx.AsyncClient, base_url: str, idx: int, run_id: str, sem: asyncio.Semaphore, stats: Stats) -> None:
    payload = {
        "source": "stress-harness",
        "application": "stress-lab",
        "name": f"StressGatewayAlert-{run_id}-{idx}",
        "service": "payments",
        "environment": "prod",
        "severity": "critical" if idx % 20 == 0 else ("high" if idx % 5 == 0 else "warning"),
        "description": f"Stress test alert {idx} for pipeline throughput validation",
        "labels": {
            "application": "stress-lab",
            "run_id": run_id,
            "sequence": str(idx),
            "workload": "20k-stress",
        },
        "annotations": {
            "summary": f"stress summary {idx}",
        },
    }

    async with sem:
        started = time.perf_counter()
        try:
            resp = await client.post(f"{base_url}/alerts", json=payload)
            latency_ms = (time.perf_counter() - started) * 1000.0
            stats.latencies_ms.append(latency_ms)
            if resp.status_code == 200:
                stats.success += 1
            else:
                stats.failed += 1
        except Exception:
            stats.latencies_ms.append((time.perf_counter() - started) * 1000.0)
            stats.failed += 1


async def run_load(base_url: str, total: int, concurrency: int, timeout: float, run_id: str) -> Stats:
    sem = asyncio.Semaphore(concurrency)
    stats = Stats(requested=total)

    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        tasks = [post_alert(client, base_url, i, run_id, sem, stats) for i in range(1, total + 1)]
        chunk = 1000
        for start in range(0, len(tasks), chunk):
            await asyncio.gather(*tasks[start : start + chunk])
            completed = min(start + chunk, total)
            print(f"completed={completed}/{total} success={stats.success} failed={stats.failed}")

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Stress ingest alerts through API Gateway")
    parser.add_argument("--base-url", default="http://localhost:8010")
    parser.add_argument("--total", type=int, default=20000)
    parser.add_argument("--concurrency", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--run-id", default=f"run-{int(time.time())}")
    parser.add_argument(
        "--p95-threshold-ms",
        type=float,
        default=None,
        help="Exit non-zero if observed p95 latency exceeds this (enables CI gating).",
    )
    parser.add_argument(
        "--p99-threshold-ms",
        type=float,
        default=None,
        help="Exit non-zero if observed p99 latency exceeds this (enables CI gating).",
    )
    parser.add_argument(
        "--min-acceptance-pct",
        type=float,
        default=None,
        help="Exit non-zero if acceptance percentage falls below this (enables CI gating).",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    stats = asyncio.run(run_load(args.base_url, args.total, args.concurrency, args.timeout, args.run_id))
    elapsed = max(0.001, time.perf_counter() - started)

    sorted_latencies = sorted(stats.latencies_ms)
    p50 = percentile(sorted_latencies, 50)
    p95 = percentile(sorted_latencies, 95)
    p99 = percentile(sorted_latencies, 99)
    acceptance_pct = round((stats.success * 100.0) / stats.requested, 2) if stats.requested else 0.0

    result = {
        "run_id": args.run_id,
        "requested": stats.requested,
        "success": stats.success,
        "failed": stats.failed,
        "acceptance_pct": acceptance_pct,
        "elapsed_seconds": round(elapsed, 2),
        "throughput_alerts_per_sec": round(stats.success / elapsed, 2),
        "latency_ms": {
            "p50": round(p50, 1),
            "p95": round(p95, 1),
            "p99": round(p99, 1),
            "max": round(sorted_latencies[-1], 1) if sorted_latencies else 0.0,
        },
    }
    print(result)

    failures = []
    if args.p95_threshold_ms is not None and p95 > args.p95_threshold_ms:
        failures.append(f"p95 {p95:.1f}ms exceeds threshold {args.p95_threshold_ms:.1f}ms")
    if args.p99_threshold_ms is not None and p99 > args.p99_threshold_ms:
        failures.append(f"p99 {p99:.1f}ms exceeds threshold {args.p99_threshold_ms:.1f}ms")
    if args.min_acceptance_pct is not None and acceptance_pct < args.min_acceptance_pct:
        failures.append(f"acceptance {acceptance_pct:.2f}% below threshold {args.min_acceptance_pct:.2f}%")

    if failures:
        for failure in failures:
            print(f"THRESHOLD VIOLATION: {failure}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
