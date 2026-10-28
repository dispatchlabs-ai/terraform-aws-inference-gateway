mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_region" { defaults = { region = "us-east-1" } }
  mock_data "aws_caller_identity" { defaults = { account_id = "123456789012" } }
  mock_resource "aws_lb" { defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/test/0123456789abcdef" } }
  mock_resource "aws_lb_target_group" { defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/test/0123456789abcdef" } }
  mock_resource "aws_lb_listener" { defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/test/0123456789abcdef/0123456789abcdef" } }
  mock_resource "aws_lb_listener_rule" { defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener-rule/app/test/0123456789abcdef/0123456789abcdef/0123456789abcdef" } }
  mock_resource "aws_iam_role" { defaults = { arn = "arn:aws:iam::123456789012:role/test" } }
  mock_resource "aws_acm_certificate" { defaults = { arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000" } }
  mock_resource "aws_sqs_queue" { defaults = { arn = "arn:aws:sqs:us-east-1:123456789012:test" } }
  mock_resource "aws_ecs_cluster" { defaults = { arn = "arn:aws:ecs:us-east-1:123456789012:cluster/test" } }
  mock_resource "aws_lambda_function" { defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:test" } }
  mock_resource "aws_cloudwatch_event_rule" { defaults = { arn = "arn:aws:events:us-east-1:123456789012:rule/test" } }
}
mock_provider "archive" {}

variables {
  name                   = "test-provider"
  vpc_id                 = "vpc-0123456789abcdef0"
  subnet_ids             = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
  domain_name            = "gateway.example.com"
  zone_id                = "Z123456789"
  image                  = "123456789012.dkr.ecr.us-east-1.amazonaws.com/gateway@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  image_repository_arn   = "arn:aws:ecr:us-east-1:123456789012:repository/gateway"
  configuration_uri      = "s3://example-configuration/gateway.json"
  configuration_sha256   = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  session_secret_arn     = "arn:aws:secretsmanager:us-east-1:123456789012:secret:session-example"
  connection_secret_arns = ["arn:aws:secretsmanager:us-east-1:123456789012:secret:connection-example"]
}

run "legacy_default_is_unchanged" {
  command = plan
  assert {
    condition     = length(aws_lb_target_group.alternate) == 0 && length(aws_lb_listener_rule.production) == 0
    error_message = "Default use must not enable the new traffic controller."
  }
  assert {
    condition     = aws_lb_target_group.gateway.health_check[0].path == "/healthz"
    error_message = "Legacy readiness cannot be silently replaced."
  }
}

run "distributed_is_paused_and_uses_readiness" {
  command = plan
  variables { distributed_deployments = true }
  assert {
    condition     = length(aws_lb_target_group.alternate) == 1 && aws_lb_target_group.gateway.health_check[0].path == "/readyz"
    error_message = "Distributed serving requires alternate targets and readiness checks."
  }
  assert {
    condition     = aws_ecs_service.gateway.deployment_configuration[0].strategy == "BLUE_GREEN"
    error_message = "Distributed deployments must not use automatic rolling retirement."
  }
  assert {
    condition     = one(aws_ecs_service.gateway.deployment_configuration[0].lifecycle_hook).target_type == "PAUSE" && one(one(aws_ecs_service.gateway.deployment_configuration[0].lifecycle_hook).timeout_configuration).action == "ROLLBACK"
    error_message = "A timeout must never force unfinished request retirement."
  }
}
