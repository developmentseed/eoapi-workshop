resource "ovh_cloud_project_kube" "primary" {
  service_name       = var.project_id
  name               = var.cluster_name
  region             = var.region
  version            = var.kube_version
  private_network_id = openstack_networking_network_v2.private.id

  private_network_configuration {
    # The subnet gateway (.1) is the router interface, which SNATs node egress
    # to the internet via the router's external gateway on Ext-Net.
    default_vrack_gateway              = "192.168.12.1"
    private_network_routing_as_default = true
  }

  # Nodes can only attach once the router interface links the subnet to the
  # routed network; be explicit so Terraform orders it correctly.
  depends_on = [openstack_networking_router_interface_v2.router]
}

resource "ovh_cloud_project_kube_nodepool" "workers" {
  service_name = var.project_id
  kube_id      = ovh_cloud_project_kube.primary.id
  name         = "workers" # NB: "_" is not allowed in node pool names
  flavor_name  = var.node_flavor

  # Simple fixed-size pool (autoscaling off) — 3 nodes by default.
  autoscale     = false
  desired_nodes = var.node_count
  min_nodes     = var.node_count
  max_nodes     = var.node_count
}
