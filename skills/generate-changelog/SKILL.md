---
name: generate-changelog
description: Generate a structured CHANGELOG.md from git history, categorized into Added/Fixed/Changed/Removed. Use when the user asks to create or update a changelog, draft release notes, or summarize commits since the last tag.
---

# Generate Changelog

Produces a `CHANGELOG.md` section from the repository's git history, split into
**Added / Fixed / Changed / Removed** (Keep a Changelog conventions).

## When to use

- The user asks for a changelog, release notes, or "what changed since the last release".
- You are cutting a release and need a human-readable summary of commits.
- You need commits since a specific tag, not just since HEAD.

## How to run

```bash
bash scripts/changelog.sh                # section titled "Unreleased"
bash scripts/changelog.sh 1.4.0          # section titled "1.4.0"
bash scripts/changelog.sh --from v1.2.0  # base ref override (default: last tag)
```

The script writes `CHANGELOG.md` in the current directory. If the file already
exists, the new section is **prepended**, so previous entries are preserved.

## What it does

1. Finds the base ref — the most recent git tag, unless `--from <ref>` is given.
2. Reads every non-merge commit subject in `base..HEAD`.
3. Classifies each commit:
   - a Conventional Commits prefix wins when present
     (`feat:` → Added, `fix:` → Fixed, `chore:`/`refactor:`/`docs:` → Changed, `revert:` → Removed);
   - otherwise a keyword fallback applies
     (`add`/`new`/`implement` → Added, `fix`/`bug`/`resolve` → Fixed, `remove`/`delete`/`drop` → Removed);
   - anything unmatched lands in **Changed**.
4. Strips the type prefix from the displayed text and emits the four sections.

## Guidance for the assistant

- Run the script rather than hand-writing a changelog — the point is that the
  output is reproducible from the git log.
- After running it, **read `CHANGELOG.md` and correct misclassifications** before
  showing it to the user. The classifier is heuristic; a commit like
  "Add more tests" is keyword-matched into *Added* when *Changed* would read
  better. Fix those by hand — do not silently ship a bad grouping.
- Never invent entries. Every line must correspond to a real commit.
- If the repo has no tags, the script falls back to the full history and says so.

## Requirements

- `git`, `bash` 4+ (uses arrays), and standard POSIX tools (`sed`, `tr`, `mktemp`).
