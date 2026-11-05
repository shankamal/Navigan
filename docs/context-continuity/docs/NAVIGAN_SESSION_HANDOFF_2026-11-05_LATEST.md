# Navigan — current session handoff, 5 November 2026

Dates use Asia/Kolkata. This document supersedes the 23 October handoff as the current recovery point. Preserve all earlier handoffs as historical evidence, not current instructions.

## 0. Upgrade Centre implementation — latest increment

- Working branch: `feature/eks-upgrade-readiness`, based on published live-inventory branch commit `006244363eca45404380beb14accb6b1d22cf063`.
- Published implementation commit: `0c710ec36ea95a5701a369a56dafbc3d2cc34ab8` — `Connect live EKS upgrade readiness`.
- Parent live-inventory commit: `dcc6a7a` — `Connect upgrade inventory and system utilities`.
- Parent planning-workspace commit: `83e8dd2` — `Build Upgrade Centre planning workspace`.
- Approved terminology: page/sidebar **Upgrades & Patching**; tabs **Upgrade Centre**, **Container Upgrades**, **System Utilities**, **Maintenance Schedule**, and **Plans & History**.
- **Container Upgrades** now calls a JWT-protected, read-only `GET /api/v1/clusters/{clusterId}/upgrade-readiness` endpoint. The EKS adapter assumes the registered customer provisioning role and discovers the live control-plane/platform version, immediate sequential Kubernetes target, support dates, managed node-group alignment/health, managed add-on compatibility, upgrade-readiness insights and active cluster updates.
- **System Utilities** is no longer a placeholder: it reads connector-reported platform components from the existing `platform-components` API, supports cluster/utility selection, displays installed version, component health, GitOps sync and observed time, and captures a requested target version in the UI.
- The UI reports READY, WARNING or BLOCKED with explicit findings and component evidence. Only the immediate next Kubernetes minor can be recommended; node skew, unhealthy resources, EKS ERROR/UNKNOWN insights and in-progress updates block planning.
- No EKS create/update/delete method exists in the adapter. Plan persistence, approval and execution buttons remain disabled. The landing **Upgrade Centre** is still preview data.
- Added the exact read-only customer-role policy at `infrastructure/bootstrap/eks-upgrade-readiness-read-policy.json`; the current bootstrap role source includes the same actions. Existing production customer roles must receive that additive policy before live testing.
- Added `scripts/deploy-eks-upgrade-readiness-prod.py`, which prepares then executes a checked CloudFormation release limited to the existing ClusterFunction package and the protected GET route. It preserves unrelated package members/resources and stops on source, runtime, stack or change-set drift.
- Validation: 2,000 backend tests passed with 25 intentional skips; all 476 frontend tests passed; TypeScript, targeted Ruff, Python compilation, SAM reconciliation, `git diff --check`, 34 focused backend/release tests and the production Next.js build passed.
- No AWS, customer-role, backend or frontend deployment was performed for commit `0c710ec36ea95a5701a369a56dafbc3d2cc34ab8`. Current production frontend remains task definition `:37` until a new release is explicitly executed.
- Next action: publish the branch, apply the additive read policy to the exact demo account role, prepare/execute the scoped backend release, then prepare/execute the existing frontend release from this branch. Perform fresh authenticated Container Upgrades and System Utilities acceptance in PROD. Do not enable upgrade execution.

## 1. Immediate recovery point

- Main repository: `https://github.com/shankamal/Navigan`.
- User checkout: `/mnt/b/Langchain_Ai/Navigan-migration-test`.
- Current feature branch: `feature/eks-upgrade-readiness`.
- Latest Upgrade Centre product-code commit: **`0c710ec36ea95a5701a369a56dafbc3d2cc34ab8`** — `Connect live EKS upgrade readiness`.
- Parent UI commit: **`954a34ab28a1d7c7a75fa2715762b305bcc2d55e`** — `Match approved five-stage lifecycle reference with three-second stages`.
- Current production frontend: ECS task definition **`navigan-frontend-TaskDefinition-j9W80aX9PBkf:37`**.
- Current immutable production image: **`905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend@sha256:7ac2946a96bf9ecb68f0337324ee04e1da4a5e9a639a02bb43d45bd8513e13e7`**.
- Deployment script reported running-image verification and health/login HTTP checks passed. Fresh authenticated end-to-end workflow and measured performance acceptance are still required.
- The user visually accepted the lifecycle/About result: “ok now it looks ok.”
- Current open question: the user cannot see Headlamp, Prometheus or Grafana in Argo CD. Resolve this visibility/application-name issue before merging the Headlamp demo PR.

Before edits:

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test
git branch --show-current
git status -sb
git log -5 --oneline
git fetch origin main
git rev-parse HEAD origin/main
```

Preserve local files. A generated `frontend/next-env.d.ts` modification was observed during the main merge flow and was not intentionally committed; recheck it before staging anything.

## 2. Lifecycle/About production increment

The previous seven-point orbit was replaced by the approved five-stage story:

1. **Prepare** — Customers · Environments
2. **Build** — Cluster management
3. **Transform** — App transformation · Planned
4. **Move** — Migration · Onboarding
5. **Evolve** — Upgrades · Planned

Implemented behavior:

- Each stage is active for **3 seconds**; the loop is 15 seconds.
- Platform-guide heading and detailed explanatory copy change with the active stage.
- Copy transitions use a gentle faded/cross-fade effect (approximately 650 ms).
- About no longer has a redundant title bar/breadcrumb.
- About is separated from operational navigation and presented as a sidebar footer icon entry.
- The page avoids an unnecessary page scrollbar at the accepted viewport while retaining responsive behavior.

Release evidence:

- Source commit: `954a34ab28a1d7c7a75fa2715762b305bcc2d55e`.
- First successful lifecycle production release: task definition `:30`.
- Image digest for that release: `sha256:7bbd4bce498b36e3b69837fcd8da8e0304b15cd45e57c5de62b39c8dc317705a`.
- User acceptance after deployment: “ok now it looks ok.”

## 3. Workspace-loading performance increment

Reported symptom: Migration data/charts and Platform Dashboard/other screens took roughly 6–8 seconds to appear.

Diagnosis recorded during implementation:

- Migration chart data is derived client-side from the migrations list; the chart package itself was not the primary bottleneck.
- Platform Dashboard launched about eight requests and held the whole view behind the slowest summaries.
- It also loaded up to 100 environment records solely to compute provider totals, although provider totals already existed in the environment summary.

Implemented at `a230178`:

- Platform Dashboard uses environment summary `byProvider`; the redundant 100-record environment request was removed.
- Dashboard sections render progressively with individual loading states instead of a single full-page blocker.
- Workspace data prefetch begins on navigation intent for Customers, Environments, Clusters, Dashboard and Migrations.
- Authorized users receive a background Migrations prefetch after about four seconds.
- Existing React Query cache behavior remains approximately 90 seconds.

Validation completed before release:

- 470 frontend tests passed.
- TypeScript passed.
- Prettier passed.
- Production Next.js build passed.

Production release:

- Commit: `a23017808c54e3136fc05f868473d59fa2dc9d16`.
- Image tag: `release-a23017808c54-09af632c1c9e`.
- Digest: `sha256:b35355a51da78e66ef6d2dd644e9f388f757e23f87b630e2be087c1dcb36e3bf`.
- Candidate and deployed task definition: `:33`.
- Rollback task recorded by the execute step: `:30`.
- Health/login HTTP checks passed.

Two prepare-only task definitions, `:31` and `:32`, were accidentally created from the older `954a34a` source. Both referenced the already-deployed lifecycle digest and **were never executed**. Do not treat them as performance releases.

Remaining acceptance: measure first and warm navigation for Dashboard, Migrations, Customers, Environments and Clusters in an authenticated production session. Record browser/network timing and identify any slow backend endpoint before further optimization. Do not claim the 6–8 second symptom is solved without those measurements.

## 4. Headlamp 0.46.0 customer-demo preparation

Demo cluster: **`New-dbs-demo-cluster`**.

Private GitOps/system repository:

- GitHub: `https://github.com/Navigan-Org1/db-schenker-new-dbs-demo-cluster-system`.
- Local checkout: `/mnt/b/Langchain_Ai/db-schenker-new-dbs-demo-cluster-system`.
- Base branch: `main`.
- Demo branch: `demo/headlamp-0.46.0`.
- Application file: `applications/30-headlamp.yaml`.
- Change: Headlamp chart `targetRevision: 0.45.0` → `targetRevision: 0.46.0`.

Current manifest facts:

- Argo Application name is **`navigan-dashboard`**, not `headlamp`.
- Chart repository is `https://kubernetes-sigs.github.io/headlamp`.
- Helm release name is `navigan-dashboard`.
- Values come from `$values/values/headlamp.yaml` in the system repository at `main`.
- Destination namespace is `navigan-dashboard`.
- Automated sync has `prune: true`, `selfHeal: true`, `CreateNamespace=true`, and `ServerSideApply=true`.

Headlamp 0.46.0 was verified as an available chart/app version and retained the Navigan-relevant settings used by the current values. The local commit initially failed because Git author identity was missing, so the first push contained no content change. Repository-local identity was then configured, the user created a PR, and the intended compare direction is:

- **base:** `main`
- **compare:** `demo/headlamp-0.46.0`

No PR number or URL is recorded in this kit. Verify the open PR shows exactly the one-line `0.45.0` → `0.46.0` change before the demo.

## 5. Argo CD naming and current blocker

The Navigan labels and Argo application names differ:

| Navigan tool | Argo CD application |
|---|---|
| Headlamp | `navigan-dashboard` |
| Prometheus + Grafana | `navigan-monitoring` |
| Cluster connector | `navigan-connector` |
| Falco | `navigan-falco` |
| System app-of-apps parent | `navigan-system` |
| Argo CD itself | Bootstrap-installed; not expected as a child Application |

The user reported none of Headlamp/Prometheus/Grafana is visible in Argo CD. First:

1. Clear all Argo CD application filters/project/namespace selectors.
2. Search the internal names above, especially `navigan-dashboard` and `navigan-monitoring`.
3. If only `navigan-system` appears, open its resource tree and inspect the child `Application` resources.
4. Confirm the parent app watches this exact system repository and `main` branch and recursively includes `applications/`.
5. Confirm the signed-in Argo role/project can list child Applications.

**Do not merge the Headlamp PR until `navigan-dashboard` is visible either in the application list or as a child of `navigan-system`.** If it is absent, the upgrade cannot be confidently demonstrated through that Argo instance; diagnose repository path, root application, project/RBAC and cluster association first.

## 6. Planned live demo and rollback

Pre-demo:

- Keep the PR open.
- Show the PR diff is one line.
- Confirm Headlamp currently reports 0.45.0.
- Confirm `navigan-dashboard` is visible and `Synced / Healthy`.
- Keep the system repository and Argo CD pages ready.

During the demo:

1. Launch Headlamp through Navigan and show 0.45.0.
2. Show the one-line PR.
3. Merge the PR to `main`.
4. Show `navigan-dashboard` reconcile through OutOfSync/Syncing and Progressing to Synced/Healthy.
5. Reopen Headlamp through Navigan and show 0.46.0.

Pushing the demo branch alone does not change the cluster because the Argo source tracks `main`; merging to `main` is the runtime trigger.

Rollback is a Git revert on `main` restoring `targetRevision: 0.45.0`, followed by Argo reconciliation. Argo's automated sync maintains declared state but does not guarantee automatic semantic rollback of a bad desired version.

## 7. Capability boundary for installing new utilities

The current GitOps shape can deploy a new Argo Application or allowed Kubernetes YAML under the system repository when the parent app watches that path and the destination/project permits it. That is enough to demonstrate Git-driven installation at the cluster layer.

It does **not** automatically make every new utility a first-class Navigan tool. A new tool may additionally need:

- a Navigan dashboard/health card;
- launch/proxy routing and private gateway support;
- role/tenant authorization;
- configuration and secret handling;
- health/readiness integration;
- tests and product navigation.

Current first-class launch paths were recorded for Headlamp, Grafana, Prometheus and Argo CD. Verify code/runtime before claiming support for another utility.

## 8. Historical migration work remains valid but is not today's active task

The 23 October handoff remains the detailed record for DEV artifact workspaces, collection/recovery, final export, migration UI architecture and the accepted Migration Overview. Key status remains:

- All 12 displayed collection jobs were user-reported successful.
- Final export downloaded with 14 collected artifacts and 2 historical exclusions.
- Target readiness, target deployment, persistent-data migration and traffic cutover were not completed.
- Broader migration workflow redesign was put on hold unless the user explicitly resumes it.

Do not overwrite those facts with the newer lifecycle/performance/GitOps work, and do not infer target migration completion.

## 9. Safe next action

First resolve the Argo CD visibility question for `New-dbs-demo-cluster`. Obtain either:

- an Argo CD screenshot with filters cleared and the application list; or
- read-only output listing Applications and the `navigan-system` resource tree/spec.

Then rehearse the upgrade without merging the PR. Separately perform authenticated production timing for the performance release. Do not make additional production/frontend or cluster mutations merely to recover context.

No credentials, tokens, private keys, signed URLs or secret values belong in this kit.
