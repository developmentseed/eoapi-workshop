# Terraform — OVH Managed Kubernetes + Route53 DNS

Provisions the infrastructure the [`eoapi-workshop` Helm chart](../charts/eoapi-workshop)
runs on:

- A **3-node `b3-16` OVH Managed Kubernetes** cluster (single fixed-size node pool).
- A private network, subnet and router (nodes egress to the internet via the
  router's external gateway).
- An **Octavia load balancer** with a public floating IP for cluster ingress.
- A **wildcard `A` record** `*.eoapi-workshop.ds.io` in **AWS Route53** pointing
  at that floating IP.

Every workshop service is served at the root of its own subdomain under the
wildcard (`stac.`, `raster.`, `vector.`, `browser.`, `manager.`, `lab-01.`, …),
so the one wildcard record covers all of them.

## Why an Octavia LB + floating IP (not a Service `LoadBalancer`)?

OVH's classic/Neutron-LBaaS load balancer is deprecated in favour of **Octavia**;
`openstack_lb_loadbalancer_v2` is the Octavia resource. We create it (and its
floating IP) up front so the public IP is known at `terraform apply` time and the
Route53 record can be created in the same run. The alternative — letting the
ingress controller create a Service-type `LoadBalancer` — provisions the LB
asynchronously, so its IP isn't available when Terraform needs it for DNS.

Point ingress-nginx at this LB by adding to its controller Service:

```yaml
metadata:
  annotations:
    loadbalancer.openstack.org/load-balancer-id: "<ingress_load_balancer_id output>"
```

so the cloud controller adopts this LB instead of creating a new one.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.9
- An **OVH API token**: <https://www.ovh.com/auth/api/createToken?GET=/*&POST=/*&PUT=/*&DELETE=/*>
  (note the application key, application secret, consumer key)
- An **OpenStack user** on the project
  ([guide](https://help.ovhcloud.com/csm/en-public-cloud-compute-openstack-users?id=kb_article_view&sysparm_article=KB0050636))
- **AWS credentials** with `route53:*` on the hosted zone, via the standard AWS
  chain (`AWS_PROFILE`, env vars, or SSO)

## Usage

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in OVH creds + project_id
terraform init
terraform plan
terraform apply
```

Then grab the kubeconfig and deploy the workshop chart:

```bash
terraform output -raw kubeconfig > kubeconfig.yaml
export KUBECONFIG=$PWD/kubeconfig.yaml
../charts/eoapi-workshop/deploy.sh deploy
```

## State

State is stored **locally** by default (`terraform.tfstate`, git-ignored) to keep
deployment prerequisites minimal. To move to remote state later, uncomment the
`backend "s3"` block in [`versions.tf`](./versions.tf) (OVH Object Storage is
S3-compatible), then run `terraform init -migrate-state`.

## Files

| File | Purpose |
|---|---|
| `versions.tf`   | Terraform + provider versions; commented remote-state backend |
| `providers.tf`  | `ovh`, `openstack`, `aws` provider config |
| `variables.tf`  | Input variables (all defaults documented) |
| `network.tf`    | Private network, subnet, router, Octavia LB + floating IP |
| `kube.tf`       | Managed Kubernetes cluster + `b3-16` node pool |
| `dns.tf`        | Route53 wildcard `A` record |
| `outputs.tf`    | kubeconfig, cluster/LB IDs, ingress public IP |
