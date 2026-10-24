# Meta MCP servers — setup, and what is blocked

**Two manual steps are required; I could do neither.**

1. `.kiro/settings/mcp.json` is write-protected for the agent (`deny fs_write`
   on `.kiro/settings/`), so the config below has to be pasted by you.
2. Both servers are **remote** and behind OAuth. The browser consent step cannot
   be completed by an agent even once configured.

Paste this into `.kiro/settings/mcp.json` (it is currently `{"mcpServers": {}}`):

```json
{
  "mcpServers": {
    "whatsapp-business-tools": {
      "url": "https://mcp.facebook.com/whatsapp_business_tools",
      "disabled": false
    },
    "devtools": {
      "url": "https://mcp.facebook.com/devtools",
      "disabled": false
    }
  }
}
```

## Verified, not assumed

| Fact | Evidence |
|---|---|
| `https://mcp.facebook.com/devtools` is a real MCP endpoint | `POST` initialize → `401 {"title":"Authentication Required","detail":"Failed to authenticate MCP request"}` — an MCP-shaped auth error, not a 404 |
| `https://mcp.facebook.com/whatsapp_business_tools` is a real MCP endpoint | same probe, same MCP-shaped 401 |
| Endpoint, plugin id `devtools`, tool prefix `devtools_` | `github.com/facebook/agentic-tools` README |
| The 9 skills | same README, table reproduced below |
| Remote, OAuth, not a bundled process | README: "The Meta Social Technologies MCP is a remote server — it is not bundled as a process; users authenticate it in their agent." |
| WhatsApp Business Tools MCP launched 2026-09-15 | TechCrunch, 2026-09-15 |

The official repo covers the `devtools` server only. The WhatsApp endpoint is a
separate product and is **not** documented in that repo — its URL is confirmed
solely by the live probe above, so treat the tool names as unknown until
discovery succeeds.

Content rephrased for compliance with licensing restrictions.

## The 9 published skills

| Skill | Purpose |
|---|---|
| `/app-health-check` | Whole-app audit: settings, security, compliance, app review |
| `/webhook-setup` | Webhook subscription wizard with test verification |
| `/app-review-prep` | App Review readiness: requirements, privileges, history |
| `/debug-webhooks` | Inspect, test and fix webhook delivery |
| `/compliance-check` | Violations, required actions, remediation |
| `/api-health` | Rate limits, call volume, deprecation warnings |
| `/api-integration` | Setup guides, auth, permissions, code examples |
| `/search-docs` | Search Meta developer documentation |
| `/debug-access-token` | Diagnose a token without it entering agent context |

`/debug-access-token` is worth noting against this repo's own rule that a secret
must never enter agent context — it is designed for exactly that constraint.

## To enable

1. Reconnect MCP servers — Kiro feature panel → **MCP Server** view → reconnect,
   or the command palette → `MCP`.
2. Complete the OAuth flow for each server.
3. Confirm with `/tools` that `devtools_*` tools are listed.

## What cannot be done until then

Tool discovery, schema inspection, READ probes and the recursive
doc→reference→changelog→code crawl all require an authenticated session. None of
it is reported here, because none of it has run.

## Audit that did NOT need the MCP

`docs/meta-subscription-audit.md` compares the app's live webhook subscription
against what this repository actually handles, using the Graph API directly. That
is the substantive answer to "are we subscribed to everything, and do we use it".

## Repo connected: skills installed

`facebook/agentic-tools` @ `67dca94` cloned and its nine skills installed to
`.kiro/skills/`. They follow the open Agent Skills standard (`SKILL.md`), which is
why they port to Kiro at all — Kiro is **not** one of the three documented targets
(Claude Code, Cursor, Codex), so this is an adaptation, not a supported install
path. There is no marketplace step for Kiro.

`debug-access-token` also ships `scripts/debug_token_probe.py`, installed with it.

## Tool inventory — 10 tools, obtained without authenticating

Derived from the `allowed-tools` frontmatter across all nine skills, so this is
Meta's own declaration rather than a guess. In Claude the namespace is
`mcp__devtools__devtools_*`; the bare tool name is what a Kiro MCP client sees.

| Tool | Purpose | Class |
|---|---|---|
| `devtools_app_list` | enumerate the apps you can administer | READ |
| `devtools_app` | app + product configuration, settings, security | READ |
| `devtools_app_review` | review status, requirements, granted privileges, history | READ |
| `devtools_compliance` | violations, required actions, remediation | READ |
| `devtools_api_usage` | rate limits, call volume, deprecations | READ |
| `devtools_discovery` | documentation / endpoint / reference search | READ |
| `devtools_webhook_list` | inspect active subscriptions | READ |
| `devtools_webhook_manage` | subscribe / unsubscribe fields, callback config | **WRITE** |
| `devtools_webhook_test` | send a test payload to the callback | **WRITE-effect** |
| `devtools_skill_invocation` | skill-invocation bookkeeping | internal |

Class is inferred from tool names and skill descriptions. **Schemas, required and
optional parameters, and permission requirements are NOT captured** — those need
an authenticated session, and nothing here should be read as if they were.

### Two of these are dangerous against this account, right now

`devtools_webhook_manage` can change the app's callback URL or field
subscriptions. The app currently has 32 WABA fields plus 2 catalog fields on
`https://wecare.digital/api/whatsapp`, and that configuration is **correct** — the
401s were our routing bug, not Meta's config. An unreviewed `webhook_manage` call
could turn a one-line code fix into a subscription outage. Do not run it without
a reviewed plan.

`devtools_webhook_test` is the useful one after the stage-prefix fix deploys: it
sends a real delivery to the live callback, which is exactly how to confirm Meta
stops receiving 401s. It has a side effect, so it is still gated.

## Still blocked

Installing the skills does not connect the server. The skills call
`devtools_*` tools that do not exist in this session, so invoking one now would
stall at its first tool call. Both remaining blockers are unchanged:

1. `.kiro/settings/mcp.json` is write-denied to the agent — paste the config above.
2. Both servers need an interactive OAuth flow.
