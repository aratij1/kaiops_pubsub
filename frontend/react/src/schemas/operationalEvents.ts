import { z } from "zod";

export const OperationalEventSchema = z.object({ id: z.string().min(1), type: z.string().min(1), data: z.record(z.unknown()) });
export type OperationalEvent = z.infer<typeof OperationalEventSchema>;
