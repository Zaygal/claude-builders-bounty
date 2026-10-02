# generate-changelog

Generate a structured `CHANGELOG.md` from your git history — every commit since
the last tag, auto-categorized into **Added / Fixed / Changed / Removed**.

## Setup (3 steps)

1. Copy `scripts/changelog.sh` into your project.
2. `chmod +x scripts/changelog.sh`
3. `bash scripts/changelog.sh 1.4.0`

That's it. `CHANGELOG.md` is created in the current directory; if it already
exists, the new section is prepended so older entries are kept.

## Usage

```bash
bash scripts/changelog.sh                 # section titled "Unreleased"
bash scripts/changelog.sh 1.4.0           # section titled "1.4.0"
bash scripts/changelog.sh --from v1.2.0   # base ref override (default: last tag)
bash scripts/changelog.sh --to v1.3.0     # end ref (default: HEAD)
bash scripts/changelog.sh --help
```

Set `CHANGELOG_FILE` to write somewhere other than `CHANGELOG.md`.

## How commits are classified

1. **Conventional Commits prefix wins** when present:
   - `feat:` → Added
   - `fix:` → Fixed
   - `chore:` / `refactor:` / `docs:` / `perf:` / `test:` / `style:` / `build:` / `ci:` → Changed
   - `revert:` / `remove:` → Removed
2. **Keyword fallback** for plain messages:
   - `add` / `new` / `introduce` / `implement` / `support` → Added
   - `fix` / `bug` / `resolve` / `patch` → Fixed
   - `remove` / `delete` / `drop` / `deprecate` / `revert` → Removed
3. Anything unmatched → **Changed**.

The type prefix is stripped from the output, so `feat: add retry logic` renders
as `- add retry logic` under **Added**.

## Known limits (be honest about them)

- The keyword fallback is a heuristic, not a semantic parser. `Add more tests`
  lands in *Added* even though *Changed* reads better. Merge commits are skipped
  entirely; a squash-merge workflow gives the cleanest output.
- It reads the git log only — it does not consult issue trackers or PR titles.

See `SAMPLE_OUTPUT.md` for the output produced against a real repository
(sindresorhus/ora).

## Requirements

`git`, `bash` 4+, and standard POSIX tools (`sed`, `tr`, `mktemp`).
