import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ecrdeploy from 'cdk-ecr-deployment';
// There are no official hand-written (L2) constructs for this service yet. 
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import path from 'path';
import * as assets from 'aws-cdk-lib/aws-ecr-assets';
 

export class InfraStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const role = new iam.Role(this, "AgentRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
    });

    role.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      resources: ["*"],
    }));
    
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:GetRepositoryPolicy", "ecr:DescribeRepositories", "ecr:ListImages", "ecr:BatchGetImage"],
      resources: ["*"],
    }));

    role.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName("CloudWatchFullAccess")
    );

    // AgentCore Memory data plane (short-term events)
    role.addToPolicy(new iam.PolicyStatement({
      actions: [
        "bedrock-agentcore:CreateEvent",
        "bedrock-agentcore:ListEvents",
        "bedrock-agentcore:RetrieveMemoryRecords",
      ],
      resources: ["*"],
    }));

    // Optional: control plane read of memory metadata
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore-control:GetMemory"],
      resources: ["*"],
    }));

    // adding memory
    const cfnMemory = new bedrockagentcore.CfnMemory(this, 'MyCfnMemory', {
      name: 'MyAgentMemory',
      eventExpiryDuration: 10,
      // the properties below are optional
      description: 'My Agent Memory',
      memoryExecutionRoleArn: role.roleArn,
      memoryStrategies: [{
        summaryMemoryStrategy: {
          name: 'SessionSummarizer',
          namespaces: ['/summaries/{actorId}/{sessionId}'],
        }
      }],
      tags: {
        Environment: "dev",
        Application: "sample_agent_langchain",
      },
    });

    cfnMemory.node.addDependency(role);

    // Create an ECR repository for the agent image
    const repository = new ecr.Repository(this, 'SampleAgentLangchainRepository', {
      repositoryName: 'sample-agent-langchain',
      lifecycleRules: [{
        description: 'Keeps a maximum number of images to minimize storage',
        maxImageCount: 10,
      }],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Allow the AgentCore execution role to pull images from this repository
    repository.grantPull(role);

    // Build a Docker image asset from local agent directory
    const dockerImageAsset = new assets.DockerImageAsset(this, 'SampleAgentLangchainImage', {
      directory: path.join(__dirname, '..','..', 'agent'),
      buildArgs: {},
      invalidation: { buildArgs: false },
      platform: assets.Platform.LINUX_ARM64,
    });

    // Push the built image to the ECR repository with :latest tag
    const ecrPush = new ecrdeploy.ECRDeployment(this, 'DeployDockerImage', {
      src: new ecrdeploy.DockerImageName(dockerImageAsset.imageUri),
      dest: new ecrdeploy.DockerImageName(`${repository.repositoryUri}:v8.0.0`),
    });

    const agentRuntime = new bedrockagentcore.CfnRuntime(this, "AgentRuntime", {
      agentRuntimeName: "sample_agent_langchain",
      description: "Sample AgentCore runtime (LangChain minimal agent)",
      roleArn: role.roleArn,
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: `${repository.repositoryUri}:v8.0.0`,
        },
      },
      protocolConfiguration: "HTTP",
      networkConfiguration: {
        networkMode: "PUBLIC",
      },
      environmentVariables: {
        LOG_LEVEL: 'INFO',
        MEMORY_ID: cfnMemory.attrMemoryId,
      },
      tags: {
        Environment: "dev",
        Application: "sample_agent_langchain",
      },
    });

    agentRuntime.node.addDependency(repository);
    agentRuntime.node.addDependency(dockerImageAsset);
    agentRuntime.node.addDependency(ecrPush);
    agentRuntime.node.addDependency(cfnMemory);




    new cdk.CfnOutput(this, "AgentRuntimeArn", {
      value: agentRuntime.attrAgentRuntimeArn,
      description: "AgentCore Runtime ARN",
      exportName: "AgentCoreRuntimeArn",
    });

    new cdk.CfnOutput(this, "EndpointName", {
      value: "DEFAULT",
      description: "Runtime Endpoint Name (DEFAULT auto-created)",
      exportName: "AgentCoreEndpointName",
    });

    new cdk.CfnOutput(this, "Region", {
      value: cdk.Stack.of(this).region,
      description: "AWS Region for AgentCore Runtime",
      exportName: "AgentCoreRegion",
    });

    new cdk.CfnOutput(this, "MemoryId", {
      value: cfnMemory.attrMemoryId,
      description: "Memory ID",
      exportName: "AgentCoreMemoryId",
    });

  }
}
