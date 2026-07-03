provider "ovh" {
  endpoint           = var.ovh_endpoint
  application_key    = var.ovh_application_key
  application_secret = var.ovh_application_secret
  consumer_key       = var.ovh_consumer_key
}

provider "openstack" {
  auth_url            = "https://auth.cloud.ovh.net/v3/"
  domain_name         = "default"
  region              = var.region
  user_domain_name    = "Default"
  project_domain_name = "Default"
  tenant_id           = var.project_id
  user_name           = var.openstack_username
  password            = var.openstack_password
}

# AWS is only used for the Route53 wildcard record. Route53 is a global
# service; the region here just satisfies the provider. Credentials are read
# from the standard AWS chain (env vars, shared config, SSO) — nothing is
# committed to this repo.
provider "aws" {
  region = var.aws_region
}

# helm + kubernetes talk to the cluster this stack creates, using the kubeconfig
# OVH returns for it. Used to install ingress-nginx and read the public IP OVH
# assigns to its load balancer (see ingress.tf).
provider "helm" {
  kubernetes = {
    host                   = ovh_cloud_project_kube.primary.kubeconfig_attributes[0].host
    client_certificate     = base64decode(ovh_cloud_project_kube.primary.kubeconfig_attributes[0].client_certificate)
    client_key             = base64decode(ovh_cloud_project_kube.primary.kubeconfig_attributes[0].client_key)
    cluster_ca_certificate = base64decode(ovh_cloud_project_kube.primary.kubeconfig_attributes[0].cluster_ca_certificate)
  }
}

provider "kubernetes" {
  host                   = ovh_cloud_project_kube.primary.kubeconfig_attributes[0].host
  client_certificate     = base64decode(ovh_cloud_project_kube.primary.kubeconfig_attributes[0].client_certificate)
  client_key             = base64decode(ovh_cloud_project_kube.primary.kubeconfig_attributes[0].client_key)
  cluster_ca_certificate = base64decode(ovh_cloud_project_kube.primary.kubeconfig_attributes[0].cluster_ca_certificate)
}
