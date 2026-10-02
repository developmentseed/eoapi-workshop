# ingress-nginx owns the cluster's public load balancer; Terraform reads the IP
# OVH assigns it and points the Route53 record at it (dns.tf).
#
# participant/chart's Ingress uses this `nginx` class, and its NetworkPolicy admits
# only this `ingress-nginx` namespace.

resource "helm_release" "ingress_nginx" {
  name             = "ingress-nginx"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  version          = var.ingress_nginx_chart_version != "" ? var.ingress_nginx_chart_version : null
  namespace        = "ingress-nginx"
  create_namespace = true

  # Wait for the controller to be Ready before we try to read its Service IP.
  wait    = true
  timeout = 600

  depends_on = [ovh_cloud_project_kube_nodepool.workers]
}

# The cloud controller assigns the LB's public IP asynchronously, a little after
# the controller pod is Ready. Give it a short grace period before reading.
resource "time_sleep" "wait_for_lb" {
  depends_on      = [helm_release.ingress_nginx]
  create_duration = "90s"
}

# The controller Service, once OVH has populated its external IP.
data "kubernetes_service" "ingress_nginx" {
  metadata {
    name      = "ingress-nginx-controller"
    namespace = helm_release.ingress_nginx.namespace
  }
  depends_on = [time_sleep.wait_for_lb]
}

locals {
  ingress_ip = data.kubernetes_service.ingress_nginx.status[0].load_balancer[0].ingress[0].ip
}
