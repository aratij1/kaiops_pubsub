export interface OnboardingSourceForm {
  connection_auth_type?: string; connection_secret_ref?: string; logs_url?: string; traces_url?: string;
  telemetry_url?: string; ticketing_url?: string; email_url?: string;
}

export function buildOnboardingSources(form: OnboardingSourceForm, provider: string, endpointUrl: string) {
  return [
    { provider, endpoint_url: endpointUrl, signal_types: ["metrics", "alerts"], auth_type: form.connection_auth_type || "none", secret_ref: form.connection_secret_ref || "", enabled: true },
    { provider: "logs", endpoint_url: form.logs_url, signal_types: ["logs"], auth_type: "none", secret_ref: "", enabled: Boolean(form.logs_url) },
    { provider: "traces", endpoint_url: form.traces_url, signal_types: ["traces"], auth_type: "none", secret_ref: "", enabled: Boolean(form.traces_url) },
    { provider: "telemetry", endpoint_url: form.telemetry_url, signal_types: ["metrics", "logs", "traces"], auth_type: "none", secret_ref: "", enabled: Boolean(form.telemetry_url) },
    { provider: "itsm", endpoint_url: form.ticketing_url, signal_types: ["tickets", "incidents", "changes"], auth_type: "none", secret_ref: "", enabled: Boolean(form.ticketing_url) },
    { provider: "email", endpoint_url: form.email_url, signal_types: ["alerts", "email"], auth_type: "none", secret_ref: "", enabled: Boolean(form.email_url) },
  ].filter((source) => source.enabled && source.endpoint_url);
}
