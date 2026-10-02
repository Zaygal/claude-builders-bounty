#!/usr/bin/env bash
#
# Install bash-command-guard into ~/.claude/hooks/ and register it as a
# Claude Code PreToolUse hook in ~/.claude/settings.json.
#
#   bash install.sh
#
# Existing settings.json content is preserved — the hook entry is merged in,
# never overwritten. Safe to run twice.

set -euo pipefail

HOOK_DIR="${CLAUDE_HOOKS_DIR:-$HOME/.claude/hooks}"
SETTINGS_DIR="${CLAUDE_SETTINGS_DIR:-$HOME/.claude}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$HOOK_DIR"
cp "$SRC_DIR/bash-command-guard.py" "$HOOK_DIR/bash-command-guard.py"
chmod +x "$HOOK_DIR/bash-command-guard.py"

python3 - "$SETTINGS_DIR/settings.json" "$HOOK_DIR/bash-command-guard.py" <<'PY'
import json
import os
import sys

settings_path, hook_path = sys.argv[1], sys.argv[2]

data = {}
if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError:
            sys.exit(f"error: {settings_path} is not valid JSON — fix it, then re-run")

command = f"python3 {hook_path}"
hooks = data.setdefault("hooks", {})
pre_tool_use = hooks.setdefault("PreToolUse", [])

already = any(
    command in [h.get("command") for h in entry.get("hooks", [])]
    for entry in pre_tool_use
)

if not already:
    pre_tool_use.append({
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": command}],
    })

os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")

print(f"{'already registered' if already else 'registered'}: {settings_path}")
PY

echo "installed: $HOOK_DIR/bash-command-guard.py"
echo "verify:    tail -f $HOOK_DIR/blocked.log"
