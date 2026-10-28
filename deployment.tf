# Opt-in only after runtime/migration qualification. ECS owns the rule weights;
# changing image/config does not destroy the old targets or credential table.
resource "aws_lb_target_group" "alternate" {
  count                = var.distributed_deployments ? 1 : 0
  name                 = "${var.name}-alt"
  port                 = 8787
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 300
  health_check {
    path                = "/readyz"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  tags = var.tags
}

resource "aws_lb_listener_rule" "production" {
  count        = var.distributed_deployments ? 1 : 0
  listener_arn = aws_lb_listener.https.arn
  priority     = 50000
  condition {
    path_pattern { values = ["/*"] }
  }
  action {
    type = "forward"
    forward {
      target_group {
        arn    = aws_lb_target_group.gateway.arn
        weight = 100
      }
      target_group {
        arn    = aws_lb_target_group.alternate[0].arn
        weight = 0
      }
      stickiness {
        enabled  = false
        duration = 1 # Required schema field; stickiness is disabled.
      }
    }
  }
  lifecycle { ignore_changes = [action] }
  tags = var.tags
}

resource "aws_iam_role" "deployment" {
  count = var.distributed_deployments ? 1 : 0
  name  = "${var.name}-deployment"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "ecs.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
  }] })
  tags = var.tags
}
resource "aws_iam_role_policy" "deployment" {
  count = var.distributed_deployments ? 1 : 0
  role  = aws_iam_role.deployment[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["elasticloadbalancing:ModifyRule"], Resource = aws_lb_listener_rule.production[0].arn },
    { Sid = "GatewayTargetRegistration", Effect = "Allow", Action = ["elasticloadbalancing:RegisterTargets", "elasticloadbalancing:DeregisterTargets"], Resource = [aws_lb_target_group.gateway.arn, aws_lb_target_group.alternate[0].arn] },
    { Effect = "Allow", Action = ["elasticloadbalancing:DescribeRules", "elasticloadbalancing:DescribeListeners", "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeTargetGroups", "elasticloadbalancing:DescribeTargetHealth"], Resource = "*" }
  ] })
}
