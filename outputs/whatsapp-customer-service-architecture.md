# WhatsApp customer service architecture — current checkpoint, 9 October 2026

Status: **PARTIALLY COMPLETE**. This is a hybrid destination architecture with explicit implementation boundaries. Audit baseline: d03ac81dfda8d1a5da461f01b4005559b2a3ada4; Business API diagnostic repair subsequently deployed as live89. Nine scoped Lambdas and seven financial/service tables were inspected. This does not certify the whole AWS account.

## Current implementation and safe customer entry

Reuse Orders draft **2167802357142172** rather than create another overlapping hub. It contains eight screens, profile summary, owned order pagination/detail, missing-order help and existing-invoice copy actions. Meta reports DRAFT and zero validation errors. It is not a published, fully routed customer-service hub. Submit Request **1107164111921876** and Review **1578178897413815** are PUBLISHED. Amendment, Drop Docs and Shipments design/legacy drafts remain drafts. Vault requires no separate Flow.

Trusted inbound sender/contact starts an expiring opaque session. Each action rechecks the permanent verified Cognito owner and trusted phone association. Customer-visible UUID is distinct from permanent Cognito sub; caller-selected phone, UUID or order number is never ownership proof. QA contact for +918100640044 currently lacks checkoutCustomerId and customerUuid. Repair through supported account verification, never by fabricating identifiers or matching a recreated contact on phone alone.

Profile summary exposes only the requested minimum. Name/address edits use current-owner conditional writes; phone and UUID remain immutable. Email verification and complex/sensitive recovery retain secure website fallback. Account summary is not permission to broadcast full addresses in ordinary chat.

```mermaid
flowchart TD
  Entry[Keyword / approved template / website WhatsApp link] --> Identity[Verify permanent owner and trusted sender]
  Identity --> Hub[Existing Orders draft / contextual customer service]
  Hub --> Orders[Owned canonical orders, 10 per page]
  Orders --> Detail[Re-read selected owned order]
  Detail --> Invoice[Resolve existing invoice and private asset]
  Detail --> Context[Owned original order A]
  Context --> Quote[Service eligibility and frozen server quote]
  Quote --> Payment[Separate order-details payment message / attempt P]
  Payment --> Verify[Independent verified settlement]
  Verify --> ServiceOrder[Create or reuse paid service order B]
  ServiceOrder --> Writeback[Idempotent Wix writeback]
  Writeback --> Request[Service request R / owned file grant]
  Request --> Delivery[Receipt / document / continuation]
  Delivery --> Review[Deduplicated completed-service review]
  Hub --> Missing[Order not found: verification queue, no charge]
  Hub --> Web[Secure authenticated web fallback]
```

The lower paid-service sequence is the release contract, not a claim that every native step is complete. Native-service, Wix writeback and dynamic Vault flags remain unset/off; Drop Docs attachment flag is false. Payment configuration is active on both WABAs; activation is separate from completed fulfillment.

## Canonical ownership and record model

| Record | Authority / role | Customer presentation |
|---|---|---|
| Permanent owner | Verified Cognito sub plus trusted contact binding | Public Customer UUID, never internal sub |
| A: original order | Singular OrderTable, customer-owned | Existing public order number |
| B: service purchase | New paid service order after independently confirmed payment | Separate website-style public order number |
| P: attempt / provider reference | PaymentAttemptsTable, frozen price and stable reference | Current pending/paid/recovery state |
| R: request | ServiceRequestsTable or FlowSubmission verification intake | Request number/status concerning A, linked to B/P |
| Wix mapping | WixOrderIds and canonical external-order completion fields | Wix IDs stay internal |
| Invoice | InvoicesTable / InvoiceAssetsTable existing financial identity | Receipt/invoice copy, no new financial invoice |
| File / grant | Secure-files record, permanent owner and paid entitlement | Authorized download/document delivery |

A missing or ambiguous A must not be replaced with B. Missing-order intake saves a verification item with public customer UUID and explicit awaiting_order_verification status/tags, without a charge. Service-specific projection and native action binding still need completion. Contact deletion/recreation must not transfer old order/file ownership to a new permanent account; guarded history/reconciliation remains authoritative.

## Services, keywords and release boundaries

| Entry | Price source | Current native status | Required next work |
|---|---|---|---|
| Orders / Customer ID | Utility | Owned text routing and Orders draft adapter exist | Verified QA identity, draft route/publish readiness, contextual actions |
| Submit Request | Wix variant ₹99 | Published paid-detail Flow; native orchestration gated | Verified A/B/P/R, terminal retry/resume, writeback and actual QA |
| Request Amendment | Wix variant ₹99 | Drafts exist | Eligibility/target binding and paid continuation contract |
| Drop Docs | Wix variant ₹350 | Drafts; encrypted picker and attachment gate closed | Validate account picker protocol; decrypt/register owned private media and CRM projection |
| Vault | Wix variant ₹49 | Secure ownership/payment/grant primitives; repayment guard deployed | Native selection, enabled safe writeback/delivery, actual paid QA |
| Shipments | No paid SKU invented | Utility design draft | Owned tracking contract and QA |
| Leave Review | Utility | Published review Flow / approved template | Verify automatic milestone and duplicate suppression in real journey |

Keywords are entry points into verified server state, not proof of ownership/payment. Website buttons may send a keyword into WhatsApp; such a link does not directly bypass the message-routing/session process to launch a native Flow. Preserve existing working review entry and website routes.

## Files, images and delivery

Six 4096px catalog artworks use the existing bucket **wecare-digital-get** under **o/catalog/services/{slug}/v1/image-4096.png** (letter o). Slugs: submit-request, request-amendment, drop-docs, vault, shipments, leave-review. The four paid Wix variants propose these artwork URLs; utility actions have no invented price.

Private incoming media is under secure/u/whatsapp/incoming/; service material under secure/u/service-requests/ and secure/u/dropdocs/; delivery under secure/d/. Existing invoice assets use secure/stack/invoices/wecare-digital-&lt;reference&gt;.png. Customer uploads must be decrypted, validated, registered against owner/order/request and tagged before staff use. The current encrypted picker contract is not certified, so keep attachment activation closed. Never put customer documents under public artwork folders.

Bucket uses private OAC access; deployed origin-response edge function rejects secure/ prefix. A real private-key metadata-based anonymous probe returned302 to homepage and did not serve the object. OAC bucket policy alone does not prove viewer privacy; preserve the edge guard. Signed URLs are temporary bearer grants, not permanent identity.

Existing-invoice copy rechecks selected owned order → reference → single authoritative invoice → private IMAGE asset; sends only to the server-derived verified recipient using the approved template. Conditional per-customer/order/UTC-day claim prevents repeat sends. Accepted send is not delivery proof. No invoice generation, new GST number, capture/refund or customer send occurred in this audit.

## Catalog automation and deployment

Fresh catalog **1457045652952851** has zero current items; sync live7 can read it and proposes four Wix variants with no blocks and applied0. Sync remains disabled/dry-run/out-of-stock. Build a durable per-revision proposal/approval/apply/readback queue; do not mistake read-only proposals for approved applied products. Both-WABA attachment and dataset connection remain live verification work. Dataset **4554612361454941** is the only intended new dataset; configured source is not proof of delivered/matched events. Do not emit synthetic Purchase to hide warnings.

Scoped deployment: Business API89, secure-files34, service-requests5, catalog-sync7, checkout41, profile10, orders7, inbound92, messages-read29. Preserve concurrent newer work and compare revision/hash before every change. Immediate diagnostic rollback is89→88 with a fresh alias revision. No provider payment settings, published Flow content, financial records or release flags were changed here.
