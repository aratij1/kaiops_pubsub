import { z } from "zod";

export const ApplicationSchema = z.object({
  id: z.union([z.string(), z.number()]), name: z.string().min(1), tenant_id: z.string().optional(), owner_team: z.string().optional(), owner_email: z.string().nullable().optional(), environment: z.string().optional(), namespace: z.string().optional(), region: z.string().optional(), technology: z.string().optional(), metrics_endpoint: z.string().optional(), status: z.string().optional(), created_at: z.string().optional(), updated_at: z.string().optional(),
}).passthrough();
export type Application = z.infer<typeof ApplicationSchema>;

const rows = z.array(ApplicationSchema);
export const ApplicationRowsSchema = z.union([z.object({ rows }).passthrough().transform((value) => value.rows), z.object({ data: z.object({ rows }).passthrough() }).passthrough().transform((value) => value.data.rows)]);
export const ApplicationDetailRowSchema = z.record(z.unknown());
const detailRows = z.array(ApplicationDetailRowSchema);
export const ApplicationDetailRowsSchema = z.union([z.object({ rows: detailRows }).passthrough().transform((value) => value.rows), z.object({ data: z.object({ rows: detailRows }).passthrough() }).passthrough().transform((value) => value.data.rows)]);
export const ApplicationMutationResponseSchema = z.object({}).passthrough();

export const NewApplicationSchema = z.object({
  tenant_id: z.string().min(1), name: z.string().min(1), owner_team: z.string().min(1), owner_email: z.string().email().nullable(), environment: z.enum(["dev", "staging", "prod"]), namespace: z.string().min(1), region: z.string().min(1), technology: z.string().min(1), metrics_endpoint: z.string().url(), monitoring_platform: z.string().min(1), labels: z.record(z.string()),
});
export type NewApplication = z.infer<typeof NewApplicationSchema>;

export const ApplicationUpdateSchema = NewApplicationSchema.extend({ status: z.string().min(1) });
export type ApplicationUpdate = z.infer<typeof ApplicationUpdateSchema>;
