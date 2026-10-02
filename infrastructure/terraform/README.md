# Terraform — OVH Managed Kubernetes + Route53 DNS

Provisions the infrastructure the per-participant stacks
([`spike/`](../../spike/README.md)) run on:

- A **3-node `b3-16` OVH Managed Kubernetes** cluster (fixed-size `workers`
  pool), plus an optional `workshop` pool for the event itself (see
  [Workshop node pool](#workshop-node-pool)).
- A private network, subnet and router (nodes egress to the internet via the
  router's external gateway).
- **ingress-nginx** (installed via Helm), whose OVH-provisioned load balancer is
  the cluster's public entry point.
- **cert-manager** (installed via Helm; toggle with `enable_cert_manager`), for
  Let's Encrypt TLS. Nothing here creates an issuer or certificate: `spike/chart`
  takes a pre-issued secret (`ingress.tlsSecret`).
- A **wildcard `A` record** `*.eoapi-workshop.ds.io` in **AWS Route53** pointing
  at that load balancer's IP.

Terraform owns the cluster **platform** (ingress-nginx, cert-manager);
`spike/deploy.sh` owns the participant release and never touches the
controllers. `terraform destroy` removes them.

Each participant's stack is served at its own subdomain under the wildcard
(`lab-u01.`, `lab-u02.`, …), so the one wildcard record covers all of them.

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

`spike/chart` routes through this install: its Ingress uses the `nginx` class,
and its NetworkPolicy admits only the `ingress-nginx` namespace.

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

Then grab the kubeconfig and deploy the participant stacks with
`spike/deploy.sh` (see [`spike/README.md`](../../spike/README.md)):

```bash
terraform output -raw kubeconfig > kubeconfig.yaml
export KUBECONFIG=$PWD/kubeconfig.yaml
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
| `kube.tf`       | Managed Kubernetes cluster + `b3-16` node pool + optional `workshop` pool |
| `ingress.tf`    | ingress-nginx (Helm) + reads the LB IP OVH assigns |
| `cert_manager.tf` | cert-manager (Helm) for Let's Encrypt TLS |
| `dns.tf`        | Route53 wildcard `A` record → the ingress LB IP |
| `outputs.tf`    | kubeconfig, cluster ID, ingress public IP |
| `workshop-pool/` | Standalone root: just the `workshop` pool, on any existing OVH cluster |

## Workshop node pool

Extra nodes for the event itself, added before and removed after. Nodes are
labelled `nodepool=workshop`; set `nodeSelector: { nodepool: workshop }` in
`spike/chart`'s values to put the participant pods on them.

Each participant pod requests 2.75 GiB, so a `b3-16` holds 4 and a `b3-32` 8–10
([`spike/README.md` "Sizing"](../../spike/README.md#sizing)). Keep one spare
node: 20 participants need 6× `b3-16`, or 3–4× `b3-32`.

- **Cluster created by this stack:** set `workshop_node_count = 6` in
  `terraform.tfvars` and `terraform apply`; set it back to `0` and apply to
  remove the pool.
- **Any other existing OVH cluster:** use the standalone `workshop-pool/` root,
  which manages only the pool (OVH API token + the cluster's ID):

  ```bash
  cd workshop-pool
  cp terraform.tfvars.example terraform.tfvars   # project_id, kube_id, OVH API keys, node_count
  terraform init && terraform apply              # add the pool (~5–10 min)
  terraform destroy                              # remove it after the workshop
  ```

Each node pulls about 3.4 GiB of images: add the pool the day before and deploy
with `prepull: true` so they are cached when participants arrive.

Tear the release down (`CONFIRM=NAMESPACE spike/deploy.sh CONTEXT NAMESPACE down`)
before removing the pool, or the participant pods sit `Pending` with nowhere to
run.
