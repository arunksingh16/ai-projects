import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as eks from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
import { KubectlV35Layer } from '@aws-cdk/lambda-layer-kubectl-v35';

export interface EksStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  modelBucketName: string;
}

export class EksStack extends cdk.Stack {
  public readonly cluster: eks.Cluster;
  public readonly vllmRole: iam.Role;

  constructor(scope: Construct, id: string, props: EksStackProps) {
    super(scope, id, props);

    // ── Cluster Admin Role ────────────────────────────────────────────────────
    // mastersRole — CDK's kubectl provider Lambda uses this role during cdk deploy.
    // Human access — assume this role for kubectl + AWS console cluster-admin.
    //
    // After cdk deploy, configure kubectl using the KubeconfigCommand output.
    // Your IAM identity needs sts:AssumeRole on this role; if it fails, attach:
    //   {"Effect":"Allow","Action":"sts:AssumeRole","Resource":"<ClusterAdminRoleArn>"}
    const clusterAdminRole = new iam.Role(this, 'ClusterAdminRole', {
      roleName: 'llm-inference-poc-cluster-admin',
      assumedBy: new iam.AccountRootPrincipal(),
      description: 'Assume this role to access EKS cluster via kubectl and AWS console',
    });

    clusterAdminRole.addToPolicy(new iam.PolicyStatement({
      actions: ['sts:AssumeRole'],
      resources: ['*'],
    }));

    // ── EKS Cluster ───────────────────────────────────────────────────────────
    this.cluster = new eks.Cluster(this, 'InferenceCluster', {
      vpc: props.vpc,
      vpcSubnets: [{ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }],
      version: eks.KubernetesVersion.V1_33,
      defaultCapacity: 0, // node groups defined explicitly below
      clusterName: 'llm-inference-poc',
      kubectlLayer: new KubectlV35Layer(this, 'KubectlLayer'),
      mastersRole: clusterAdminRole,
      // API_AND_CONFIG_MAP: enables Access Entries (EKS 1.28+) while keeping
      // aws-auth ConfigMap so managed node groups can still register themselves.
      authenticationMode: eks.AuthenticationMode.API_AND_CONFIG_MAP,
    });

    // ── System Node Group ─────────────────────────────────────────────────────
    // Runs cluster-critical services: CoreDNS, Prometheus, Grafana
    this.cluster.addNodegroupCapacity('system-nodes', {
      instanceTypes: [new ec2.InstanceType('m5.large')],
      minSize: 1,
      maxSize: 2,
      capacityType: eks.CapacityType.ON_DEMAND,
      labels: { role: 'system' },
      subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      nodegroupName: 'system-nodes',
      amiType: eks.NodegroupAmiType.AL2023_X86_64_STANDARD,
    });

    // ── GPU Inference Node Group ──────────────────────────────────────────────
    // g5.xlarge: 24GB VRAM, enough to serve Mistral-7B-Instruct-v0.2.
    // NOTE: For faster provisioning (60–90s vs 3–4 min) replace with Karpenter.
    this.cluster.addNodegroupCapacity('gpu-inference', {
      instanceTypes: [new ec2.InstanceType('g5.xlarge')],
      diskSize: 200, // EBS root volume for model caching via hostPath
      minSize: 1,
      maxSize: 3,
      capacityType: eks.CapacityType.ON_DEMAND,
      labels: { role: 'inference', workload: 'gpu' },
      taints: [
        {
          key: 'nvidia.com/gpu',
          value: 'true',
          effect: eks.TaintEffect.NO_SCHEDULE,
        },
      ],
      subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      nodegroupName: 'gpu-inference',
      amiType: eks.NodegroupAmiType.AL2023_X86_64_NVIDIA,
    });

    // ── IRSA helper ───────────────────────────────────────────────────────────
    // clusterOpenIdConnectIssuer is a Token (Fn::GetAtt) — cannot be used as a
    // plain object key at synth time. CfnJson defers the condition map to deploy time.
    const oidcIssuer = this.cluster.clusterOpenIdConnectIssuer;
    const oidcProviderArn = this.cluster.openIdConnectProvider.openIdConnectProviderArn;

    // ── IRSA: vLLM → S3 ──────────────────────────────────────────────────────
    // ServiceAccount (vllm in inference ns) is managed in k8s/service-accounts.yaml.
    // Annotate it with VllmRoleArn from CDK outputs.
    const modelBucket = s3.Bucket.fromBucketName(this, 'ModelBucket', props.modelBucketName);

    this.vllmRole = new iam.Role(this, 'VllmRole', {
      assumedBy: new iam.WebIdentityPrincipal(oidcProviderArn, {
        StringEquals: new cdk.CfnJson(this, 'VllmOidcCondition', {
          value: {
            [`${oidcIssuer}:sub`]: 'system:serviceaccount:inference:vllm',
            [`${oidcIssuer}:aud`]: 'sts.amazonaws.com',
          },
        }),
      }),
    });
    modelBucket.grantRead(this.vllmRole);

    // ── IRSA: OTel Collector → CloudWatch ────────────────────────────────────
    // ServiceAccount (otel-collector in observability ns) is managed in
    // k8s/service-accounts.yaml. Annotate it with OtelCollectorRoleArn.
    const otelRole = new iam.Role(this, 'OtelRole', {
      assumedBy: new iam.WebIdentityPrincipal(oidcProviderArn, {
        StringEquals: new cdk.CfnJson(this, 'OtelOidcCondition', {
          value: {
            [`${oidcIssuer}:sub`]: 'system:serviceaccount:observability:otel-collector',
            [`${oidcIssuer}:aud`]: 'sts.amazonaws.com',
          },
        }),
      }),
    });
    otelRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'cloudwatch:PutMetricData',
        'logs:CreateLogGroup',
        'logs:CreateLogStream',
        'logs:PutLogEvents',
        'logs:DescribeLogStreams',
      ],
      resources: ['*'],
    }));

    // ── Outputs ───────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ClusterName', {
      value: this.cluster.clusterName,
      description: 'EKS cluster name',
    });

    new cdk.CfnOutput(this, 'ClusterAdminRoleArn', {
      value: clusterAdminRole.roleArn,
      description: 'IAM role ARN for kubectl + console access',
    });

    new cdk.CfnOutput(this, 'KubeconfigCommand', {
      value: `aws eks update-kubeconfig --name llm-inference-poc --role-arn ${clusterAdminRole.roleArn} --region ${this.region}`,
      description: 'Run this after deploy to configure kubectl',
    });

    new cdk.CfnOutput(this, 'VllmRoleArn', {
      value: this.vllmRole.roleArn,
      description: 'Paste into eks.amazonaws.com/role-arn annotation on the vllm ServiceAccount in k8s/service-accounts.yaml',
    });

    new cdk.CfnOutput(this, 'OtelCollectorRoleArn', {
      value: otelRole.roleArn,
      description: 'Paste into eks.amazonaws.com/role-arn annotation on the otel-collector ServiceAccount in k8s/service-accounts.yaml',
    });
  }
}
