import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';

export class BedrockStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const genaiFn = new lambda.Function(this, 'GenAILambda', {
      runtime: lambda.Runtime.NODEJS_18_X,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset('lambda'),
      environment: {
        REGION: `${process.env.CDK_DEFAULT_REGION}`,
      },
      timeout: cdk.Duration.seconds(30)
    });

    // Add permissions to call Bedrock
    genaiFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["bedrock:InvokeModel"],
      resources: ["*"] // scope down later in production
    }));

    // API Gateway setup
    new apigw.LambdaRestApi(this, 'GenAIEndpoint', {
      handler: genaiFn,
      proxy: false,
      defaultMethodOptions: {
        apiKeyRequired: false,
      },
    }).root.addMethod('POST');
  }
}
