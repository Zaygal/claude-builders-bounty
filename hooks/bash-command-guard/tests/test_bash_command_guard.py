#!/usr/bin/env python3
"""
Tests for bash-command-guard.py

Runs the hook as a subprocess exactly the way Claude Code does — JSON payload on
stdin — and asserts the exit code (0 = allow, 2 = block) plus the log entry.

    python3 tests/test_bash_command_guard.py     # standalone
    pytest tests/test_bash_command_guard.py      # or under pytest
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "bash-command-guard.py"

# (command, expected_rule_or_None)
BLOCKED = [
    ("rm -rf /", "rm-rf"),
    ("rm -rf /*", "rm-rf"),
    ("rm -rf ~", "rm-rf"),
    ("rm -rf ~/documents", "rm-rf"),
    ("rm -rf $HOME", "rm-rf"),
    ("rm -rf *", "rm-rf"),
    ("rm -rf .", "rm-rf"),
    ("rm -rf ..", "rm-rf"),
    ("rm -rf /etc", "rm-rf"),
    ("rm -rf /home/user", "rm-rf"),
    ("rm -rf ../../", "rm-rf"),
    ("sudo rm -rf /var", "rm-rf"),
    ('psql -c "DROP TABLE users"', "sql-drop"),
    ("DROP TABLE users;", "sql-drop"),
    ("mysql -e 'DROP DATABASE prod'", "sql-drop"),
    ("TRUNCATE TABLE users", "sql-truncate"),
    ("psql -c 'TRUNCATE orders'", "sql-truncate"),
    ('mysql -e "DELETE FROM users"', "sql-delete"),
    ("DELETE FROM orders;", "sql-delete"),
    ('psql -c "DELETE FROM public.users"', "sql-delete"),
    ("git push --force origin main", "force-push"),
    ("git push -f", "force-push"),
    ("git push --force", "force-push"),
    # compound commands: the dangerous half must still be caught
    ("cd /tmp && rm -rf /", "rm-rf"),
    ("echo hi; DROP TABLE users;", "sql-drop"),
    ("npm run build && git push --force", "force-push"),
    ("true || rm -rf ~", "rm-rf"),
    # no target at all
    ("rm -rf", "rm-rf"),
]

ALLOWED = [
    "ls -la",
    "pwd",
    "git status",
    "git log --oneline -20",
    "git push origin main",
    "git push --force-with-lease origin main",
    "npm install",
    "npm run build",
    "npx tsc --noEmit",
    "python3 -m pytest",
    "rm file.txt",
    "rm -f stale.log",
    "rm -rf node_modules",
    "rm -rf dist",
    "rm -rf .next",
    "rm -rf build",
    "rm -rf __pycache__",
    "rm -rf coverage",
    "rm -rf node_modules dist build",
    'psql -c "DELETE FROM users WHERE id = 1"',
    "DELETE FROM orders WHERE created_at < now();",
    'echo "DROP TABLE users"',  # string literal, not a statement
    "docker ps",
    "kubectl get pods",
    "find . -name '*.tmp' -delete",
    "tar -czf backup.tar.gz src/",
    "chmod +x scripts/changelog.sh",
]

_failures = []


def _run(command, log_path, cwd="/test/project"):
    payload = {
        "session_id": "test-session",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
    }
    env = dict(os.environ)
    env["CLAUDE_GUARD_LOG"] = str(log_path)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_blocked(tmp_path):
    log = tmp_path / "blocked.log"
    for command, expected_rule in BLOCKED:
        proc = _run(command, log)
        if proc.returncode != 2:
            _failures.append(f"NOT BLOCKED (exit {proc.returncode}): {command!r}")
        if "BLOCKED by bash-command-guard" not in proc.stderr:
            _failures.append(f"NO EXPLANATION on stderr: {command!r}")
    text = log.read_text() if log.exists() else ""
    for command, expected_rule in BLOCKED:
        flat = " ".join(command.split())
        if flat not in text:
            _failures.append(f"NOT LOGGED: {flat!r}")


def test_allowed(tmp_path):
    log = tmp_path / "blocked.log"
    for command in ALLOWED:
        proc = _run(command, log)
        if proc.returncode != 0:
            _failures.append(
                f"FALSE POSITIVE (exit {proc.returncode}): {command!r} -> {proc.stderr.strip()[:80]}"
            )
        if proc.stdout.strip():
            _failures.append(f"NOISE on stdout for allowed command: {command!r}")


def test_log_format(tmp_path):
    log = tmp_path / "format.log"
    _run("rm -rf /", log, cwd="/test/project")
    line = log.read_text().strip()
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 4:
        _failures.append(f"LOG FORMAT wrong (expected 4 fields): {line!r}")
        return
    stamp, rule, project, cmd = parts
    if not stamp.endswith("Z") or "T" not in stamp:
        _failures.append(f"LOG TIMESTAMP not ISO-8601 UTC: {stamp!r}")
    if rule != "rm-rf":
        _failures.append(f"LOG RULE wrong: {rule!r}")
    if project != "project=/test/project":
        _failures.append(f"LOG PROJECT PATH wrong: {project!r}")
    if not cmd.startswith("cmd=rm -rf"):
        _failures.append(f"LOG COMMAND wrong: {cmd!r}")


def test_ignores_non_bash(tmp_path):
    log = tmp_path / "blocked.log"
    payload = {"tool_name": "Write", "tool_input": {"file_path": "/x", "content": "rm -rf /"}}
    env = dict(os.environ)
    env["CLAUDE_GUARD_LOG"] = str(log)
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, env=env, timeout=30,
    )
    if proc.returncode != 0:
        _failures.append("non-Bash tool should be ignored (exit 0)")


def test_fails_open_on_garbage(tmp_path):
    log = tmp_path / "blocked.log"
    env = dict(os.environ)
    env["CLAUDE_GUARD_LOG"] = str(log)
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="{not valid json",
        capture_output=True, text=True, env=env, timeout=30,
    )
    if proc.returncode != 0:
        _failures.append("malformed payload must fail open (exit 0)")


def main():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_blocked(tmp)
        test_allowed(tmp)
        test_log_format(tmp)
        test_ignores_non_bash(tmp)
        test_fails_open_on_garbage(tmp)

    total = len(BLOCKED) + len(ALLOWED) + 3
    if _failures:
        print(f"FAIL — {len(_failures)} problem(s):")
        for f in _failures:
            print("  ✗", f)
        return 1
    print(f"PASS — {len(BLOCKED)} destructive commands blocked, "
          f"{len(ALLOWED)} normal commands unaffected, log format + fail-open verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
