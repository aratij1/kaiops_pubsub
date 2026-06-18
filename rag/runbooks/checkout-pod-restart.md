kind: runbook
title: Checkout pod crash loop restart
services: checkout

# Checkout pod crash loop restart

When checkout pods enter crash loop after a runtime configuration reload, inspect
the most recent config change and restart the affected pod or deployment.

Recommended remediation:

1. Check Kubernetes events for `checkout-api`.
2. Confirm the crash loop is isolated to the latest config reload.
3. Restart the affected pod or roll the deployment.
4. Confirm checkout availability and error-rate recovery.
