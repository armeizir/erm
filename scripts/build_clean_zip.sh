#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT="${1:-$ROOT/riskproject_clean_${STAMP}.zip}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/riskproject"
rsync -a \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='env/' \
  --exclude='__pycache__/' \
  --exclude='*.py[cod]' \
  --exclude='.DS_Store' \
  --include='.env.example' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='db.sqlite3' \
  --exclude='*.sqlite3' \
  --exclude='*.sqlite3.*' \
  --exclude='*.db' \
  --exclude='*.dump' \
  --exclude='*.sql' \
  --exclude='*.sql.gz' \
  --exclude='backups/' \
  --exclude='prod_exports/' \
  --exclude='exports/' \
  --exclude='*.tar.gz' \
  --exclude='*.zip' \
  --exclude='media/' \
  --exclude='staticfiles/' \
  --exclude='*.log' \
  --exclude='*.backup' \
  --exclude='*.backup.*' \
  --exclude='*.backup_*' \
  --exclude='*_backup*' \
  --exclude='*.bak' \
  "$ROOT/" "$TMP/riskproject/"

# Fail closed if a sensitive artifact slipped through.
if find "$TMP/riskproject" -type f \( \
    -name 'db.sqlite3' -o -name '*.sqlite3' -o -name '*.sqlite3.*' -o \
    -name '.env' -o -name '*.dump' -o -name '*.sql' -o -name '*.sql.gz' \
  \) -print -quit | grep -q .; then
  echo 'ERROR: sensitive data artifact detected in clean export.' >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"
rm -f "$OUTPUT"
(
  cd "$TMP"
  zip -qry "$OUTPUT" riskproject
)
echo "$OUTPUT"
