# Modernization Phase 19 — Azure Container Apps

## Outcome

KaiOps now has a production-oriented Azure Container Apps deployment baseline
that preserves the existing React/Vite UI and the real Python service
entrypoints. It does not claim unsafe service consolidation.

## Delivered

- Bicep for a zone-redundant Container Apps environment, Log Analytics,
  managed identity, Key Vault references, ACR pull, revisions, probes, resource
  limits, and HTTP/Service Bus scaling.
- Runtime-configured Nginx UI image with internal service proxies and unbuffered
  SSE forwarding.
- Manual GitHub deployment workflow using Azure workload identity, Bicep
  compilation, `what-if`, and incremental deployment.
- Fail-closed parameter validation: placeholders and mutable `latest` tags are
  rejected before Azure login or mutation.
- Deployment, rollback, scaling, and environment-validation guidance.

## Validation evidence

- Bicep compiled successfully with Azure CLI 2.76.0.
- `production.parameters.json` passed structural validation in explicit
  template mode.
- The ACA UI image completed its React production build.
- Nginx entrypoint substitution preserved Nginx variables and `nginx -t`
  passed after rendering all internal host values.

## External acceptance gate

No Azure subscription deployment was attempted because the checked-in file
contains deliberate tenant-specific placeholders. Production acceptance still
requires immutable images in ACR, real Key Vault secret URIs, supported regional
zone redundancy, `what-if` review, smoke tests, and revision rollback rehearsal.
The workflow prevents placeholders from crossing that gate.
