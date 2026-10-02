# Sample output

Both runs below are real, produced against
**[sindresorhus/ora](https://github.com/sindresorhus/ora)** — a public repo with
78 commits and 24 tags at the time of testing.

---

## 1. Default path — commits since the last tag

```console
$ git clone https://github.com/sindresorhus/ora && cd ora
$ bash scripts/changelog.sh 9.5.0
changelog: wrote CHANGELOG.md  [9.5.0]  1 commit(s) since `v9.4.1`
```

`CHANGELOG.md`:

```markdown
# Changelog

All notable changes to this project are documented here.

## [9.5.0] - 2026-10-02

_Changes since `v9.4.1`._

### Added

- _(none)_

### Fixed

- _(none)_

### Changed

- Meta tweaks

### Removed

- _(none)_
```

Only one commit sat between the last tag and HEAD, and it was placed in
**Changed** — no `feat:`/`fix:` prefix and no keyword match.

---

## 2. Explicit range — `--from v9.0.0`

```console
$ bash scripts/changelog.sh --from v9.0.0 9.5.0
changelog: wrote CHANGELOG.md  [9.5.0]  18 commit(s) since `v9.0.0`
```

`CHANGELOG.md`:

```markdown
# Changelog

All notable changes to this project are documented here.

## [9.5.0] - 2026-10-02

_Changes since `v9.0.0`._

### Added

- Add `successSymbol` and `failSymbol` options to `oraPromise`
- Add FAQ item
- Add more tests for `discardStdin`
- Support external writes to stream while spinning

### Fixed

- Fix type definitions (#257)

### Changed

- Meta tweaks
- Minor tweaks (#258)
- 9.4.1
- Minor tweaks
- 9.4.0
- Test tweaks
- Validate some options better
- 9.3.0
- Reduce flicker in rendering
- Document Ctrl+C behavior for discardStdin
- 9.2.0
- Update `stdin-discarder` dependency (#251)
- 9.1.0

### Removed

- _(none)_
```

---

## Honest notes on this output

- **`Removed` is empty** because ora removed nothing in that range. The section
  still renders as `_(none)_` rather than disappearing, so all four categories
  are visible on every run.
- **`Add more tests for discardStdin`** lands in *Added* via the keyword fallback
  (`add` → Added). *Changed* would arguably read better. This is the heuristic's
  documented limit, and the README says so — the fix is a human pass, not a
  cleverer regex.
- **Version-bump commits** (`9.4.1`, `9.4.0`, …) appear under *Changed*. In a repo
  that tags those commits they usually fall outside the range instead.
- Merge commits are skipped entirely (`--no-merges`), which is why the counts here
  are lower than `git rev-list --count` would suggest.
