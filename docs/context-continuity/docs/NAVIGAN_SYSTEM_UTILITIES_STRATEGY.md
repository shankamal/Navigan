# Navigan System Utilities strategy and architecture

Status: proposed lifecycle architecture; Installed Utilities UI implemented against existing APIs on 16 November 2026. New registration, installation and GitOps execution are not implemented by this UI increment.

## Product surfaces

- Installed utilities: scoped cluster inventory, package versions, observation freshness, health and governed upgrade entry points.
- Catalogue: currently a description of existing platform adapters. Future approved, versioned installation templates must be stored and reviewed through backend APIs.
- Change plans: active utility drafts and governed approval records.
- Maintenance & history: recorded maintenance starts and terminal change records, in the browser timezone.

## Target architecture

Workspace UI -> scoped APIs -> catalogue and planner -> durable execution workflow -> registered cluster system Git repository -> Argo CD -> cluster services. Connector observations flow back to verification and inventory. Keep the existing API/DB/Cognito boundaries; the durable executor requires a separately reviewed infrastructure design. No API request should wait for an entire installation or upgrade.

Catalogue entries should contain identity, approved publisher/package source, chart and application versions separately, immutable artifact identity, supported Kubernetes/distribution/cloud constraints, dependencies, RBAC/CRDs/storage requirements, configuration schema, secret references, deployment templates, verification checks and recovery limitations. Helm-based packages come first; add packaging adapters rather than arbitrary execution scripts.

## Governed workflow

Select scoped cluster and registered package -> configure Install/Upgrade/Configure/Remove plan -> assess compatibility/dependencies/permissions/diff/recovery -> review -> approve exact plan and artifact identities -> revalidate during maintenance window -> publish authorized Git change -> observe Argo reconciliation -> verify runtime version and utility-specific health.

Prepare PR before the window, but merge the deployment change only inside the authorized window when automated Argo reconciliation is enabled. Git merge is not successful deployment. Use idempotent operations, compare-and-swap repository updates, plan versions and one active change per shared chart/cluster. Recheck evidence and invalidate approval when material inputs change. External repository merge protections must be considered; an application timer alone cannot enforce a maintenance gate against manual merges.

Discover existing utilities separately from adoption. Monitoring (Grafana and Prometheus) is one chart group. Argo CD and the Navigan connector require dedicated procedures because they supply deployment and observation. Unknown discovered utilities remain visible without claiming upgrade support.

Recovery should use a reviewed desired-state revert where supported. CRDs, persistent data, irreversible schema changes and operator migrations require package-specific recovery; never promise universal automatic rollback. Fleet changes begin with one cluster, then controlled batches with health gates.

## Delivery sequence

1. Current increment: accepted installed-utilities/table layout, scoped inventory, searchable adapter catalogue, active utility plans and recorded maintenance/history. Reuse existing create-draft/review/approval APIs. Keep execution disabled.
2. Versioned catalogue backend and registration/review permissions; installation plan models, configuration validation, compatibility and recovery evidence.
3. Headlamp end-to-end install/upgrade GitOps workflow, maintenance-gated change publication and verified health; monitoring stack and Falco follow.
4. Extensible registration templates, adoption and fleet batches after the first complete workflow is validated.

## Current limits

No fabricated update totals, application versions, installed counts, schedules, catalogue approvals or runtime health. Platform inventory currently exposes chart version, not application version. UI therefore shows application version as Not reported. New utility registration and installation have no backend endpoints yet and are explicitly described as unavailable. No live repository write, Argo sync or cluster operation occurs through this increment.
