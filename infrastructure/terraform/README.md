# Terraform — OVH Managed Kubernetes + Route53 DNS

Provisions the infrastructure the [`eoapi-workshop` Helm chart](../charts/eoapi-workshop)
runs on:

- A **3-node `b3-16` OVH Managed Kubernetes** cluster (single fixed-size node pool).
- A private network, subnet and router (nodes egress to the internet via the
  router's external gateway).
- **ingress-nginx** (installed via Helm), whose OVH-provisioned load balancer is
  the cluster's public entry point.
- **cert-manager** (installed via Helm; toggle with `enable_cert_manager`), used
  by the workshop chart for Let's Encrypt TLS.
- A **wildcard `A` record** `*.eoapi-workshop.ds.io` in **AWS Route53** pointing
  at that load balancer's IP.

Terraform owns the cluster **platform** (ingress-nginx, cert-manager); the
workshop chart's `deploy.sh` owns the **application** (PGO + the eoAPI release).
So `deploy.sh teardown` never removes platform controllers — `terraform destroy`
does. This avoids `deploy.sh` deleting resources out from under Terraform's state.

Every workshop service is served at the root of its own subdomain under the
wildcard (`stac.`, `raster.`, `vector.`, `browser.`, `manager.`, `lab-01.`, …),
so the one wildcard record covers all of them.

## How the ingress IP + DNS are wired

OVH Managed Kubernetes provisions a load balancer whenever you create a
Service of type `LoadBalancer`, and assigns it a public IP asynchronously — and
it does **not** honour the `loadbalancer.openstack.org/load-balancer-id`
annotation to adopt a pre-created Octavia LB (verified: it just makes its own).

So rather than pre-create a LB, Terraform:

1. installs **ingress-nginx** (`helm_release`), which creates the Service and
   causes OVH to provision the LB;
2. waits ~90s, then **reads the IP** OVH assigned via a `kubernetes_service`
   data source (`ingress.tf`);
3. creates the Route53 wildcard record from that IP (`dns.tf`).

All in one `terraform apply`. If OVH hasn't assigned the IP within the grace
period, the apply errors on the DNS record — just re-run `terraform apply` and
the data source re-reads the now-assigned IP. The IP is chosen by OVH at
LB-creation time and changes if ingress-nginx is destroyed and recreated.

The chart's `deploy.sh` detects this ingress-nginx install (the `nginx`
ingressclass) and leaves it untouched.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.9
- An **OVH API token**: <https://www.ovh.com/auth/api/createToken?GET=/*&POST=/*&PUT=/*&DELETE=/*>
  (note the application key, application secret, consumer key)
- A dedicated **OpenStack user** (`user-xxxxxxxx`) on the project — **not** your
  OVH SSO login
  ([guide](https://help.ovhcloud.com/csm/en-public-cloud-compute-openstack-users?id=kb_article_view&sysparm_article=KB0050636)).
  Download its RC file for the exact `OS_USERNAME` / `OS_TENANT_ID` / region.
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
| `providers.tf`  | `ovh`, `openstack`, `aws`, `helm`, `kubernetes` provider config |
| `variables.tf`  | Input variables (all defaults documented) |
| `network.tf`    | Private network, subnet, router |
| `kube.tf`       | Managed Kubernetes cluster + `b3-16` node pool |
| `ingress.tf`    | ingress-nginx (Helm) + reads the LB IP OVH assigns |
| `cert_manager.tf` | cert-manager (Helm) for Let's Encrypt TLS |
| `dns.tf`        | Route53 wildcard `A` record → the ingress LB IP |
| `outputs.tf`    | kubeconfig, cluster ID, ingress public IP |
