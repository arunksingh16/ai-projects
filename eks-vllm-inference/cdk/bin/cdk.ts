#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { ModelStorageStack } from '../lib/model-storage-stack';
import { NetworkingStack } from '../lib/networking-stack';
import { EksStack } from '../lib/eks-stack';

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region:  process.env.CDK_DEFAULT_REGION ?? 'eu-west-1',
};

// Stack 1 — S3 bucket for model weights
const storageStack = new ModelStorageStack(app, 'ModelStorageStack', {
  env,
  description: 'S3 model artifact storage for LLM inference POC',
});

// Stack 2 — VPC and subnet configuration
const networkingStack = new NetworkingStack(app, 'NetworkingStack', {
  env,
  description: 'VPC with public + private subnets for the inference cluster',
});

// Stack 3 — EKS cluster, node groups, addons, namespaces, IRSA roles
const eksStack = new EksStack(app, 'EksStack', {
  env,
  description: 'EKS cluster with GPU inference node group, EBS CSI driver, and IRSA roles',
  vpc: networkingStack.vpc,
  modelBucketName: storageStack.modelBucket.bucketName,
});

// Explicit dependencies so CloudFormation deploys in the right order
eksStack.addDependency(networkingStack);
eksStack.addDependency(storageStack);

cdk.Tags.of(app).add('Project', 'LLMInferencePOC');
cdk.Tags.of(app).add('ManagedBy', 'CDK');
