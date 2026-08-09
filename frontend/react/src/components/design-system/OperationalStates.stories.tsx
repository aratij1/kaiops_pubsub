import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "react-aria-components";

import { EmptyState, ErrorState, LoadingState, PageHeader, StaleDataNotice, TechnicalDetails } from ".";

const meta = { title: "KaiMS/Operational states" } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const PageAndStates: Story = {
  render: () => <div style={{ display: "grid", gap: 16 }}>
    <PageHeader eyebrow="Live operations" title="Alert investigation" description="Evidence, context, and proposed remediation in one workspace." actions={<Button className="k-button is-primary">Refresh</Button>} />
    <StaleDataNotice updatedAt="2026-08-04T08:30:00Z" refresh={() => undefined} />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
      <LoadingState label="Collecting context" />
      <EmptyState title="No matching incidents" description="Broaden the time window or source filters." />
      <ErrorState description="The evidence service did not respond." retry={() => undefined} />
    </div>
    <TechnicalDetails><pre>{JSON.stringify({ trace_id: "trc-42", source: "prometheus" }, null, 2)}</pre></TechnicalDetails>
  </div>,
};
