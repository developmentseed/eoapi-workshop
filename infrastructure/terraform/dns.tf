# One wildcard A record to the ingress LB covers every participant's host
# (lab-u01., lab-u02., ...).

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
