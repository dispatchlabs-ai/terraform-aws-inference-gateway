terraform {
  required_version = ">= 1.5.0, < 2.0.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 6.0, < 7.0" }
  }
}
provider "aws" { region = var.region }
variable "region" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "domain_name" { type = string }
variable "zone_id" { type = string }
variable "image" { type = string }
variable "image_repository_arn" { type = string }
variable "configuration_uri" { type = string }
variable "configuration_sha256" { type = string }
variable "session_secret_arn" { type = string }
variable "connection_secret_arns" { type = list(string) }
module "gateway" {
  source                 = "../.."
  name                   = "example-provider"
  vpc_id                 = var.vpc_id
  subnet_ids             = var.subnet_ids
  domain_name            = var.domain_name
  zone_id                = var.zone_id
  image                  = var.image
  image_repository_arn   = var.image_repository_arn
  configuration_uri      = var.configuration_uri
  configuration_sha256   = var.configuration_sha256
  session_secret_arn     = var.session_secret_arn
  connection_secret_arns = var.connection_secret_arns
}
output "url" { value = module.gateway.url }
