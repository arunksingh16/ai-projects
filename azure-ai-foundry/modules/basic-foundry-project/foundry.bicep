// Creates an Azure AI resource with proxied endpoints for the Azure AI services provider

@description('Azure region of the deployment')
param location string

@description('Tags to add to the resources')
param tags object

@description('That name is the name of our application. It has to be unique. Type a name followed by your resource group name. (<name>-<resourceGroupName>)')
param aiFoundryName string


/*
  An AI Foundry resources is a variant of a CognitiveServices/account resource type
*/ 
resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: aiFoundryName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'S0'
  }
  kind: 'AIServices'
  properties: {
    // Defines developer API endpoint subdomain
    customSubDomainName: aiFoundryName

    disableLocalAuth: true
    // Set to use with AI Foundry
    allowProjectManagement: true    
    // Required property for Cognitive Services accounts
    publicNetworkAccess: 'Enabled'
  }
}


// Projects are folders to organize your work in AI Foundry such as Agents, Evaluations, Files
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  name: 'first-project'
  identity: {
    type: 'SystemAssigned'
  }
  parent: account
  location: location
  properties: {
    displayName: 'project'
    description: 'My first project'
  }
}