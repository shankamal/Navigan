# Navigan session handoff — 25 October 2026 (latest)

This is the current checkpoint. It supersedes older current-status sections where they conflict; retain older entries as history.

## Repository and working rules

- Repository: https://github.com/shankamal/Navigan
- Active branch: `new_migration_approach_18oct26`.
- User checkout: `/mnt/b/Langchain_Ai/Navigan-migration-test`.
- AWS profile `navigan`, region `ap-south-1`, account `905418045935`.
- User works from WSL and has no direct cluster terminal/network access established. Do not assume laptop kubectl can reach a private EKS endpoint.
- Before changes, check branch, status and recent commits. Preserve user files and unrelated modifications; no reset, clean or extra worktree.
- Keep fixes scoped and progress updates concise. Do not request approval repeatedly for already-authorized work.
- Primary migration objective remains collecting source definitions and exact container image content into private S3, then export and target validation. Broad UI consistency work remains deferred to final stabilization.
- Shared physical connector / authorized customer association requirements in older notes remain unresolved unless separately proven. Do not treat the older source-scoped installer fix as that implementation.

## Accepted login design

User accepted the design after commit `1a7fab6492c5aa0c48676f5f85b87e7af5b39e28`, then explicitly requested compact controls and a slightly narrower right panel in `6916e119a6445e7b6b1526514e79a42e4d3b19d5`.

- Charcoal Deloitte title bar; light left story area; charcoal right sign-in area.
- Coloured Indian king at a ship helm and harbour illustration retained. Do not revert to grayscale king.
- No left Navigan logo/name block. One reverse Navigan mark sits beside **Welcome to Navigan** on the right.
- Exact left headline on two lines: **Navigate your cloud.** / **Simplify your operations.**
- Supporting line: **Manage with confidence. Migrate with clarity.**
- First headline line uses lighter charcoal type, second deep green with more separation; supporting text is smaller and normal, no longer italic.
- Sign-in subtitle: **Sign in to your workspace.**
- Sign in button is Deloitte green `#86BC25`, with dark readable text. The user's latest request supersedes earlier deep-green button preferences for this login button.
- Small provider logos; AWS logo only, with no repeated AWS text label.
- Latest desktop split: 64% story / 36% dark panel; form max-width 360px; desktop input and primary button height 40px. Narrow two-column layout uses 55/45; mobile input/button heights remain 48px/44px.
- No scroll on normal login at the checked viewport sizes. Do not hide scrollbars to conceal inaccessible content; expanded auth challenges/errors must remain accessible.
- Auth/Cognito behavior was preserved. 14 focused login/auth-entry tests passed after branding changes. Actual-component browser fixtures verified desktop/mobile layout; latest compact CSS checked at 1536x696 and 1024x600 with matching document/client dimensions. These are fixture checks, not proof of live authenticated sign-in.

Relevant files:
`frontend/src/shared/auth/sign-in-screen.tsx`,
`frontend/src/shared/auth/login-form.tsx`,
`frontend/src/shared/auth/login-workspace.css`,
`frontend/src/shared/components/navigan-mark.tsx`,
`frontend/public/graphics/navigan-royal-harbour.webp`.

## Frontend deployment status: distinguish deployed from prepared

Frontend ECS cluster: `navigan-frontend-Cluster-bw32Pkwxn8Cs`.
Service: `navigan-frontend-Service-vMtHq9h7A9mz`.
Task family: `navigan-frontend-TaskDefinition-j9W80aX9PBkf`.

- **Last confirmed deployed: revision 22.** User's ECS output showed PRIMARY / COMPLETED, desired 1, running 1, pending 0. No rollback.
- The execute helper initially raised “Service did not retain the requested revision” before the later ECS observation confirmed completion. Do not redeploy solely because of that earlier message. Exact timing cause was not independently established; helper's final running-image and HTTP checks were not reached.
- Revision 22 image: `905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend@sha256:5931ba5db8970e0977bab80524547ab202d4158eb8f07cd6f16df67e633e786a`.
- **Latest prepared candidate: revision 23**, containing compact-controls change `6916e11`.
- Revision 23 image: `905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend@sha256:bab279913816fed2e113f8e4cb94187bbeeb835f0781896eb0959c25a55047f6`.
- Revision 23 release plan: `/mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-frontend-zg_c5ip6/release-plan.json`.
- Exact execute command was supplied, but **no execution result for revision 23 has been received**. Verify live state rather than claiming it deployed.
- Deploy helper: `scripts/deploy-frontend-prod.py`. Build/register with --prepare; promote only via --execute and its actual newly printed plan path. Never give a literal placeholder as a runnable command or select an arbitrary latest temporary plan.
- Python: `/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python`; TMPDIR: `/mnt/b/Langchain_Ai/navigan-deploy-tmp`.
- Backend readiness requires the shared Aurora cluster `aws-infra-platform-db` to be available; a stopped DB caused one prepare to stop before deployment.

### ECR verification correction

Commit `d148e62c65e19b0b76d83b2ea440e6a5901bbe3e` fixes identical duplicate ECR manifest rows. User diagnostic showed two rows for one requested digest with no failures. Helper accepts duplicates only when digest, manifest text and media type agree; missing/conflicting manifests remain blocked. Linux/amd64 selection retained. **33 offline deployment tests passed.** Fix is already on this branch; do not repeat it or weaken verification.

## UI data performance work already completed

- Three production summary routes (customers, environments, clusters) were deployed and verified present through `scripts/deploy-summary-apis-prod.py` at `62d4b6c`.
- User network evidence then showed summary 200 responses around 420–434ms, regular lists around 397–437ms, and no previous burst of 28 fallback count requests. This does not prove all full-page load latency resolved.
- Frontend `d5a70bc` split sign-in presentation into a dynamic import, separated migration create-page imports, and added intent-based prefetch. Later login releases preserve these changes. Do not reintroduce eager auth presentation or migration barrel imports.

## Cluster tools incident — resolved without a code change

- User reported recurring disabled Headlamp, Argo CD, Prometheus and Grafana buttons after daily node shutdown/startup.
- Initial screenshot: several components showed Healthy, but launch access said cluster had not connected to shared tools gateway; Argo CD showed Missing.
- AWS screenshot identified EKS cluster **dbs-sims-clus2**, node group **dbs-sims-clus2-system-ng**, **desired size 0**, and no Fargate profiles.
- After restoring worker capacity, user explicitly confirmed **all healthy and buttons enabled**. Recovery occurred without connector reinstall, gateway redeploy or code changes for this incident.
- Do not reopen this as an active tunnel outage unless new symptoms appear. Enabled buttons alone do not prove each tool's browser launch was tested.
- Code read during investigation: cluster connector automatically retries its tools tunnel; chart selects nodes labelled `navigan.io/platform-services=true`. No replacement-node label defect was proven.
- **Remaining follow-up, deferred:** stale health/status presentation. Navigan displayed Healthy while worker capacity was zero. Distinguish freshness, component health and tool access readiness; do not claim a stale-health fix has been implemented.
- No cluster, gateway, IAM or source-agent mutation was performed by the assistant during this investigation. Do not reinstall tools or modify gateway security based on the old screenshot.

## Next session

1. Read this handoff first, then inspect branch/status and any newer user output.
2. Confirm whether revision 23 was executed, using existing user evidence or read-only ECS status.
3. Preserve the accepted login design; no further redesign is requested.
4. Cluster tools incident is resolved. Stale health reporting and broad UI consistency remain deferred; continue only the next user-directed task.
