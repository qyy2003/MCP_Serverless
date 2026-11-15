#!/usr/bin/env bash
# Manage our changes to the serverless-benchmarks (SeBS) submodule as a patch.
#
# The submodule stays pinned to an upstream commit; everything we change in it
# lives in patches/serverless-benchmarks.patch in this repository.
#
#   scripts/sebs-patch.sh apply    apply the patch to the submodule's working tree
#   scripts/sebs-patch.sh export   write the submodule's working-tree changes to the patch
#   scripts/sebs-patch.sh revert   remove the patch from the submodule's working tree
#   scripts/sebs-patch.sh status   show whether the patch is applied
#
# Workflow: apply -> edit files in serverless-benchmarks/ -> export -> commit the patch.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUBMODULE="$ROOT/serverless-benchmarks"
PATCH="$ROOT/patches/serverless-benchmarks.patch"

sub() { git -C "$SUBMODULE" "$@"; }

is_applied() { sub apply --reverse --check "$PATCH" 2>/dev/null; }

case "${1:-}" in
  apply)
    if is_applied; then
      echo "Patch already applied."
    else
      sub apply --whitespace=nowarn "$PATCH"
      echo "Applied $PATCH"
    fi
    ;;
  export)
    mkdir -p "$(dirname "$PATCH")"
    # Mark new files as intent-to-add so the diff includes them, then unmark.
    sub add --intent-to-add --all
    sub diff --binary HEAD > "$PATCH"
    sub reset --quiet
    echo "Exported $(grep -c '^diff --git' "$PATCH") files to $PATCH"
    ;;
  revert)
    if is_applied; then
      sub apply --reverse "$PATCH"
      echo "Reverted $PATCH"
    else
      echo "Patch is not applied (or the tree has unexported edits); nothing reverted." >&2
      exit 1
    fi
    ;;
  status)
    if is_applied; then
      echo "applied"
    elif sub apply --check "$PATCH" 2>/dev/null; then
      echo "not applied"
    else
      echo "diverged: the submodule has changes that are not in the patch (run export?)"
    fi
    ;;
  *)
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
