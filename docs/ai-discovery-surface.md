# The AI discovery surface: `/mcp`, `/llms.txt`, `/llms-full.txt`

Added 2026-09-28. This is the reference for how an AI assistant reads wecare.digital, what
each artifact is actually worth, and the routing behaviour that makes one of them
non-obvious to deploy.

## The three things, and which one matters

| Path | What it is | Certainty it is used |
|---|---|---|
| `/mcp` | Read-only MCP server, Streamable HTTP | **High.** A protocol with clients that exist today |
| `/llms.txt` | Curated markdown map of the public pages | Low. A convention no vendor has committed to |
| `/llms-full.txt` | The same plus every article title and summary | Low, same reason |

The honest ranking is deliberate. `/mcp` is the one that changes what an agent can do:
it connects once and then asks a specific question — "which page covers dispute
resolution", "find posts about visas" — and gets a scoped, structured answer. The llms.txt
files hand over a fixed snapshot and hope.

**Do not oversell llms.txt.** It was proposed by Jeremy Howard in September 2024
([llmstxt.org](https://llmstxt.org)) and is published by Anthropic, Stripe, Vercel,
Cloudflare and Supabase, so it is respectable company. But as of 2026 adoption sits near
one site in ten, Google has stated Search does not use the file, and no major AI vendor has
committed its answer engine to reading it. It is also **not** an access-control file: it
grants nothing and blocks nothing, and no crawler is obliged to fetch it. `robots.txt` is
where permission lives. Treat llms.txt as cheap insurance with one certain benefit — a
correct, machine-readable statement of what this site publishes and how it may be cited.

## `/mcp` — the part with a real protocol

Transport is **Streamable HTTP, stateless, JSON response mode**, implemented against the
[2025-11-25 spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).
Handler: `amplify/functions/ai/mcp/handler.py`. Deploy: `scripts/deploy_mcp_server.py`.

| Method | Answer | Why |
|---|---|---|
| `POST` | one JSON object, or `202` with no body for a notification | The spec's explicit alternative to SSE |
| `GET` | `405` + `Allow: POST, OPTIONS` | "...or else return HTTP 405 Method Not Allowed, indicating that the server does not offer an SSE stream at this endpoint" |
| `DELETE` | `405` | Stateless, so no session was ever issued |
| `OPTIONS` | `204` + CORS | `Mcp-Session-Id` and `MCP-Protocol-Version` must be named or a browser client cannot send them |

Nothing here is degraded. **API Gateway HTTP API buffers its Lambda integration** — no
chunked transfer, no Server-Sent Events, 30 s ceiling — so the SSE arm of the transport is
not available, and the spec offers the JSON arm as an equal alternative rather than a
fallback. SSE only buys unsolicited server-to-client messages, and this server has no
long-running tool and nothing to push.

Protocol version handling has one trap worth naming, because it looks like a redundancy
somebody will tidy away:

- `initialize` offers **2025-11-25**, the newest.
- A request with **no** `MCP-Protocol-Version` header assumes **2025-03-26**, because the
  spec says so explicitly.

`LATEST_PROTOCOL_VERSION` and `DEFAULT_PROTOCOL_VERSION` therefore differ on purpose, and
`test_the_absent_default_is_not_the_newest_version` exists to stop them being merged.

### Five tools, all reads

`get_site_summary`, `list_pages`, `search_pages`, `search_blog`, `get_blog_post`. Plus two
JSON resources: `wecare://site/summary` and `wecare://pages/catalog`.

The endpoint **cannot act**: no message send, no request create or amend, no payment
capture or refund, no contact or order read, nothing behind a sign-in. That is enforced by
absence rather than by a permission — the handler imports no `boto3` at all, which
`test_the_handler_imports_no_aws_client` asserts — and by
`READ_ONLY_TOOLS`, a frozen allowlist that `tools/list` and `tools/call` both resolve
through and that is compared for **exact equality** in
the MCP surface verifier. A check that only confirms the current tools still work would
pass just as happily after someone added `send_whatsapp`; that one fails on the addition.

### The threat model is cost, not disclosure

Everything this endpoint returns is already public, so there is nothing to leak. The
exposure is spend, which `amplify/functions/core/site-language/handler.py` already learned
on the only other anonymous route on the site: a public endpoint in front of a billed API
works out near $32,000/hour at 15 rps, and caching cannot help because attacker text never
repeats a cache key.

So:

- The blog corpus is fetched **once per warm sandbox**, memoised for 15 minutes.
  `/api/seo-tools/blog-public` returns the whole 889-post corpus as 924 kB in about 5 s and
  is already the hottest function in the fleet at ~392k invocations a week. An uncached
  public endpoint in front of it would be a free amplifier.
- An expired cache serves **stale** rather than empty when the upstream fails. Reporting
  zero posts because of a two-second blip would make the blog look empty, which is the same
  failure `generate-sitemap.js` refuses to write a sitemap for.
- No tool reaches Bedrock. If one is ever added, `_enabled_tools()` is the choke point where
  it is gated, and it needs its own rate cap **before** being switched on — the only limit
  in front of `/mcp` today is the API Gateway stage throttle (100 rps / 200 burst), which is
  real but **shared with all 358 other routes**.

## The routing trap, which is the non-obvious part

Amplify Hosting 301-redirects any extension-less path that matches no rule, to add a
trailing slash — **and it does so for POST as well as GET**. Measured on the live site
before this work:

```
$ curl -X POST -D- https://wecare.digital/mcp
HTTP/2 301
location: /mcp/
```

For MCP that is fatal rather than untidy. Every client message is a POST, and RFC 9110
permits a client to rewrite POST to GET when following a 301; others refuse to follow a
redirect on a non-idempotent method at all. Either way the handshake never arrives, and the
endpoint appears to exist while never working — the worst available failure shape.

An explicit rule defeats the normalizer. That is proven rather than assumed: `/get` has
`/get` and `/get/` rules at status 200 and returns HTTP 200 with no redirect, while
`/anything-random` 301s. So `deploy_mcp_server.py` registers both spellings:

```
/mcp   -> https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/mcp   200
/mcp/  -> https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/mcp   200
```

**Rule order is load-bearing.** Amplify evaluates `customRules` top-down and the last rule
is the terminal catch-all `/<*>` -> `/404.html` at `404-200`. A rule added after it is
dead. The two rules above are inserted immediately *before* the catch-all, and the script
reads the list back afterwards to assert the catch-all is still last and that no
pre-existing rule was dropped.

`404-200` is `NOT_FOUND_REWRITE` and is only evaluated once the file lookup misses, which
is how it sits at the bottom without shadowing the ~123 exported pages. Do not change it to
a plain `200`: that matches unconditionally and would serve the home page for the whole
site.

The retired human-readable AI documentation route has no rewrite. The live machine-readable surfaces are `/mcp`, `/llms.txt` and `/llms-full.txt`.

### One standing hazard

`scripts/provision_legacy_redirects.py` rebuilds the rule list as
`[its own redirects] + [pre-existing non-redirect rules]`, and recognises a rule as its own
only when the source is in its `RETIRED` set. Its comments warn that a rule it does not
model survives "by luck, not by design". The `/mcp` rules are status-200 rewrites, so they
land in the preserved bucket — the same one that has kept `/api/<*>` and `/get/<*>` alive.
After any run of that script:

```
python scripts/deploy_mcp_server.py --verify
```

## One catalogue, five consumers

`config/public-pages.json` is the single source for the public page set. It is **derived,
not authoritative**: the render allowlist is `PUBLIC_PAGE_META` plus the `isPublic` chain in
`src/pages/_app.tsx`, and the crawl allowlist is `PUBLIC_EXACT` in
`scripts/generate-sitemap.js`. Those two decide what exists; the catalogue describes it.

```
src/pages/_app.tsx                PUBLIC_PAGE_META + isPublic chain   render allowlist
scripts/generate-sitemap.js       PUBLIC_EXACT                        crawl allowlist
config/public-pages.json          the catalogue         llms.txt + the MCP server's zip
amplify/functions/ai/mcp/  READ_ONLY_TOOLS, PROTOCOL_VERSIONS  what /mcp serves
src/lib/ai-surface.ts             metadata shared by the machine-readable AI surfaces
```

Five descriptions of one truth, in four languages, because the consumers cannot share a
module — a React allowlist, two Node generators, a Python Lambda, and a TS constants file.
`src/test/PublicAiSurface.test.ts` holds them in step. Each drift is silent in its own way:

| Drift | Consequence |
|---|---|
| catalogue has a page `_app.tsx` does not | llms.txt advertises a URL that serves the staff sign-in shell at HTTP 200 |
| `_app.tsx` has a page the catalogue lacks | the page is invisible to every agent |
| `ai-surface.ts` disagrees with the handler | generated AI discovery metadata can describe tools that do not exist |
| a named robots.txt agent loses a `Disallow` | that crawler is **granted** `/workspace/` |

`src/lib/ai-surface.ts` restates a handful of values rather than importing the catalogue,
and that is measured rather than lazy: `resolveJsonModule` would inline the whole document
— every description plus the 20-line `_comment` block — into the client chunk, and JSON
imports are not tree-shaken per key, so the retired human-readable AI page used to ship ~8 kB of commentary to render
five bullet points.

### The robots.txt footgun, stated plainly

`robots.txt` has **no inheritance**: a named `User-agent` group *replaces* the
`User-agent: *` group for that agent. So the obvious way to welcome a crawler —

```
User-agent: GPTBot
Allow: /
```

— does not mean "same as everyone, and welcome". It means GPTBot has no `Disallow` at all,
which grants it `/workspace/`, the authenticated dashboard that the `*` group is the only
thing holding out of the index. Welcoming a crawler by name and publishing the internal
route map is the same edit. The four `Disallow` lines are therefore repeated verbatim in the
AI-agent group, and `PublicAiSurface.test.ts` asserts each named agent is restricted at
least as tightly as `*`.

## Build order

```
next build
  -> scripts/generate-sitemap.js            writes out/sitemap.xml
  -> scripts/generate-blog-search-index.js  writes out/blog/search-index.json
  -> scripts/generate-llms-txt.js           writes out/llms.txt, out/llms-full.txt
```

The llms.txt generator must run **last**, because it reads `out/blog/search-index.json`
instead of fetching `/api/seo-tools/blog-public` a fourth time during one build. Asserted by
`runs the llms.txt generator after the blog search index`.

Failure policy differs per artifact on purpose:

- **Refuses to write** when a catalogued page is absent from the export, or when a URL it
  would advertise is `Disallow`ed in robots.txt. Both publish a statement known to be
  false. Note `generate-sitemap.js` only *warns* on the first condition — it can afford to,
  because it emits routes it actually found, so a stale entry just makes the sitemap
  shorter. This file emits what the catalogue says, so a stale entry becomes a published
  dead link a model will cite.
- **Warns only** on a missing or empty blog index. The file degrades to the page map, which
  is still correct. The sitemap takes the opposite line because losing 834 URLs is a ranking
  event that takes weeks to undo.

## Stale artifact, do not reuse

`seo/llm/llms-txt-draft.md` is a complete, careful, hand-written llms.txt — for the **retired
previous site**. It advertises `/bnb`, `/legal-champ`, `/ritual`, `[retired public path 74ea5c7a]`, `[retired public path 14041cbc]`,
`[retired public path 9109e567]` and `/_functions/*`, and not one of those exists now. It is the reason
`/llms.txt` is generated rather than committed: a hand-maintained file describing a site
that changes is a file that will be wrong, and wrong quietly.

## Verifying

`wecare-mcp` is outside `scripts/check_deployed_source.py`, which derives its fleet from the
`SPECS` list in `deploy_all_lambdas.py` and so cannot see a `DELEGATED` function.
`wecare-seo-tools` has the same gap for the same reason. Both build deterministic zips, so
re-running the owning deploy script is the drift check: it reports `rules already correct` and
an unchanged `CodeSha256` when nothing moved.

```
python scripts/deploy_mcp_server.py --verify      # Lambda, route, hosting rules, rule order
python scripts/audit_route_auth.py --gate         # /mcp must appear as expected-public

# a real handshake
curl -sS -X POST https://wecare.digital/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

# must be 405, and that is correct rather than broken
curl -sS -o /dev/null -w '%{http_code}\n' https://wecare.digital/mcp
```

## Related

- `.kiro/steering/lambda-snapstart-deploy.md` (retired 2026-10-09, af7858fa) — why a code change is not live until the
  `live` alias moves. `deploy_mcp_server.py` publishes and moves it itself.
- `amplify/functions/core/site-language/handler.py` — the cost threat model for an
  unauthenticated route, written out at length.
- `scripts/generate-sitemap.js` — the allowlist this catalogue must agree with.
