kind: dependency
title: Payments dependency graph
services: payments
dependencies: checkout, ledger, fraud, postgres-primary

# Payments dependency graph

The payments service depends on checkout, ledger, fraud, and postgres-primary.
Latency in payments can propagate to checkout completion, ledger posting, and
fraud scoring.
