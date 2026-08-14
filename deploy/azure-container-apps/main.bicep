targetScope = 'resourceGroup'

@description('Short environment prefix, for example kaiops-prod.')
param namePrefix string
param location string = resourceGroup().location
param containerRegistryServer string
param keyVaultName string
param serviceBusNamespace string
param oidcIssuer string
param oidcAudience string
param oidcClientId string
param otlpEndpoint string
@description('Reachable Temporal frontend host:port, typically a managed Temporal endpoint.')
param temporalAddress string
param mysqlDatabase string = 'kaiops'
param revisionSuffix string = utcNow('yyyyMMddHHmm')
@description('Purpose-built, allowlisted remediation runner image used by the manual Container Apps Job.')
param remediationJobImage string

@secure()
param mysqlDatabaseUrlSecretUri string
@secure()
param serviceBusConnectionSecretUri string
@secure()
param azureBlobConnectionSecretUri string
@secure()
param remediationInternalTokenSecretUri string

@description('Existing KaiOps-compatible processes. Domain is metadata; it does not merge runtimes.')
param apps array

var tags = {
  application: 'kaiops'
  managedBy: 'bicep'
  environment: namePrefix
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-identity'
  location: location
  tags: tags
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-environment'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    zoneRedundant: true
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: first(split(containerRegistryServer, '.'))
}

resource registryPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'AcrPull')
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

resource keyVaultSecretsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, identity.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource containerApps 'Microsoft.App/containerApps@2024-03-01' = [for app in apps: {
  name: '${namePrefix}-${app.name}'
  location: location
  tags: union(tags, { domain: app.domain })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Multiple'
      maxInactiveRevisions: 5
      ingress: app.ingress ? {
        external: app.external
        targetPort: app.targetPort
        transport: 'auto'
        allowInsecure: false
        traffic: [{ latestRevision: true, weight: 100 }]
      } : null
      registries: [{ server: containerRegistryServer, identity: identity.id }]
      secrets: [
        { name: 'database-url', keyVaultUrl: mysqlDatabaseUrlSecretUri, identity: identity.id }
        { name: 'servicebus-connection', keyVaultUrl: serviceBusConnectionSecretUri, identity: identity.id }
        { name: 'blob-connection', keyVaultUrl: azureBlobConnectionSecretUri, identity: identity.id }
        { name: 'remediation-internal-token', keyVaultUrl: remediationInternalTokenSecretUri, identity: identity.id }
      ]
    }
    template: {
      revisionSuffix: revisionSuffix
      containers: [{
        name: app.name
        image: app.image
        command: contains(app, 'command') ? app.command : null
        args: contains(app, 'args') ? app.args : null
        env: concat([
          { name: 'ENVIRONMENT', value: 'production' }
          { name: 'CLOUD_PROVIDER', value: 'azure' }
          { name: 'DEPLOYMENT_PROFILE', value: 'azure-cloud' }
          { name: 'AUTH_MODE', value: 'oidc' }
          { name: 'OIDC_ISSUER', value: oidcIssuer }
          { name: 'OIDC_AUDIENCE', value: oidcAudience }
          { name: 'OIDC_CLIENT_ID', value: oidcClientId }
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'DB', value: 'mysql' }
          { name: 'DB_DATABASE', value: mysqlDatabase }
          { name: 'EVENT_BUS_PROVIDER', value: 'azure-service-bus' }
          { name: 'AZURE_SERVICE_BUS_ENABLED', value: 'true' }
          { name: 'AZURE_SERVICE_BUS_CONNECTION_STRING', secretRef: 'servicebus-connection' }
          { name: 'OBJECT_STORAGE_ENABLED', value: 'true' }
          { name: 'OBJECT_STORAGE_PROVIDER', value: 'azure-blob' }
          { name: 'AZURE_BLOB_CONNECTION_STRING', secretRef: 'blob-connection' }
          { name: 'OTEL_EXPORTER_OTLP_ENDPOINT', value: otlpEndpoint }
          { name: 'TEMPORAL_ADDRESS', value: temporalAddress }
          { name: 'CONTEXT_AGENT_URL', value: 'https://${namePrefix}-context-agent.${environment.properties.defaultDomain}' }
          { name: 'RESOLUTION_AGENT_URL', value: 'https://${namePrefix}-resolution-agent.${environment.properties.defaultDomain}' }
          { name: 'APPROVAL_SERVICE_URL', value: 'https://${namePrefix}-approval-service.${environment.properties.defaultDomain}' }
          { name: 'ORCHESTRATOR_URL', value: 'https://${namePrefix}-orchestrator.${environment.properties.defaultDomain}' }
          { name: 'REMEDIATION_ENGINE_URL', value: 'https://${namePrefix}-remediation-engine.${environment.properties.defaultDomain}' }
          { name: 'MONITORING_ADAPTER_URL', value: 'https://${namePrefix}-monitoring-adapter.${environment.properties.defaultDomain}' }
          { name: 'MODEL_ROUTER_URL', value: 'https://${namePrefix}-model-router.${environment.properties.defaultDomain}' }
          { name: 'APPLICATION_ONBOARDING_URL', value: 'https://${namePrefix}-application-onboarding.${environment.properties.defaultDomain}' }
        ], app.name == 'remediation-engine' ? [
          { name: 'REMEDIATION_TEMPORAL_ENABLED', value: 'true' }
          { name: 'REMEDIATION_TEMPORAL_TASK_QUEUE', value: 'kaiops-remediation' }
          { name: 'REMEDIATION_INTERNAL_TOKEN', secretRef: 'remediation-internal-token' }
          { name: 'REMEDIATION_DEFAULT_EXECUTOR', value: 'azure_container_apps_job' }
          { name: 'REMEDIATION_ACA_JOB_NAME', value: '${namePrefix}-remediation' }
          { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
          { name: 'AZURE_RESOURCE_GROUP', value: resourceGroup().name }
        ] : app.name == 'temporal-workflow-worker' ? [
          { name: 'REMEDIATION_TEMPORAL_ENABLED', value: 'true' }
          { name: 'REMEDIATION_TEMPORAL_TASK_QUEUE', value: 'kaiops-remediation' }
          { name: 'REMEDIATION_INTERNAL_TOKEN', secretRef: 'remediation-internal-token' }
          { name: 'AI_LAYER_REQUEST_TIMEOUT_SECONDS', value: '1000' }
        ] : app.name == 'ui' ? [
          { name: 'API_GATEWAY_HOST', value: '${namePrefix}-api-gateway.${environment.properties.defaultDomain}' }
          { name: 'MONITORING_ADAPTER_HOST', value: '${namePrefix}-monitoring-adapter.${environment.properties.defaultDomain}' }
          { name: 'APPROVAL_SERVICE_HOST', value: '${namePrefix}-approval-service.${environment.properties.defaultDomain}' }
        ] : [], contains(app, 'env') ? app.env : [])
        resources: {
          cpu: app.cpu
          memory: app.memory
        }
        probes: app.ingress ? [
          { type: 'Startup', httpGet: { path: app.healthPath, port: app.targetPort }, initialDelaySeconds: 5, periodSeconds: 5, failureThreshold: 30 }
          { type: 'Readiness', httpGet: { path: app.healthPath, port: app.targetPort }, periodSeconds: 10, failureThreshold: 3 }
          { type: 'Liveness', httpGet: { path: app.healthPath, port: app.targetPort }, periodSeconds: 30, failureThreshold: 3 }
        ] : []
      }]
      scale: {
        minReplicas: app.minReplicas
        maxReplicas: app.maxReplicas
        rules: app.queueScale ? [{
          name: 'servicebus-backlog'
          custom: {
            type: 'azure-servicebus'
            metadata: {
              namespace: serviceBusNamespace
              topicName: app.topic
              subscriptionName: app.subscription
              messageCount: '20'
            }
            auth: [{ secretRef: 'servicebus-connection', triggerParameter: 'connection' }]
          }
        }] : app.ingress ? [{
          name: 'http-concurrency'
          http: { metadata: { concurrentRequests: '50' } }
        }] : []
      }
    }
  }
  dependsOn: [keyVaultSecretsRole, registryPullRole]
}]

resource remediationJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${namePrefix}-remediation'
  location: location
  tags: union(tags, { domain: 'integration-remediation' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [{ server: containerRegistryServer, identity: identity.id }]
    }
    template: {
      containers: [{
        name: 'remediation'
        image: remediationJobImage
        env: [
          { name: 'ENVIRONMENT', value: 'production' }
          { name: 'CLOUD_PROVIDER', value: 'azure' }
          { name: 'KAI_OPS_EXECUTION_PLAN', value: '{"commands":[],"scripts":[],"queries":[],"rollback":[]}' }
        ]
        resources: { cpu: json('1.0'), memory: '2Gi' }
      }]
    }
  }
  dependsOn: [registryPullRole]
}

resource remediationJobOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(remediationJob.id, identity.id, 'Container Apps Jobs Operator')
  scope: remediationJob
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b9a307c4-5aa3-4b52-ba60-2b17c136cd7b')
  }
}

output managedEnvironmentId string = environment.id
output managedIdentityPrincipalId string = identity.properties.principalId
output remediationJobName string = remediationJob.name
output applications array = [for (definition, index) in apps: {
  name: containerApps[index].name
  fqdn: definition.ingress ? containerApps[index].properties.configuration.ingress.fqdn : null
}]
