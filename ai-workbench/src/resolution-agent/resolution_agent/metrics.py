from prometheus_client import Counter, Gauge, Histogram


INVESTIGATION_DURATION = Histogram("kaims_resolution_investigation_duration_seconds", "Bounded investigation duration.")
EVIDENCE_COUNT = Gauge("kaims_resolution_evidence_count", "Normalized evidence records in the latest investigation.")
HYPOTHESIS_COUNT = Gauge("kaims_resolution_hypothesis_count", "Hypotheses in the latest investigation.")
RESOLUTION_CONFIDENCE = Gauge("kaims_resolution_confidence", "Deterministic leading-hypothesis confidence.")
INCONCLUSIVE_TOTAL = Counter("kaims_resolution_inconclusive_total", "Inconclusive investigations.")
PLAN_BLOCKED_TOTAL = Counter("kaims_resolution_plan_blocked_total", "Plans blocked by evidence or policy gates.")
HITL_TOTAL = Counter("kaims_resolution_hitl_total", "Plans routed to human approval.")
HOTL_TOTAL = Counter("kaims_resolution_hotl_total", "Plans authorized for autonomous execution.")
EXECUTION_TOTAL = Counter("kaims_resolution_execution_total", "Resolution execution attempts.")
VALIDATION_FAILED_TOTAL = Counter("kaims_resolution_validation_failed_total", "Independent validation failures.")
ROLLBACK_TOTAL = Counter("kaims_resolution_rollback_total", "Resolution rollback attempts.")
RECURRENCE_TOTAL = Counter("kaims_resolution_recurrence_total", "Incident recurrences within the review window.")
