# Protected blue/green rollout

**Opt-in source implementation; not live-qualified.** `distributed_deployments`
defaults to false. Keep it false on legacy images. Enabling it replaces tasks;
it is not inert staging or a qualified first migration.

Protocol 2 serves each request on one replica. Only the elected writer rotates
OAuth credentials. Health checks and this controller execute no inference.
The runtime renews task protection, transfers ownership after credential writes,
forwards late arrivals during drain, and closes HTTP admission before unprotecting.
An unresolved rotation leaves a durable `credential-rotation:<secret-id>` marker;
never clear it or restore an old refresh token without reconciling provider and
AWSCURRENT state. A crash/timeout is not permission to repeat a token rotation.

## Gates

Use AWS provider 6.67+ and the compatible runtime. The module retains service,
cluster, owner table and signing key. The production rule has priority 50000;
existing higher-priority image/auth routes stay separate. ECS owns its weights;
the controller shifts them back during a paused rollback before draining.
Two PAUSE stages gate cutover and cleanup; timeout rolls back, never forces drain.
Do not deregister targets or stop tasks while their application work is active.

Run `scripts/rollout.py` from a trusted VPC host permitted to reach task port 8787,
with AWS CLI credentials and an owner-only file of gateway administrator
authorization in `GATEWAY_ADMIN_TOKEN_FILE`. Do not expose this port publicly.
The controller needs ECS describe/get-task-protection/continue, ELB describe/modify-rule, and DynamoDB get/put/update
on the owner table; it does not read provider secrets.

Pin a manifest from observed ECS/ALB state, not inferred “latest” values:

```json
{
  "cluster": "<cluster ARN>",
  "service": "<service ARN>",
  "deployment": "<service deployment ARN>",
  "owner_table": "<table name>",
  "listener_rule": "<production rule ARN>",
  "source": {
    "tasks": ["<source task ARN>"],
    "task_definition": "<source task definition ARN>",
    "target_group": "<source target group ARN>"
  },
  "target": {
    "tasks": ["<candidate task ARN>"],
    "task_definition": "<candidate task definition ARN>",
    "target_group": "<candidate target group ARN>"
  }
}
```

Include every task in each target group. With sustained authenticated qualification
traffic running separately: `cutover` at POST_SCALE_UP, then `drain` at
POST_PRODUCTION_TRAFFIC_SHIFT until drained, then `finish`. Each command takes
`--manifest FILE --operation-id UUID`. It verifies identities, protection,
target health, routing and writer ownership. It never treats its own success as
end-to-end qualification.

`rollback` reactivates source, transfers the writer back, shifts new traffic and
drains and retires candidate streams **before** permitting ECS rollback. Repeat while draining.
`cleanup-target` is recovery-only after the source route is confirmed. `cleanup-source`
resumes source retirement after an interrupted finish. A successful retirement
response only acknowledges shutdown. The controller waits for app-owned
unprotection or STOPPED before authorizing ECS cleanup; verify final traffic too.

Interruptions leave both sets protected. Resume a failed action with its same UUID
only after the previous process has exited; the DynamoDB controller lock has no
lease/TTL. If AWS advanced past its pause, inspect state and use the corresponding
drain/cleanup action rather than reissuing cutover. Release/reassign a retained
controller lock only after verifying the original process is gone. A lost retirement
reply may need manual state reconciliation; it is not permission to force cleanup. Never bypass
an unresolved credential rotation, invent a drain timeout, or force StopTask.
Retirement resumption recognizes app-owned unprotection; never clear task
protection externally. Task definitions remain registered for exact rollback.

## Qualification boundary

Run `python3 -m unittest discover -s scripts -p 'test_*.py'`, `tofu test` (mock
providers; plan-only) and validate the basic example. These checks do not qualify the managed service behavior.
Acceptance still requires exact old/new artifacts, real ALB/ECS cutover, sustained
requests, an active long stream, OAuth expiry, rollback and controller interruption,
with no deployment-caused failures or duplicate provider execution.

The legacy binary cannot seal its writer cooperatively. The controller therefore
refuses legacy cutover/retirement. Legacy request forwarding is compatibility,
not proof that first migration is safe. Do not enable this flag in an existing
legacy installation until that migration is separately qualified.

References: [ECS pause hooks](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/pause-lifecycle-hooks.html),
[task protection](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-scale-in-protection.html).
