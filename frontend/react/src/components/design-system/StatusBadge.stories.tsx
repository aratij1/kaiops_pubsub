import type { Meta, StoryObj } from "@storybook/react-vite";

import { ConfidenceExplanation, EnvironmentBadge, EvidenceSource, StatusBadge } from ".";

const meta = {
  title: "KaiMS/Status and evidence",
  component: StatusBadge,
  tags: ["autodocs"],
} satisfies Meta<typeof StatusBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Statuses: Story = {
  args: { tone: "success", children: "Healthy" },
  render: () => <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
    <StatusBadge tone="critical">Critical</StatusBadge>
    <StatusBadge tone="warning">Warning</StatusBadge>
    <StatusBadge tone="success">Healthy</StatusBadge>
    <StatusBadge tone="info">Investigating</StatusBadge>
    <StatusBadge tone="inactive">Inactive</StatusBadge>
  </div>,
};

export const OperationalEvidence: Story = {
  args: { tone: "info", children: "Evidence" },
  render: () => <div style={{ display: "grid", gap: 16, maxWidth: 560 }}>
    <div style={{ display: "flex", gap: 8 }}><EnvironmentBadge environment="production" /><EnvironmentBadge environment="staging" /></div>
    <EvidenceSource source="Prometheus" timestamp="2026-08-04T08:30:00Z" freshness="fresh">CPU saturation confirms the alert signal.</EvidenceSource>
    <ConfidenceExplanation score={0.86} reasons={["Three independent evidence sources agree", "A matching resolved incident exists"]} />
  </div>,
};
