import { describe, expect, it } from "vitest";
import { resourceDomain } from "./CloudResourcesRoute";

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
