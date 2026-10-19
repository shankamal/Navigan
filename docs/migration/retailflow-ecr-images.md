# Retailflow images in private ECR — DEV

The current Navigan lab reference manifests use public Python, Nginx, PostgreSQL, Redis, BusyBox and curl images. Application code and web assets are mounted through ConfigMaps. This does not establish the contents or build process of the separate `arajendr/RetailFlow` repository, which was unavailable to the connected repository reader.

## Copy the actual source references

From the existing WSL DEV checkout with AWS CLI, the navigan AWS profile and a running Linux Docker daemon:

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

The copied tags include the upstream tag, amd64 and a suffix from the inspected local image identity. New repositories use immutable tags and scan-on-push. The copier tags the inspected image ID, pushes and confirms ECR metadata. Existing repositories are retained; unrelated AWS/Kubernetes resources are not modified. Existing tags are not overwritten. Images already referencing this registry are left in place.

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
