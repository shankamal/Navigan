# Selective releases: build once, deploy many

This is the DEV-first automation contract. The first implementation is a read-only
planner and a GitHub workflow that tests the planner. It does not yet build or
publish release artifacts, execute CloudFormation, apply SQL or update a service.
Existing verification workflows remain independent. Do not describe this planning
pilot as an enabled end-to-end deployment pipeline.

## Two independent decisions

1. **Build:** compare a selected source revision with the previous release
   manifest. Build only artifacts affected by changed inputs and dependencies.
   Keep all unchanged artifact references in the next manifest.
2. **Deploy:** compare the approved candidate manifest with the target
   environment's last successful deployment record. Deploy only changed artifact
   references and required configuration changes. Promotion performs no builds
   and no republishing.

Do not use the latest push or HEAD~1 as a guessed deployed baseline. Changes can
span multiple commits, deployments can fail, and DEV and PROD can run different
releases. Initial baseline adoption must be established explicitly from live
evidence before an executor can operate on an existing environment.

## Impact rules

| Change | Artifact selection | Other checks |
|---|---|---|
| Frontend source/dependencies | Frontend | Frontend tests/build checks |
| Frontend tests only | None | Frontend tests |
| Python source/dependencies | Backend and image worker | Backend tests |
| Infrastructure only | Template bundle | Infrastructure validation |
| Lambda runtime/build inputs in templates | Backend and templates | Backend/infrastructure checks |
| New SQL migration | Database bundle | Disposable database migration tests |
| Applied SQL edit/deletion/rename | Review required | Do not silently replace history |
| Runner or embedded EKS Terraform | Runner image | Terraform checks |
| Connector or tools gateway source | Corresponding image | Corresponding checks |
| API specification | No automatic application rebuild | Producer/consumer contract checks |
| Documentation | None | No cloud deployment |
| Unknown path | Review required | Define its dependencies first |

The image-worker Dockerfile currently copies the Python source tree, so source
changes also invalidate that image's input hash. This is an explicit dependency,
not an instruction to build every component. Bootstrap-template changes require
backend/template-consistency checks. Existing source agents and customer GitOps
repositories are not automatically upgraded by an image build or by this planner.

## Immutable release manifest

The format is `navigan-release-manifest-v1`, with `sourceRevision` and a `components`
map. Each component has an `inputHash`, artifact `sha256`, immutable `uri`, and an
explicit `portable` boolean. Container URIs contain an exact digest. Packaged
artifacts have an S3 object key and `versionId`; record the content checksum too.
No credentials, tokens or environment-specific secrets belong in the manifest.

Each successful target deployment separately records `environment`, `status`,
`configurationHash`, and the exact deployed `manifest`. A failed run must not
replace that successful record. Configuration is not baked into a release bundle.
An environment-only change can require a deployment without any artifact build.

The planner validates references, not their remote existence or provenance. A
future executor must independently verify artifact bytes/digests, retained object
versions, approvals, live targets, scope, pending migrations and post-deployment
acceptance. No planner flag authorizes execution; `readyForDeployment` stays false.

## Frontend portability prerequisite

The current frontend embeds public identity/application settings with
`NEXT_PUBLIC_*` build arguments. It is not yet a portable single-image artifact
across differently configured environments. Do not build a second PROD image and
call that build-once promotion. Move environment-specific browser settings into a
validated, non-secret runtime configuration mechanism, retain private values on
the server, and test the same image with both configurations in DEV before
enabling frontend promotion. Until then, mark these artifacts non-portable; the
planner reports them for review instead of silently accepting promotion.

## Try the planner locally

Use an explicit known release commit, or a complete previous release manifest:

```bash
python scripts/plan-release.py --base <baseline-commit> --head HEAD --output release-plan.json
python scripts/plan-release.py --baseline-manifest <previous-manifest.json> --head HEAD
```

For an implementation smoke test, compare the commit immediately before adding
the planner with its new commit. That only tests change classification; it does
not establish a live deployment baseline. The CLI never guesses one.

Promotion planning uses `--promote-manifest`, `--deployment-record`,
`--environment`, and `--config-hash`. Both selected and skipped components are
explicit. Promotion always returns empty build/publish lists.

`.github/workflows/dev-release-plan.yml` runs these rules on PRs and supports a
manual baseline input. GitHub requires a workflow_dispatch definition on the
default branch before manual dispatch becomes available. Use the local CLI while
the workflow exists only on a feature branch. This workflow has no AWS credentials
or OIDC permission and cannot deploy either environment.

## Remaining implementation sequence

1. Verify classification against representative changes in the DEV pilot.
2. Establish the initial successful artifact/deployment records from live evidence.
3. Implement portable frontend runtime configuration with the same-image DEV test.
4. Build and publish only selected artifacts, once, then finalize the manifest.
5. Add a DEV executor consuming that manifest: prepare the SAM change set, apply
   only required compatible migrations through a private runner, deploy selected
   components, and perform authenticated checks before recording success.
6. Add PROD promotion of the accepted manifest after DEV acceptance. Do not rebuild
   artifacts during approval, deployment, retries or rollback.

Application rollback restores prior immutable artifacts/configuration. Database
changes stay forward-only and backward-compatible; rollback does not drop schema.
