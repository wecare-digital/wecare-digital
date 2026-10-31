# Customer order link generation — source and live-runtime audit

**Audited 2026-10-31 · Region: us-east-1 · Branch: `wecare.digital`**

## Decision

The single public customer destination is **`https://wecare.digital/orders/`**, for every
website, WhatsApp and RCS order and every home-menu Request action. No new public
per-order links of the form `/orders/?o=<order-number>` may be generated. The
authenticated history table expands a selected row; the one-use selector is kept in
the browser's `sessionStorage`, never inserted into a URL.

**Do not delete the incoming legacy `?o=` reader yet.** A previously sent WhatsApp
button or bookmarked link may still contain it. `src/lib/orderPage.ts` validates
that selector and `OrdersPage.tsx` removes it from the address bar; the customer
must sign in and backend ownership checks still apply. Removing the parser now
would break old paid buyers without preventing a single new outgoing link.

## Findings

| Surface | Source of truth | Current source contract |
|---|---|---|
| Checkout terminal status | `src/pages/checkout/status.tsx`, `src/lib/orderPage.ts` | `orderPagePath` returns `/orders/`; one-use session selection |
| Home Request menu and row actions | `src/components/Header.tsx`, `src/components/orders/OrderActionsMenu.tsx` | Six service actions go to `/orders/`; the originating row is stashed in one-use session storage |
| Invoice-paid WhatsApp CTA | `amplify/functions/payments/invoice-engine/handler.py` | `_send_order_page_link` sets `'url': _ORDER_PAGE_URL` with no order query string; public Order Number appears in message **text**, not the URL |
| WhatsApp verified customer command | `amplify/functions/messaging/whatsapp-business-api/flows/customer_commands.py` | `ORDERS_URL = 'https://wecare.digital/orders/'` |
| RCS order-update source template | `rcs/templates/source/wecare_order_update.json` | Body contains plain `https://wecare.digital/orders/`; order ID is a separate text variable |
| Single order detail | `src/components/orders/OrderDetail.tsx` | Authorized inline component, not a separate public route |
| Auth gate | `src/components/orders/OrdersPage.tsx`, `src/lib/safeReturnPath.ts` | `/auth?return=/orders/` after absent/expired customer session; return allowlisted |

A source search for literal `/orders/?o=` found historical docs and old
compatibility comments, not a current link creator. The older source code before
commit `ebcc95582c89bf4e79dec4a6afd25e85e05f56d2` did generate
`f'{_ORDER_PAGE_URL}?o={order_number}'`. That expression was changed to
`_ORDER_PAGE_URL` on **2026-10-31 at 03:41 UTC**. Its offline payment-rail verifier
already asserts the exact CTA URL and its place after the paid invoice.

### Critical runtime drift — production is still stale

A live AWS Lambda read on 2026-10-31 found:

- `wecare-invoice-engine:live` -> version **271**, deployed **2026-10-30
  07:27 UTC**, code SHA-256 (base64):
  `nZkkuqluHspXy87UPCdmTfnTzftvKrZiVi6YnipoevE=`.
- `wecare-invoice-engine:$LATEST` has the **same** code SHA and timestamp.
- The source fix `ebcc9558` was committed on **2026-10-31**. Therefore it is
  not part of either deployed Lambda code package. The old backend can still send
  the `?o=` URL until a new invoice-engine package is published and its `live`
  alias is moved.
- PR #2004 has already been merged (`3b59208`) and Amplify release #406 succeeded,
  but Amplify only publishes the **frontend**, not this invoice-engine Lambda.

**Do not call the customer-facing backend change live until the Lambda alias is
updated and its code SHA is verified.** A Git merge or an update of `$LATEST`
alone does not fix this.

## Safe backend release procedure

1. Use a **pinned, reviewed Git commit** containing the canonical URL change,
   in a clean checkout. Do not deploy the entire Lambda fleet or blindly use a
   concurrently moving `HEAD`.
2. Run the hermetic payment rail test in an isolated runner; it must pass the
   `LINK` assertion:
   `page_action.get("url") == "https://wecare.digital/orders/"`.
   Also run `pytest -q tests/test_orders_single_page_contract.py
   tests/test_canonical_customer_order_urls_20261031.py`.
3. From that exact reviewed tree, run
   `python scripts/deploy_all_lambdas.py wecare-invoice-engine --dry-run`.
   This must validate the single packaged Lambda, dependency layers and handler.
4. Record the old `live` version **271**, alias revision and package SHA as
   rollback evidence. Run the same script without `--dry-run` for
   **`wecare-invoice-engine` only**. The repository deployment script uses
   code/revision preconditions and `scripts/snapstart_publish.py` to publish
   the immutable version and move `live`; do not run bare
   `update-function-code` and assume the alias changed.
5. Verify `GetAlias` now points to a **new Active version** with the expected
   reviewed zip SHA, and that backend configuration/payment environment are
   unchanged. Perform a non-paying smoke/contract check; do **not** create a real
   order or send an unsolicited customer WhatsApp message.
6. If the validation fails, roll the `live` alias back to the recorded version
   using revision-protected conditional update, and reverify.
7. Existing messages already delivered through Meta/RCS cannot be edited or
   recalled by changing website/Lambda code. Legacy `?o=` links remain safe
   incoming aliases to the canonical history page.

## Scope boundaries

- Internal REST actions such as `/orders/{id}` and
  `/ecommerce/checkout/status` are authenticated **data endpoints**, not
  separate customer pages. Do not delete them.
- Invoice download URLs are short-lived, signed **file** links; do not rewrite
  them to `/orders/`.
- `/request-amendment/`, `/vault/`, and related service pages remain
  direct-access/legacy pages. They are not per-order URLs; the public navigation
  now enters them through the Orders hub.
- The Google translation **relay** and internal payment/WhatsApp relays are
  unrelated to customer order-detail URL generation. They were not removed.
- This audit verifies repository source and the Lambda alias metadata. It does
  not prove that every remotely approved RCS/Meta template or already-delivered
  message matches the repository. Those require separate provider readbacks.

## Regression guard

`tests/test_canonical_customer_order_urls_20261031.py` scans active `src/`
and `amplify/functions/` code for literal order-specific public URL creation,
checks backend WhatsApp CTA and RCS URLs, verifies menu/checkout destinations,
and preserves the legacy input sanitizer and ownership gate.

The original paid WhatsApp end-to-end test
(`scripts/verify_whatsapp_catalog_payment_rail.py`) continues to check the
actual captured outgoing `cta_url` payload: its URL must be the canonical
Orders history, not a link whose query contains a customer identifier.
