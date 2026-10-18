# Retired URL forwarding removal - 2026-10-02

Owner explicitly requested removal of forwarding for the 31 former staff/content paths listed in chat, following the [retired public path ef531503] complaint.

## Sources and resulting behavior

- Live Amplify app `d22dm4b0jn71jw`, Hosting > Rewrites and redirects: removed `[retired public path ef531503]`, `[retired public path ef531503]/`, `[retired public path ef531503]/<*>` 302 rules. Fresh configuration went from 12 rules to nine. Only www host canonicalisation remains an explicit Amplify redirect; internal API/media/MCP rewrites and the missing-page catch-all are retained unchanged.
- `scripts/provision_legacy_redirects.py`: desired configuration no longer recreates access redirects.
- `src/pages/404.tsx`: at the owner's final follow-up instruction, the retired URL list was removed entirely. One simple missing-page rule applies: the CDN serves HTTP 404, then the browser calls `router.replace('/')` for every missing path. There are no individual legacy destinations or exceptions. The CDN retains its real HTTP 404.
- `scripts/probe_url_host_matrix.py`: lists retired URLs as audit expectations, not runtime redirects. Access expectations now require 404.
- Current public pages, including `/get/`, `/vault/`, `/cart/`, and customer sign-in, and staff routes under `/workspace/` are retained. No DNS, subdomain fallback, or certificate changes.

## Validation

Frontend tests passed, including real component navigation tests for all retired prefixes, descendants, case/encoding, and other missing paths. Four Python configuration/snapshot tests passed. Full production build passed, including TypeScript and static export.

Live Amplify configuration was read immediately before the update, compared with the saved array, then only the three access rules were removed. Pre-change evidence: `snapshots/retired-url-rules-before-20261002.json`.

## Completion

Final owner instruction: one shared 404-to-home behavior, no retired-prefix list. Commit `8b24baa0` deployed through Amplify job `1231`: BUILD, DEPLOY and VERIFY all SUCCEED. Fifty frontend tests and four configuration tests passed; the final production build passed.

Live browser navigation to `[retired public path ef531503]/`, `[retired public path 282d0fd5]/`, and `/definitely-not-a-page/` reached `https://wecare.digital/`. Thirty-two retired path probes (the 31 owner-listed paths plus access) returned HTTP 404 with no Location header. All 32 former paths are absent from the static page export. `/get/`, `/vault/`, `/shop/`, `/cart/`, `/orders/`, `/account/sign-in/`, `/workspace/access/`, and `[retired public path]` returned HTTP 200 at their own URLs.

The two MCP rewrites are declared in `scripts/deploy_mcp_server.py`, `HOSTING_RULES` at lines 133-136. They cover `/mcp` and `/mcp/` and proxy both to `/prod/mcp`; they do not create two servers. The public handler is `amplify/functions/ai/mcp/handler.py`, Lambda `wecare-mcp`. Audit dictionaries in `scripts/probe_url_host_matrix.py` and `scripts/retired_url_probe.py` do not install redirects. Historical comments and snapshots may describe prior behavior and are not the live configuration.

## Recovery evidence

Revert the scoped source commit and deploy only if owner requests recovery. Saved pre-change rules are evidence, not authorization to restore the removed redirects. Restoring DNS or certificates is outside this change.
