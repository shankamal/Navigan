# Cluster Management Priority Development Baseline

Baseline date: 17 September 2026

This document is the canonical priority roadmap for cluster-management
development. Status must be updated as implementation and verification progress.

## Baseline requirements

| ID | Requirement | Baseline status |
|---|---|---|
| CM-P0-01 | A customer can have multiple environments. | Complete |
| CM-P0-02 | An environment can have multiple clusters. | Complete |
| CM-P0-03 | A cluster can have multiple worker node groups. | Implemented locally; deployment verification pending |
| CM-P0-04 | A newly provisioned cluster starts with exactly one system node group for mandatory platform applications. | Partial: system group and connector are complete; Prometheus and Grafana baseline implemented locally; remaining platform utilities and automated delivery are pending |
| CM-P0-05 | A Cloud Engineer can request additional application node groups when an application is ready to onboard. | Implemented locally; deployment verification pending |
| CM-P0-06 | Cluster Management provides an EKS Compute-style view of the default and additional node groups. | Implemented locally with a tabbed workspace; live Kubernetes node inventory remains a later enhancement |
| CM-P0-07 | The connector is installed automatically on the system node group and namespace discovery completes without manual installation. | Complete in Dev |

## Mandatory system-node baseline

The system node group is Navigan-managed infrastructure reserved for approved
platform services. It must:

- be the only node group created during initial cluster provisioning;
- use on-demand capacity with minimum and desired capacity of at least two;
- reject nano and micro instance types;
- carry Navigan system labels and the system-only scheduling taint;
- use the Navigan-managed shared node security group;
- automatically run the Navigan connector;
- ultimately run Argo CD, Falco, the AWS Private CA integration, dashboard
  services, observability, certificate integration and other approved mandatory
  utilities;
- become ready only after mandatory bootstrap health checks succeed.

Argo CD must deploy immutable, approved versions of platform utilities. "Latest"
means the latest version approved and promoted by Navigan, not an unpinned
container `latest` tag.

## Current priority: application node-group management

This increment completes CM-P0-03, CM-P0-05 and CM-P0-06 together.

### Required workflow

1. Display live node-group inventory on the cluster Compute view.
2. Allow a Cloud Engineer to create an application node-group request.
3. Start with constraints inherited from the approved environment and cluster
   blueprint.
4. Collect only permitted request-specific values, including name, application
   purpose, instance types, capacity type, scaling and disk size.
5. Validate networking, availability-zone coverage, instance availability,
   encryption and policy limits.
6. Require independent Platform Architect review and approval.
7. Generate, certify and apply an immutable Terraform plan.
8. Track provisioning status and display the resulting node group.
9. Preserve the system node group and unrelated node groups during every change.
10. Record request, approval, execution and failure details in the audit trail.

### Acceptance criteria

- Initial cluster creation still accepts exactly one system node group.
- Application node groups can only be added after the cluster is active and its
  platform baseline is ready.
- Cloud Engineers cannot bypass the approved environment or cluster blueprint.
- Platform Architects cannot approve their own requests.
- Terraform plans cannot delete or replace unrelated node groups.
- Every Navigan-managed node group receives the shared node security group.
- System taints are not applied to application node groups.
- The Compute view shows purpose, instance types, capacity type, desired/min/max
  size, Kubernetes readiness and provisioning status.
- Failed operations are recoverable and do not incorrectly mark the cluster or
  node group ready.

## Subsequent priority

After application node-group management:

1. Complete the mandatory system-utility baseline through Argo CD.
2. Implement the live Cluster Dashboard.
3. Implement audited, short-lived WebKubectl sessions.

### Monitoring foundation

The versioned baseline in `platform/monitoring` installs Prometheus and Grafana
on the protected system nodes. It is currently an explicit, repeatable
installation step. The next increment must move this same pinned baseline under
customer-level Argo CD governance, report component health through the
connector, and expose only sanitized dashboard data through Navigan.
