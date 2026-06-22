#!/usr/bin/env bash
# Instantiate the feature-campaign design+build chain for one RFC.
# Copies feature-campaign/{design,build} into ../rfc-<id>/{design,build}
# and replaces __RFC_ID__ / __RFC_PATH__ tokens. Validates each stage.
set -euo pipefail

usage() { echo "usage: instantiate.sh --id <rfc-id> --rfc-path <repo-relative path to RFC.md>" >&2; }

RFC_ID=""; RFC_PATH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --id) RFC_ID="${2:?}"; shift 2 ;;
    --rfc-path) RFC_PATH="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done
[ -n "$RFC_ID" ] && [ -n "$RFC_PATH" ] || { usage; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"        # .../striatum/workflows/feature-campaign
WF_ROOT="$(dirname "$HERE")"                                 # .../striatum/workflows
REPO_ROOT="$(cd "$WF_ROOT/../.." && pwd)"                    # gpu-fleet repo root
DEST="$WF_ROOT/rfc-$RFC_ID"
[ ! -e "$DEST" ] || { echo "error: campaign already exists: $DEST" >&2; exit 2; }
[ -f "$REPO_ROOT/$RFC_PATH" ] || { echo "error: RFC not found at repo path: $RFC_PATH" >&2; exit 2; }

mkdir -p "$DEST"
cp -R "$HERE/design" "$HERE/build" "$DEST/"

# Token substitution. RFC_PATH contains slashes -> use | as sed delimiter.
find "$DEST" -type f \( -name '*.json' -o -name '*.md' \) -print0 | while IFS= read -r -d '' f; do
  sed -i -e "s/__RFC_ID__/$RFC_ID/g" -e "s|__RFC_PATH__|$RFC_PATH|g" "$f"
done

echo "Instantiated $DEST"
for stage in design build; do
  printf 'validate %-7s: ' "$stage"
  striatum --repo "$REPO_ROOT" workflow validate --allow-same-model-pairing "$DEST/$stage/workflow.json"
done
