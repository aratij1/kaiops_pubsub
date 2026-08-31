// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfidenceMeter, KaiInsight, RiskBadge } from ".";
import { KAI_BRAND, applyKaiTheme } from "../config/brand";

describe("Kai Design System", () => {
  it("keeps canonical product language in one configuration", () => {
    expect(KAI_BRAND.productName).toBe("KaiMS");
    expect(KAI_BRAND.positioning).toBe("Understand. Decide. Resolve.");
  });

  it("applies a supported theme and brand marker", () => {
    applyKaiTheme("dark");
    expect(document.documentElement).toHaveAttribute("data-ui-theme", "dark");
    expect(document.documentElement).toHaveAttribute("data-kai-brand", "kaims");
  });

  it("communicates risk and confidence with text, not color alone", () => {
    render(<><RiskBadge risk="critical" /><ConfidenceMeter value={0.82} /><KaiInsight title="Likely deployment regression" confidence={0.82}>Correlated evidence</KaiInsight></>);
    expect(screen.getByText("critical risk")).toBeVisible();
    expect(screen.getAllByLabelText("Kai Confidence 82 percent")).toHaveLength(2);
    expect(screen.getByText("Kai Insight")).toBeVisible();
  });
});
