# Live link and subdomain audit - 2026-10-02

Checked 2026-10-02T09:28:57.008869+05:30 (Asia/Kolkata). Read-only audit; no DNS, redirect, certificate, page or provider configuration changed.

AWS account 775261844268, us-east-1. Amplify latest build 1215 succeeded for commit 863c6ebd. Route 53 public zone has 32 records, zero exact www.wecare.digital records. Existing wildcard A/AAAA records remain.

## Results

- All 33 non-blog sitemap URLs and five additional customer pages returned HTTP 200: 38 page URLs total.
- All 34 distinct non-blog internal navigation targets found in live HTML resolved successfully. The /r/wa target is a short-link flow, not a content page. No public workspace navigation link was found.
- The sitemap contains 1409 URLs; 1376 blog post/pagination/topic URLs were excluded from this audit, following the owner request to omit repeated blog links.
- /checkout/ and /sign-in/ are diagnostic unknown paths and return 404. The real customer sign-in route is /account/sign-in/; current checkout pages are /checkout/status/ and /checkout/success/. These diagnostic 404s are not broken links advertised by public navigation.
- [retired public path ef531503]/ and [retired public path ef531503]/nested/ redirect home with the fixed from=access parameter. Other sampled retired routes return 404 with the home-navigation document. HTTP checks do not execute its JavaScript; router.replace home behavior was confirmed from source, not a browser run.
- The public MCP endpoint returns 405 to GET by design. It is not a missing content page.
- MTA-STS policy at https://mta-sts.wecare.digital/.well-known/mta-sts.txt returns 200; the host root returns 403. The policy should remain on its dedicated email hostname.

## Findings requiring attention

1. Unknown single-segment API path /api/definitely-no-route returns 302 to /contact/ and then HTML 200. Unknown multi-segment /api/definitely/no/route correctly returns JSON 404. API clients may mistake the HTML response for successful API data.
2. The deleted www DNS record has not reappeared. Amplify still lists www in its domain association and retains the www-to-apex 301 rule. Current live www/shop/ preserves the path and reaches /shop/. DNS removal and application/CDN hostname configuration are separate layers; no hostname association was removed in this audit.
3. Nested a.b.wecare.digital resolves through wildcard DNS but fails TLS certificate verification. Existing certificate covers one-label wildcard hosts. No new certificate was requested, per owner instruction.
4. Live version 59 environment WIX_SITE_URL on wecare-whatsapp-business-api still names https://www.wecare.digital. A canonical-apex source update would remove this stale hostname dependence; its consumer should be checked before changing it.
5. orders.py:303 passes https://admin.wecare.digital as an Origin in an internal Lambda invocation. This is an internal header value, not a browser destination. It deserves review against the receiving function authentication/CORS contract.
6. Most old api/app/store/r host mentions in source are comments or historical documentation, not active URL literals. Python AST scan found one short obsolete-host literal: the internal admin Origin above. Do not treat every text match as an active broken callback.
7. sg.wecare.digital is an email tracking CNAME; the HTTPS probe did not resolve its terminal address. Its provider ownership and current email use need a separate check. sip.wecare.digital refuses HTTPS on port 443; that does not prove the SIP protocol service is unhealthy. default._bimi is a TXT email-authentication label, not an HTTPS site.

## Current public page URLs

| URL | HTTP |
|---|---|
| https://wecare.digital/ | 200 |
| https://wecare.digital/anew/ | 200 |
| https://wecare.digital/bharat-rx/ | 200 |
| https://wecare.digital/blog/ | 200 |
| https://wecare.digital/clear-closure/ | 200 |
| https://wecare.digital/contact/ | 200 |
| https://wecare.digital/dastavez/ | 200 |
| https://wecare.digital/drop-docs/ | 200 |
| https://wecare.digital/elsewhere/ | 200 |
| https://wecare.digital/expo-week/ | 200 |
| https://wecare.digital/grahak-os/ | 200 |
| https://wecare.digital/hunar/ | 200 |
| https://wecare.digital/leave-review/ | 200 |
| https://wecare.digital/niji-setu/ | 200 |
| https://wecare.digital/orders/ | 200 |
| https://wecare.digital/perks/ | 200 |
| https://wecare.digital/privacy/ | 200 |
| https://wecare.digital/refer-and-earn/ | 200 |
| https://wecare.digital/request-amendment/ | 200 |
| https://wecare.digital/ritual-guru/ | 200 |
| https://wecare.digital/shop/ | 200 |
| https://wecare.digital/shop/file-assist/ | 200 |
| https://wecare.digital/shop/guided-resolution/ | 200 |
| https://wecare.digital/shop/kiosk/ | 200 |
| https://wecare.digital/shop/merchandise/ | 200 |
| https://wecare.digital/shop/paperwork/ | 200 |
| https://wecare.digital/shop/referral-partner/ | 200 |
| https://wecare.digital/shop/viveka/ | 200 |
| https://wecare.digital/submit-request/ | 200 |
| https://wecare.digital/terms/ | 200 |
| https://wecare.digital/vault/ | 200 |
| https://wecare.digital/vayulok/ | 200 |
| https://wecare.digital/zip/ | 200 |
| https://wecare.digital/cart/ | 200 |
| https://wecare.digital/account/sign-in/ | 200 |
| https://wecare.digital/checkout/status/ | 200 |
| https://wecare.digital/checkout/success/ | 200 |
| https://wecare.digital/get/ | 200 |

## Host probes

| URL | Terminal result |
|---|---|
| http://wecare.digital/ | https://wecare.digital/ |
| https://a.b.wecare.digital/ | HTTP 0 / SSLCertVerificationError |
| https://admin.wecare.digital/ | https://wecare.digital/ |
| https://api.wecare.digital/ | https://wecare.digital/ |
| https://app.wecare.digital/ | https://wecare.digital/ |
| https://auth.wecare.digital/ | https://wecare.digital/ |
| https://checkout.wecare.digital/ | https://wecare.digital/ |
| https://default._bimi.wecare.digital/ | HTTP 0 / gaierror |
| https://link-audit-unknown.wecare.digital/ | https://wecare.digital/ |
| https://link-audit-unknown.wecare.digital/old/path?old=1 | https://wecare.digital/ |
| https://mta-sts.wecare.digital/ | HTTP 403 / no redirect |
| https://r.wecare.digital/ | https://wecare.digital/ |
| https://selfcare.wecare.digital/ | https://wecare.digital/ |
| https://customerservice.wecare.digital/ | https://wecare.digital/ |
| https://sg.wecare.digital/ | HTTP 0 / gaierror |
| https://shop.wecare.digital/ | https://wecare.digital/ |
| https://shop.wecare.digital/old/path?old=1 | https://wecare.digital/ |
| https://signin.wecare.digital/ | https://wecare.digital/ |
| https://sip.wecare.digital/ | HTTP 0 / ConnectionRefusedError |
| https://retired-legacy-host.invalid/ | https://wecare.digital/ |
| https://store.wecare.digital/ | https://wecare.digital/ |
| https://workspace.wecare.digital/ | https://wecare.digital/ |
| https://www.wecare.digital/ | https://wecare.digital/ |
| https://www.wecare.digital/shop/ | https://wecare.digital/shop/ |
| https://www.xout.wecare.digital/ | https://wecare.digital/ |
| https://xout.wecare.digital/ | https://wecare.digital/ |
| https://zzz-not-a-host.wecare.digital/ | https://wecare.digital/ |

## Retired path probes

| URL | Result |
|---|---|
| [retired public path 4de4916f]/ | 200 - https://wecare.digital/?from=access |
| [retired public path 4de4916f]/nested/ | 200 - https://wecare.digital/?from=access |
| [retired public path 7fe2c71b]/ | 404 - [retired public path 7fe2c71b]/ |
| [retired public path 90a0ef7a]/ | 404 - [retired public path 90a0ef7a]/ |
| [retired public path 5213f24c]/ | 404 - [retired public path 5213f24c]/ |
| https://wecare.digital/definitely-not-a-page/ | 404 - https://wecare.digital/definitely-not-a-page/ |
| [retired public path ef456375]/ | 404 - [retired public path ef456375]/ |
| [retired public path 2ede3fd1]/ | 404 - [retired public path 2ede3fd1]/ |
| [retired public path 69a623a8]/ | 404 - [retired public path 69a623a8]/ |
| https://wecare.digital/llm/ | 404 - https://wecare.digital/llm/ |
| [retired public path 2531611c]/ | 404 - [retired public path 2531611c]/ |
| [retired public path f977c0cb]/ | 404 - [retired public path f977c0cb]/ |
| https://wecare.digital/partners/ | 404 - https://wecare.digital/partners/ |
| [retired public path f517c20b]/ | 404 - [retired public path f517c20b]/ |
| [retired public path 583fa2cc]/ | 404 - [retired public path 583fa2cc]/ |
| [retired public path 68ca05fc]/ | 404 - [retired public path 68ca05fc]/ |
| [retired public path c83b940f]/ | 404 - [retired public path c83b940f]/ |
| [retired public path 049c189c]/ | 404 - [retired public path 049c189c]/ |
| [retired public path b93c9470]/ | 404 - [retired public path b93c9470]/ |

## Scope limits

Checks establish document delivery, redirect chains and HTML navigation. They do not establish WhatsApp OTP delivery, payment capture, receipt authorization, authenticated dashboard operations, or every client-rendered/dynamic link. No OTP, message, call, payment mutation or OAuth callback replay was performed. Arbitrary possible hostnames cannot be enumerated; Route 53 records, repository-discovered hosts and representative wildcard/nested names were checked. DNS email-validation records were inventoried but are not website pages.

## Complete Route 53 record-name inventory

| Name | Type |
|---|---|
| wecare.digital. | A |
| wecare.digital. | AAAA |
| wecare.digital. | MX |
| wecare.digital. | NS |
| wecare.digital. | SOA |
| wecare.digital. | TXT |
| 4a86798516fdfe9b3c019d1d34dff6ac.wecare.digital. | CNAME |
| *.wecare.digital. | A |
| *.wecare.digital. | AAAA |
| _a6bab3f26842aff9ed68562dfbb31b1b.wecare.digital. | CNAME |
| _amazonses.wecare.digital. | TXT |
| default._bimi.wecare.digital. | TXT |
| _dmarc.wecare.digital. | TXT |
| cv4zuam4avmurrtes4etpikvkkbkxect._domainkey.wecare.digital. | CNAME |
| google._domainkey.wecare.digital. | TXT |
| mopqbzjxtouvnrv23lnfspfxxt2kiqpa._domainkey.wecare.digital. | CNAME |
| s1._domainkey.wecare.digital. | CNAME |
| s2._domainkey.wecare.digital. | CNAME |
| sel1._domainkey.wecare.digital. | CNAME |
| v5w4wexbfyum54omlfe7l6ayada7j2nq._domainkey.wecare.digital. | CNAME |
| _mta-sts.wecare.digital. | TXT |
| _smtp._tls.wecare.digital. | TXT |
| bvn6u42phnxv.wecare.digital. | CNAME |
| mta-sts.wecare.digital. | A |
| mta-sts.wecare.digital. | AAAA |
| _ad87a8bb607afbdecf8beca0dd280a55.mta-sts.wecare.digital. | CNAME |
| qu75cp2vx25y.wecare.digital. | CNAME |
| sg.wecare.digital. | CNAME |
| sip.wecare.digital. | A |
| xout.wecare.digital. | A |
| xout.wecare.digital. | AAAA |
| www.xout.wecare.digital. | CNAME |
