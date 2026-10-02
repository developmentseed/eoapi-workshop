# cert-manager is cluster platform, so Terraform owns it (like ingress-nginx);
# `terraform destroy` owns its removal. Nothing in this repo creates an issuer
# or certificate: spike/chart takes a pre-issued secret (`ingress.tlsSecret`).

resource "helm_release" "cert_manager" {
  count = var.enable_cert_manager ? 1 : 0

  name             = "cert-manager"
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = var.cert_manager_chart_version != "" ? var.cert_manager_chart_version : null
  namespace        = "cert-manager"
  create_namespace = true

  # Install the CRDs (Certificate, ClusterIssuer, ...) with the controller.
  values = [yamlencode({
    crds = { enabled = true }
  })]

  wait    = true
  timeout = 600

  depends_on = [ovh_cloud_project_kube_nodepool.workers]
}
