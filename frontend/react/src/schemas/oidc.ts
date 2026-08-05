import { z } from "zod";

export const OidcDiscoverySchema = z.object({ authorization_endpoint: z.string().url(), token_endpoint: z.string().url() }).passthrough();
export const OidcTokenResponseSchema = z.object({ access_token: z.string().min(1), token_type: z.string().optional(), expires_in: z.number().positive().optional(), id_token: z.string().optional() }).passthrough();
