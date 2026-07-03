output "kubeconfig" {
  description = "Raw kubeconfig for the managed cluster. Write it out with: terraform output -raw kubeconfig > kubeconfig.yaml"
  value       = ovh_cloud_project_kube.primary.kubeconfig
  sensitive   = true
}

output "cluster_id" {
  description = "OVH managed Kubernetes cluster ID"
  value       = ovh_cloud_project_kube.primary.id
}

output "ingress_public_ip" {
  description = "Public IP OVH assigned to the ingress-nginx load balancer (target of the wildcard DNS record)"
  value       = local.ingress_ip
}

output "wildcard_domain" {
  description = "Wildcard hostname now resolving to the ingress load balancer"
  value       = var.wildcard_domain
}
