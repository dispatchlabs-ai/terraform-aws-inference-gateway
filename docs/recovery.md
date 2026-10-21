# Ownership, upgrades and recovery

There must be exactly one coordination identity for a set of live provider
credentials. The DynamoDB table, ECS cluster and service name are part of that
identity. Do not run a second module or old standalone process against the same
OAuth secrets. A fresh empty table cannot fence writers using another table.

The table has Terraform `prevent_destroy` plus AWS deletion protection. A name
change or table replacement therefore requires an explicit migration. Stop all
old tasks and every external writer, verify their actual terminal state, then
prepare the replacement. For intentional teardown, first apply desired count
zero and verify all tasks are STOPPED; only then remove the lifecycle/deletion
protections in a reviewed module fork and destroy. Never bypass protection on a
live writer, delete an old record because its heartbeat is stale, or restore an
old owner-table snapshot beside a live service.

## Migrate or roll back

1. Stage the new module with desired count zero and a real pinned image/config.
2. Stop the old service, disable automatic restart and verify its process is gone.
3. Start the ECS service, verify authenticated provider requests, then switch DNS.
4. Retain the previous image/config and current secrets for rollback. Retire the
   old host once acceptance succeeds.

To return to an uncoordinated deployment, scale ECS to zero and verify **every**
task, including draining and replacement tasks, reached `STOPPED`. Then start
one old process using the latest credentials. Never roll OAuth secrets back just
because an earlier image is restored.

For normal image upgrades, keep the same table/cluster/service identity. ECS can
run replacement ingress tasks before stopping the previous ones. The runtime
allows only the recorded owner to initialize providers. A failed owner heartbeat
permits StopTask; only an actual `STOPPED` task or its durable receipt permits a
conditional takeover. Missing ECS records alone do not prove a task stopped.

A deployment can interrupt streams and pause new provider work during draining.
ALB deregistration allows up to 300 seconds; Fargate allows 120 seconds after
SIGTERM, and the runtime uses a shorter deadline. Provider inference is never
automatically replayed, because a lost response does not prove it was uncharged.

## Missing STOPPED evidence

Inspect `stopped_events_dead_letter_queue_url`, the observer's CloudWatch logs,
ECS task history and the owner item. The observer binds the receipt to the exact
current owner task; late events for older tasks cannot fence a successor. Repair
permissions or delivery, establish that the exact task stopped, and replay the
original event. Do not forge a receipt or clear the record based on elapsed time.
CloudWatch alarms are observable without SNS, but external delivery requires a
configured, verified `alarm_actions` destination.

## Regional disaster recovery

Retain the committed infrastructure, pinned image, non-secret configuration,
versioned Terraform state and the current credential set independently. Configure
Secrets Manager replication and ECR/S3 copies in the caller's backup region when
needed; the module does not silently change an account-wide replication policy.

Before starting recovery, fence all original-region tasks and external writers.
If that cannot be established, reauthorize independent provider sessions for the
recovery deployment instead of risking shared rotating refresh tokens. Restore a
compatible image and configuration with a fresh coordination table only after
fencing. Provider-side rotation may have completed before the final secret
replicated, so regional replicas do not guarantee OAuth recovery without login.
Pi Durable agent state belongs to the workload and has its own recovery process.
