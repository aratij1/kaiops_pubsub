import { CopilotAnswerSchema, type CopilotAnswer } from "../schemas/copilot";
import { requestValidated } from "./apiClient";

export async function askCopilot(token: string, query: string): Promise<CopilotAnswer> {
  return requestValidated("/api-gateway/copilot/query", CopilotAnswerSchema, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
}
