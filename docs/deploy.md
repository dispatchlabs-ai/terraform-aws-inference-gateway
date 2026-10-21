# Deploy a provider gateway

## Validate the example

Clone this repository, then run `tofu -chdir=examples/basic init -backend=false`
and `tofu -chdir=examples/basic validate`. Terraform can be substituted for
OpenTofu. This checks configuration syntax and provider schemas without AWS
credentials or resource creation. It does not prove that your VPC, provider
accounts or image work. The example uses required input variables rather than
private deployment identifiers.

## Prepare inputs

Use a dedicated gateway deployment and do not share its OAuth secrets with any
other live application or coordination table. Before replacing an existing
uncoordinated gateway, follow the fencing steps in [recovery](recovery.md).

| Input | Requirement |
| --- | --- |
| `name` | Stable 2–24 character name. Renaming changes coordination identity. |
| `vpc_id`, `subnet_ids` | Existing VPC and two public subnets in distinct AZs, with Internet Gateway routes. No NAT gateway is created. |
| `domain_name`, `zone_id` | Existing public Route 53 hosted zone and your chosen HTTPS hostname. |
| `image`, `image_repository_arn` | Compatible private ECR image pinned by SHA-256, and its repository ARN. Build and retain it separately. |
| `configuration_uri`, `configuration_sha256` | Immutable S3 JSON configuration and its content checksum. |
| `session_secret_arn` | Existing session signing secret, 32 random bytes encoded as 64 lowercase hexadecimal characters. |
| `connection_secret_arns` | Existing native Pi credentials in Secrets Manager. Values never enter Terraform. |
| `enable_employee_access` | Default false. Create the durable identity, credential, usage and policy table; use `access_table_name` in the runtime configuration. |
| `authentication_secret_arns` | Optional read-only secret ARNs for employee authentication, such as a Google OAuth client secret. |
| `desired_count` | Default two ingress tasks; use zero for staging or fencing. No provider concurrency cap is imposed. |
| `cpu`, `memory`, `cpu_architecture` | Defaults 512, 2048, X86_64. Use a valid Fargate combination and matching image. |
| `kms_key_arns` | Optional customer-managed keys needed by configuration/credential storage. |
| `manage_dns` | Default true. Set false when a caller manages an existing alias. |
| `alarm_actions` | Optional SNS destinations; alarms otherwise have no outbound notification delivery. |

The module accepts existing credentials, not secret values or enrollments. Enroll
OAuth through the gateway runtime's native login with all writers stopped. A
provider's refresh token must not be copied from another active application.
Grant workload identities and models explicitly in the configuration; the module
cannot decide which accounts or roles should be trusted.

Employee access requires a compatible runtime and its
[employee setup](https://github.com/dispatchlabs-ai/dispatch/blob/main/packages/inference-gateway/docs/employee-access.md).
The module creates no employee identities or spending limits. Its optional access
table uses point-in-time recovery, deletion protection and TTL only for expiring
credentials/login flows. Include this table in backup and regional recovery;
restoring only provider secrets does not restore employee access or usage.

Build the runtime from a clean committed
[Dispatch checkout](https://github.com/dispatchlabs-ai/dispatch) using its
`packages/inference-gateway/Dockerfile`. Push to your ECR repository and record
the returned digest. Pass the digest URI, not a mutable tag. The public package
is source alpha; this module does not supply a published runtime image.

The non-secret JSON configuration must bind `0.0.0.0:8787`, use your public HTTPS
audience, and name the same secrets and region. Upload it under an immutable,
content-addressed key in a private versioned S3 bucket. Compute its SHA-256 from
the exact uploaded bytes. The runtime checks it before starting. Keep ECR and S3
artifacts, current secrets and Terraform state in your backup plan. Point-in-time
recovery of the owner table is not a substitute for credential backups.

## Plan and apply

Use a versioned remote state backend with locking and an approved AWS deployment
identity. Set the example variables in an ignored file or adapt the module call
into your infrastructure repository. Pin the module source to an immutable Git
revision for deployment. Run `tofu plan -out=gateway.tfplan`, inspect it, then
`tofu apply gateway.tfplan`. Do not put passwords, API keys or OAuth objects in
variables or state.

Fresh deployments can start with the default two tasks. Migrations stage with
zero tasks until the old writer is confirmed stopped. Desired count zero alone
does not prove running tasks have stopped. The ownership table is protected
against automatic deletion/replacement; see [recovery](recovery.md) before
changing its identity or destroying the deployment.

Verify certificate issuance, public DNS, both healthy ALB targets, authenticated
catalog access and a real provider completion. Exercise a task takeover and a
credential refresh before treating the installation as qualified. `/healthz`
proves the HTTP process is alive; it does not prove provider authorization.

Logs contain metadata only; the gateway contract excludes prompt, response and
credential content from its logs. The ALB listener has a 3,600-second idle timeout
and the runtime sends SSE heartbeat comments. Existing streams may still end on
task shutdown. The service uses on-demand Fargate, not Spot. Public IPv4, ALB,
Fargate, logs, Secrets Manager, S3 and DynamoDB all contribute to cost; this
module neither purchases savings plans nor imposes a spending cap.
