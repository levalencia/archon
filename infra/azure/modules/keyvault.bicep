// Key Vault module: RBAC-enabled, VM identity gets Secrets User role

param location string
param kvName string
param vmPrincipalId string

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

// Key Vault Secrets User role assignment for the VM's managed identity
// Role definition ID: 4633458b-17de-408a-b874-0445c86b69e6
resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, vmPrincipalId, '4633458b-17de-408a-b874-0445c86b69e6')
  scope: kv
  properties: {
    principalId: vmPrincipalId
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalType: 'ServicePrincipal'
  }
}

output kvId string = kv.id
output kvUri string = kv.properties.vaultUri
