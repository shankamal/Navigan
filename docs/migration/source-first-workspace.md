# Source-first application migration workspace (DEV)

The DEV plan route uses SourceWorkspaceEntry and SourceMigrationWorkspace, with the same six-stage navigation as discovery:

1. Source connection
2. Discovery & assessment
3. Migration scope
4. Target & compatibility
5. Review & approval
6. Execute

Entry requires completed matching source inventory and assessment evidence. Namespace selection is a browsing filter, not selection of every workload. Workloads are selected explicitly; saved scope contains their observed dependencies and referenced routing resources. A shared ingress does not pull every other backend service into scope. Missing references and incomplete discovery remain visible.

Deployment structure analysis now belongs to discovery. The new Deployment sources and versions panel captures customer/source-scoped GitHub repository locations and registry hosts once, inspects pinned repository commits and referenced images, correlates artifacts with live workload metadata, and shows gaps. Unique candidates can be confirmed together; ambiguous candidates can be resolved individually. User confirmation is distinct from independently verified deployed Git provenance. Migration Scope shows a read-only summary for selected workloads instead of repeated deployment-method forms. Previously saved deploymentSources metadata is preserved for compatibility.

The connector now reads Pods and ReplicaSets with list-only access, follows controller owner references, and reports current-Pod container image identities, including init containers, separately from configured image tags. It exports only approved Helm/GitOps/app-version metadata values. No Pod logs, exec access, environment values, Secret bodies, ConfigMap values or repository/script bodies are uploaded by discovery. Completed Pods are excluded from current runtime evidence.

Saving uses the existing migration PUT API and planningDraft schema with workflow=SOURCE_FIRST and deploymentSources. Selected namespace names represent selected workloads, not every namespace browsed. Source-first configuration validation binds the draft to original source and assessed scope independently of later target changes.

Target selection is enabled after a successful scope save. The existing PUT API accepts a target-only update after assessment when the DEV source-first flag is enabled; registered cluster customer, platform, identity, ACTIVE status, environment/version and ownership are checked. Current support is EKS; AKS, GKE and OpenShift adapters remain pending. Source evidence and selected scope are retained. Existing target-assessment and target-compatibility APIs evaluate the saved application scope; old-target findings and unrelated resource findings do not control the source-first decision. Observed dependencies marked RECREATE are included in API/storage evidence checks.

Review presents readiness gaps. Static repository inspection is implemented. Helm rendering, original values provenance, selective Helm/YAML/script extraction, validated adapted package generation, migration approval integration and execution remain pending. Approval/execution controls remain unavailable. Standalone Pod selection requires collection support not present in the current connector; discovered application controllers remain selectable.

Production routing retains the existing planning workspace. Deploy changes only to the selected DEV branch/instance through deploy-source-connection-screen-dev.py. The new increment adds four JWT-protected API routes and scoped metadata-read IAM permissions; it reuses existing JSON columns and requires no database schema migration. See deployment-source-discovery.md for deployment and limitations.

Validation includes the source-first scope/editor tests and backend source-first planning/target tests. The existing migration-planning.test.tsx suite has 21 failures against the preceding commit's legacy editor UI as well; it does not exercise the new workspace entry.
