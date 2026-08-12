# Private network + subnet + router giving the cluster nodes internet egress
# (image pulls, etc.) via the router's external gateway on OVH's Ext-Net.

data "openstack_networking_network_v2" "ext_net" {
  name   = "Ext-Net"
  region = var.region
}

resource "openstack_networking_network_v2" "private" {
  name           = "${var.cluster_name}-net"
  region         = var.region
  admin_state_up = "true"
}

resource "openstack_networking_subnet_v2" "private" {
  name        = "${var.cluster_name}-subnet"
  network_id  = openstack_networking_network_v2.private.id
  region      = var.region
  cidr        = "192.168.12.0/24"
  enable_dhcp = true
  no_gateway  = false
}

resource "openstack_networking_router_v2" "router" {
  name                = "${var.cluster_name}-router"
  region              = var.region
  admin_state_up      = true
  external_network_id = data.openstack_networking_network_v2.ext_net.id
}

resource "openstack_networking_router_interface_v2" "router" {
  router_id = openstack_networking_router_v2.router.id
  region    = var.region
  subnet_id = openstack_networking_subnet_v2.private.id
}

# NB: we do NOT pre-create the ingress load balancer. OVH Managed Kubernetes
# does not honour the `loadbalancer.openstack.org/load-balancer-id` annotation
# to adopt a pre-existing Octavia LB — it provisions its own. So ingress-nginx
# owns the LB (see ingress.tf) and Terraform reads the public IP OVH assigns to
# it for the Route53 record (see dns.tf).
