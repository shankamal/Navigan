# Navigan lifecycle introduction

Approved 2 November 2026: reuse the light circular platform hub and animated bot
in the post-login transition and About Navigan.

## Behaviour

- Successful Cognito sign-in (including the final MFA/password challenge) marks
  a non-sensitive, tab-local sessionStorage flag immediately before the existing
  document redirect. No token or user information is stored in this flag.
- The existing authenticated gate checks identity before the introduction can
  mount. The workspace mounts after the 11.2-second sequence or Skip and continue.
- Completion clears the flag. Route changes and ordinary page refreshes do not
  replay the sequence. A fresh completed sign-in marks it again.
- Restricted session storage fails open to the workspace, without blocking login.
- Reduced-motion users bypass the post-login animation. About shows a static
  complete lifecycle. About uses the same scene, with explicit playback/replay.
- A hidden tab pauses the sequence. Resume and Skip remain available on return.
- About Navigan is in the authenticated sidebar and uses `/about`.
- App Transformation, Onboarding and Upgrades remain labelled planned. The bot
  uses local captions; it does not make network or AI requests or play audio.

## Production rollout

Frontend-only release. No API, database, collector, Cognito, IAM or infrastructure
updates. Use the existing `scripts/deploy-frontend-prod.py --prepare` on validated
main, then execute the actual release-plan.json printed by preparation. Do not
reuse an older plan. The helper captures the current running task for rollback.
DEV runtime deployment/reconciliation is deferred at the user's request.

After deployment, sign out and sign in at navigan.click. Check automatic playback,
Skip, dashboard entry, no replay while navigating or refreshing, and About replay.
Check mobile navigation and reduced motion. A local fixture is not evidence of
successful live Cognito sign-in or a completed production deployment.

## Local validation

31 focused tests: lifecycle, authentication entry routing, login form and shell.
TypeScript and Next production build passed. Browser fixture verified the real
shared component and shell at desktop and a 360px iframe, visible About navigation,
playback, Skip and workspace handoff. No application console errors were observed;
browser-extension metadata errors were excluded. Live authenticated PROD checks
remain pending deployment.
