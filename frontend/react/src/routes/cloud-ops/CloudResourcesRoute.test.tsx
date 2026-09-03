import { describe, expect, it } from "vitest";
import { resourceDomain, resourcesInProject } from "./CloudResourcesRoute";

describe("resourceDomain", () => {
  it.each([
    ["mysql_database", "aws", "Databases"], ["kafka_topic", "confluent", "Messaging"],
    ["deployment", "kubernetes", "Kubernetes"], ["airflow_pipeline", "gcp", "Data Pipelines"],
    ["virtual_machine", "azure", "Infrastructure"], ["api_service", "custom", "Services"],
    ["subscription", "azure", "Cloud"],
  ])("classifies %s from %s as %s", (resource_type, provider, expected) => {
    expect(resourceDomain({ resource_type, provider })).toBe(expected);
  });
});

describe("resourcesInProject", () => {
  it("excludes stale resources from another project and fails closed", () => {
    const rows = [{ id: "wanted", project_id: "robot-shop" }, { id: "stale", project_id: "demo-project" }] as never;
    expect(resourcesInProject(rows, "robot-shop").map((row) => row.id)).toEqual(["wanted"]);
    expect(resourcesInProject(rows, "")).toEqual([]);
  });
});
