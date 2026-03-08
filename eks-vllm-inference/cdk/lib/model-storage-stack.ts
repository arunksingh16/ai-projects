import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export class ModelStorageStack extends cdk.Stack {
  public readonly modelBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ── Model Artifact Bucket ─────────────────────────────────────────────────
    // Versioning enabled: allows safe rollback if a new model checkpoint breaks
    // inference. Combined with a lifecycle rule to expire old versions after 30
    // days so storage costs don't accumulate.
    //
    // Access is granted to vLLM pods via IRSA (see networking-eks-stack.ts).
    // No credentials in the pod — only IAM role assumption from the service account.
    this.modelBucket = new s3.Bucket(this, 'ModelArtifactBucket', {
      bucketName: `llm-model-artifacts-${this.account}-${this.region}`,
      versioned: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN, // do NOT delete model weights on stack teardown

      lifecycleRules: [
        {
          id: 'expire-old-model-versions',
          enabled: true,
          noncurrentVersionExpiration: cdk.Duration.days(30),
        },
        {
          id: 'abort-incomplete-multipart',
          enabled: true,
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(1),
        },
      ],
    });

    // ── Expected S3 layout ────────────────────────────────────────────────────
    // s3://<bucket>/models/mistral-7b-instruct-v0.2/
    //   config.json
    //   tokenizer.json
    //   tokenizer_config.json
    //   special_tokens_map.json
    //   pytorch_model-00001-of-00002.bin  (or .safetensors shards)
    //   pytorch_model-00002-of-00002.bin
    //   generation_config.json
    //
    // Upload command (run from wherever you have the weights):
    //   aws s3 sync ./mistral-7b-instruct-v0.2 \
    //     s3://<bucket>/models/mistral-7b-instruct-v0.2/ \
    //     --storage-class INTELLIGENT_TIERING

    // ── Outputs ───────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ModelBucketName', {
      value: this.modelBucket.bucketName,
      description: 'Set MODEL_BUCKET env var in vLLM init container',
    });

    new cdk.CfnOutput(this, 'ModelBucketArn', {
      value: this.modelBucket.bucketArn,
    });
  }
}
