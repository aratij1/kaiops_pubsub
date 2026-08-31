# Modernization Phase 17 — Production OIDC Authentication

## Outcome

Production KaiOps now requires deployment-selected OIDC authentication. The same standards-based implementation supports Microsoft Entra ID and Keycloak through issuer discovery; local username/password login remains available only in explicitly local/demo/test environments.

## Scope completed

- Added `AUTH_MODE=local|oidc` with strict production startup validation.
- Production rejects local auth, incomplete OIDC settings, and non-HTTPS issuers.
- Added cached OIDC discovery and JWKS validation with allowed asymmetric algorithms, signature, issuer, audience, expiry, issued-at, subject, and key-ID checks.
- Added configurable nested role claim, explicit external-to-KaiOps role mapping, and tenant claim mapping.
- External tokens do not require or create local database sessions/users.
- Local password login and refresh routes return unavailable outside local development auth.
- OIDC mode seeds role definitions but does not seed default users.
- Added external `/auth/me` compatibility without persisting identity-provider profile data.
- Added MFA/step-up enforcement for approve/modify and remediation execution using configurable `acr`/`amr` values.
- Added public, non-secret `/auth/config` discovery for the SPA.
- Added browser Authorization Code + PKCE login. Access tokens remain only in React memory; verifier/state are short-lived in session storage and state is validated on callback.
- Added an enterprise SSO login state and explicitly labelled the local-development login.

## Deployment settings

Required in production:

```text
ENVIRONMENT=production
AUTH_MODE=oidc
OIDC_ISSUER=https://<entra-tenant-or-keycloak-realm>
OIDC_AUDIENCE=<kaiops-api-audience>
OIDC_CLIENT_ID=<public-spa-client-id>
OIDC_ROLE_CLAIM=roles
OIDC_TENANT_CLAIM=tenant_id
OIDC_ROLE_MAPPINGS={"external-role":"Administrator"}
```

For Keycloak's default nested roles, use `OIDC_ROLE_CLAIM=realm_access.roles`. Register the exact KaiOps callback URLs, require PKCE, and enable the token endpoint's SPA CORS policy. Secrets are not accepted by or returned to the browser.

## MySQL and API compatibility

No schema changes. Existing local JWT behavior and routes remain compatible in local/demo/test. Existing bearer-protected API contracts are unchanged; OIDC access tokens are accepted in production.

## Validation

- Compose validation: passed.
- Backend compile across settings, validator, services, dependencies, router, and gateway: passed.
- Focused authentication/tenant/gateway tests: 25 passed.
- Frontend TypeScript: passed.
- Frontend unit tests: 14 passed.
- Production frontend build: passed.
- App bundle: 664.21 kB / 162.07 kB gzip; CSS: 133.13 kB / 24.61 kB gzip.

## Security implications

No token is written to local storage. OIDC failures return generic messages without token/claim leakage. External users must have an explicitly mapped KaiOps role. Sensitive actions require a configured step-up value. Provider logout remains provider-owned; KaiOps immediately drops its in-memory token.

## Known limitations

Live Entra ID and Keycloak acceptance tests require tenant/realm application registrations and cannot be completed from repository-only credentials. Key Vault/managed-identity secret references belong to the Azure Container Apps deployment phase; this OIDC SPA flow itself uses no client secret.

## Rollback

For local/demo/test only, set `AUTH_MODE=local`. Production intentionally cannot roll back to local passwords; rollback is to the prior application revision while the identity-provider configuration is corrected.

## Recommended next phase

Phase 18: expand OpenTelemetry through the collector and add provider-neutral workflow, queue, SSE, MySQL, object-storage, connector, and model telemetry.
