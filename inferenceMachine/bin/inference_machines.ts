#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { InferenceLabStack } from '../lib/inference-lab-stack';

const app = new cdk.App();

const requiredContext = (name: string): string => {
  const value = app.node.tryGetContext(name) ?? process.env[name];
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`Missing ${name}. Use scripts/inference-lab deploy or pass --context ${name}=<value>.`);
  }
  return value;
};

const account = process.env.CDK_DEFAULT_ACCOUNT;
const region = process.env.CDK_DEFAULT_REGION;
if (!account || !region) throw new Error('CDK_DEFAULT_ACCOUNT and CDK_DEFAULT_REGION must be set by the AWS profile.');

new InferenceLabStack(app, 'InferenceLabEc1Stack', {
  env: { account, region },
  availabilityZone: requiredContext('availabilityZone'),
  machineImageId: requiredContext('machineImageId'),
  instanceType: (app.node.tryGetContext('instanceType') ?? process.env.INFERENCE_INSTANCE_TYPE ?? 'g6e.2xlarge') as string,
});
