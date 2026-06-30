#!/usr/bin/env bash
# PostToolUse gate — runs after every Edit / Write / MultiEdit.
#
# Keep this FAST: lint / format-check / typecheck only. The FULL test suite
# is run by the `tester` agent at milestones, not here, so editing stays quick.
#
# Exit code 2 = block and show the message to Claude so it fixes the issue.

set -uo pipefail

# ===================== CONFIGURE THIS FOR YOUR STACK =====================
# Examples:
#   Python:     QUICK_CMD="ruff check . && pyright"
#   Node/TS:    QUICK_CMD="npm run lint && npm run typecheck"
#   Go:         QUICK_CMD="gofmt -l . && go vet ./..."
#   Rust:       QUICK_CMD="cargo fmt --check && cargo clippy -- -D warnings"
# Skip a tool until it's installed (e.g. before the Phase 1 venv exists).
QUICK_CMD='ok=0
if command -v ruff   >/dev/null 2>&1; then ruff check . || ok=1; fi
if command -v pyright >/dev/null 2>&1; then pyright    || ok=1; fi
exit $ok'
# ========================================================================

out="$(bash -c "$QUICK_CMD" 2>&1)"
status=$?

if [ "$status" -ne 0 ]; then
  {
    echo "Quick-check failed. Fix these before continuing:"
    echo "----------------------------------------------"
    echo "$out"
  } >&2
  exit 2
fi

exit 0
