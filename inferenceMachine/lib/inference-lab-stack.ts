import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface InferenceLabStackProps extends cdk.StackProps {
  readonly availabilityZone: string;
  readonly instanceType: string;
  readonly machineImageId: string;
}

/** A single-AZ inference lab with compute and data as separate lifecycle boundaries. */
export class InferenceLabStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: InferenceLabStackProps) {
    super(scope, id, props);
    const tags = { Application: 'inference-lab', Environment: 'personal', ManagedBy: 'cdk', Purpose: 'inference-pocs' };
    Object.entries(tags).forEach(([key, value]) => cdk.Tags.of(this).add(key, value));

    const vpc = new ec2.Vpc(this, 'InferenceLabVpc', {
      vpcName: 'inference-lab-ec1-vpc', availabilityZones: [props.availabilityZone], natGateways: 0,
      subnetConfiguration: [{ name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24, mapPublicIpOnLaunch: true }],
    });
    const securityGroup = new ec2.SecurityGroup(this, 'InferenceLabSecurityGroup', {
      vpc, securityGroupName: 'inference-lab-ec1-ssm-only',
      description: 'No inbound access; operator access is only through SSM.', allowAllOutbound: true,
    });
    const role = new iam.Role(this, 'InferenceLabInstanceRole', {
      roleName: 'inference-lab-ec1-instance-role', assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'SSM management role for the inference lab instance.',
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')],
    });
    const dataVolume = new ec2.CfnVolume(this, 'InferenceLabDataVolume', {
      availabilityZone: props.availabilityZone, encrypted: true, size: 500, volumeType: 'gp3',
      tags: [{ key: 'Name', value: 'inference-lab-ec1-data' }, ...Object.entries(tags).map(([key, value]) => ({ key, value }))],
    });
    // Preserve real lab data on deletion/update, but do not strand an empty
    // disk when an initial stack creation rolls back before an instance boots.
    dataVolume.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE);
    const instance = new ec2.Instance(this, 'InferenceLabInstance', {
      instanceName: 'inference-lab-ec1-instance', instanceType: new ec2.InstanceType(props.instanceType),
      machineImage: ec2.MachineImage.genericLinux({ [this.region]: props.machineImageId }), vpc,
      vpcSubnets: { subnets: [vpc.publicSubnets[0]] }, securityGroup, role, requireImdsv2: true, detailedMonitoring: true,
      blockDevices: [{ deviceName: '/dev/sda1', volume: ec2.BlockDeviceVolume.ebs(100, { encrypted: true, volumeType: ec2.EbsDeviceVolumeType.GP3, deleteOnTermination: true }) }],
    });
    cdk.Tags.of(instance).add('Name', 'inference-lab-ec1-instance');
    const attachment = new ec2.CfnVolumeAttachment(this, 'InferenceLabDataVolumeAttachment', { device: '/dev/sdf', instanceId: instance.instanceId, volumeId: dataVolume.ref });
    attachment.addDependency(dataVolume);
    instance.addUserData(
      '#!/bin/bash', 'set -euxo pipefail', 'mkdir -p /data',
      // Attachments created after instance launch are absent from IMDS. Embed
      // the CloudFormation volume ID, then wait for its Nitro NVMe symlink.
      `VOLUME_ID='${dataVolume.ref}'`,
      'VOLUME_SERIAL=$(printf "%s" "$VOLUME_ID" | tr -d "-")',
      'for attempt in $(seq 1 60); do DATA_DEVICE=$(readlink -f "/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_$VOLUME_SERIAL" || true); [ -n "${DATA_DEVICE:-}" ] && break; sleep 2; done',
      'test -n "${DATA_DEVICE:-}"', 'if ! blkid "$DATA_DEVICE"; then mkfs.ext4 -F "$DATA_DEVICE"; fi',
      'UUID=$(blkid -s UUID -o value "$DATA_DEVICE")',
      'grep -q "UUID=$UUID /data " /etc/fstab || echo "UUID=$UUID /data ext4 defaults,nofail 0 2" >> /etc/fstab',
      'mountpoint -q /data || mount /data', 'chmod 0755 /data',
    );
    new cdk.CfnOutput(this, 'InstanceId', { value: instance.instanceId });
    new cdk.CfnOutput(this, 'DataVolumeId', { value: dataVolume.ref });
    new cdk.CfnOutput(this, 'PortForwardExample', { value: `AWS_PROFILE=<profile> AWS_REGION=${this.region} scripts/inference-lab port-forward 8000 8000` });
  }
}
