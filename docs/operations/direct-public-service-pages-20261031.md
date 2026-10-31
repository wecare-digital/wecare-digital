# Public service URLs: direct pages, not Orders redirects
31 October 2026 · release plan and rollback contract

## Approved public destinations

| Header/Orders menu action | Direct public route | Customer action after page load |
| --- | --- | --- |
| Submit Request | https://wecare.digital/submit-request/ | Explicit approved WhatsApp Submit Request entry |
| Request Amendment | https://wecare.digital/request-amendment/ | Explicit approved WhatsApp amendment entry |
| Drop Docs | https://wecare.digital/drop-docs/ | Explicit approved WhatsApp document entry |
| Vault | https://wecare.digital/vault/ | Public explanation; explicit Vault WhatsApp entry |
| Shipments → Track | https://wecare.digital/shipments/track/ | Explicit approved shipment tracking entry |
| Shipments → Pickup Request | https://wecare.digital/request-pickup/ | Explicit approved pickup entry |
| Leave Review | https://wecare.digital/leave-review/ | Explicit approved WhatsApp review entry |
| Subscribe | https://wecare.digital/subscribe/ | Explicit approved Subscribe entry |

Each **landing page** must serve public HTML at its own URL without an HTTP or
client-side automatic redirect to /orders/, /auth/ or Home. The user chooses to
open WhatsApp; no payment or template is triggered merely by visiting a public
page. All existing authentication/payment/owner checks remain server-owned.

**Only one special Vault exception is deliberate:** `/vault/?file=<fileId>` is
the existing customer-only exact-file route. It may send unauthenticated users
to /auth/ and can mint a private download URL only after verifying identity,
file ownership, recorded captured payment and the paid access window.
Unknown, invalid or revoked file IDs keep the 404 → homepage fallback.
Bare /vault/ never redirects; this *supersedes* the earlier bare-route homepage
fallback now that the owner wants a direct public Vault page.

Existing authenticated **per-order** Review and Subscribe actions in the Orders
action menu still send only after a deliberate click. Header navigation never
silently queues such actions. Copied page URLs and page reloads cannot send.

## Release order — production-safe two-phase cutover

1. **Review the PR and run tests:** `npm run typecheck`,
   `npm run build`, the public-route regression test and all Vault/auth/WhatsApp
   idempotency tests. Verify the Next.js static export has each
   `out/<route>/index.html` with the correct self-canonical and expected content.
2. **Deploy the new static pages** through Amplify build/release. Keep all
   existing redirect rules while the new files are being published. Test the
   exported `/<route>/index.html` URLs against the production domain; the old
   direct `/<route>/` paths still 301 to Orders until the next step.
3. **Only after the eight exported assets return HTTP 200**, apply the
   code-controlled redirect update:
   `python scripts/provision_legacy_redirects.py --apply`.
   Its release gate checks the page assets itself, snapshots the old rules and
   preserves the current 200 API/media rewrites and terminal 404 fallback.
   This removes ten old service redirect rules (bare and slash variants of
   five routes). The historical `/shop/shipments-track` alias remains a 301,
   but now points straight to `/shipments/track/`, not Orders. All twelve
   approved blog-merge 301s remain.
4. Verify `python scripts/provision_legacy_redirects.py --verify` and
   `python scripts/probe_url_host_matrix.py --only public` return direct 200.
   Check clean browser + no-cache HTTP requests: old 301 responses may be
   cached by browsers. Validate both slash spellings, share metadata and
   mobile header search. Ensure private `?file=` WhatsApp links still require
   login, paid entitlement and ownership; an invalid link must not become an
   anonymous public file page.
5. The public-page catalogue was updated in
   `config/public-pages.json`; the separate MCP deployment must include
   that generated catalogue if its live listing is expected to change.
   Verify approved WhatsApp short links separately; there is no new template
   or Flow approval in this PR.

## Rollback

- If the new static pages fail after deployment, **restore the exact Amplify
  customRules JSON snapshot saved by the provisioning script**, returning old
  routes to Orders until the website issue is corrected. Keep API/file/404
  rules byte-for-byte unchanged.
- If a WhatsApp entry fails, roll back its **page/menu navigation** only after
  checking the server-side customer guard; do not create a second payment rail.
- Never install any 301/302 rule on `/vault/`. Amplify path-only redirects
  cannot distinguish `/vault/?file=<fileId>` and would break approved
  customer download buttons.

No live hosting rules should be mutated by merging the PR alone. Production
deployment, customer-facing route checks and any IaC drift reconciliation are
separate release actions.
