"""Persist STOPPED proof only for the currently recorded owner task."""
import os
import boto3
from botocore.exceptions import ClientError


def handler(event, context):
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
