# Deployment-source discovery — DEV increment, 19 October 2026

Branch: `new_migration_approach_18oct26`. This extends Discovery & Assessment and simplifies Migration Scope. It does not enable migration execution.

## Delivered behavior

- Workload/container image references, current-Pod runtime image identities and observed digests are distinct. Init containers are included. Owner references join ReplicaSets to Deployments and Jobs to CronJobs; image/name similarity is never used as ownership proof. Finished Pods are excluded. Collection failures, pagination and missing runtime observations are visible gaps.
- Approved metadata values identify Helm chart/release, application version, and Argo CD/Flux/manager hints. Arbitrary labels/annotations remain excluded. GitOps application specifications are not yet queried.
- Source connections are saved once per registered customer/source cluster. Other assessments using that registration reuse them. Delivery settings updates preserve discovery settings and analysis. Cross-customer reuse remains blocked.
- GitHub repository input accepts a GitHub.com URL or owner/repository, revision and optional deployment directory. Public repositories use anonymous access; private repositories use a source-specific fine-grained token or reuse the customer's active GitHub App installation with a single-repository contents:read token. GitLab/Azure Repos adapters and source-specific GitHub App onboarding are not added by this increment.
- Static analysis resolves the requested revision to an exact commit, indexes Chart.yaml metadata, templated Helm file locations, plain manifest identities/images, Kustomize files and script deployment command/path hints. Scripts are never executed. Rendered values, complete pipeline invocation structure and deployed-commit provenance remain unverified.
- Matching namespace/API/kind/name or chart metadata produces candidates. Unique candidates can be confirmed in bulk; ambiguous candidates can be selected individually. Confirmed means user-selected, not a verified deployed commit.
- Registry checks inspect referenced images only. Source-account AWS ECR uses backend IAM; public or authenticated OCI/Docker Registry V2 endpoints use anonymous, username/read-token or pre-issued bearer credentials. Current DEV IAM image metadata reads cover ap-south-1 in account 905418045935. Other ECR accounts/regions require further permission setup. Private network registries/custom CAs are not supported by backend HTTP access.
- Digest differences are observations, not automatic drift verdicts: multi-architecture index and platform manifest digests can legitimately differ. Registry metadata availability is not proof of target pull access or target compatibility.
- Discovery has Workloads & versions, Deployment structure, Container registry and Evidence gaps views. Migration Scope has a selected-only evidence summary and discovery link. All mutations check permissions and optimistic versions; view rendering does not launch analysis, refresh or installation.

## APIs

All require existing JWT authentication and migration access; mutations require `migration.edit` and customer access. Features require backend `MIGRATION_SOURCE_FIRST_ENABLED=true`.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/v1/source-clusters/{sourceClusterId}/deployment-sources` | Source connection settings, version and available customer GitHub organizations. |
| PUT | `/api/v1/source-clusters/{sourceClusterId}/deployment-sources` | Versioned save of repository/registry settings, optional write-only credentials, access verification and inspected artifact confirmations. |
| GET | `/api/v1/migrations/{migrationId}/deployment-evidence` | Evidence correlated with the latest assessment inventory, plus inspected-source timestamps. |
| POST | `/api/v1/migrations/{migrationId}/deployment-evidence` | `{version}` runs bounded static repository/registry inspection. `{version, refreshCluster:true}` explicitly requests a fresh cluster inventory/assessment. |

Existing `source_clusters.delivery_configuration` JSON stores deploymentDiscovery, deploymentAuthentication metadata and sanitized deploymentAnalysis alongside delivery settings. Credential values live only in Secrets Manager; public settings omit secret version IDs and source detail responses omit authentication internals. No schema migration. Analysis stores references and evidence summaries, never raw repository files or credentials. The inspected source commit is separate from the live inventory's observation time. Configuration changes invalidate old candidate results; confirmations do not change the repository/registry configuration digest.

Scans are bounded to three repository roots, thirty eligible files per repository, 100 KB per file, 500 indexed artifacts per root and a shared analysis time budget. Partial scans are labelled. YAML aliases/tags are excluded from parsing. Large repositories should use the relevant deployment/environment directory. Advanced Helm rendering and dynamic shell dependency resolution remain pending.

## Deploy from WSL

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test
git pull --ff-only origin new_migration_approach_18oct26
python3 scripts/deploy-source-connection-screen-dev.py --profile navigan --apply --upgrade-source-connector
```

If both Lambda code updates succeeded but the configuration phase stopped, add `--finish-deployment` to the same command. This resumes routes, IAM, environment and the optional connector upgrade without downloading dependencies or re-uploading Lambda packages. Successful write-only AWS CLI operations with empty stdout are accepted.

The script backs up the current two Lambda ZIPs/configuration, bundles pinned PyYAML and updated migration modules, adds only the four new JWT routes using the existing integration/authorizer/scopes, grants migration metadata-read permissions, and reuses GitHub App settings from the current DEV cluster function. It does not alter the database schema.

The optional connector upgrade targets the approved DB Schenker DEV lab only: SSM instance i-08e28d9b2242cbd53, source SRC-2f0e434335e04ef0bdccd74cb3322f2c. It first authenticates the existing connector and checks that source identity. It adds Pods/ReplicaSets list permissions and mounts a versioned code-only ConfigMap into the existing deployment. It preserves registration, credential references and the connector image. No new connector enrollment, duplicate deployment, interactive SSM session or Docker build is needed. A failed rollout requests the previous deployment revision. This is a DEV runtime override; a future normal connector image build must contain these modules too.

## Test with DBS_Migration_Assessment

1. Open Discovery & Assessment. Existing completed evidence remains readable.
2. Use Manage deployment sources to save the application's repository/revision/deployment directory and registry hostnames. GitHub URLs and credentials are not accepted in repository input; use owner/repository.
3. Use Analyze deployment sources. Review artifacts, candidates and per-image registry access statuses. Resolve ambiguous candidates or confirm unique candidates after review.
4. After the connector upgrade, use Refresh cluster evidence once to collect current Pods and deployment metadata. This creates new inventory/assessment versions and temporarily returns the assessment to discovery; previous snapshots remain stored. Re-save/review migration scope against the new evidence before target compatibility.
5. Open Migration Workspace, select a subset of workloads, and confirm the deployment summary contains only that subset and no deployment-method form.

Local tests use API/Kubernetes/AWS/GitHub fixtures. Real customer repository authorization, registry responses, DEV API deployment and SSM rollout require verification in the user's AWS instance; no live deployment is implied by local test success.

## Authenticated connection setup — 19 October 2026

Source connections now appears before the discovery controls. Fields are editable for migration.edit users; load failures have a retry action and missing permissions are explained. Each connection has an authentication selector, mandatory markers and tooltips. Save connections persists configuration; Save and verify access also checks repository contents at the selected revision/directory and registry `/v2/` access. Discovery/assessment starts and cluster-evidence refresh require verified configured repositories and registries, or a saved explicit inventory-only choice. Existing completed evidence remains available.

GitHub.com supports public access, existing customer App installations, and fine-grained tokens restricted to selected repositories with Contents: read-only. This increment does not add OAuth or new source-specific App installation onboarding. Tokens for personal and organization repositories can be entered without going through the cluster-system-repository App onboarding.

Registry V2 supports public registries, username plus read-only token (including Docker Hub/private robot credentials), and pre-issued bearer tokens. Cloud registries requiring an external authentication service can use an appropriate short-lived bearer token. ECR IAM mode validates the registry account against the registered source AWS account; no AWS keys are entered. Registry API verification is not proof that all repository/image paths are accessible; analysis checks each image reference. Separate-host token challenges never receive credentials except Docker Hub's fixed auth.docker.io host. Other hosted registries with separate token services must use a pre-issued bearer token. The backend performs only GET requests to registry metadata APIs, never pushes images.

New credentials are encrypted with Secrets Manager's default encryption, using customer/source-derived names below `navigan/source-connections/`. Stored version IDs pin each saved configuration to its credential version, so a failed database save cannot silently rotate credentials used by the previous saved configuration. Authentication values do not enter source JSON, assessment JSON, application logs, responses or browser storage. Password inputs are cleared after success/failure. Previously encrypted credential versions remain in Secrets Manager under its normal version retention rules; removing a connection removes the active reference, not the retained secret. This is source-registration reuse within one customer, not a cross-customer credential pool.

Registry reads require HTTPS, valid public DNS addresses and strict TLS; connections pin the vetted address while retaining hostname verification. Private, loopback, link-local and mixed public/private DNS answers are rejected; redirects are not followed. Requests, response sizes and verification work are bounded. Unsupported endpoint access remains visible as an access failure rather than a connected status.

Deploy this UI/backend increment with the existing DEV script (no connector restart is required for this increment):

```bash
git pull --ff-only origin new_migration_approach_18oct26
python3 scripts/deploy-source-connection-screen-dev.py --profile navigan --apply
```

The DEV script now packages source_authentication.py and grants Secrets Manager create/put/read only under the source-connections prefix, plus ECR GetAuthorizationToken. New routes and schema changes are unnecessary. For Retailflow use `https://github.com/arajendr/RetailFlow` and registry `905418045935.dkr.ecr.ap-south-1.amazonaws.com`, choosing a source-repository token if the existing customer App does not cover arajendr. Verify from the browser after deploying; no live AWS or private repository authentication has been tested from the development agent environment.
