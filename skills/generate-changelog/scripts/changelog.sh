#!/usr/bin/env bash
#
# changelog.sh — generate a structured CHANGELOG.md from a project's git history.
#
#   bash changelog.sh              # new section titled "Unreleased"
#   bash changelog.sh 1.4.0        # new section titled "1.4.0"
#   bash changelog.sh --from v1.2.0  # override the base ref (default: last tag)
#
# Commits are read since the last git tag, classified into
# Added / Fixed / Changed / Removed, and written to CHANGELOG.md.
# If CHANGELOG.md already exists, the new section is prepended.
#
# Options:
#   --from <ref>     base ref to read commits from   (default: last tag)
#   --to <ref>       end ref                          (default: HEAD)
#   --version <str>  version label for the section    (default: Unreleased)
#   -h, --help       show this help

set -euo pipefail

VERSION="Unreleased"
FROM=""
TO="HEAD"

usage() {
  sed -n '2,22p' "$0" | sed -E 's/^# ?//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --from)    FROM="${2:-}";    shift 2 ;;
    --to)      TO="${2:-}";      shift 2 ;;
    --version) VERSION="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)         VERSION="$1";     shift ;;
  esac
done

OUT="${CHANGELOG_FILE:-CHANGELOG.md}"
DATE="$(date -u +%Y-%m-%d)"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "error: not inside a git repository" >&2
  exit 1
fi

# --- range: commits since the last tag (or an explicit --from ref) ----------
if [ -n "$FROM" ]; then
  RANGE="${FROM}..${TO}"
  BASE_NOTE="since \`${FROM}\`"
elif LAST_TAG="$(git describe --tags --abbrev=0 "$TO" 2>/dev/null || true)" && [ -n "$LAST_TAG" ]; then
  RANGE="${LAST_TAG}..${TO}"
  BASE_NOTE="since \`${LAST_TAG}\`"
else
  RANGE="$TO"
  BASE_NOTE="full history (no previous tag found)"
fi

# --- strip the conventional-commit prefix from a subject --------------------
clean_subject() {
  printf '%s' "$1" \
    | sed -E 's/^[a-zA-Z]+(\([^)]*\))?!?:[[:space:]]*//' \
    | sed -E 's/[[:space:]]+$//'
}

# --- classify a commit subject ----------------------------------------------
categorize() {
  local s
  s="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"

  # 1) A Conventional Commits prefix wins when present.
  case "$s" in
    feat:*|feat\(*\):*|feature:*)                                  echo Added;   return ;;
    fix:*|fix\(*\):*|bugfix:*|hotfix:*)                            echo Fixed;   return ;;
    remove:*|drop:*|revert:*)                                      echo Removed; return ;;
    perf:*|refactor:*|chore:*|docs:*|style:*|test:*|build:*|ci:*)  echo Changed; return ;;
  esac

  # 2) Keyword fallback for non-conventional messages.
  case "$s" in
    *remov*|*delet*|*drop*|*deprecat*|*revert*)                    echo Removed; return ;;
    *add*|*new*|*introduc*|*implement*|*support*)                  echo Added;   return ;;
    *fix*|*bug*|*resolv*|*patch*|*hotfix*)                         echo Fixed;   return ;;
  esac

  # 3) Anything else counts as a change.
  echo Changed
}

# --- collect ----------------------------------------------------------------
ADDED=(); FIXED=(); CHANGED=(); REMOVED=()

while IFS= read -r subject; do
  [ -z "$subject" ] && continue
  case "$(categorize "$subject")" in
    Added)   ADDED+=("$(clean_subject "$subject")") ;;
    Fixed)   FIXED+=("$(clean_subject "$subject")") ;;
    Removed) REMOVED+=("$(clean_subject "$subject")") ;;
    *)       CHANGED+=("$(clean_subject "$subject")") ;;
  esac
done < <(git log "$RANGE" --no-merges --pretty=format:'%s')

# --- render -----------------------------------------------------------------
section() {
  local title="$1"; shift
  printf '### %s\n\n' "$title"
  if [ "$#" -eq 0 ]; then
    printf -- '- _(none)_\n\n'
  else
    local entry
    for entry in "$@"; do printf -- '- %s\n' "$entry"; done
    printf '\n'
  fi
}

TMP="$(mktemp)"
{
  printf '## [%s] - %s\n\n' "$VERSION" "$DATE"
  printf '_Changes %s._\n\n' "$BASE_NOTE"
  section Added   ${ADDED[@]+"${ADDED[@]}"}
  section Fixed   ${FIXED[@]+"${FIXED[@]}"}
  section Changed ${CHANGED[@]+"${CHANGED[@]}"}
  section Removed ${REMOVED[@]+"${REMOVED[@]}"}
} > "$TMP"

# --- write, preserving any existing entries below the new section -----------
if [ -f "$OUT" ]; then
  { cat "$TMP"; printf '\n'; cat "$OUT"; } > "${OUT}.new"
  mv "${OUT}.new" "$OUT"
else
  printf '# Changelog\n\nAll notable changes to this project are documented here.\n\n' > "$OUT"
  cat "$TMP" >> "$OUT"
fi
rm -f "$TMP"

TOTAL=$(( ${#ADDED[@]} + ${#FIXED[@]} + ${#CHANGED[@]} + ${#REMOVED[@]} ))
echo "changelog: wrote ${OUT}  [${VERSION}]  ${TOTAL} commit(s) ${BASE_NOTE}"
