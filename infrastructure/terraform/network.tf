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

###############################################################################
# Ingress load balancer
#
# OVH's classic/Neutron-LBaaS load balancer is deprecated in favour of Octavia.
# `openstack_lb_loadbalancer_v2` is the Octavia (LBaaS v2) resource, so this IS
# an Octavia load balancer. We pre-create it (plus a floating IP) so the public
# address is known at apply time and the Route53 wildcard record (see dns.tf)
# can be created in the same run — instead of racing an async Service-type
# LoadBalancer provisioned later by the ingress controller.
#
# Point ingress-nginx at this LB by annotating its controller Service with:
#     loadbalancer.openstack.org/load-balancer-id: <lb id — see outputs>
# so the cloud controller adopts this LB rather than creating a new one.
###############################################################################

resource "openstack_lb_loadbalancer_v2" "ingress" {
  name          = "${var.cluster_name}-ingress-lb"
  region        = var.region
  vip_subnet_id = openstack_networking_subnet_v2.private.id
}

resource "openstack_networking_floatingip_v2" "ingress" {
  pool   = data.openstack_networking_network_v2.ext_net.name
  region = var.region
}

resource "openstack_networking_floatingip_associate_v2" "ingress" {
  region      = var.region
  floating_ip = openstack_networking_floatingip_v2.ingress.address
  port_id     = openstack_lb_loadbalancer_v2.ingress.vip_port_id
}
