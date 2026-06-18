kind: deployment
title: Deployment 2.5 payments-api release
services: payments
deployment: Deployment 2.5

# Deployment 2.5 payments-api release

Deployment 2.5 changed payment timeout handling and checkout retry behavior.
The deployment touched `payments-api`, downstream `checkout`, and ledger
authorization paths.

Risk indicators:

- Increased p95 latency
- Increased checkout retry rate
- Higher payment authorization queue depth
