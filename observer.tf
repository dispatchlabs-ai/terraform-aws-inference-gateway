resource "aws_cloudwatch_log_group" "observer" {
  name              = "/aws/lambda/${var.name}-stopped"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}
resource "aws_iam_role" "observer" {
  name               = "${var.name}-stopped"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = var.tags
}
resource "aws_iam_role_policy" "observer" {
  role = aws_iam_role.observer.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["dynamodb:UpdateItem"], Resource = aws_dynamodb_table.owner.arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.observer.arn}:*" },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.failed_events.arn }
  ] })
}
data "archive_file" "observer" {
  type        = "zip"
  source_file = "${path.module}/lambda/stopped.py"
  output_path = "${path.root}/.terraform/${var.name}-stopped.zip"
}
resource "aws_lambda_function" "observer" {
  function_name    = "${var.name}-stopped"
  role             = aws_iam_role.observer.arn
  runtime          = "python3.13"
  handler          = "stopped.handler"
  filename         = data.archive_file.observer.output_path
  source_code_hash = data.archive_file.observer.output_base64sha256
  timeout          = 30
  environment {
    variables = { CLUSTER_ARN = aws_ecs_cluster.gateway.arn, SERVICE = local.service, OWNER_TABLE = aws_dynamodb_table.owner.name }
  }
  dead_letter_config { target_arn = aws_sqs_queue.failed_events.arn }
  tags       = var.tags
  depends_on = [aws_iam_role_policy.observer]
}
resource "aws_cloudwatch_event_rule" "stopped" {
  name = "${var.name}-stopped"
  event_pattern = jsonencode({
    source = ["aws.ecs"], "detail-type" = ["ECS Task State Change"],
    detail = { clusterArn = [aws_ecs_cluster.gateway.arn], group = ["service:${local.service}"], lastStatus = ["STOPPED"] }
  })
  tags = var.tags
}
resource "aws_sqs_queue" "failed_events" {
  name                      = "${var.name}-stopped-failures"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
}
resource "aws_sqs_queue_policy" "events" {
  queue_url = aws_sqs_queue.failed_events.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sqs:SendMessage", Resource = aws_sqs_queue.failed_events.arn,
    Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.stopped.arn } }
  }] })
}
resource "aws_cloudwatch_event_target" "stopped" {
  rule = aws_cloudwatch_event_rule.stopped.name
  arn  = aws_lambda_function.observer.arn
  dead_letter_config { arn = aws_sqs_queue.failed_events.arn }
  retry_policy {
    maximum_event_age_in_seconds = 86400
    maximum_retry_attempts       = 185
  }
  depends_on = [aws_sqs_queue_policy.events]
}
resource "aws_lambda_permission" "events" {
  statement_id  = "EcsStoppedEvents"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.observer.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.stopped.arn
}
resource "aws_cloudwatch_metric_alarm" "failed_events" {
  alarm_name          = "${var.name}-stopped-events-failed"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.failed_events.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  tags                = var.tags
}
resource "aws_cloudwatch_metric_alarm" "unhealthy" {
  alarm_name          = "${var.name}-healthy-tasks-low"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.gateway.arn_suffix, TargetGroup = aws_lb_target_group.gateway.arn_suffix }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  threshold           = var.desired_count
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = var.alarm_actions
  tags                = var.tags
}
resource "aws_cloudwatch_metric_alarm" "request_errors" {
  alarm_name          = "${var.name}-request-errors"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.gateway.arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  tags                = var.tags
}
