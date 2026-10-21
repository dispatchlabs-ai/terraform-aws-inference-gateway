data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  partition         = data.aws_partition.current.partition
  account_id        = data.aws_caller_identity.current.account_id
  region            = data.aws_region.current.region
  service           = var.name
  configuration_arn = "arn:${local.partition}:s3:::${trimprefix(var.configuration_uri, "s3://")}"
  task_arn_pattern  = "arn:${local.partition}:ecs:${local.region}:${local.account_id}:task/${var.name}/*"
  ecs_trust         = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = local.account_id }, ArnLike = { "aws:SourceArn" = "arn:${local.partition}:ecs:${local.region}:${local.account_id}:*" } } }] })
}

resource "aws_ecs_cluster" "gateway" {
  name = var.name
  tags = var.tags
}
resource "aws_dynamodb_table" "owner" {
  name         = "${var.name}-owner"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  tags                        = var.tags
  deletion_protection_enabled = true
  lifecycle { prevent_destroy = true }
  # No TTL: expiry must never permit concurrent OAuth writers.
}
resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/ecs/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}
resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = local.ecs_trust
  tags               = var.tags
}
resource "aws_iam_role_policy" "execution" {
  role = aws_iam_role.execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = var.image_repository_arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.gateway.arn}:*" }
  ] })
}
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = local.ecs_trust
  tags               = var.tags
}
resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = concat([var.session_secret_arn], var.connection_secret_arns) },
    { Effect = "Allow", Action = ["secretsmanager:PutSecretValue"], Resource = var.connection_secret_arns },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = local.configuration_arn },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"], Resource = aws_dynamodb_table.owner.arn },
    { Effect = "Allow", Action = ["ecs:DescribeTasks", "ecs:StopTask"], Resource = local.task_arn_pattern, Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.gateway.arn } } }
  ], length(var.kms_key_arns) == 0 ? [] : [{ Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = var.kms_key_arns }]) })
}

resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "Public HTTPS ingress"
  vpc_id      = var.vpc_id
  tags        = var.tags
}
resource "aws_security_group" "task" {
  name        = "${var.name}-task"
  description = "ALB ingress and authenticated gateway peer forwarding"
  vpc_id      = var.vpc_id
  tags        = var.tags
}
resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_vpc_security_group_egress_rule" "alb" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.task.id
  ip_protocol                  = "tcp"
  from_port                    = 8787
  to_port                      = 8787
}
resource "aws_vpc_security_group_ingress_rule" "alb" {
  security_group_id            = aws_security_group.task.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8787
  to_port                      = 8787
}
resource "aws_vpc_security_group_ingress_rule" "peer" {
  security_group_id            = aws_security_group.task.id
  referenced_security_group_id = aws_security_group.task.id
  ip_protocol                  = "tcp"
  from_port                    = 8787
  to_port                      = 8787
}
resource "aws_vpc_security_group_egress_rule" "peer" {
  security_group_id            = aws_security_group.task.id
  referenced_security_group_id = aws_security_group.task.id
  ip_protocol                  = "tcp"
  from_port                    = 8787
  to_port                      = 8787
}
resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.task.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_lb" "gateway" {
  name                       = var.name
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = var.subnet_ids
  idle_timeout               = 3600
  drop_invalid_header_fields = true
  tags                       = var.tags
}
resource "aws_lb_target_group" "gateway" {
  name                 = var.name
  port                 = 8787
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 300
  health_check {
    path                = "/healthz"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  tags = var.tags
}
resource "aws_acm_certificate" "gateway" {
  domain_name       = var.domain_name
  validation_method = "DNS"
  tags              = var.tags
  lifecycle { create_before_destroy = true }
}
resource "aws_route53_record" "validation" {
  for_each = { for option in aws_acm_certificate.gateway.domain_validation_options : option.domain_name => option }
  zone_id  = var.zone_id
  name     = each.value.resource_record_name
  type     = each.value.resource_record_type
  ttl      = 60
  records  = [each.value.resource_record_value]
}
resource "aws_acm_certificate_validation" "gateway" {
  certificate_arn         = aws_acm_certificate.gateway.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.gateway.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.gateway.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.gateway.arn
  }
}
resource "aws_route53_record" "gateway" {
  count   = var.manage_dns ? 1 : 0
  zone_id = var.zone_id
  name    = var.domain_name
  type    = "A"
  alias {
    name                   = aws_lb.gateway.dns_name
    zone_id                = aws_lb.gateway.zone_id
    evaluate_target_health = true
  }
}

resource "aws_ecs_task_definition" "gateway" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }
  container_definitions = jsonencode([{
    name            = "gateway", image = var.image, essential = true,
    user            = "1000:1000", readonlyRootFilesystem = true, stopTimeout = 120,
    linuxParameters = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } },
    portMappings    = [{ containerPort = 8787, protocol = "tcp" }],
    environment = [
      { name = "AWS_REGION", value = local.region },
      { name = "DISPATCH_GATEWAY_CONFIG", value = var.configuration_uri },
      { name = "DISPATCH_GATEWAY_CONFIG_SHA256", value = var.configuration_sha256 },
      { name = "DISPATCH_GATEWAY_ECS_CLUSTER", value = aws_ecs_cluster.gateway.arn },
      { name = "DISPATCH_GATEWAY_ECS_SERVICE", value = local.service },
      { name = "DISPATCH_GATEWAY_OWNER_TABLE", value = aws_dynamodb_table.owner.name }
    ],
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.gateway.name, "awslogs-region" = local.region, "awslogs-stream-prefix" = "gateway", "mode" = "non-blocking", "max-buffer-size" = "10m" } }
  }])
  tags = var.tags
}
resource "aws_ecs_service" "gateway" {
  name                               = local.service
  cluster                            = aws_ecs_cluster.gateway.id
  task_definition                    = aws_ecs_task_definition.gateway.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 90
  availability_zone_rebalancing      = "ENABLED"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.gateway.arn
    container_name   = "gateway"
    container_port   = 8787
  }
  tags       = var.tags
  depends_on = [aws_lb_listener.https, aws_iam_role_policy.task, aws_iam_role_policy.execution, aws_cloudwatch_event_target.stopped, aws_lambda_permission.events]
}
