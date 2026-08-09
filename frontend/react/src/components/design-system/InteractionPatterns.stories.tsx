import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "react-aria-components";

import { ConfirmationDialog, DataTable, MasterDetailLayout, SectionNavigation, StatusBadge } from ".";

const meta = { title: "KaiMS/Interaction patterns" } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const incidents = [
  { id: "INC-1042", service: "checkout", severity: "Critical" },
  { id: "INC-1041", service: "catalog", severity: "Warning" },
];

export const NavigationAndConfirmation: Story = {
  render: () => <div style={{ display: "grid", gap: 24 }}>
    <SectionNavigation items={[
      { id: "context", label: "Context", content: "Correlated runtime and ownership context." },
      { id: "evidence", label: "Evidence", content: "Prometheus and log evidence." },
      { id: "remediation", label: "Remediation", content: "Proposed safe action plan." },
    ]} />
    <ConfirmationDialog trigger={<Button className="k-button is-danger">Execute remediation</Button>} title="Execute this remediation?" description="This restarts the checkout deployment in production and will be recorded in the audit trail." confirmLabel="Execute" destructive onConfirm={() => undefined} />
  </div>,
};

export const MasterDetailTable: Story = {
  render: () => <MasterDetailLayout master={<DataTable caption="Open incidents" rows={incidents} rowKey={(row) => row.id} columns={[
    { id: "incident", header: "Incident", cell: (row) => row.id },
    { id: "service", header: "Service", cell: (row) => row.service },
    { id: "severity", header: "Severity", cell: (row) => <StatusBadge tone={row.severity === "Critical" ? "critical" : "warning"}>{row.severity}</StatusBadge> },
  ]} />} detail={<div><h2>INC-1042</h2><p>Checkout latency breached its production SLO.</p></div>} />,
};
