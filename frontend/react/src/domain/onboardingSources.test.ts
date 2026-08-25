import { describe, expect, it } from "vitest";
import { buildOnboardingSources } from "./onboardingSources";

describe("buildOnboardingSources", () => {
  it("supports multiple application-specific alert and investigation sources", () => {
    const rows = buildOnboardingSources({ logs_url: "https://logs.example", ticketing_url: "https://jira.example", email_url: "imaps://mail.example/INBOX" }, "prometheus", "https://prom.example");
    expect(rows.map((row) => row.provider)).toEqual(["prometheus", "logs", "itsm", "email"]);
  });
});
