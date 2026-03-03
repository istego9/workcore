targetScope = 'resourceGroup'

@description('Primary Azure region for runtime resources.')
param location string = resourceGroup().location

@description('Tags applied to resources.')
param tags object = {}

@description('Container registry name (globally unique, lowercase).')
param acrName string

@description('Key Vault name (globally unique).')
param keyVaultName string

@description('Log Analytics workspace name.')
param logAnalyticsName string

@description('Container Apps managed environment name.')
param containerAppsEnvName string

@description('Storage account name for MinIO Azure Files backend (globally unique, lowercase).')
param storageAccountName string

@description('Azure Files share name mounted to MinIO.')
param minioShareName string = 'minio-data'

@description('Static Web App name.')
param staticWebAppName string

@description('Static Web App region (Static Web Apps is not available in UAE North).')
param staticWebAppLocation string = 'westeurope'

@description('Azure OpenAI account name (globally unique).')
param azureOpenAIAccountName string

@description('Virtual network name.')
param vnetName string = 'vnet-workcore-prod-uaen'

@description('Address space for the WorkCore VNet.')
param vnetAddressPrefix string = '10.42.0.0/16'

@description('Delegated subnet name for PostgreSQL Flexible Server.')
param postgresSubnetName string = 'snet-postgres-flex'

@description('Delegated subnet CIDR for PostgreSQL Flexible Server.')
param postgresSubnetPrefix string = '10.42.1.0/24'

@description('Delegated subnet name for Container Apps environment infrastructure.')
param containerAppsSubnetName string = 'snet-containerapps'

@description('Delegated subnet CIDR for Container Apps environment infrastructure.')
param containerAppsSubnetPrefix string = '10.42.2.0/23'

@description('Private DNS zone name for PostgreSQL Flexible Server private access.')
param postgresPrivateDnsZoneName string = 'private.postgres.database.azure.com'

@description('PostgreSQL Flexible Server name.')
param postgresServerName string

@description('PostgreSQL admin login.')
param postgresAdminLogin string

@secure()
@description('PostgreSQL admin password.')
param postgresAdminPassword string

@description('PostgreSQL database name for WorkCore.')
param postgresDatabaseName string = 'workflow'

@description('PostgreSQL major version.')
@allowed([
  '14'
  '15'
  '16'
])
param postgresVersion string = '16'

@description('PostgreSQL SKU name.')
param postgresSkuName string = 'Standard_B2s'

@description('PostgreSQL SKU tier.')
@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param postgresSkuTier string = 'Burstable'

@description('PostgreSQL backup retention in days.')
@minValue(7)
@maxValue(35)
param postgresBackupRetentionDays int = 14

@description('PostgreSQL storage size in GiB.')
@minValue(32)
param postgresStorageSizeGB int = 32

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: 'Enabled'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    enableRbacAuthorization: true
    enabledForDeployment: false
    enabledForTemplateDeployment: false
    enabledForDiskEncryption: false
    tenantId: tenant().tenantId
    sku: {
      name: 'standard'
      family: 'A'
    }
    publicNetworkAccess: 'Enabled'
    softDeleteRetentionInDays: 90
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    allowSharedKeyAccess: true
    publicNetworkAccess: 'Enabled'
  }
}

resource fileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  name: '${storageAccount.name}/default/${minioShareName}'
  properties: {
    accessTier: 'TransactionOptimized'
    enabledProtocols: 'SMB'
  }
  dependsOn: [
    storageAccount
  ]
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: postgresSubnetName
        properties: {
          addressPrefix: postgresSubnetPrefix
          delegations: [
            {
              name: 'postgres-flex-delegation'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: containerAppsSubnetName
        properties: {
          addressPrefix: containerAppsSubnetPrefix
          delegations: [
            {
              name: 'container-apps-delegation'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
    ]
  }
}

var postgresSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, postgresSubnetName)
var containerAppsSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, containerAppsSubnetName)

resource postgresPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: postgresPrivateDnsZoneName
  location: 'global'
  tags: tags
}

resource postgresPrivateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  name: '${postgresPrivateDnsZone.name}/${vnet.name}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: postgresServerName
  location: location
  tags: tags
  sku: {
    name: postgresSkuName
    tier: postgresSkuTier
  }
  properties: {
    version: postgresVersion
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: postgresStorageSizeGB
    }
    backup: {
      backupRetentionDays: postgresBackupRetentionDays
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: postgresSubnetId
      privateDnsZoneArmResourceId: postgresPrivateDnsZone.id
    }
    authentication: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
  }
  dependsOn: [
    postgresPrivateDnsZoneLink
  ]
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgresServer
  name: postgresDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

var logAnalyticsSharedKey = listKeys(logAnalytics.id, '2022-10-01').primarySharedKey

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: containerAppsSubnetId
      internal: false
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticWebAppName
  location: staticWebAppLocation
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    allowConfigFileUpdates: true
    enterpriseGradeCdnStatus: 'Disabled'
    publicNetworkAccess: 'Enabled'
  }
}

resource azureOpenAI 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: azureOpenAIAccountName
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: toLower(azureOpenAIAccountName)
    publicNetworkAccess: 'Enabled'
  }
}

output acrLoginServer string = acr.properties.loginServer
output keyVaultUri string = keyVault.properties.vaultUri
output containerAppsEnvId string = containerAppsEnv.id
output staticWebAppDefaultHostname string = staticWebApp.properties.defaultHostname
output postgresServerFqdn string = postgresServer.properties.fullyQualifiedDomainName
output postgresDatabaseName string = postgresDatabaseName
output postgresAdminLogin string = postgresAdminLogin
output storageAccountNameOut string = storageAccount.name
output storageFileShareName string = minioShareName
output openAIEndpoint string = 'https://${azureOpenAI.name}.openai.azure.com/'
