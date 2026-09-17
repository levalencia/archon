// Cognitive Services RBAC module: assign Cognitive Services User to VM identity

param cognitiveServicesAccountName string
param vmPrincipalId string

// Reference the existing Cognitive Services account
resource cogAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: cognitiveServicesAccountName
}

// Cognitive Services User: a]dcf8e8-9c11-4d74-ab53-80fcbc1cc47b (inference only)
resource cogRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cogAccount.id, vmPrincipalId, 'a]dcf8e8-9c11-4d74-ab53-80fcbc1cc47b')
  scope: cogAccount
  properties: {
    principalId: vmPrincipalId
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    principalType: 'ServicePrincipal'
  }
}
