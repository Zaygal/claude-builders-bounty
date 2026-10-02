# bash-command-guard

A Claude Code `PreToolUse` hook that blocks destructive bash commands **before**
they execute. Pure Python 3 stdlib — no dependencies.

## Install (1 command)

```bash
bash install.sh
```

That copies the hook to `~/.claude/hooks/` and registers it in
`~/.claude/settings.json`, preserving anything already in that file. Safe to
re-run. (Prefer to do it by hand? `cp bash-command-guard.py ~/.claude/hooks/ && chmod +x ~/.claude/hooks/bash-command-guard.py`,
then merge `settings.example.json` into `~/.claude/settings.json`.)

## What it blocks

| Pattern | Example | Rule |
|---|---|---|
| `rm -rf` on a dangerous target | `rm -rf /`, `rm -rf ~`, `rm -rf *`, `rm -rf /etc`, `rm -rf ..` | `rm-rf` |
| `DROP TABLE` (+ `DATABASE`/`SCHEMA`/`VIEW`/`INDEX`) | `psql -c "DROP TABLE users"` | `sql-drop` |
| `TRUNCATE` | `TRUNCATE TABLE orders` | `sql-truncate` |
| `DELETE FROM` without `WHERE` | `DELETE FROM users;` | `sql-delete` |
| `git push --force` / `-f` | `git push --force origin main` | `force-push` |

Compound commands are inspected segment by segment, so
`cd /tmp && rm -rf /` and `npm run build && git push --force` are both caught.

## What it deliberately allows

- `rm -rf` on ordinary build output — `node_modules`, `dist`, `.next`, `build`,
  `target`, `__pycache__`, `coverage`, `.cache`, and friends.
- `git push --force-with-lease` — the safe variant.
- `DELETE FROM users WHERE id = 1` — scoped deletes.
- `echo "DROP TABLE users"` — SQL inside a quoted string is only inspected when
  the quoting command is a database client (`psql`, `mysql`, `sqlite3`, …).
- `rm file.txt`, `rm -f stale.log` — non-recursive deletes.

When a command is blocked, Claude sees this and does not execute it:

```
BLOCKED by bash-command-guard
  rule:    rm-rf
  reason:  rm -rf target `/`
  command: rm -rf /
  logged:  /root/.claude/hooks/blocked.log

This command was not executed. Rewrite it to be scoped and reversible
(narrow the path, add a WHERE clause, use --force-with-lease), or ask the
user to run it manually if it is genuinely intended.
```

## The log

Every blocked attempt appends one line to `~/.claude/hooks/blocked.log`:

```
2026-10-02T01:33:33Z | rm-rf | project=/home/me/app | cmd=rm -rf /
2026-10-02T01:33:34Z | sql-delete | project=/home/me/app | cmd=mysql -e "DELETE FROM users"
```

Fields: ISO-8601 UTC timestamp, rule name, project path, attempted command.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_GUARD_LOG` | `~/.claude/hooks/blocked.log` | Log destination |
| `CLAUDE_GUARD_ALLOW_RM` | *(empty)* | Colon-separated extra `rm -rf` targets to permit |
| `CLAUDE_HOOKS_DIR` | `~/.claude/hooks` | Where the hook is installed |
| `CLAUDE_PROJECT_DIR` | payload `cwd` | Used for the `project=` log field |

## Tests

```bash
python3 tests/test_bash_command_guard.py
```

Runs the hook the way Claude Code does — JSON on stdin — across 28 destructive
commands and 27 ordinary ones, and checks the log format, the non-Bash bypass,
and fail-open behaviour.

## Known limitations (read these)

- **Fails open.** If the payload is malformed the hook exits `0` rather than
  blocking the session. A guard that bricks the editor on a parse error is worse
  than one that misses a bad payload. This is a deliberate trade-off, not an
  oversight.
- **It is a pattern matcher, not a shell parser.** It splits on `&&`, `||`, `;`,
  `|` and newlines without a full grammar, so a command obfuscated through
  `eval`, base64, a heredoc, or a variable indirection will not be caught.
- **Unrecognised `rm -rf` targets are blocked.** `rm -rf mydir` is refused
  because it is not on the build-artifact allowlist. Add it to
  `CLAUDE_GUARD_ALLOW_RM` or edit `SAFE_RM_BASENAMES` if that is too strict for
  your workflow.
- **`DELETE FROM` inside a non-database string is allowed**, but a bare
  `DELETE FROM t` in a shell script is blocked even if the string is a comment.
- Only `Bash` tool calls are inspected; other tools pass through untouched.

## Requirements

Python 3.8+, Claude Code with hooks support
([docs](https://docs.anthropic.com/claude-code/hooks)).
