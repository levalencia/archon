// Azure Container Registry with managed-identity pull access for the VM.

param location string
param registryName string
param vmPrincipalId string

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    dataEndpointEnabled: false
  }
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource vmPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, vmPrincipalId, acrPullRoleId)
  scope: registry
  properties: {
    principalId: vmPrincipalId
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      acrPullRoleId
    )
    principalType: 'ServicePrincipal'
  }
}

output registryId string = registry.id
output registryName string = registry.name
output loginServer string = registry.properties.loginServer
