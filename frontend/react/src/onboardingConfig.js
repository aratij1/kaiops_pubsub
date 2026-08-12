export const MONITORING_TOOL_OPTIONS = ["prometheus", "new_relic", "datadog"];

export const ALERT_DOC_KIND_OPTIONS = ["incident", "jira", "runbook", "deployment", "change", "dependency", "remediation"];

export const ONBOARDING_SOURCE_DOC_EXTENSIONS = new Set(["txt", "md", "markdown", "json", "csv", "log", "yaml", "yml"]);

export const ONBOARDING_SOURCE_DOC_BUCKETS = [
  { key: "ticket", label: "Past Tickets" },
  { key: "troubleshooting", label: "Troubleshooting Docs" },
  { key: "rca", label: "RCA / Postmortem Docs" },
  { key: "resolution", label: "Resolution Docs" },
  { key: "logs", label: "Logs" },
  { key: "other", label: "Other Evidence" },
];

export const ONBOARDING_SOURCE_DOC_SAMPLE_FILES = {
  ticket: { href: "/source_doc_sample_past_ticket.md", label: "Download past ticket sample" },
  troubleshooting: { href: "/source_doc_sample_troubleshooting.md", label: "Download troubleshooting sample" },
  rca: { href: "/source_doc_sample_rca_and_logs.txt", label: "Download RCA and logs sample" },
  resolution: { href: "/source_doc_sample_troubleshooting.md", label: "Download resolution sample" },
  logs: { href: "/source_doc_sample_rca_and_logs.txt", label: "Download logs sample" },
  other: { href: "/source_doc_sample_past_ticket.md", label: "Download evidence sample" },
};

export const DOCUMENT_PROVIDER_ROLES = new Set(["administrator", "l2_engineer", "l3_engineer"]);
