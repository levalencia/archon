// Cognitive Services RBAC module: allow the VM identity to run inference.

param cognitiveServicesAccountName string
param vmPrincipalId string

resource cogAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: cognitiveServicesAccountName
}

// Cognitive Services OpenAI User: inference and deployment read access.
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource cogRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cogAccount.id, vmPrincipalId, cognitiveServicesOpenAIUserRoleId)
  scope: cogAccount
  properties: {
    principalId: vmPrincipalId
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      cognitiveServicesOpenAIUserRoleId
    )
    principalType: 'ServicePrincipal'
  }
}
