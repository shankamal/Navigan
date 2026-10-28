# Source Connection Screen DEV rollout

Scope: new_migration_approach_18oct26, local Next.js development server and navigan-ashok-dev migration Lambda functions only.

The new first screen includes Assessment Name, all accessible active customers, new or existing source registration, hosting location, distribution and delivery-specific inputs. A registration is per cluster and may be reused by assessments. Source-first drafts persist in the existing migration table with an empty target configuration and discoveryMode MANUAL. The database target_platform remains EKS as the P0 destination family; no target environment or cluster is selected.

The connector worker skips manual DRAFT records. A recent authenticated connector heartbeat is required for verification; enrollment alone is insufficient. This verifies the connector channel, not Kubernetes inventory or application compatibility. No assessment call or discovery action is made by this screen. The separate discovery screen is intentionally deferred.

## Activate on DEV

From the existing Navigan checkout:

```bash
git pull --ff-only origin new_migration_approach_18oct26
python3 scripts/deploy-source-connection-screen-dev.py --profile navigan --apply
cd frontend
npm run dev
```

Stop an existing frontend dev process first so port 3000 is available. The new UI is selected only under NODE_ENV=development; production builds retain the existing entry point. Set MIGRATION_SOURCE_FIRST_ENABLED=false on the frontend development process to restore the old form. The DEV Lambda flag is independent and enabled by the deployment script. Do not use old stage scripts that reuse a previously built Lambda artifact for this change.

The deploy script validates the branch, AWS account 905418045935, region ap-south-1 and deployed DEV nested stack. It downloads and backs up each current Lambda package, replaces only the four changed migration Python modules, preserves deployed dependencies and all other files, updates the connector Lambda first, then the API Lambda, and enables the source-first flag only on the API Lambda. It does not change API routes, IAM roles, database schema, images or non-migration functions. Use without --apply to stage packages without modifying functions. Backups and original environment configurations remain in a private local temporary directory printed by the script. This direct Lambda update is a DEV patch and is not a CloudFormation deployment; a later infrastructure deployment must carry forward the flag or deliberately disable it.

## Delivery notes

AWS SSM is the current automated installation path. Manual Helm and GitOps generate an enrollment bootstrap compatible with migration_connector/bootstrap.ps1 and require the existing pinned image/API environment configuration. The chart itself is already in migration_connector/helm; no Git repository is written automatically. Existing non-migration capabilities remain available. Existing assessment records retain their legacy detail screens; new manual drafts reopen the source screen from the migration list.

## Validation

Run the focused frontend source connection and migration regression tests, TypeScript, and the migration model/service/repository/connector/handler tests. Live AWS verification requires the user's existing navigan profile. The screen stops after source verification; Source Discovery, scope selection, target comparison, approval and execution remain future increments.
