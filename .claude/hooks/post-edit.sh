#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# FastRecce PostToolUse Hook
# Fires after Claude edits a file. Auto-lints/typechecks based on
# file extension. Fails gracefully if tools aren't installed yet.
# ─────────────────────────────────────────────────────────────

set -u

# The file path is passed via CLAUDE_TOOL_INPUT env var (JSON).
# We extract it with basic parsing to avoid jq dependency.
FILE_PATH="${CLAUDE_FILE_PATH:-}"

# Fallback: try parsing from CLAUDE_TOOL_INPUT JSON
if [ -z "$FILE_PATH" ] && [ -n "${CLAUDE_TOOL_INPUT:-}" ]; then
  FILE_PATH=$(echo "$CLAUDE_TOOL_INPUT" | grep -o '"file_path"[^,}]*' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
fi

# Nothing to do if we don't know which file changed
[ -z "$FILE_PATH" ] && exit 0

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

case "$FILE_PATH" in
  *.py)
    # Python: run ruff on the specific file
    if command -v ruff >/dev/null 2>&1; then
      cd "$PROJECT_ROOT/backend" 2>/dev/null || exit 0
      ruff check --fix "$FILE_PATH" 2>&1 | head -30 || true
    fi
    ;;
  *.ts|*.tsx)
    # TypeScript: run tsc project-wide (fast with incremental build)
    if [ -d "$PROJECT_ROOT/frontend/node_modules" ]; then
      cd "$PROJECT_ROOT/frontend" 2>/dev/null || exit 0
      npx tsc --noEmit -p tsconfig.app.json 2>&1 | head -30 || true
    fi
    ;;
esac

exit 0
