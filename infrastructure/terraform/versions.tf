terraform {
  required_version = ">= 1.9.0"

  required_providers {
    ovh = {
      source  = "ovh/ovh"
      version = "~> 2.12"
    }
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 1.54"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.31"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # State is stored on the local machine by default (see terraform.tfstate,
  # which is git-ignored). This keeps the prerequisites for a deployment to a
  # minimum — no state bucket required to get started.
  #
  # To migrate to remote state later, uncomment the block below, fill in a
  # bucket, and run `terraform init -migrate-state`. OVH Object Storage is
  # S3-compatible, so the standard S3 backend works against it:
  #
  # backend "s3" {
  #   endpoints                   = { s3 = "https://s3.<region>.io.cloud.ovh.net/" }
  #   bucket                      = "<state-bucket>"
  #   key                         = "eoapi-workshop/terraform.tfstate"
  #   region                      = "<region>"
  #   access_key                  = "<access-key>"   # prefer -backend-config
  #   secret_key                  = "<secret-key>"   # prefer -backend-config
  #   skip_credentials_validation = true
  #   skip_region_validation      = true
  #   skip_metadata_api_check      = true
  #   skip_requesting_account_id  = true
  # }
}
