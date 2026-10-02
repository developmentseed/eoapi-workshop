# The workshop node pool on an existing OVH cluster not created by ../ (for one
# that is, set `workshop_node_count` there). OVH labels the nodes
# nodepool=<pool_name>; select them with participant/chart's `nodeSelector`.

terraform {
  required_version = ">= 1.9.0"
  required_providers {
    ovh = {
      source  = "ovh/ovh"
      version = "~> 2.12"
    }
  }
}

variable "project_id" {
  description = "OVH public cloud project (tenant) ID"
  type        = string
}

variable "kube_id" {
  description = "ID of the existing managed Kubernetes cluster (Public Cloud → Managed Kubernetes → the cluster's ID)"
  type        = string
}

variable "pool_name" {
  description = "Node pool name; nodes get the label nodepool=<pool_name>"
  type        = string
  default     = "workshop"
}

variable "node_flavor" {
  description = "OVH flavor for the pool's nodes"
  type        = string
  default     = "b3-16"
}

variable "node_count" {
  description = "Number of nodes in the pool; sizing in ../README.md \"Workshop node pool\""
  type        = number
  default     = 3
}

variable "ovh_endpoint" {
  description = "OVH API endpoint"
  type        = string
  default     = "ovh-eu"
}

variable "ovh_application_key" {
  type      = string
  sensitive = true
}

variable "ovh_application_secret" {
  type      = string
  sensitive = true
}

variable "ovh_consumer_key" {
  type      = string
  sensitive = true
}

provider "ovh" {
  endpoint           = var.ovh_endpoint
  application_key    = var.ovh_application_key
  application_secret = var.ovh_application_secret
  consumer_key       = var.ovh_consumer_key
}

resource "ovh_cloud_project_kube_nodepool" "workshop" {
  service_name  = var.project_id
  kube_id       = var.kube_id
  name          = var.pool_name
  flavor_name   = var.node_flavor
  autoscale     = false
  desired_nodes = var.node_count
  min_nodes     = var.node_count
  max_nodes     = var.node_count
}
