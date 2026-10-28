# Customer creation UI enhancement

The approved design uses customer profile on the left and contacts plus readiness on the right, with white/neutral surfaces and authentic cloud-provider logos. It is implemented on `feature/ui-migration-enhancements`, created from main commit `8c6d5741cff2c514fc3a9a9b32cdf549da2ca0d0`. Main includes all commits from `new_migration_approach_18oct26` through PR #12.

## Behaviour

- Add/edit a contact in a keyboard-accessible dialog. Only a validated contact added to the customer contributes to readiness; cancelled edits preserve the original row.
- Selected provider logos and the customer name/provider/primary-contact checklist update from current draft values.
- Name-only drafts remain supported. Email, phone and description remain optional; the current create/update API, permission checks, idempotency and optimistic version headers are retained.
- Editing a customer does not change provider associations; they remain managed separately through the existing customer details screen.
- Sticky Cancel/Save actions and responsive stacking are scoped to this form. Link navigation and reload/close warn about unsaved changes.
- Provider picker branding is opt-in for this form. Other provider-management screens keep their existing presentation.

## Local validation

Run from `frontend`:

```bash
npm run typecheck
npm test
npm run format:check
npm run build
```

The frontend workflow also runs `scripts/check-customer-creation.mjs` against its local Next server. It uses synthetic Cognito sessions and intercepts every platform API call; no live customer is created. The browser script verifies contact validation/editing, readiness, provider payloads, dirty navigation, desktop/mobile layout and name-only draft save. See the root `design-qa.md` for visual evidence and acceptance limits.

## User-executed DEV build and deployment

Use a clean checkout; preserve any local changes first.

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test &&
git fetch origin &&
git switch feature/ui-migration-enhancements &&
git pull --ff-only origin feature/ui-migration-enhancements &&
bash scripts/build.sh dev &&
bash scripts/deploy.sh dev
```

This reuses the existing release configuration, ECR and artifact storage. With the existing frontend-only release baseline, this UI change builds/deploys frontend only. Inspect the printed selected stages before execution if additional components have subsequently been enrolled. No new resources, backend API deployment or database migration is needed for this UI change. DEV currently serves the candidate frontend on port 3001 through the existing deployment helper.

In DEV, verify empty/partial draft states, AWS/Azure selection, primary and technical contact add/edit/remove, optional email/phone, unsaved changes, save and reopen, and narrow-screen layout. Actual authenticated DEV acceptance is not implied by fixture tests.

## Merge ownership

Ashok executes merging and deployment commands. Do not merge this branch or deploy to PROD automatically. Supply validation and merge commands when requested. Keep Migration feature changes separate until customer UI acceptance; broader migration redesign remains deferred.
