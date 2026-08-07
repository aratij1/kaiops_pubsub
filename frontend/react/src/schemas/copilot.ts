import { z } from "zod";

export const CopilotLinkSchema = z.object({
  label: z.string(),
  path: z.string(),
});

export const CopilotAnswerSchema = z.object({
  trace_id: z.string().optional(),
  intent: z.string().nullable().optional(),
  answer: z.string(),
  data: z.record(z.unknown()).optional(),
  links: z.array(CopilotLinkSchema).optional(),
}).passthrough();

export type CopilotAnswer = z.infer<typeof CopilotAnswerSchema>;
export type CopilotLink = z.infer<typeof CopilotLinkSchema>;
