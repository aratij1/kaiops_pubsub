from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass

import httpx


@dataclass
class Stats:
    requested: int = 0
    success: int = 0
    failed: int = 0


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
        try:
            resp = await client.post(f"{base_url}/alerts", json=payload)
            if resp.status_code == 200:
                stats.success += 1
            else:
                stats.failed += 1
        except Exception:
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
    args = parser.parse_args()

    started = time.perf_counter()
    stats = asyncio.run(run_load(args.base_url, args.total, args.concurrency, args.timeout, args.run_id))
    elapsed = max(0.001, time.perf_counter() - started)

    print(
        {
            "run_id": args.run_id,
            "requested": stats.requested,
            "success": stats.success,
            "failed": stats.failed,
            "acceptance_pct": round((stats.success * 100.0) / stats.requested, 2) if stats.requested else 0.0,
            "elapsed_seconds": round(elapsed, 2),
            "throughput_alerts_per_sec": round(stats.success / elapsed, 2),
        }
    )


if __name__ == "__main__":
    main()
