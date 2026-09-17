// Cogentrex Azure VM Infrastructure – Sweden Central
// Deploys: VNet, NSG, static public IP, Linux VM (Standard_B2s),
// system-assigned identity, Key Vault with RBAC, Log Analytics,
// Application Insights, Cognitive Services role assignment, and cloud-init.

targetScope = 'resourceGroup'

// ─── Parameters ────────────────────────────────────────────────────────────────

@description('Azure region for all resources')
param location string = 'swedencentral'

@description('Admin username for the VM')
param adminUsername string = 'cogentrex'

@description('SSH public key for the admin user')
@secure()
param adminSshPublicKey string

@description('VM size')
param vmSize string = 'Standard_B2s'

@description('Name of the existing Cognitive Services account for inference')
param cognitiveServicesAccountName string = 'cogentrex'

@description('Resource group of the existing Cognitive Services account')
param cognitiveServicesResourceGroup string = resourceGroup().name

@description('Cloud-init configuration (base64-encoded)')
param cloudInitBase64 string = loadFileAsBase64('./cloud-init.yml')

@description('Unique suffix for globally-unique resource names')
param nameSuffix string = uniqueString(resourceGroup().id)

// ─── Variables ─────────────────────────────────────────────────────────────────

var prefix = 'cogentrex'
var vnetName = '${prefix}-vnet'
var subnetName = '${prefix}-subnet'
var nsgName = '${prefix}-nsg'
var pipName = '${prefix}-pip'
var nicName = '${prefix}-nic'
var vmName = '${prefix}-vm'
var kvName = 'ctxkv${take(nameSuffix, 8)}'
var lawName = '${prefix}-law'
var aiName = '${prefix}-ai'
var acrName = '${prefix}${nameSuffix}'
var githubIdentityName = '${prefix}-github-dev'

// ─── Modules ───────────────────────────────────────────────────────────────────

module network './modules/network.bicep' = {
  name: 'network'
  params: {
    location: location
    vnetName: vnetName
    subnetName: subnetName
    nsgName: nsgName
    pipName: pipName
    nicName: nicName
  }
}

module monitoring './modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    lawName: lawName
    aiName: aiName
  }
}

module keyVault './modules/keyvault.bicep' = {
  name: 'keyVault'
  params: {
    location: location
    kvName: kvName
    vmPrincipalId: vm.outputs.vmPrincipalId
    applicationInsightsConnectionString: monitoring.outputs.aiConnectionString
  }
}

module vm './modules/vm.bicep' = {
  name: 'vm'
  params: {
    location: location
    vmName: vmName
    vmSize: vmSize
    adminUsername: adminUsername
    adminSshPublicKey: adminSshPublicKey
    nicId: network.outputs.nicId
    cloudInitBase64: cloudInitBase64
  }
}

// ─── Cognitive Services RBAC ───────────────────────────────────────────────────

// Cognitive Services User role – allows inference calls via managed identity
module cognitiveRbac './modules/cognitive-rbac.bicep' = {
  name: 'cognitiveRbac'
  scope: resourceGroup(cognitiveServicesResourceGroup)
  params: {
    cognitiveServicesAccountName: cognitiveServicesAccountName
    vmPrincipalId: vm.outputs.vmPrincipalId
  }
}

module acr './modules/acr.bicep' = {
  name: 'acr'
  params: {
    location: location
    registryName: acrName
    vmPrincipalId: vm.outputs.vmPrincipalId
  }
}

module githubIdentity './modules/github-identity.bicep' = {
  name: 'githubIdentity'
  params: {
    location: location
    identityName: githubIdentityName
    githubSubject: 'repo:levalencia@6962857/cogentrex@1342041970:environment:development'
    vmName: vmName
    registryName: acr.outputs.registryName
  }
}

// ─── Outputs ───────────────────────────────────────────────────────────────────

output vmName string = vmName
output vmId string = vm.outputs.vmId
output publicIpAddress string = network.outputs.publicIpAddress
output publicIpFqdn string = '${network.outputs.publicIpAddress}.sslip.io'
output keyVaultName string = kvName
output logAnalyticsWorkspaceId string = monitoring.outputs.lawId
output appInsightsName string = aiName
output vmPrincipalId string = vm.outputs.vmPrincipalId
output acrId string = acr.outputs.registryId
output acrName string = acr.outputs.registryName
output acrLoginServer string = acr.outputs.loginServer
output githubIdentityClientId string = githubIdentity.outputs.clientId
output githubIdentityPrincipalId string = githubIdentity.outputs.principalId
output githubIdentityId string = githubIdentity.outputs.identityId
