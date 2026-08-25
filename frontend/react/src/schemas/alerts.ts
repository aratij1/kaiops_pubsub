import { z } from "zod";

const UnknownRecordSchema = z.record(z.unknown());
const OptionalStringSchema = z.string().nullish().transform((value) => value ?? undefined);
const OptionalIdentifierSchema = z.union([z.string(), z.number()]).nullish().transform((value) => value ?? undefined);
const OptionalRecordSchema = UnknownRecordSchema.nullish().transform((value) => value ?? undefined);

export const AlertRowSchema = z.object({
  id: OptionalIdentifierSchema,
  alert_id: OptionalIdentifierSchema,
  incident_id: OptionalIdentifierSchema,
  ticket_id: OptionalStringSchema,
  jira_key: OptionalStringSchema,
  jira_url: OptionalStringSchema,
  incident_disposition: OptionalStringSchema,
  origin_system: OptionalStringSchema,
  ingestion_channel: OptionalStringSchema,
  deduplicated_count: z.number().nullish().transform((value) => value ?? undefined),
  name: OptionalStringSchema,
  alert_name: OptionalStringSchema,
  service: OptionalStringSchema,
  application: OptionalStringSchema,
  environment: OptionalStringSchema,
  source: OptionalStringSchema,
  severity: OptionalStringSchema,
  status: OptionalStringSchema,
  created_at: OptionalStringSchema,
  updated_at: OptionalStringSchema,
  labels: OptionalRecordSchema,
  annotations: OptionalRecordSchema,
  metadata: OptionalRecordSchema,
}).passthrough();

export type AlertRow = z.infer<typeof AlertRowSchema>;

const RowsSchema = z.array(AlertRowSchema);
const DirectRowsResponseSchema = z.object({ rows: RowsSchema }).passthrough();
const DataRowsResponseSchema = z.object({ data: DirectRowsResponseSchema }).passthrough();

export const AlertRowsResponseSchema = z.union([
  DataRowsResponseSchema.transform((value) => value.data.rows),
  DirectRowsResponseSchema.transform((value) => value.rows),
]);

export type AlertRowsResponse = z.infer<typeof AlertRowsResponseSchema>;
