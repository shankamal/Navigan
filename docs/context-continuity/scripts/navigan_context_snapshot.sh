#!/usr/bin/env bash
# Read-only local snapshot: no AWS access, no git branch changes, no builds or deployments.
set -euo pipefail
REPO="${1:-/mnt/b/Langchain_Ai/Navigan-migration-test}"
if [[ ! -d "$REPO/.git" && ! -f "$REPO/.git" ]]; then
  echo "ERROR: not a Git checkout: $REPO" >&2
  exit 2
fi
cd "$REPO"
printf '=== Time (UTC) ===\n'; date -u '+%Y-%m-%dT%H:%M:%SZ'
printf '\n=== Repository ===\n'; git rev-parse --show-toplevel
printf '\n=== Branch / commit ===\n'; git branch --show-current; git log -1 --format='%h %s'
printf '\n=== Working tree ===\n'; git status --short
printf '\n=== Migration planning files ===\n'
for p in 'frontend/src/app/(workspace)/migrations/[migrationId]/plan/page.tsx' 'frontend/src/modules/migration-management/planning-workspace.tsx'; do
  if [[ -f "$p" ]]; then echo "PRESENT $p"; else echo "MISSING $p"; fi
done
printf '\n=== Local OIDC config key presence / CRLF status (no values) ===\n'
python3 - <<'PY'
from pathlib import Path
p = Path('frontend/.env.local')
if not p.is_file():
    print('NO_LOCAL_ENV_FILE')
else:
    lines=p.read_bytes().split(b'\n')
    for key in (b'NEXT_PUBLIC_OIDC_CLIENT_ID',b'NEXT_PUBLIC_OIDC_AUTHORITY',b'NEXT_PUBLIC_APP_URL'):
        v=next((x.split(b'=',1)[1] for x in lines if x.startswith(key+b'=')),None)
        print(f'{key.decode()}: {"PRESENT" if v is not None and v.strip() else "MISSING_OR_EMPTY"}; CR={bool(v is not None and b"\r" in v)}')
PY
printf '\nSnapshot complete. No cloud reads or changes performed.\n'
