import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

export class NetworkingStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ── VPC ──────────────────────────────────────────────────────────────────
    this.vpc = new ec2.Vpc(this, 'InferenceVpc', {
      maxAzs: 2,
      natGateways: 1, // single NAT to reduce cost in POC
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
      ],
    });

    // Tag subnets so the AWS Load Balancer Controller can discover them
    this.vpc.publicSubnets.forEach(subnet =>
      cdk.Tags.of(subnet).add('kubernetes.io/role/elb', '1'),
    );
    this.vpc.privateSubnets.forEach(subnet =>
      cdk.Tags.of(subnet).add('kubernetes.io/role/internal-elb', '1'),
    );

    // ── Outputs ───────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'VpcId', {
      value: this.vpc.vpcId,
      description: 'VPC ID for the inference cluster',
    });
  }
}
