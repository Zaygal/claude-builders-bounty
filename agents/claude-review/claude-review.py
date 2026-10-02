#!/usr/bin/env python3
"""
claude-review — review a GitHub pull request and emit a structured Markdown comment.

    claude-review --pr https://github.com/owner/repo/pull/123

Fetches the PR (metadata + diff) with `gh`, asks a model for a structured review,
and prints Markdown with the four required sections:

    . Summary of changes (2-3 sentences)
    . Identified risks (list)
    . Improvement suggestions (list)
    . Confidence score: Low / Medium / High

Backends (auto-detected in this order):
    1. claude    - the Claude Code CLI (`claude -p`), i.e. a Claude Code agent
    2. anthropic - the Anthropic Messages API, via ANTHROPIC_API_KEY
    3. openai    - any OpenAI-compatible endpoint, via LLM_BASE_URL + LLM_API_KEY
                   (covers DeepSeek, OpenRouter, Ollama, vLLM, ...)

Examples
--------
    claude-review --pr owner/repo#123
    claude-review --pr <url> --post           # also comment on the PR
    claude-review --pr <url> --backend openai --model deepseek-chat
    claude-review --pr <url> --dry-run        # print the prompt, call nothing

Stdlib only. Requires `gh` (authenticated) on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
DEFAULT_OPENAI_MODEL = "deepseek-chat"

# Diff hygiene: never send lockfiles, binaries or vendored output to the model.
# Override with CLAUDE_REVIEW_SKIP (set it to "" to disable skipping entirely).
# `vendor/` is deliberately NOT skipped by default — in repos that vendor their
# own source (e.g. chalk) it holds the actual change.
_DEFAULT_SKIP = (
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|"
    r"Gemfile\.lock|composer\.lock|go\.sum|\.min\.js|\.min\.css|dist/|build/|"
    r"node_modules/|\.snap$|\.lock$)"
)
SKIP_PATTERNS = re.compile(os.environ.get("CLAUDE_REVIEW_SKIP", _DEFAULT_SKIP), re.I)
MAX_DIFF_CHARS = int(os.environ.get("CLAUDE_REVIEW_MAX_DIFF", "60000"))

SYSTEM_PROMPT = """You are a senior engineer performing a code review of a pull request.

Write a review in GitHub-flavoured Markdown using EXACTLY these four sections and \
headings, in this order:

## Summary
2-3 sentences describing what this change does and why.

## Risks
A bullet list of concrete risks (correctness, security, data loss, performance, \
backwards compatibility, missing tests). If there are none, write "- None identified."

## Suggestions
A bullet list of specific, actionable improvements. Reference file or symbol names \
where you can. If there are none, write "- None."

## Confidence
Exactly one word from: Low, Medium, High — then a dash and one short sentence \
saying what limited or supported your confidence.

Rules:
- Be specific and concrete. No filler, no praise padding, no restating the diff.
- Do not invent files, functions or behaviour that are not in the diff.
- If the diff is truncated or you cannot see enough context, say so in Confidence.
- Never output anything before `## Summary` or after the Confidence line.
"""


# --------------------------------------------------------------------------
# PR fetching
# --------------------------------------------------------------------------

def parse_pr_url(value: str):
    """Accept a full URL, or `owner/repo#123` / `owner/repo 123`."""
    value = value.strip()
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", value)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = re.match(r"([\w.-]+)/([\w.-]+)(?:#|\s+)(\d+)$", value)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    raise SystemExit(f"error: cannot parse PR reference: {value!r}")


def _gh(args, timeout=120):
    if shutil.which("gh") is None:
        raise SystemExit("error: `gh` is not on PATH — install the GitHub CLI and authenticate")
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise SystemExit(f"error: gh {' '.join(args[:2])} failed:\n{proc.stderr.strip()}")
    return proc.stdout


def fetch_pr(owner, repo, number):
    slug = f"{owner}/{repo}"
    fields = "title,body,author,additions,deletions,changedFiles,baseRefName,headRefName,url,state,isDraft"
    meta = json.loads(_gh(["pr", "view", str(number), "--repo", slug, "--json", fields]))
    diff = _gh(["pr", "diff", str(number), "--repo", slug])
    try:
        files = json.loads(_gh(["pr", "view", str(number), "--repo", slug, "--json", "files"]))
        meta["files"] = [f.get("path") for f in files.get("files", [])]
    except SystemExit:
        meta["files"] = []
    meta["slug"] = slug
    meta["number"] = number
    meta["diff"] = diff
    return meta


def condense_diff(diff: str):
    """Drop lockfiles/binaries and cap the size. Returns (text, note)."""
    kept, dropped = [], 0
    for chunk in re.split(r"(?=^diff --git )", diff, flags=re.M):
        if not chunk.strip():
            continue
        first = chunk.splitlines()[0]
        path = first.replace("diff --git ", "").split(" b/")[-1].strip()
        if SKIP_PATTERNS.search(path):
            dropped += 1
            continue
        kept.append(chunk)
    text = "".join(kept)
    note = ""
    if dropped:
        note += f"\n\n({dropped} lockfile/generated/binary file(s) omitted from the diff.)"
    if len(text) > MAX_DIFF_CHARS:
        text = text[:MAX_DIFF_CHARS]
        note += f"\n\n(Diff truncated to the first {MAX_DIFF_CHARS} characters of " \
                f"{len(diff)} — later files are not visible.)"
    return text, note


def build_prompt(meta, truncated_diff, note):
    files = ", ".join(meta.get("files") or []) or "(not listed)"
    body = (meta.get("body") or "").strip()
    if len(body) > 3000:
        body = body[:3000] + "…"
    return f"""# Pull request to review

Repository: {meta['slug']}
PR: #{meta['number']} — {meta['title']}
Author: {(meta.get('author') or {}).get('login', 'unknown')}
State: {meta.get('state', '?')}{' (draft)' if meta.get('isDraft') else ''}
Branch: {meta.get('headRefName', '?')} -> {meta.get('baseRefName', '?')}
Size: +{meta.get('additions', 0)} / -{meta.get('deletions', 0)} in {meta.get('changedFiles', 0)} file(s)

PR description:
\"\"\"
{body or '(no description provided)'}
\"\"\"

Files changed: {files}

Diff:
```diff
{truncated_diff}
```
{note}

Now write the review, following the four-section format exactly.
"""


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

def _post_json(url, payload, headers, timeout=180):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise SystemExit(f"error: {url} returned HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"error: could not reach {url}: {exc.reason}")


def backend_claude(prompt, model):
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("error: `claude` CLI not found on PATH")
    proc = subprocess.run(
        [claude, "-p", prompt, "--model", model],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(
            "error: `claude -p` produced no review. If it reports 'Not logged in', "
            "run `claude` and use /login, or pick another backend with --backend."
        )
    return proc.stdout.strip()


def backend_anthropic(prompt, model):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("error: ANTHROPIC_API_KEY is not set")
    payload = {
        "model": model,
        "max_tokens": 2000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _post_json(
        "https://api.anthropic.com/v1/messages",
        payload,
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    return "".join(block.get("text", "") for block in data.get("content", [])).strip()


def backend_openai(prompt, model):
    base = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not base or not key:
        raise SystemExit("error: set LLM_BASE_URL and LLM_API_KEY for the openai backend")
    url = base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    data = _post_json(url, payload, {"Authorization": f"Bearer {key}"})
    return data["choices"][0]["message"]["content"].strip()


def choose_backend(requested):
    if requested != "auto":
        return requested
    if shutil.which("claude"):
        return "claude"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if (os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")) and \
       (os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        return "openai"
    raise SystemExit(
        "error: no backend available. Install and log in to the `claude` CLI, "
        "or set ANTHROPIC_API_KEY, or set LLM_BASE_URL + LLM_API_KEY."
    )


def default_model(backend):
    return {
        "claude": DEFAULT_CLAUDE_MODEL,
        "anthropic": DEFAULT_ANTHROPIC_MODEL,
        "openai": os.environ.get("LLM_MODEL", DEFAULT_OPENAI_MODEL),
    }[backend]


# --------------------------------------------------------------------------
# Output shaping
# --------------------------------------------------------------------------

REQUIRED = ("Summary", "Risks", "Suggestions", "Confidence")


def normalise(raw):
    """Guarantee the four sections exist, in order."""
    out = {}
    for name in REQUIRED:
        m = re.search(rf"^#{{1,6}}\s*{name}\s*$", raw, re.I | re.M)
        if not m:
            continue
        start = m.end()
        nxt = re.search(r"^#{1,6}\s*\w+", raw[start:], re.M)
        end = start + nxt.start() if nxt else len(raw)
        out[name] = raw[start:end].strip()
    if len(out) != len(REQUIRED):
        missing = [n for n in REQUIRED if n not in out]
        raise SystemExit(
            f"error: model output is missing section(s): {', '.join(missing)}.\n"
            f"--- raw output ---\n{raw[:1500]}"
        )
    conf = out["Confidence"].strip()
    word = re.search(r"\b(low|medium|high)\b", conf, re.I)
    out["Confidence"] = conf if word else f"Medium — model returned: {conf[:120]}"
    return out


def render(sections, meta, backend, model):
    return "\n".join([
        "## Automated review",
        "",
        f"_Model: `{model}` · backend: `{backend}` · PR #{meta['number']} in {meta['slug']}_",
        "",
        "### Summary of changes",
        "",
        sections["Summary"],
        "",
        "### Identified risks",
        "",
        sections["Risks"],
        "",
        "### Improvement suggestions",
        "",
        sections["Suggestions"],
        "",
        f"### Confidence score: `{sections['Confidence'].split('—')[0].split('-')[0].strip()}`",
        "",
        sections["Confidence"],
        "",
        "<sub>Generated by claude-review — a machine review. A human should confirm before acting.</sub>",
    ])


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="claude-review",
        description="Review a GitHub PR and emit a structured Markdown comment.",
    )
    ap.add_argument("--pr", required=True, help="PR URL, or owner/repo#123")
    ap.add_argument("--backend", default="auto", choices=["auto", "claude", "anthropic", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", default=None, help="write the review to this file")
    ap.add_argument("--post", action="store_true", help="post the review as a PR comment")
    ap.add_argument("--dry-run", action="store_true", help="print the prompt; call no model")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    args = ap.parse_args(argv)

    owner, repo, number = parse_pr_url(args.pr)
    meta = fetch_pr(owner, repo, number)
    diff, note = condense_diff(meta["diff"])
    prompt = build_prompt(meta, diff, note)

    if args.dry_run:
        print(prompt)
        return 0

    backend = choose_backend(args.backend)
    model = args.model or default_model(backend)
    sys.stderr.write(f"[claude-review] {meta['slug']}#{number} via {backend} ({model})\n")

    raw = {"claude": backend_claude, "anthropic": backend_anthropic, "openai": backend_openai}[backend](prompt, model)
    sections = normalise(raw)
    body = render(sections, meta, backend, model)

    if args.json:
        print(json.dumps({"pr": f"{meta['slug']}#{number}", "backend": backend,
                          "model": model, "sections": sections, "markdown": body}, indent=2))
    else:
        print(body)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
        sys.stderr.write(f"[claude-review] wrote {args.out}\n")

    if args.post:
        proc = subprocess.run(
            ["gh", "pr", "comment", str(number), "--repo", meta["slug"], "--body-file", "-"],
            input=body, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            raise SystemExit(f"error: posting the comment failed:\n{proc.stderr.strip()}")
        sys.stderr.write(f"[claude-review] posted: {proc.stdout.strip()}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
