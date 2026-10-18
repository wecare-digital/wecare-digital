# Owner-requested custom redirect removal - 2026-10-01

Authority: the owner instructed "delete all url redirects now" and "dont delete any new puplic page". This supersedes the previous SEO and frozen-template redirect preservation instructions for custom hosting redirects.

## Executed change

AWS account 775261844268, us-east-1, Amplify app d22dm4b0jn71jw. AWS MCP UpdateApp removed 138 custom redirect rules from a 146-rule configuration. Independent GetApp readback confirms eight rules remain, with zero custom redirect statuses. All eight original internal rewrites remain unchanged and in their original order: /get, /get/, /get/<*>, /r/<*>, /api/<*>, /mcp, /mcp/, and the /<*> -> /404.html 404-200 fallback.

Removed rules include the www-to-apex rule, [retired public path 74ea5c7a], [retired public path 14041cbc], [retired public path 32bc4583], [retired public path 282d0fd5], [retired public path b180810d], other legacy public aliases, workspace prefix aliases, slash forms and wildcard mappings. No page file, current public content, API route, media object or provider registration was deleted. Approved templates containing old [retired public path 282d0fd5] or [retired public path b180810d] URLs were not rewritten or sent; their old links now use missing-page behavior under the owner's override.

The retained 404 page can navigate to home in JavaScript. Built-in HTTPS/trailing-slash normalization and application authentication/payment navigation are separate from custom hosting redirects; this change does not disable those required platform flows. Browser-cached prior 301 responses can outlive a hosting-rule change.

## Source and verification

The existing provisioning entry point now converges to zero custom redirects instead of reconstructing legacy mappings. It preserves rewrites verbatim, snapshots before mutations, refuses to write without the existing fallback, and does nothing when converged. Canonical frontend SEO author references now use /anew/; the SEO suggestion list uses the current public catalogue. Old SEO-preservation source commentary was corrected.

Focused Python rollback/removal/IAM checks: 11 passed. Public AI surface/route registration: 46 passed. TypeScript and full production export/build passed, including sitemap, blog search and llms generation. Independent page inventory: 36 public pages HTTP 200, 112 workspace shells HTTP 200, system 404 checked. Live sitemap: 1407 URLs, excluding 1376 blog post/pagination/topic URLs leaves 31 URLs. A successful page response does not establish checkout payment completion or protected-data authorization.

## Live probes after removal

| Path | Status | Location |
|---|---|---|
| [retired public path 74ea5c7a]/ | 404 |  |
| [retired public path 14041cbc]/ | 404 |  |
| [retired public path 32bc4583]/ | 404 |  |
| [retired public path 282d0fd5]/ | 404 |  |
| [retired public path b180810d]/ | 404 |  |
| [retired public path ef531503]/ | 404 |  |
| [retired public path 8a68a2cf]/ | 404 |  |
| [retired public path f1430fb7]/ | 404 |  |
| [retired public path 5b217199]/ | 404 |  |
| [retired public path 3b13e953]/ | 404 |  |
| /anew/ | 200 |  |
| /terms/ | 200 |  |
| /orders/ | 200 |  |
| /shop/ | 200 |  |
| /cart/ | 200 |  |
| /checkout/status/ | 200 |  |
| /api/ecommerce/checkout | 404 |  |
| /icons/shopping-bag.svg | 200 |  |
| /mcp | 405 |  |

## Rollback

The exact 146-rule pre-change snapshot is docs/execution/snapshots/amplify-custom-rules-before-owner-removal-20261001.json. To restore, first review the current live rules, then supply this snapshot's complete array to Amplify UpdateApp(customRules=...). Restoration would reintroduce owner-retired redirects and therefore requires a new owner instruction. Do not restore the old before-8.4 snapshot or replace unrelated app settings. Source rollback is limited to the files in this change.

## Change authority

A0_READ: AWS identity/GetApp, live HTTP probes, route/sitemap inventory. A1_LOCAL: provisioner, tests, canonical SEO references and audit artifacts. A3_PRODUCTION: owner-explicit removal of custom hosting redirects, with snapshot and exact preserved-rewrite checks. No secret value reads, provider sends, payment mutations or public-page deletions.
