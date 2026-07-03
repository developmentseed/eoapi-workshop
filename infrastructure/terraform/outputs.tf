output "kubeconfig" {
  description = "Raw kubeconfig for the managed cluster. Write it out with: terraform output -raw kubeconfig > kubeconfig.yaml"
  value       = ovh_cloud_project_kube.primary.kubeconfig
  sensitive   = true
}

output "cluster_id" {
  description = "OVH managed Kubernetes cluster ID"
  value       = ovh_cloud_project_kube.primary.id
}

output "ingress_load_balancer_id" {
  description = "Octavia LB ID — set as loadbalancer.openstack.org/load-balancer-id on the ingress-nginx controller Service so it adopts this LB"
  value       = openstack_lb_loadbalancer_v2.ingress.id
}

output "ingress_public_ip" {
  description = "Public floating IP of the ingress load balancer (target of the wildcard DNS record)"
  value       = openstack_networking_floatingip_v2.ingress.address
}

output "wildcard_domain" {
  description = "Wildcard hostname now resolving to the ingress load balancer"
  value       = var.wildcard_domain
}
