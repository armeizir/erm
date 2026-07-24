#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

failed=0

echo '[1/4] Checking tracked sensitive filenames...'
tracked="$(git ls-files 2>/dev/null || true)"
if printf '%s\n' "$tracked" | grep -E '(^|/)(\.env$|db\.sqlite3$|.*\.sqlite3($|\.)|backups/|prod_exports/|.*\.dump$|.*\.sql(\.gz)?$)' ; then
  echo 'ERROR: sensitive artifact is tracked by Git.' >&2
  failed=1
fi

echo '[2/4] Checking legacy insecure settings module...'
if [ -f riskproject/settings.py ]; then
  echo 'ERROR: riskproject/settings.py still exists; use riskproject/settings/{dev,prod}.py only.' >&2
  failed=1
fi

echo '[3/4] Checking duplicate reassessment admin route...'
if grep -R --line-number --include='*.py' 'path([[:space:]]*"admin/"[[:space:]]*,[[:space:]]*admin\.site\.urls' reassessment riskproject 2>/dev/null; then
  echo 'ERROR: default Django admin route is exposed outside the ERM RiskAdminSite.' >&2
  failed=1
fi

echo '[4/4] Checking secret-access bypasses...'
if grep -R --line-number --include='*.py' \
    -E 'setting\.ai_api_key|app_setting\.email_host_password' \
    risk corporate_risk monthly_report awareness 2>/dev/null \
    | grep -Ev '/migrations/|/tests?\.py:|/test_[^/]*\.py:' ; then
  echo 'ERROR: runtime code bypasses encrypted runtime secret accessors.' >&2
  failed=1
fi

if [ "$failed" -ne 0 ]; then
  exit 1
fi

echo 'Security preflight: OK'
