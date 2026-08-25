import type { Meta, StoryObj } from "@storybook/react-vite";

import {
  ApprovalCard,
  AutonomyBadge,
  CausalPath,
  ConfidenceIndicator,
  EvidenceBadge,
  ExecutionTimeline,
  LifecycleStepper,
  ReadinessScore,
  RecoveryIndicator,
  ResolutionCard,
  RiskIndicator,
  SafetyEnvelope,
  ValidationComparison,
} from ".";

function SemanticOperationsStory() {
  return <main style={{ display: "grid", gap: 16, maxWidth: 980, color: "var(--k-color-text)" }}>
    <section style={{ display: "flex", gap: 8, flexWrap: "wrap" }}><AutonomyBadge mode="Guided" /><RiskIndicator risk="Low" /><EvidenceBadge provenance="LIVE" /><EvidenceBadge provenance="INFERRED" /><RecoveryIndicator recovered label="Recovery verified" /></section>
    <LifecycleStepper stages={["Detected", "Understanding", "Root cause", "Resolution", "Executing", "Verifying", "Recovered"]} current={3} />
    <ConfidenceIndicator score={91} reasons={["Five supporting signals", "One historical match", "No significant contradiction"]} />
    <CausalPath nodes={[{ kind: "Hypothesis", label: "Connection pool saturation" }, { kind: "Service", label: "Checkout API" }, { kind: "Impact", label: "Payment timeouts" }]} />
    <ResolutionCard title="Restart checkout-api canary pods" rationale="Recreate the unhealthy connection pool on a limited traffic slice." facts={[{ label: "Blast radius", value: "5% traffic" }, { label: "Rollback", value: "Automatic" }, { label: "Duration", value: "~3 minutes" }]} />
    <SafetyEnvelope controls={[{ label: "Allowed scope", value: "1 pod" }, { label: "Traffic exposure", value: "≤5%" }, { label: "Automatic stop", value: "Enabled" }, { label: "Approval", value: "Required" }]} />
    <ApprovalCard title="Restart one canary instance" reason="Production mutation policy requires a human decision." />
    <ExecutionTimeline events={[{ time: "12:41", title: "Pre-state captured", state: "Complete" }, { time: "12:42", title: "Canary prepared", state: "Current" }]} />
    <ValidationComparison rows={[{ signal: "Error rate", before: "12.4%", after: "0.8%", target: "<1%" }, { signal: "P95 latency", before: "4.1s", after: "420ms", target: "<500ms" }]} />
    <ReadinessScore score={87} capabilities={[{ label: "Observability", score: 100 }, { label: "Topology", score: 91 }, { label: "Resolution", score: 65 }, { label: "Governance", score: 100 }]} />
  </main>;
}

const meta = {
  title: "KaiMS/Semantic operations",
  component: SemanticOperationsStory,
  parameters: { layout: "padded" },
} satisfies Meta<typeof SemanticOperationsStory>;

export default meta;
type Story = StoryObj<typeof meta>;

export const OperationsTrustLanguage: Story = {};
