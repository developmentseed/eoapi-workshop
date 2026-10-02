###############################################################################
# OVH / OpenStack
###############################################################################

variable "region" {
  description = "OVH region for the cluster (UPPERCASE, e.g. GRA11, DE1). See https://www.ovhcloud.com/en/public-cloud/regions-availability/"
  type        = string
}

variable "project_id" {
  description = "OVH public cloud project (tenant) ID"
  type        = string
}

variable "ovh_endpoint" {
  description = "OVH API endpoint"
  type        = string
  default     = "ovh-eu"
}

variable "ovh_application_key" {
  description = "Application Key for the OVH API token"
  type        = string
  sensitive   = true
}

variable "ovh_application_secret" {
  description = "Application Secret for the OVH API token"
  type        = string
  sensitive   = true
}

variable "ovh_consumer_key" {
  description = "Consumer Key for the OVH API token"
  type        = string
  sensitive   = true
}

variable "openstack_username" {
  description = "OpenStack username (horizon.cloud.ovh.net user)"
  type        = string
  sensitive   = true
}

variable "openstack_password" {
  description = "OpenStack password"
  type        = string
  sensitive   = true
}

###############################################################################
# Kubernetes cluster
###############################################################################

variable "cluster_name" {
  description = "Name of the managed Kubernetes cluster"
  type        = string
  default     = "eoapi-workshop"
}

variable "kube_version" {
  description = "Kubernetes minor version for the managed cluster"
  type        = string
  default     = "1.35"
}

variable "node_flavor" {
  description = "OVH flavor for the worker nodes. See https://www.ovhcloud.com/en/public-cloud/prices/"
  type        = string
  default     = "b3-16"
}

variable "node_count" {
  description = "Number of worker nodes in the pool"
  type        = number
  default     = 3
}

variable "workshop_node_count" {
  description = "Nodes in the extra `workshop` pool (0 = no pool). 20 participants need 6× b3-16 or 3–4× b3-32, one spare included (participant/README.md \"Sizing\")."
  type        = number
  default     = 0
}

variable "workshop_node_flavor" {
  description = "OVH flavor for the workshop pool's nodes"
  type        = string
  default     = "b3-16"
}

variable "ingress_nginx_chart_version" {
  description = "ingress-nginx Helm chart version to install. Empty string installs the latest; pin for reproducibility."
  type        = string
  default     = ""
}

variable "enable_cert_manager" {
  description = "Install cert-manager (for Let's Encrypt TLS). Harmless when idle."
  type        = bool
  default     = true
}

variable "cert_manager_chart_version" {
  description = "cert-manager Helm chart version. Empty string installs the latest; pin for reproducibility."
  type        = string
  default     = ""
}

###############################################################################
# DNS (AWS Route53)
###############################################################################

variable "aws_region" {
  description = "AWS region for the provider (Route53 itself is global)"
  type        = string
  default     = "us-east-1"
}

variable "route53_zone_name" {
  description = "Name of the existing Route53 hosted zone that owns the record"
  type        = string
  default     = "ds.io"
}

variable "wildcard_domain" {
  description = "Wildcard hostname to point at the cluster ingress load balancer"
  type        = string
  default     = "*.eoapi-workshop.ds.io"
}

variable "dns_record_ttl" {
  description = "TTL (seconds) for the wildcard A record"
  type        = number
  default     = 300
}
