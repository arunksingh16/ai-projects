


## Install CSI driver for Amazon EBS

```
eksctl create iamserviceaccount \
--name ebs-csi-controller-sa \
--namespace kube-system \
--cluster my-cluster \
--role-name AmazonEKS_EBS_CSI_DriverRole \
--role-only \
--attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy \
--approve
```

the above command:
- Creates an IAM Role
- Configures it for IRSA (OIDC trust relationship)
- Associates it with the service account ebs-csi-controller-sa

That is the classic and most common method used for EKS add-ons.

Make sure your cluster has OIDC enabled, otherwise IRSA won't work. If empty, enable the oidc.
```
aws eks describe-cluster \
--name llm-inference-poc \
--query "cluster.identity.oidc.issuer" \
--output text
```

After this open console and go to add on 

<img width="1600" height="674" alt="image" src="https://github.com/user-attachments/assets/fd37417b-0457-4c66-bc0f-85c5671e6b10" />

After installation you should see

<img width="932" height="181" alt="image" src="https://github.com/user-attachments/assets/7f7ee731-4f1c-4160-93ee-1e86211506de" />

## Install AWS Load Balancer Controller with Helm

```
# Admin access entry for your IAM role:
aws eks create-access-entry \
  --cluster-name llm-inference-poc \
  --principal-arn arn:aws:iam::xx:user/terraform \
  --region eu-west-1

# Then attach admin permissions:
aws eks associate-access-policy \
  --cluster-name llm-inference-poc \
  --principal-arn arn:aws:iam::<aws_account>:user/terraform-dmytro \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster \
  --region eu-west-1
# Use profile
eksctl create iamserviceaccount \
--cluster llm-inference-poc \
--namespace kube-system \
--name aws-load-balancer-controller \
--attach-policy-arn arn:aws:iam::<aws_account>:policy/AWSLoadBalancerControllerIAMPolicy \
--override-existing-serviceaccounts \
--region eu-west-1 \
--profile <user profile> \
--approve

# install
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=my-cluster \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set region=eu-west-1 \
  --set vpcId=<vpc-id> \
  --version 1.14.0
```

once done check pod status 

<img width="1600" height="167" alt="image" src="https://github.com/user-attachments/assets/31f8456d-de14-45d8-963d-8c59f36d6703" />
