# Promote the UI enhancements to PROD

Scope: Customer creation, Environment creation/details, Cluster setup, and shared overview/donut presentation. No SAM, API, database, collector or existing customer-cluster deployment. Known minor Cluster setup presentation polish is deferred by the user.

The user reported PROD frontend task revision24 stable with desired1/running1/pending0 on29October2026. Preparation reads the live service again rather than assuming that revision is still current.

## Validate and merge (user executes)

Use the existing checkout. Preserve generated next-env.d.ts and private/untracked files. No clean, reset, stash or force-push is needed. Fetch explicitly because this checkout previously had a restricted fetch configuration.

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test &&
git fetch origin \
  '+refs/heads/main:refs/remotes/origin/main' \
  '+refs/heads/feature/ui-migration-enhancements:refs/remotes/origin/feature/ui-migration-enhancements' &&
git switch feature/ui-migration-enhancements &&
git merge --ff-only origin/feature/ui-migration-enhancements &&
git diff --check origin/main...HEAD &&
(cd frontend && npm run typecheck && npm test)
```

After validation passes:

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test &&
if git show-ref --verify --quiet refs/heads/main; then
  git switch main
else
  git switch --no-track -c main origin/main
fi &&
git merge --ff-only origin/main &&
git merge --ff-only feature/ui-migration-enhancements &&
git push origin main
```

Fast-forward guards stop if either branch has diverged; inspect any failure instead of forcing it.

## Prepare the immutable frontend release

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test &&
TMPDIR=/var/tmp /mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-frontend-prod.py --profile navigan --prepare
```

The helper requires local main to match origin/main and clean release-source paths. It exports committed frontend source, builds once in Linux Docker, starts that same image with two fixture configurations to test portability, and pushes to the existing navigan/frontend repository. It copies the actual running PROD task and registers a candidate with its immutable image digest and three allowlisted public OIDC/app settings, derived from the verified existing PROD CloudFormation/Cognito configuration. Existing API origin/path, feature flags, sidecars, roles, network and remaining settings are preserved. Conflicting existing public settings or secret bindings stop preparation. This frontend-only path does not gate on unrelated collector health.

Preparation saves private original/candidate task records, rollback reference and release-plan.json. It does not update the ECS service. Do not share the private records. Share only the final summary/plan path when requesting help. Docker progress is visible.

## Execute the saved plan (user executes)

Use the exact release-plan.json path printed by preparation:

```bash
TMPDIR=/var/tmp /mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-frontend-prod.py --profile navigan \
  --execute /var/tmp/navigan-prod-frontend-REPLACE/release-plan.json
```

Execution does not rebuild. It rechecks account, PROD identity/API settings, stable baseline, original-task fingerprint, exact candidate delta and ECR digest. It updates only the existing frontend service task reference. It waits for steady state and verifies the requested task/image, health/login endpoints and public runtime configuration. A circuit-breaker rollback or incorrect runtime is reported as failure. Browser sign-in and the five changed UI areas still require authenticated acceptance.

## Rollback

Use the saved plan's previousTask (not an assumed revision). First inspect the rollout. The existing ECS service can be restored with:

```bash
aws ecs update-service --profile navigan --region ap-south-1 \
  --cluster navigan-frontend-Cluster-bw32Pkwxn8Cs \
  --service navigan-frontend-Service-vMtHq9h7A9mz \
  --task-definition PREVIOUS_TASK_ARN_FROM_THE_SAVED_PLAN \
  --query 'service.taskDefinition' --output text --no-cli-pager
```

Wait for steady state, check the running task/image and sign in again. No automatic rollback is performed for failed post-rollout HTTP/runtime checks; the saved task remains the explicit recovery point.

## Verification in development

127 focused promotion/domain regression tests passed without live AWS/Docker calls. Coverage includes portable candidate deltas and configuration conflicts, immutable image verification, failed portability checks preventing publication, format2 preparation without a service update, stale runtime configuration preventing execution, incorrect deployed runtime failure, task drift, rollback detection and legacy domain-release compatibility. Actual AWS preparation/deployment and authenticated PROD acceptance are pending user execution.


## Rollout timing fix after successful revision25 promotion

The user confirmed revision25 COMPLETED, public health/login/runtime-config checks passed and the new UI is visible in PROD. The previous helper returned from its services_stable waiter before the strict rollout-state check passed. It now polls the requested revision for COMPLETED for up to ten additional minutes, without issuing another service update. FAILED rollouts and changed task references still stop, and a timeout is reported as pending completion rather than an assumed rollback. Runtime guard failures print a concise stopped message instead of a Python traceback.130 targeted production/domain regression tests passed, including delayed completion, timeout without writes and failed-rollout rejection. This changes future deployment tooling only. Do not rebuild or rerun the already-completed revision25 deployment.
