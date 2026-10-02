# claude-review

Review a GitHub pull request and get a structured Markdown review comment:
summary, identified risks, improvement suggestions, and a confidence score.

```console
$ claude-review --pr https://github.com/chalk/chalk/pull/689
```

## Setup (3 steps)

1. Install `gh` and authenticate: `gh auth login`
2. Pick a backend — either log in to the `claude` CLI (`claude` then `/login`),
   or set `ANTHROPIC_API_KEY`, or set `LLM_BASE_URL` + `LLM_API_KEY` for any
   OpenAI-compatible endpoint.
3. Run it: `python3 claude-review.py --pr <PR URL>`

No Python dependencies — stdlib only, Python 3.8+.

## Usage

```bash
# review a PR (accepts a URL, or owner/repo#123)
python3 claude-review.py --pr https://github.com/owner/repo/pull/123
python3 claude-review.py --pr owner/repo#123

# also post it as a comment on the PR
python3 claude-review.py --pr owner/repo#123 --post

# write to a file / emit JSON / skip the model call
python3 claude-review.py --pr owner/repo#123 --out review.md
python3 claude-review.py --pr owner/repo#123 --json
python3 claude-review.py --pr owner/repo#123 --dry-run   # prints the prompt, calls nothing

# choose a backend explicitly
python3 claude-review.py --pr owner/repo#123 --backend claude
python3 claude-review.py --pr owner/repo#123 --backend anthropic --model claude-sonnet-4-20250514
python3 claude-review.py --pr owner/repo#123 --backend openai   --model deepseek-chat
```

## Output format

```markdown
## Automated review

### Summary of changes
<2-3 sentences>

### Identified risks
- <concrete risk>

### Improvement suggestions
- <actionable suggestion>

### Confidence score: `Medium`
Medium — <what limited or supported the confidence>
```

The model is instructed to emit exactly these four sections; the tool parses and
re-renders them, and **fails loudly** if a section is missing rather than
inventing one.

## Backends

Auto-detection order: `claude` → `anthropic` → `openai`.

| Backend | Needs | Notes |
|---|---|---|
| `claude` | the Claude Code CLI, logged in | A Claude Code agent: shells out to `claude -p` |
| `anthropic` | `ANTHROPIC_API_KEY` | Direct Messages API call |
| `openai` | `LLM_BASE_URL` + `LLM_API_KEY` | Any OpenAI-compatible endpoint — DeepSeek, OpenRouter, vLLM, Ollama |

## GitHub Action

`github-action-review.yml` runs the reviewer on `pull_request` events and posts
the comment automatically. Copy it to `.github/workflows/` and set the `LLM_*`
secrets (or `ANTHROPIC_API_KEY`).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_REVIEW_MAX_DIFF` | `60000` | Max diff characters sent to the model |
| `CLAUDE_REVIEW_SKIP` | lockfiles, `dist/`, `build/`, `node_modules/`, `.min.*` | Regex of paths to drop from the diff; set to `""` to disable skipping |
| `LLM_MODEL` | `deepseek-chat` | Model for the `openai` backend |

## Tested on real PRs

See `SAMPLE_OUTPUT.md` — full reviews of `chalk/chalk#689` (+335/-34, 6 files)
and `sindresorhus/slugify#82` (+43/-4, 2 files).

## Honest limitations

- **It is a review, not a gate.** The confidence score is the model's own
  self-assessment, not a measured accuracy figure.
- **Diff-only context.** It sees the diff and the PR description — not the
  surrounding codebase, the CI result, or previous review comments. Findings that
  depend on code outside the diff will be missed, and the model is told to say so
  in the Confidence line when the diff is truncated.
- **Large PRs are truncated** at `CLAUDE_REVIEW_MAX_DIFF` characters, and the
  truncation is stated in the prompt so the model can flag it.
- **Lockfiles and build output are dropped** from the diff by default, which
  makes the review cheaper but means a change *inside* a skipped path is
  invisible. Override with `CLAUDE_REVIEW_SKIP`.
- **Posting is opt-in** (`--post`); by default it only prints.
