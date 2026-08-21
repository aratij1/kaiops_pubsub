import { describe, expect, it } from "vitest";
import { deriveExecutionCommands } from "./appHelpers.jsx";

describe("deriveExecutionCommands", () => {
  it("uses the governed catalog plan when model analysis is diagnostic-only", () => {
    const commands = deriveExecutionCommands({
      recommendation: {
        commands: [],
        metadata: {
          remediation_analysis: {
            execution_ready: false,
            commands: ["kubectl get pods -n prod"],
          },
          execution_plan: {
            execution_ready: true,
            commands: [
              "ansible-playbook playbooks/restart-service.yml -e service=policy-engine -e env=prod",
            ],
            validation_commands: ["curl -fsS http://policy-engine:8000/healthz"],
          },
        },
      },
    }, []);

    expect(commands).toContain(
      "cmd: ansible-playbook playbooks/restart-service.yml -e service=policy-engine -e env=prod",
    );
    expect(commands).toContain("query: curl -fsS http://policy-engine:8000/healthz");
    expect(commands).not.toContain("cmd: kubectl get pods -n prod");
  });
});
