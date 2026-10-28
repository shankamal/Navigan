# Retailflow images in private ECR — DEV

The current Navigan lab reference manifests use public Python, Nginx, PostgreSQL, Redis, BusyBox and curl images. Application code and web assets are mounted through ConfigMaps. This does not establish the contents or build process of the separate `arajendr/RetailFlow` repository, which was unavailable to the connected repository reader.

## Copy the actual source references

From the existing WSL DEV checkout with AWS CLI, the navigan AWS profile and Docker CLI and Buildx:

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test
git pull --ff-only origin new_migration_approach_18oct26
python3 scripts/mirror-retailflow-images-dev.py --profile navigan --apply
```

Without --apply, the script performs source discovery and prints the proposed repositories without pulling or pushing images.

The script checks AWS account 905418045935 and the approved DEV branch. It uses SSM Run Command on existing control-plane instance i-08e28d9b2242cbd53 to read only image references in namespace retailflow. It includes controller templates, Pods and init containers; raw Pod bodies, environment values and Secrets are not printed or exported. The source lab must report only amd64 nodes.

It mirrors each discovered image for linux/amd64 into private ECR in ap-south-1. This is an image copy, not a new Retailflow build and not an all-architecture registry mirror. Existing source registry credentials are handled by the local Docker client. AWS registry login receives its password via stdin; tokens are not included in command arguments or reports.

Repositories retain the original registry and repository hierarchy, for example:

```text
905418045935.dkr.ecr.ap-south-1.amazonaws.com/retailflow/docker.io/library/python
905418045935.dkr.ecr.ap-south-1.amazonaws.com/retailflow/docker.io/nginxinc/nginx-unprivileged
905418045935.dkr.ecr.ap-south-1.amazonaws.com/retailflow/docker.io/library/postgres
```

The copied tags include the upstream tag, amd64 and a suffix from the selected source manifest digest. New repositories use immutable tags and scan-on-push. Buildx copies the pinned manifest and layers between registries, and the script verifies that ECR reports the exact selected source digest. Existing repositories are retained; unrelated AWS/Kubernetes resources are not modified. Existing tags are not overwritten. Images already referencing this registry are left in place.

The local `retailflow-ecr-images.json` report contains source references, resolved upstream references, ECR references and ECR digest references. Upstream tags are resolved at copy time; they are not proof of the exact bytes previously running in source Pods. A single-platform mirror can have a different digest from the upstream multi-architecture index.

Running Kubernetes workload image references are not changed by the push. To discover ECR image paths as source evidence, the next increment must configure source-node pull access and update the reviewed deployment image references, then refresh source discovery. Application code stored in ConfigMaps remains separate from these base images.

## Navigan source screen

Enter the registry host once:

```text
905418045935.dkr.ecr.ap-south-1.amazonaws.com
```

Navigan discovers multiple workload/container images automatically; there is no per-image entry form. Changing this host field does not rewrite running workloads or mirror images.

The current GitHub repository field expects owner/repository, for example arajendr/RetailFlow. It reuses a customer-bound GitHub App installation with a single-repository contents:read token. A connection for navigan-org1 does not grant access to a private repository owned by arajendr. The current cluster GitHub authorization flow provisions organization system repositories and requires write privileges; it must not be presented as a read-only source-repository onboarding flow. A separate source GitHub connect/installation binding flow remains required for a private personal-account application repository.

Validation is local fixture-based. Actual ECR image uploads, source registry access and source live inventory require the user's WSL/AWS environment.

## Switch the existing source cluster after copying

Once step 1 has produced retailflow-ecr-images.json, run from that same checkout:

```bash
git pull --ff-only origin new_migration_approach_18oct26
python3 scripts/use-retailflow-ecr-source-dev.py --profile navigan --apply
```

The mapping is read locally; no manual copy/paste or interactive SSM session is required. Use --report /path/to/retailflow-ecr-images.json when running from a different directory. Without --apply, only preflight/read operations run.

The source-only switch verifies every mapped ECR image, resolves the instance-profile role from the approved EC2 control plane, checks that the remote host actually uses that role/account, and validates the Retailflow source controllers and amd64/Ready nodes. All required current container/init-container image references must map to copied images before changes start. Paused, OnDelete, partitioned controllers and standalone Pods require a reviewed rollout plan rather than forced recreation.

The script adds a separate IAM inline policy to the source host role: GetAuthorizationToken plus pull access only to the ECR repositories in the mapping. The source lab's control plane and workers share this role in Terraform. A namespace-scoped image-pull Secret is created and explicitly referenced by the changed workload Pod templates; other existing pull-secret references are preserved by Kubernetes strategic merge. A root-owned systemd service/timer on the existing control plane refreshes the ECR credential every six hours and after boot. Credentials travel through stdin/API request bodies, never command-line arguments or reports. No additional connector, external static AWS key or customer-wide push privilege is installed.

An ECR-backed diagnostic Job verifies registry pull and baseline API/frontend readiness before updating controllers. StatefulSets are updated sequentially, followed by DaemonSets, Deployments and future CronJob templates; rollouts and application readiness are checked again afterward. Source Pods restart, including PostgreSQL and Redis, so this operation does not promise uninterrupted service. PVCs and application Secret/ConfigMap contents are not changed. Existing Jobs and their Pods are retained as historical/in-flight executions and are never replayed automatically.

Original controller templates are backed up under /opt/navigan/retailflow-ecr/backup-* with private filesystem permissions. Failed patches, rollouts or final health checks trigger a template rollback; concurrent template edits block automatic overwrite and require backup review. The failure message distinguishes restored templates from rollback failures. Credential-refresh infrastructure and read-only IAM policy remain installed when an application switch rolls back.

The source host stores reusable image patches in /opt/navigan/retailflow-ecr/source-image-patches.json, and the local checkout gets retailflow-source-ecr-result.json. These are live-controller updates and exported patches; no inaccessible application Git repository is silently edited. Integrate the generated image and imagePullSecrets patches into the actual deployment repository before subsequently reapplying original manifests, to prevent reverting source image references.

After successful checks, use Navigan's Refresh cluster evidence action and configure its source registry host as 905418045935.dkr.ecr.ap-south-1.amazonaws.com. Newly rolled application Pods should report ECR references. Retained old Jobs may still show historical Docker Hub references until their normal cleanup. The target environment is not accessed.

### Docker platform metadata handling

The mirror script uses Docker Buildx registry operations only. It resolves the source's linux/amd64 child manifest, reads the pinned image config to verify its platform, then uses `imagetools create --prefer-index=false` to copy the single-platform image into ECR. It does not pull, inspect, tag or push through the local Docker daemon, avoiding its missing-content/platform metadata failures. ECR must report the exact source manifest digest before the mapping is recorded. Existing matching immutable tags are reused; mismatches and copy failures stop the script. This does not prune images, change Docker settings or modify live source workloads.
