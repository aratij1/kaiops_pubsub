# KaiOps Corrected Architecture

This diagram separates the product into explicit layers:

- Alert sources
- Landing pad and application workflow layer
- Message bus backbone
- AI intelligence layer
- Output and notification layer
- Cross-cutting governance

Open `kaiops-corrected-architecture.svg` to view the corrected box-and-arrow architecture.

Layer diagrams:

- `layer-01-monitoring-intake.svg`
- `layer-02-alert-intelligence-workflow.svg`
- `layer-03-ai-intelligence.svg`
- `layer-04-approval-remediation.svg`
- `layer-05-data-rag.svg`
- `layer-06-notification-governance.svg`

Enterprise-scale proposed architecture:

- `kaiops-proposed-scalable-enterprise-architecture.svg`

Azure production deployment architecture:

- `kaiops-azure-production-scalable-architecture.svg`

Application layer to AI layer API contracts:

- `application-ai-layer-api-contracts.md`

Complete incident processing flow with message bus topics:

- `kaiops-complete-incident-processing-flow.svg`
- `kaiops-complete-incident-processing-flow.md`
