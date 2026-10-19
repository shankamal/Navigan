# Deployment-source discovery — DEV increment, 19 October 2026

Branch: `new_migration_approach_18oct26`. This extends Discovery & Assessment and simplifies Migration Scope. It does not enable migration execution.

## Delivered behavior

- Workload/container image references, current-Pod runtime image identities and observed digests are distinct. Init containers are included. Owner references join ReplicaSets to Deployments and Jobs to CronJobs; image/name similarity is never used as ownership proof. Finished Pods are excluded. Collection failures, pagination and missing runtime observations are visible gaps.
- Approved metadata values identify Helm chart/release, application version, and Argo CD/Flux/manager hints. Arbitrary labels/annotations remain excluded. GitOps application specifications are not yet queried.
- Source connections are saved once per registered customer/source cluster. Other assessments using that registration reuse them. Delivery settings updates preserve discovery settings and analysis. Cross-customer reuse remains blocked.
- GitHub repository input accepts a GitHub.com URL or owner/repository, revision and optional deployment directory. Public repositories use anonymous access; private repositories use a source-specific fine-grained token or reuse the customer's active GitHub App installation with a single-repository contents:read token. GitLab/Azure Repos adapters and source-specific GitHub App onboarding are not added by this increment.
- Static analysis resolves the requested revision to an exact commit, indexes Chart.yaml metadata, templated Helm file locations, plain manifest identities/images, Kustomize files and script deployment command/path hints. Scripts are never executed. Rendered values, complete pipeline invocation structure and deployed-commit provenance remain unverified.
- Matching namespace/API/kind/name or chart metadata produces candidates. Unique candidates can be confirmed in bulk; ambiguous candidates can be selected individually. Confirmed means user-selected, not a verified deployed commit.
- Registry checks inspect referenced images only. AWS ECR uses independently authorized IAM access; public or authenticated OCI/Docker Registry V2 endpoints use anonymous, username/read-token or pre-issued bearer credentials. Current DEV IAM image metadata reads cover ap-south-1 in account 905418045935. Other ECR accounts/regions can use a customer role with the necessary trust and permissions. Private network registries/custom CAs are not supported by backend HTTP access.
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

Registry V2 supports public registries, username plus read-only token (including Docker Hub/private robot credentials), and pre-issued bearer tokens. Cloud registries requiring an external authentication service can use an appropriate short-lived bearer token. ECR IAM modes no longer compare the registry account to the source cluster account. Existing backend access or a separately configured customer role is used; no AWS keys are entered. Registry API verification is not proof that all repository/image paths are accessible; analysis checks each image reference. Separate-host token challenges never receive credentials except Docker Hub's fixed auth.docker.io host. Other hosted registries with separate token services must use a pre-issued bearer token. The backend performs only GET requests to registry metadata APIs, never pushes images.

New credentials are encrypted with Secrets Manager's default encryption, using customer/source-derived names below `navigan/source-connections/`. Stored version IDs pin each saved configuration to its credential version, so a failed database save cannot silently rotate credentials used by the previous saved configuration. Authentication values do not enter source JSON, assessment JSON, application logs, responses or browser storage. Password inputs are cleared after success/failure. Previously encrypted credential versions remain in Secrets Manager under its normal version retention rules; removing a connection removes the active reference, not the retained secret. This is source-registration reuse within one customer, not a cross-customer credential pool.

Registry reads require HTTPS, valid public DNS addresses and strict TLS; connections pin the vetted address while retaining hostname verification. Private, loopback, link-local and mixed public/private DNS answers are rejected; redirects are not followed. Requests, response sizes and verification work are bounded. Unsupported endpoint access remains visible as an access failure rather than a connected status.

Deploy this UI/backend increment with the existing DEV script (no connector restart is required for this increment):

```bash
git pull --ff-only origin new_migration_approach_18oct26
python3 scripts/deploy-source-connection-screen-dev.py --profile navigan --apply
```

The DEV script now packages source_authentication.py and grants Secrets Manager create/put/read only under the source-connections prefix, plus ECR GetAuthorizationToken. New routes and schema changes are unnecessary. For Retailflow use `https://github.com/arajendr/RetailFlow` and registry `905418045935.dkr.ecr.ap-south-1.amazonaws.com`, choosing a source-repository token if the existing customer App does not cover arajendr. Verify from the browser after deploying; no live AWS or private repository authentication has been tested from the development agent environment.

## Independent registry accounts — 19 October 2026

Registry hosting is independent of Navigan hosting, the source cluster and the migration target. The shared DEV account is a deployment constraint only. The account-comparison restriction was removed in that increment. The subsequent provider-form update below replaces direct backend IAM connections with explicit customer roles. A new AWS ECR customer-role method works with a separately authorized registry account/region, including a role in the same account for budget-conscious DEV testing.

1. Add the ECR registry hostname. Account and region are derived from it and displayed separately from the source cluster.
2. Choose **AWS ECR · Customer IAM role (any account)** and enter `arn:aws:iam::<registry-account>:role/navigan-source-discovery/NaviganRegistryReadOnly`.
3. Select **Save connections**. Navigan generates and persists an External ID for this authorized customer/source/registry connection; it cannot be supplied by the browser.
4. Expand **Customer role trust and permissions**. The registry administrator creates the role with IAM path `/navigan-source-discovery/`, using the displayed exact Navigan backend principal, External ID condition and ECR metadata permission policy. An example provisioning command is `aws iam create-role --path /navigan-source-discovery/ --role-name NaviganRegistryReadOnly --assume-role-policy-document file://trust.json`; attach the displayed permission policy separately. Provisioning is performed in the registry account, not automatically by Navigan.
5. Select **Save and verify access**. Verification rejects roles that can be assumed without the External ID or with an incorrect External ID. Only then does it assume the role with the saved ID and temporary credentials. A restrictive session policy allows ECR GetAuthorizationToken and DescribeImages in the registry account/region. No application deployment, IAM administration, image pushes or secret reads are allowed by that session.
6. Image analysis uses the same saved role identity, registry account and region. Unverified role connections cannot be used for role-based image inspection.

The DEV deployment script grants STS AssumeRole only for the `navigan-source-discovery/` IAM path and exposes the backend principal ARN in settings for the trust template. This intentionally avoids arbitrary-role assumption, including the source-connector installation role. No customer/source AWS account ID is hardcoded into runtime registry authorization. The customer must grant trust and permissions; entering an ARN alone does not grant access. Temporary AWS credentials never enter the source configuration or API response.

The screen identifies common registry providers from their hostname. Docker Hub, GHCR, Harbor and other standards-compatible public HTTPS registries use public, username/read-token or bearer-token access. Azure ACR and Google Artifact Registry can use a suitable provider-issued token through these adapters; native Azure/GCP federation onboarding is not implemented. Connector-routed private-network registry access and custom CA support are still pending and are explicitly described as unavailable. No unimplemented network-access method is offered as an active option.

Validation includes independent registry/source accounts, registry-region selection, customer-bound External IDs, negative trust checks, constrained role paths/session policies, temporary credential use, saved trust guidance and provider-specific UI options. Cross-account AWS access has been mocked in tests; live access still requires customer role provisioning and DEV verification.

## Provider-specific registry form and removal of platform IAM shortcut

The active registry form now separates provider from authentication. Providers: Amazon ECR, Azure Container Registry, Google Artifact Registry/GCR, Docker Hub, GHCR, Harbor and other OCI/Docker registries. Hostnames infer known providers, while the selector also supports self-hosted registries. The backend validates provider/hostname consistency and allowed authentication modes; provider metadata is stored with the source connection, not in the credential secret.

The AWS ECR Navigan IAM role option has been removed. New AWS ECR connections use the customer IAM role method, including in the shared DEV account. Previously saved platform IAM connections must be replaced before discovery can start. New API saves reject AWS_IAM, and analysis does not silently use the platform role for unconfigured ECR credentials. Existing completed assessment evidence is retained.

The suggested AWS role name is `NaviganRegistryReadOnly`, with IAM path `/navigan-source-discovery/`. For DEV account 905418045935 its ARN is `arn:aws:iam::905418045935:role/navigan-source-discovery/NaviganRegistryReadOnly`. The form pre-fills this naming convention from the entered registry account. The role is not created automatically and must trust the displayed backend principal with the generated External ID. The same role name/path may be used in another authorized registry account; only the account ID and that connection's External ID differ.

Azure labels identify the application client ID / ACR repository-token username and client secret / token password. Google access-token mode supplies username `oauth2accesstoken` and asks for a short-lived Google OAuth token. GHCR identifies read:packages credentials; Harbor identifies robot-account pull credentials. These are provider-specific presentations of the supported standard registry token exchanges, not native identity-federation onboarding. Live provider authentication is still verified from the customer's DEV environment; tests use mocked remote services.

The DEV deployment policy no longer grants the backend its own ECR GetAuthorizationToken/DescribeImages shortcut for deployment discovery. Those operations use the explicitly configured customer role, even in the shared DEV AWS account.

After saving an AWS role connection, Download AWS role setup exports a CloudFormation JSON template containing the selected role name/path, exact backend principal, generated External ID and read-only ECR metadata permissions. Deploy it in the registry account using CloudFormation, then verify the connection. An existing role must have its policies updated instead of being created again. No IAM role was created by the development agent.

## Existing IAM role reuse

AWS authentication now offers **Create new IAM role** and **Existing IAM role** separately. Both use temporary credentials and the same bounded read-only ECR session policy. The existing-role mode takes a registry-account role ARN, retains the connection's generated External ID and does not generate a role-creation download. The administrator adds the displayed trust statement to the existing trust policy without removing existing EC2/EKS/service principals, and attaches the ECR metadata read policy separately.

Existing roles in the dedicated `/navigan-source-discovery/` path work under the existing deployment authorization. For an existing role outside that path, the deployment operator authorizes its exact ARN once, without broadening the caller to arbitrary IAM roles:

```bash
python3 scripts/deploy-source-connection-screen-dev.py --profile navigan --apply --registry-role-arn arn:aws:iam::905418045935:role/YOUR_EXISTING_ROLE_NAME
```

The flag is repeatable and preserves previously authorized ARNs. It configures an exact-resource STS permission and `SOURCE_REGISTRY_ALLOWED_ROLE_ARNS` (a server-controlled JSON list). A browser cannot add to this list. Configuring a connection does not modify the IAM role or its trust policy; an unauthorized ARN produces ROLE_AUTHORIZATION_REQUIRED rather than using fallback platform credentials. Registry-account binding, correct/absent/incorrect External ID checks, and the read-only session policy are enforced for both role methods. Names/paths of existing roles are retained.
