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
