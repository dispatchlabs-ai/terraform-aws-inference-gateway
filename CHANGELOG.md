# Changelog

## Unreleased

- Retain rollback task definitions; wait for app-owned retirement before ECS
  cleanup and support resuming confirmed retirement.
- Keep unresolved credential journals intact across handoff, including an
  explicitly pinned migration from the earlier sealed-error implementation.
- Supply ECS's required deployment ARN when continuing a pause and expose safe
  AWS diagnostics. Nine controller regressions pass; one real protocol-2 release
  completed without observed probe failures. Natural renewal/live rollback
  qualification remains outstanding.

## [0.1.0-alpha.3](https://github.com/dispatchlabs-ai/terraform-aws-inference-gateway/compare/v0.1.0-alpha.2...v0.1.0-alpha.3) — 2026-10-28

### Fixed

- Allow the blue/green deployment role to register and deregister targets in
  this gateway's primary and alternate target groups. Missing permissions
  prevented replacement tasks from joining the load balancer.

### Added

- Add opt-in protocol-2 blue/green configuration, task-protection IAM and a
  checked cutover/drain/rollback controller. Default legacy behavior is unchanged;
  first migration and live AWS qualification remain outstanding. Requires AWS
  provider 6.67+ for pause hooks.

- Add optional durable employee access/usage storage and read-only authentication secret grants. Employee spending limits remain unset; policy and identity administration belong to the gateway runtime.

### Changed

- Document the separately maintained private runtime and replace its obsolete monorepo source link.

- Rename the repository to `terraform-aws-inference-gateway`; module inputs, resource identities and published tags are unchanged.

## [0.1.0-alpha.2](https://github.com/dispatchlabs-ai/terraform-aws-inference-gateway/releases/tag/v0.1.0-alpha.2) — 2026-10-20

- Match ECS-normalized container defaults so repeated plans do not replace an unchanged task definition.
- Clarify DNS staging during migration and record the observed recovery gap with default draining.

## [0.1.0-alpha.1](https://github.com/dispatchlabs-ai/terraform-aws-inference-gateway/releases/tag/v0.1.0-alpha.1) — 2026-10-20

Initial source alpha: HTTPS ALB, dedicated ECS Fargate service, single-provider
ownership table, durable STOPPED observer, least-privilege IAM, metadata logs,
alarms and recovery guidance. The runtime is built separately from Dispatch.
