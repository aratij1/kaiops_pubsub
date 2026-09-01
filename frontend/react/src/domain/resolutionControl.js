export const RESOLUTION_CONTROL_SCHEMA = "kaims.resolution-control.v1";

const WATCH_ONLY_TOKENS = new Set(["watch_only", "monitor_only", "observation_only", "observe_only"]);

function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function token(value) {
  return String(value || "").trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
}

function embeddedControl(source) {
  const candidate = object(source);
  if (!candidate) return null;
  const controls = [
    candidate,
    candidate.resolution_control,
    candidate.metadata?.resolution_control,
    candidate.parameters?.resolution_control,
    candidate.resolution_lifecycle?.control,
    candidate.metadata?.resolution_lifecycle?.control,
    candidate.parameters?.resolution_lifecycle?.control,
  ];
  return controls.map(object).find((control) => control?.schema_version === RESOLUTION_CONTROL_SCHEMA) || null;
}

function legacyWatchOnly(sources) {
  return sources.some((source) => {
    const candidate = object(source);
    if (!candidate) return false;
    if (candidate.watch_only === true) return true;
    return ["disposition", "resolution_mode", "handling_mode", "action_mode"]
      .some((key) => WATCH_ONLY_TOKENS.has(token(candidate[key])));
  });
}

export function resolveResolutionControl(sources, { diagnosticOnly = false, finalizedDiagnostic = false } = {}) {
  const candidates = (Array.isArray(sources) ? sources : [sources]).filter(Boolean);
  const persisted = candidates.map(embeddedControl).find(Boolean);
  if (persisted) {
    const disposition = token(persisted.disposition);
    const hasConflict = Array.isArray(persisted.conflicts) && persisted.conflicts.length > 0;
    // A versioned backend decision is the source of truth. UI plan inference
    // must not relabel an approved/executed corrective action as watch-only.
    const persistedDiagnostic = disposition === "watch_only" || disposition === "investigate" || (finalizedDiagnostic && !hasConflict);
    const watchOnlyAuthorized = persisted.watch_only_authorized === true;
    const autoClose = disposition === "watch_only" && persisted.auto_close === true && watchOnlyAuthorized && !hasConflict;
    return {
      ...persisted,
      disposition: persistedDiagnostic ? (disposition === "watch_only" ? "watch_only" : "investigate") : disposition,
      authoritative: true,
      diagnosticOnly: persistedDiagnostic,
      autoClose,
      watchOnlyAuthorized,
      approvalRequired: !persistedDiagnostic && disposition === "approval_required" && persisted.approval_required === true,
      executionAllowed: !persistedDiagnostic && disposition === "execution_ready" && persisted.execution_allowed === true,
    };
  }

  const watchOnly = legacyWatchOnly(candidates);
  return {
    schema_version: "legacy-derived",
    disposition: watchOnly ? "watch_only" : diagnosticOnly ? "investigate" : "unknown",
    authoritative: false,
    diagnosticOnly: Boolean(diagnosticOnly),
    // Legacy diagnostic-only records remain open. Auto-closure requires an
    // explicit watch-only marker; lack of an executable plan is not proof of
    // recovery or permission to close an incident.
    autoClose: Boolean(watchOnly),
    watchOnlyAuthorized: Boolean(watchOnly),
    approvalRequired: false,
    executionAllowed: false,
    conflicts: [],
  };
}
