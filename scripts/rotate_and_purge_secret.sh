#!/usr/bin/env bash
set -euo pipefail

SECRET_LABEL="${SECRET_LABEL:-}"
OLD_SECRET="${OLD_SECRET:-}"
REMOTE="${REMOTE:-}"
BACKUP_TAG="${BACKUP_TAG:-pre-secret-purge-$(date +%Y%m%d%H%M%S)}"
REPLACEMENTS_FILE="${REPLACEMENTS_FILE:-scripts/replacements.txt}"

die() {
  echo "error: $*" >&2
  exit 1
}

require_value() {
  local name="$1"
  local value="$2"
  [[ -n "$value" ]] || die "$name is required."
  [[ "$value" != "OLD_SECRET" ]] || die "$name still contains the placeholder value."
  [[ "$value" != "SECRET_LABEL" ]] || die "$name still contains the placeholder value."
  [[ "$value" != "REMOTE" ]] || die "$name still contains the placeholder value."
  [[ "$value" != "<set-me>" ]] || die "$name still contains the placeholder value."
}

require_value SECRET_LABEL "$SECRET_LABEL"
require_value OLD_SECRET "$OLD_SECRET"
require_value REMOTE "$REMOTE"

echo "Rotate/revoke the secret in the provider first: $SECRET_LABEL"
echo "History rewriting only removes repository references; it does not invalidate a leaked credential."
echo
echo "Creating backup tag: $BACKUP_TAG"
git tag "$BACKUP_TAG"

mkdir -p "$(dirname "$REPLACEMENTS_FILE")"
printf '%s==>***REMOVED***\n' "$OLD_SECRET" > "$REPLACEMENTS_FILE"
chmod 600 "$REPLACEMENTS_FILE"

command -v git-filter-repo >/dev/null 2>&1 || command -v git-filter-repo.py >/dev/null 2>&1 || {
  die "git filter-repo is required. Install it, then rerun this script."
}

if command -v git-filter-repo >/dev/null 2>&1; then
  git filter-repo --replace-text "$REPLACEMENTS_FILE"
else
  git-filter-repo.py --replace-text "$REPLACEMENTS_FILE"
fi

echo
echo "Optional BFG alternative for simple string replacements:"
echo "  java -jar bfg.jar --replace-text $REPLACEMENTS_FILE ."
echo "  git reflog expire --expire=now --all && git gc --prune=now --aggressive"
echo
echo "Review the rewritten history, then force-push intentionally:"
echo "  git push --force --all $REMOTE"
echo "  git push --force --tags $REMOTE"
echo
echo "After pushing, ask hosts/collaborators to purge caches and reclone."
