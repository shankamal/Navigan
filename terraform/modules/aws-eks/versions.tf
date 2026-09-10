terraform {
  required_version = "= 1.13.2"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
provider "aws" {
  region = var.region
  assume_role {
    role_arn      = var.provisioning_role_arn
    external_id   = var.external_id
    session_name  = "NaviganTerraform"
  }
  default_tags {
    tags = var.tags
  }
}
