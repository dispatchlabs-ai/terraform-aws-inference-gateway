"""Observe serving health and retain STOPPED proof for the recorded owner."""
import json
import os
import boto3
from botocore.exceptions import ClientError


def serving_health():
    elb = boto3.client("elbv2")
    allowed = set(json.loads(os.environ["TARGET_GROUPS"]))
    rule = os.environ.get("LISTENER_RULE")
    active = allowed
    if rule:
        actions = elb.describe_rules(RuleArns=[rule])["Rules"][0]["Actions"]
        if len(actions) != 1 or actions[0]["Type"] != "forward":
            raise ValueError("Unexpected production listener action")
        active = {g["TargetGroupArn"] for g in actions[0]["ForwardConfig"]["TargetGroups"] if g.get("Weight", 1) > 0}
        if not active or not active <= allowed:
            raise ValueError("Unexpected production target groups")
    # During a split, every receiving group must be healthy. A healthy standby
    # must never hide an unhealthy serving group. Read the live rule on every poll
    # so automatic rollback and manual traffic recovery are covered too.
    healthy = min(sum(t["TargetHealth"]["State"] == "healthy"
                      for t in elb.describe_target_health(TargetGroupArn=group)["TargetHealthDescriptions"])
                  for group in active)
    boto3.client("cloudwatch").put_metric_data(
        Namespace="InferenceGateway", MetricData=[{
            "MetricName": "ServingHealthyHostCount", "Unit": "Count", "Value": healthy,
            "Dimensions": [{"Name": "Service", "Value": os.environ["SERVICE"]}],
        }])


def handler(event, context):
    if event.get("source") == "aws.events" and event.get("detail-type") == "Scheduled Event":
        serving_health()
        return
    detail = event.get("detail", {})
    if (event.get("source") != "aws.ecs"
            or detail.get("clusterArn") != os.environ["CLUSTER_ARN"]
            or detail.get("group") != "service:" + os.environ["SERVICE"]
            or detail.get("lastStatus") != "STOPPED"):
        return
    task_arn = detail["taskArn"]
    try:
        boto3.client("dynamodb").update_item(
            TableName=os.environ["OWNER_TABLE"],
            Key={"id": {"S": "provider-owner"}},
            UpdateExpression="SET stoppedTaskArn = :task, stoppedAt = :time",
            ConditionExpression="taskArn = :task",
            ExpressionAttributeValues={
                ":task": {"S": task_arn}, ":time": {"S": event["time"]}
            },
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
