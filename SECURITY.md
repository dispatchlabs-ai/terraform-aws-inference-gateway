# Security

This pre-1.0 source alpha has no security support SLA. Report vulnerabilities
privately through this repository's GitHub private vulnerability reporting when
available. Do not include live credentials, prompts or customer information in
public issues. For deployment-specific exposure, revoke or rotate affected
credentials through the owning provider and fence all gateway writers first.

The workload boundary is authenticated HTTPS with explicit identity/model grants
in the runtime. Peer tasks reauthenticate forwarded requests. The task role reads
only configured secrets and writes only connection credentials. Anyone able to
assume this task role, mutate its image/config, edit its owner table or administer
the AWS account is inside the trusted operator boundary. Protect those rights.

Task coordination protects ordinary crashes and deployments; it is not Byzantine
consensus against a compromised privileged task. It does not permit concurrent
regional writers, independent tables over the same credentials, or restoration
of stale OAuth state while a current writer is active.
