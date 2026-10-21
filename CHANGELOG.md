# Changelog

## Unreleased

- Document the separately maintained private runtime and replace its obsolete monorepo source link.

- Add optional durable employee access/usage storage and read-only authentication secret grants. Employee spending limits remain unset; policy and identity administration belong to the gateway runtime.

- Rename the repository to `terraform-aws-inference-gateway`; module inputs, resource identities and published tags are unchanged.

## 0.1.0-alpha.2 — 2026-10-20

- Match ECS-normalized container defaults so repeated plans do not replace an unchanged task definition.
- Clarify DNS staging during migration and record the observed recovery gap with default draining.

## 0.1.0-alpha.1 — 2026-10-20

Initial source alpha: HTTPS ALB, dedicated ECS Fargate service, single-provider
ownership table, durable STOPPED observer, least-privilege IAM, metadata logs,
alarms and recovery guidance. The runtime is built separately from Dispatch.
