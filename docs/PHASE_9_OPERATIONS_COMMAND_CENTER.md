# Phase 9 — Navigation and Operations Command Center

Primary navigation now follows business workflows rather than implementation
architecture: Operations, Intelligence, Automation and Platform. Alert intake,
service-detail, audit, gateway-safety and agent-flow routes remain bookmarkable
for compatibility but are not primary navigation destinations. Technical agent
internals are presented as Kai Trace/developer-mode concepts.

The home route is the Operations Command Center. Its summary uses loaded
incident, alert, closure, gateway and estate-readiness records. It explicitly
renders `Unavailable` when change or estate telemetry cannot support a metric;
the UI does not synthesize operational statistics.

Rollback requires restoring the previous navigation registry and dashboard
component. Route paths and APIs were not removed or renamed.
