import { describe, expect, it } from "vitest";
import { projectIdentityFromAlert } from "./projectIdentity";

describe("projectIdentityFromAlert", () => {
  it("prefers explicit project labels", () => {
    expect(projectIdentityFromAlert({ labels: { project_name: "payments" }, service: "api" })).toBe("payments");
  });
  it("reads embedded KaiMS context", () => {
    expect(projectIdentityFromAlert({ annotations: { kaiops_context: '{"application":"checkout"}' } })).toBe("checkout");
  });
  it("derives a Jira application without exposing the generic connector", () => {
    expect(projectIdentityFromAlert({ source: "jira", service: "jira-tickets", name: "github-status: unavailable" })).toBe("github-status");
  });
  it("ignores generic and malformed identities safely", () => {
    expect(projectIdentityFromAlert({ service: "jira-tickets", annotations: { kaiops_context: "{" } })).toBe("");
  });
});
