# Source-first application migration workspace (DEV)

The DEV plan route uses SourceWorkspaceEntry and SourceMigrationWorkspace, with the same six-stage navigation as discovery:

1. Source connection
2. Discovery & assessment
3. Migration scope
4. Target & compatibility
5. Review & approval
6. Execute

Entry requires completed matching source inventory and assessment evidence. Namespace selection is a browsing filter, not selection of every workload. Workloads are selected explicitly; saved scope contains their observed dependencies and referenced routing resources. A shared ingress does not pull every other backend service into scope. Missing references and incomplete discovery remain visible.

Deployment source entries record user-provided method (Helm, manifests, script, repository, other, unknown), shared bundle name, reference and optional Helm release for an explicitly selected workload. They are metadata, not proof of original artifact collection or successful extraction. No raw Secret or ConfigMap content is added.

Saving uses the existing migration PUT API and planningDraft schema with workflow=SOURCE_FIRST and deploymentSources. Selected namespace names represent selected workloads, not every namespace browsed. Source-first configuration validation binds the draft to original source and assessed scope independently of later target changes.

Target selection is enabled after a successful scope save. The existing PUT API accepts a target-only update after assessment when the DEV source-first flag is enabled; registered cluster customer, platform, identity, ACTIVE status, environment/version and ownership are checked. Current support is EKS; AKS, GKE and OpenShift adapters remain pending. Source evidence and selected scope are retained. Existing target-assessment and target-compatibility APIs evaluate the saved application scope; old-target findings and unrelated resource findings do not control the source-first decision. Observed dependencies marked RECREATE are included in API/storage evidence checks.

Review presents readiness gaps. Original artifact ingestion/analysis, selective Helm/YAML/script extraction, validated adapted package generation, migration approval integration and execution are not implemented by this screen. Approval/execution controls remain unavailable. Standalone Pod selection requires collection support not present in the current connector; discovered application controllers remain selectable.

Production routing retains the existing planning workspace. Deploy changes only to the selected DEV branch/instance through the existing deploy-source-connection-screen-dev.py script; no API Gateway or database schema migration is required.

Validation includes the source-first scope/editor tests and backend source-first planning/target tests. The existing migration-planning.test.tsx suite has 21 failures against the preceding commit's legacy editor UI as well; it does not exercise the new workspace entry.
