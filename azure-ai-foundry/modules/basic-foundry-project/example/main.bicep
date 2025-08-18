// Execute this main file to deploy Azure AI Foundry resources in the basic security configuration

// Parameters
@minLength(2)
@maxLength(12)
@description('Name for the AI resource and used to derive name of dependent resources.')
param aiHubName string = 'demo-ai'

@description('Azure region used for the deployment of all resources.')
param location string = resourceGroup().location

@description('Set of tags to apply to all resources.')
param tags object = {}

// Variables
var name = toLower('${aiHubName}')

// Create a short, unique suffix, that will be unique to each resource group
var uniqueSuffix = substring(uniqueString(resourceGroup().id), 0, 4)


module aiHub '../../modules/foundry.bicep' = {
  name: 'ai-${name}-${uniqueSuffix}-deployment'
  params: {
    location: location
    tags: tags
    // AI Foundry resources
    aiFoundryName: 'ai-foundry-${uniqueSuffix}'

  }
}

// Outputs
output resourceGroupName string = resourceGroup().name
output resourceGroupId string = resourceGroup().id
