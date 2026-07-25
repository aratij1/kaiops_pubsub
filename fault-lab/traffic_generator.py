#!/usr/bin/env python3
"""Generate safe HTTP traffic against all services in KaiOps Fault Lab."""

import argparse
import json
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    with urllib.request.urlopen(args.base_url + "/api/scenarios") as response:
        scenarios = json.load(response)["items"]
    services = sorted({scenario["service"] for scenario in scenarios})
    print(f"Sending traffic to {len(services)} services. Press Ctrl+C to stop.")
    while True:
        for service in services:
            try:
                with urllib.request.urlopen(f"{args.base_url}/workload/{service}", timeout=5) as response:
                    print(service, response.status)
            except urllib.error.HTTPError as error:
                print(service, error.code)
            except Exception as error:
                print(service, type(error).__name__)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
