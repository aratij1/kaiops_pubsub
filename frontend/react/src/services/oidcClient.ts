export interface AuthConfig {
  mode: "local" | "oidc";
  local_development_only: boolean;
  issuer: string | null;
  client_id: string | null;
  audience: string | null;
  pkce_required: boolean;
}

interface Discovery {
  authorization_endpoint: string;
  token_endpoint: string;
}

const VERIFIER_KEY = "kaiops.oidc.verifier";
const STATE_KEY = "kaiops.oidc.state";

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((value) => { binary += String.fromCharCode(value); });
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function discovery(config: AuthConfig): Promise<Discovery> {
  const response = await fetch(`${config.issuer?.replace(/\/$/, "")}/.well-known/openid-configuration`);
  if (!response.ok) throw new Error("Identity provider discovery failed");
  return OidcDiscoverySchema.parse(await response.json());
}

export async function beginOidcLogin(config: AuthConfig): Promise<void> {
  if (!config.issuer || !config.client_id) throw new Error("OIDC is not configured");
  const metadata = await discovery(config);
  const verifier = base64Url(crypto.getRandomValues(new Uint8Array(48)));
  const challenge = base64Url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
  const state = base64Url(crypto.getRandomValues(new Uint8Array(24)));
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
  const redirectUri = `${location.origin}${location.pathname}`;
  const query = new URLSearchParams({
    client_id: config.client_id,
    response_type: "code",
    redirect_uri: redirectUri,
    scope: "openid profile email",
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });
  location.assign(`${metadata.authorization_endpoint}?${query}`);
}

export async function completeOidcLogin(config: AuthConfig): Promise<string | null> {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  if (!code) return null;
  const expectedState = sessionStorage.getItem(STATE_KEY);
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!expectedState || params.get("state") !== expectedState || !verifier) throw new Error("OIDC callback state validation failed");
  if (!config.client_id) throw new Error("OIDC client is not configured");
  const metadata = await discovery(config);
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.client_id,
    code,
    code_verifier: verifier,
    redirect_uri: `${location.origin}${location.pathname}`,
  });
  const response = await fetch(metadata.token_endpoint, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
  if (!response.ok) throw new Error("OIDC authorization code exchange failed");
  const tokens = OidcTokenResponseSchema.parse(await response.json());
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
  history.replaceState({}, document.title, location.pathname);
  return tokens.access_token ?? null;
}
import { OidcDiscoverySchema, OidcTokenResponseSchema } from "../schemas/oidc";
