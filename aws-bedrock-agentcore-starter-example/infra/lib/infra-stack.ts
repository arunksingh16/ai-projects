import * as fs from "fs";
import * as path from "path";
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ecr from "aws-cdk-lib/aws-ecr";

export class InfraStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const policyPath = path.join(__dirname, "./../", "iampolicy.json");
    const policy = JSON.parse(fs.readFileSync(policyPath, "utf8"));

    // Define trust policy via assumedBy with conditions
    // This adds extra security constraints — even though Bedrock AgentCore is the principal, it can only assume the role under these conditions:
    // 1. The source account must be <account-id> (your AWS account ID)
    // 2. The source ARN must match the pattern arn:aws:bedrock-agentcore:us-east-1:<account-id>:*
    // This ensures that only Bedrock AgentCore can assume this role, and only in the specified region and account.
    // 🔐 Why This Is Needed
    // If you're building a Bedrock Agent and assigning it a role for runtime execution (e.g., to log to CloudWatch, call ECR, X-Ray, etc.), you need to:
    // Trust bedrock-agentcore.amazonaws.com
    // Secure that trust using SourceAccount + SourceArn conditions
    // This ensures only Bedrock agents in your own account and region can assume the role — not random agents elsewhere.

    const assumedBy = new iam.PrincipalWithConditions(
      new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      {
        StringEquals: {
          "aws:SourceAccount": "<account-id>",
        },
        ArnLike: {
          "aws:SourceArn": "arn:aws:bedrock-agentcore:us-east-1:<account-id>:*",
        },
      },
    );

    // Create the IAM role with the trust policy
    const role = new iam.Role(this, "MyBedrockAgentRole", {
      assumedBy,
      roleName: "MyBedrockAgentRole",
    });

    // Attach inline policy from JSON
    const inlinePolicy = new iam.Policy(this, "MyInlinePolicy", {
      document: iam.PolicyDocument.fromJson(policy),
    });
    role.attachInlinePolicy(inlinePolicy);

    // Create ECR repository
    const repository = new ecr.Repository(this, "BedrockAgentCoreRepository", {
      repositoryName: "bedrock-agentcore",
    });
    
  }
}
