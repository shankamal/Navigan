# Restore production summary APIs

Production frontend revision 15 is accepted. Browser evidence shows three summary requests returning HTTP 404, followed by separate pageSize=1 count requests. Successful list calls take roughly 4–8 seconds; effective-access calls are roughly 200–480 ms in this capture. Screenshots establish a missing production summary contract, not whether API Gateway or handler deployment is responsible, nor the cause of individual list latency.

The existing frontend calls /customers/summary, /environments/summary and /clusters/summary. Its compatibility fallback issues 9 customer, 11 environment and 8 cluster count calls. Restoring three working summaries removes these 28 fallback calls on a cold dashboard load. Regular list requests remain; this release does not promise a specific latency improvement.

## Scope

Use scripts/deploy-summary-apis-prod.py. Default mode reads account, stacks, Lambda configuration and routes. --prepare downloads checksum-verified deployed ZIPs and adds only the existing summary contract to each handler/repository if absent. AST checks prove all other Python nodes are preserved; known existing summary implementations remain unchanged and unknown implementations fail closed. Dependencies, authentication modules, write paths, environment variables and database settings remain untouched. Cluster summaries retain the installed archived-cluster visibility boundary; an older incompatible boundary stops preparation for review.

The helper adds missing summary routes using the corresponding live list route's JWT authorizer, scopes and integration, plus an exact API/stage/method/path Lambda invocation permission. It uses existing private versioned deployment storage and a parent change set containing only the three affected nested stacks. It rejects resource deletion/replacement, unrelated changes, stale stack/Lambda revisions and unexpected templates. Private original templates, ZIPs and Lambda configurations are retained for rollback review. No database migration, IAM role change, frontend rebuild or migration/connector deployment is required.

## Release

From the existing new_migration_approach_18oct26 checkout:

```bash
git pull --ff-only origin new_migration_approach_18oct26

TMPDIR=/mnt/b/Langchain_Ai/navigan-deploy-tmp \
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-summary-apis-prod.py --profile navigan --prepare
```

Inspect the printed summary route status and change set. Preparation does not update running APIs. Execute the newly printed release-plan.json using the same script's --execute PLAN argument. Do not reuse another script's release plan. If a deployed package differs from the supported contract, retain the private record and review the reported guard rather than widening the release scope.

After execution, refresh the authenticated dashboard with Network open. Confirm all three /summary calls return 200 with counts, the pageSize=1 fallback burst is absent, and counts agree with authorized list filters. Verify customer/environment/cluster screens and an existing draft remain usable. Capture the duration of remaining list requests. Authentication, multi-customer visibility and production end-to-end timing cannot be verified locally.

Validation: 12 release/package/query scope tests and 4 existing frontend summary/fallback tests passed. Tests cover JWT route inheritance, exact invocation permission, additive handler behavior, GET-only read-only execution, existing tenant scope, archived-cluster filtering, native dependency preservation, unknown contracts, unrelated modifications and replacement rejection. CLI help checked. No AWS release has been prepared or executed by the agent.
