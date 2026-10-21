# Terraform AWS provider gateway

Run a shared Pi inference gateway on AWS while keeping provider API keys and
OAuth credentials out of workloads. This module deploys a public HTTPS ALB,
Fargate ingress tasks across availability zones, and coordination that allows
one task to own provider operations safely.

**Source alpha.** Created by Chris Reynolds, cofounder of Dispatch Labs AI.
MIT licensed. Requires an AWS account, an existing VPC with two public subnets,
a Route 53 zone, a compatible container image, and enrolled Secrets Manager
credentials. It creates billable infrastructure. It does not provision provider
accounts, host agent databases, or guarantee uninterrupted streams.

## Use it with your AI agent

Give an agent with shell, file and web access this prompt:

> Follow https://github.com/dispatchlabs-ai/terraform-aws-provider-gateway/blob/main/docs/deploy.md.
> Clone the source alpha, initialize and validate its basic example, and explain
> the AWS resources and inputs needed for my deployment. Do not deploy until I
> request it. Never put credential values in Terraform or logs.

The immediate result is a validated configuration and a concrete inventory of
your deployment inputs. This prompt is a documented workflow, not a claim of
verified compatibility with every agent.

Manual path:

```sh
git clone https://github.com/dispatchlabs-ai/terraform-aws-provider-gateway.git
cd terraform-aws-provider-gateway
tofu -chdir=examples/basic init -backend=false
tofu -chdir=examples/basic validate
```

No AWS credentials are needed for validation. Follow the
[deployment guide](docs/deploy.md) to supply real inputs, inspect a plan, build the
runtime and deploy. Terraform 1.5+ or OpenTofu is supported by the configuration;
AWS provider 6.x and Archive provider 2.7+ are required. The deployed runtime is
Linux. Module authoring commands are portable shell commands for Linux/macOS.

## What it creates

- A dedicated ECS cluster and Fargate service, defaulting to two 0.5-vCPU/2-GiB
  tasks, public IPs for outbound access, and security groups accepting service
  traffic only from the ALB or another gateway task.
- An internet-facing ALB, ACM certificate, DNS validation records and optional
  Route 53 alias; HTTPS is the public entry point.
- A strongly consistent DynamoDB owner record with point-in-time recovery and
  deletion protection. No TTL or lease-only promotion is used.
- An EventBridge/Lambda observer retaining proof that an owner task stopped,
  with a dead-letter queue and CloudWatch alarms.
- Least-privilege task/execution roles and bounded-retention logs. Provider
  credentials and the signing key remain in caller-owned Secrets Manager.

All inference and catalog work uses one provider owner. The standby authenticates
and forwards requests without initializing providers. Takeover requires actual
ECS `STOPPED` evidence; an expired heartbeat only permits stopping the old task.
This protects rotating OAuth credentials but permits a recovery gap. In-flight
streams can be interrupted and are never automatically replayed.

The module expects the ECS-aware runtime in
[Dispatch's inference gateway](https://github.com/dispatchlabs-ai/dispatch/tree/main/packages/inference-gateway).
It is not a generic arbitrary-container hosting module. Runtime protocol,
authentication, model grants and credential refresh belong to that package.

Read [inputs and operation](docs/deploy.md), [recovery](docs/recovery.md),
[contributing](CONTRIBUTING.md), [security](SECURITY.md), and
[release notes](CHANGELOG.md). Alarm resources do not send notifications unless
`alarm_actions` supplies a working SNS destination.
