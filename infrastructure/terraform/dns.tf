# Wildcard A record: *.eoapi-workshop.ds.io -> ingress load balancer floating IP.
# spike/chart serves each participant's stack at its own subdomain under this
# wildcard (lab-u01., lab-u02., ...), so a single wildcard record covers all of
# them.

data "aws_route53_zone" "this" {
  name         = var.route53_zone_name
  private_zone = false
}

resource "aws_route53_record" "wildcard" {
  zone_id = data.aws_route53_zone.this.zone_id
  name    = var.wildcard_domain
  type    = "A"
  ttl     = var.dns_record_ttl
  records = [local.ingress_ip]
}
