# Weekly GitHub Dev Summary (Claude)

An n8n workflow that runs every Friday, collects the week's GitHub activity for a
repository, asks Claude to write a narrative summary of it, and posts the result
to a Discord or Slack webhook.

```
Weekly (Fri 17:00)
   └─ Config ─ Compute window
                 ├─ Get commits        ─┐
                 ├─ Get closed issues  ─┼─ Build context ─ Claude API ─ Build payload ─ Deliver to webhook
                 └─ Get merged PRs     ─┘
```

## Setup — 5 steps

1. **Import.** In n8n: *Workflows → ⋯ → Import from File* → select `weekly-dev-summary.json`.
2. **GitHub credential.** Create a *GitHub API* credential (Settings → Credentials) using a
   personal access token with read access to the repo, then select it on the three `Get …` nodes.
3. **Anthropic credential.** Create a *Header Auth* credential — **Name** `x-api-key`,
   **Value** your Anthropic API key — and select it on the `Claude API` node.
4. **Configure.** Open the **Config** node and set six values:

   | Field | Example | Notes |
   |---|---|---|
   | `repoOwner` | `sindresorhus` | GitHub user or org |
   | `repoName` | `ora` | Repository name |
   | `language` | `EN` | `EN` or `FR` |
   | `deliveryTarget` | `discord` | `discord` (uses `content`) or `slack` (uses `text`) |
   | `webhookUrl` | `https://discord.com/api/webhooks/…` | Incoming webhook URL |
   | `model` | `claude-sonnet-4-20250514` | Claude model to call |

5. **Activate.** Toggle the workflow on. It fires on the cron `0 17 * * 5`
   (every Friday at 17:00 in the instance's timezone). Use *Execute Workflow* to run it once now.

## What it does

1. **Config** — the six values above.
2. **Compute window** — builds the ISO timestamps for the last 7 days.
3. **Get commits / Get closed issues / Get merged PRs** — three GitHub API calls,
   scoped to that window (`commits?since=&until=`, `issues?state=closed&since=`,
   `pulls?state=closed&sort=updated`).
4. **Build context** — filters to the window (issues are stripped of pull requests;
   PRs are kept only if `merged_at` falls inside it), then formats commits, closed
   issues and merged PRs into one prompt. The language instruction is appended here.
5. **Claude API** — `POST https://api.anthropic.com/v1/messages` with
   `anthropic-version: 2023-06-01`, asking for 3–5 short paragraphs and explicitly
   telling the model not to invent anything absent from the data.
6. **Build payload** — extracts the text from the response and throws if Claude
   returned no text, so a silent empty summary can't reach the channel.
7. **Deliver to webhook** — posts `{content: …}` (Discord) or `{text: …}` (Slack),
   with a header line and a stats line prepended.

## Changing the schedule

Edit the **Weekly (Fri 17:00)** trigger's cron expression. It is a standard
5-field cron interpreted in the n8n instance's timezone.

## Email instead of a webhook

Add an *Email Send* node after **Build payload**, map its body to
`{{ $json.message }}`, and delete the **Deliver to webhook** node. Everything
upstream is unchanged.

## Honest verification status

**This workflow has NOT been executed on a live n8n instance, and no execution
screenshot is included.** I am not going to present an unexecuted workflow as
tested. Specifically:

- **I attempted the local install and it failed.** `npm install n8n` on this machine
  (Node 26.7.0) dies compiling the native `@confluentinc/kafka-javascript` module under
  `node-gyp` (`gyp ERR! not ok`, then `=== install exit: 1 ===`). n8n supports Node
  20–24; Node 26 is outside that range, so this is not a configuration I could work
  around from here. This is an observed failure, not a guess.
- A full end-to-end run also needs an **Anthropic API key**, which was not
  available here — so the `Claude API` node could not have produced a real
  response regardless.

What *was* verified:

- **Structural validation passes** — valid JSON; 10 nodes; every node has the
  required keys; all node types are real `n8n-nodes-base.*` types; all 9
  connections point at nodes that exist; every node is reachable from the trigger;
  and all 6 `$('Node')` references resolve to nodes that exist.
- The two Code nodes and the GitHub/Anthropic request shapes were written against
  the current n8n node versions (`code` v2, `httpRequest` v4.2, `set` v3.4,
  `scheduleTrigger` v1.2).

To verify it for real: import it, set the two credentials, set `webhookUrl`, and
hit *Execute Workflow*. If anything fails, the likely culprits are the
credentials, not the graph — the structure is validated.
