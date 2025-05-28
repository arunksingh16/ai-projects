# AWS CDK Application for Amazon Bedrock

This project is an AWS CDK application written in TypeScript. It defines and deploys AWS resources to interact with Amazon Bedrock, a service that provides access to foundation models from AI21 Labs, Anthropic, Stability AI, and Amazon.

## Architecture

The CDK application deploys the following resources:

- **AWS Lambda Function**: A Node.js Lambda function (written in TypeScript) that uses the AWS SDK to invoke a Bedrock model (specifically, `amazon.titan-text-lite-v1`).
- **Amazon API Gateway**: An API Gateway endpoint that triggers the Lambda function. This allows you to send prompts to the Bedrock model via an HTTP POST request.

## Prerequisites

- AWS CDK installed and configured.
- Node.js and npm installed.

## Deployment

1. **Install dependencies**:
   ```bash
   npm install
   ```
2. **Synthesize the CloudFormation template**:
   ```bash
   npx cdk synth
   ```
3. **Deploy the stack**:
   ```bash
   npx cdk deploy
   ```

## Usage

After deployment, the API Gateway endpoint URL will be displayed in the output. You can send a POST request to this endpoint with a JSON body containing a `prompt` field:

```json
{
  "prompt": "Your prompt here"
}
```

The Lambda function will invoke the Bedrock model with your prompt and return the model's response.

## Customization

- **Bedrock Model**: You can change the Bedrock model ID in `lambda/handler.ts`.
- **Lambda Configuration**: You can modify the Lambda function's configuration (e.g., memory, timeout) in `lib/bedrock-stack.ts`.
- **API Gateway**: You can customize the API Gateway settings (e.g., authentication, rate limiting) in `lib/bedrock-stack.ts`.

## Cleanup

To remove the deployed resources, run:

```bash
npx cdk destroy
```
