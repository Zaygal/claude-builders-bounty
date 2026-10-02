#!/usr/bin/env python3
"""
Claude Code PreToolUse hook — blocks destructive bash commands before they run.

Reads the Claude Code hook payload on stdin, inspects the Bash `command`, and
blocks it when it matches a destructive pattern.

Exit codes (Claude Code hook contract):
    0   allow the command
    2   block the command — stderr is fed back to Claude as the reason

Every blocked attempt is appended to ~/.claude/hooks/blocked.log as:
    <ISO-8601 UTC timestamp> | <rule> | project=<path> | cmd=<command>

Design notes
------------
* Fails open. If the payload cannot be parsed the hook exits 0 rather than
  blocking every command in the session. A guard that bricks the editor on a
  malformed payload is worse than one that misses it. Documented in the README.
* `rm -rf` is blocked by default, with an allowlist for ordinary build-artifact
  directories (node_modules, dist, .next, ...) so day-to-day work is unaffected.
  Extend it with CLAUDE_GUARD_ALLOW_RM (colon-separated paths).

No third-party dependencies — Python 3.8+ stdlib only.
"""

import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

HOOKS_DIR = Path(os.environ.get("CLAUDE_HOOKS_DIR", Path.home() / ".claude" / "hooks"))
LOG_PATH = Path(os.environ.get("CLAUDE_GUARD_LOG", HOOKS_DIR / "blocked.log"))

# ---------------------------------------------------------------------------
# rm -rf policy
# ---------------------------------------------------------------------------

# Literal targets that must never be removed recursively.
DANGEROUS_TARGETS = {
    "/", "/*", "~", "~/*", "$HOME", "${HOME}", ".", "./", "..", "../", "*", "./*", "../*",
}

# Top-level system directories — `rm -rf /etc` is never acceptable.
SYSTEM_PREFIXES = (
    "/etc", "/usr", "/var", "/bin", "/sbin", "/lib", "/lib64", "/opt", "/root",
    "/home", "/boot", "/dev", "/sys", "/proc", "/srv", "/mnt", "/media",
)

# Relative paths that are normal build output and safe to remove recursively.
SAFE_RM_BASENAMES = {
    "node_modules", ".next", "dist", "build", "target", "__pycache__", ".cache",
    "coverage", "out", ".turbo", ".parcel-cache", ".pytest_cache", ".mypy_cache",
    ".venv", "venv", "tmp", ".tox", "htmlcov", ".nuxt", ".svelte-kit", ".output",
}


def _extra_allowed():
    raw = os.environ.get("CLAUDE_GUARD_ALLOW_RM", "")
    return {p.strip() for p in raw.split(":") if p.strip()}


def _segments(command):
    """Split a shell command on separators so each sub-command is checked."""
    return [s for s in re.split(r"&&|\|\||[;|\n]", command) if s.strip()]


def _tokens(segment):
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _is_dangerous_target(target, allow):
    if target in DANGEROUS_TARGETS:
        return True
    if target in allow:
        return False
    if target.startswith("~") or target.startswith("$HOME") or target.startswith("${HOME}"):
        return True
    if target.startswith("$"):
        return True  # unexpanded variable — cannot prove it is safe
    if target.startswith("/"):
        if target.startswith(SYSTEM_PREFIXES):
            return True
        # absolute path one level deep, e.g. /var, /data — treat as systemic
        if target.count("/") <= 1:
            return True
        return False
    if ".." in Path(target).parts:
        return True  # escapes the project directory
    return Path(target).name not in SAFE_RM_BASENAMES


def rule_rm_rf(command):
    allow = _extra_allowed()
    for segment in _segments(command):
        toks = _tokens(segment)
        idx = next((i for i, t in enumerate(toks) if t == "rm" or t.endswith("/rm")), None)
        if idx is None:
            continue
        args = toks[idx + 1:]
        flags = [a for a in args if a.startswith("-")]
        targets = [a for a in args if not a.startswith("-")]
        combined = "".join(f.lstrip("-") for f in flags)
        if "r" not in combined or "f" not in combined:
            continue
        if not targets:
            return "rm -rf with no target (would be ambiguous)"
        for target in targets:
            if _is_dangerous_target(target, allow):
                return f"rm -rf target `{target}`"
    return None


# ---------------------------------------------------------------------------
# SQL + git rules
# ---------------------------------------------------------------------------

QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
DB_CLIENTS = {
    "psql", "mysql", "mariadb", "sqlite3", "sqlite", "mongo", "mongosh", "redis-cli",
    "cockroach", "clickhouse-client", "clickhouse", "snowsql", "bq", "sqlcmd", "duckdb",
    "pgcli", "mycli", "mysqlsh",
}


def _strip_quoted(text):
    return QUOTED_RE.sub(" ", text)


def _sql_surfaces(command):
    """The text the SQL rules should inspect.

    Bare SQL is inspected directly. SQL hidden inside quotes is only inspected
    when the quoting command is a database client — so `psql -c "DROP TABLE users"`
    is caught, while `echo "DROP TABLE users"` is left alone.
    """
    surfaces = [_strip_quoted(command)]
    for segment in _segments(command):
        toks = _tokens(segment)
        if toks and os.path.basename(toks[0]) in DB_CLIENTS:
            surfaces.extend(q.strip("'\"") for q in QUOTED_RE.findall(segment))
    return surfaces


def rule_drop_table(command):
    for surface in _sql_surfaces(command):
        m = re.search(r"\bDROP\s+(TABLE|DATABASE|SCHEMA|VIEW|INDEX)\b\s*([^\s;]*)", surface, re.I)
        if m:
            return f"{m.group(0).strip()} (irreversible schema/data destruction)"
    return None


def rule_truncate(command):
    for surface in _sql_surfaces(command):
        if re.search(r"\bTRUNCATE\s+(TABLE\s+)?[`\"\[]?\w", surface, re.I):
            return "TRUNCATE … (empties a table with no row-level recovery)"
    return None


def rule_delete_without_where(command):
    for surface in _sql_surfaces(command):
        for statement in re.split(r";", surface):
            if not re.search(r"\bDELETE\s+FROM\b", statement, re.I):
                continue
            if not re.search(r"\bWHERE\b", statement, re.I):
                table = re.search(r"\bDELETE\s+FROM\s+[`\"\[]?(\w+)", statement, re.I)
                name = table.group(1) if table else "?"
                return f"DELETE FROM {name} without a WHERE clause (would remove every row)"
    return None


def rule_force_push(command):
    for segment in _segments(command):
        if not re.search(r"\bgit\s+push\b", segment, re.I):
            continue
        if re.search(r"--force-with-lease", segment):
            continue  # the safe variant — explicitly permitted
        if re.search(r"--force\b", segment) or re.search(r"(^|\s)-\w*f", segment):
            return "git push --force (rewrites published history)"
    return None


RULES = (
    ("rm-rf", rule_rm_rf),
    ("sql-drop", rule_drop_table),
    ("sql-truncate", rule_truncate),
    ("sql-delete", rule_delete_without_where),
    ("force-push", rule_force_push),
)


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def evaluate(command):
    """Return (rule_name, reason) for the first matching rule, else None."""
    for name, rule in RULES:
        reason = rule(command)
        if reason:
            return name, reason
    return None


def project_path(payload):
    return (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or payload.get("cwd")
        or os.getcwd()
    )


def log_block(rule, command, project):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        flat = " ".join(command.split())
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} | {rule} | project={project} | cmd={flat}\n")
    except OSError:
        pass  # never let a logging failure change the decision


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0  # fail open — see module docstring

    if payload.get("tool_name") not in (None, "", "Bash"):
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if not command.strip():
        return 0

    verdict = evaluate(command)
    if verdict is None:
        return 0

    rule, reason = verdict
    project = project_path(payload)
    log_block(rule, command, project)

    sys.stderr.write(
        "BLOCKED by bash-command-guard\n"
        f"  rule:    {rule}\n"
        f"  reason:  {reason}\n"
        f"  command: {' '.join(command.split())}\n"
        f"  logged:  {LOG_PATH}\n"
        "\n"
        "This command was not executed. Rewrite it to be scoped and reversible\n"
        "(narrow the path, add a WHERE clause, use --force-with-lease), or ask the\n"
        "user to run it manually if it is genuinely intended.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
