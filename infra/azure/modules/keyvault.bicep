// Key Vault module: RBAC-enabled, VM identity gets read-only secret access.

param location string
param kvName string
param vmPrincipalId string
@secure()
param applicationInsightsConnectionString string

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
  }
}

// Key Vault Secrets User role assignment for the VM's managed identity.
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, vmPrincipalId, keyVaultSecretsUserRoleId)
  scope: kv
  properties: {
    principalId: vmPrincipalId
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      keyVaultSecretsUserRoleId
    )
    principalType: 'ServicePrincipal'
  }
}

resource appInsightsSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'applicationinsights-connection-string'
  properties: {
    value: applicationInsightsConnectionString
  }
}

output kvId string = kv.id
output kvName string = kv.name
output kvUri string = kv.properties.vaultUri
