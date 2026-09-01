kind: runbook
title: Runbook - kaiops-test-verify-2
alert_type: kaiops-test-verify-2-monitoring
severity: critical
services: kaiops-test-verify-2
tenant_id: default
environment: prod
namespace: kaiops
source: rule-generation-agent
application_id: bae55dfb-5df9-4ac3-b4d2-d077dfc65fe5

# Runbook - kaiops-test-verify-2

## Summary
Auto-generated monitoring runbook for kaiops-test-verify-2 (prod).

## Description
Auto-generated monitoring runbook for **kaiops-test-verify-2**.

- Tenant: default
- Environment: prod
- Namespace: kaiops
- Owner team: platform-ops

## Alert Rules
### kaiops-test-verify-2-target-down (critical)
- Condition: `up{job="kaiops-test-verify-2"} == 0` for `2m`
- Summary: kaiops-test-verify-2 target is down
- Description: Prometheus cannot scrape the application target.
- Troubleshooting steps:
  - Confirm the service process is running and healthy.
  - Check recent deploys/restarts for this service.
  - Verify network connectivity between Prometheus and the target.

### kaiops-test-verify-2-cpu-high (warning)
- Condition: `rate(process_cpu_seconds_total[5m]) > 0.85` for `5m`
- Summary: kaiops-test-verify-2 CPU usage high
- Description: Sustained CPU saturation detected.
- Troubleshooting steps:
  - Inspect recent traffic spikes or inefficient code paths.
  - Check for runaway background jobs or retry storms.
  - Consider scaling out if load is legitimate.

### kaiops-test-verify-2-memory-high (warning)
- Condition: `process_resident_memory_bytes > 5e+08` for `10m`
- Summary: kaiops-test-verify-2 memory usage high
- Description: Sustained memory growth detected.
- Troubleshooting steps:
  - Check for memory leaks via recent deploys.
  - Inspect cache sizes and unbounded in-memory collections.
  - Consider a rolling restart if growth is unbounded.
