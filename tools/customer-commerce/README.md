# WECARE conversation-only customer commerce connector

The customer uses the ChatGPT or Claude conversation. There is no separate shopping website,
HTML resource, embedded storefront, custom graphical app, product artwork or homepage.
The owner explicitly corrected the first visual implementation to require in-app chat only.
That graphical implementation and its preview server were removed, not hidden behind a flag.
The WECARE logo belongs to the plugin listing/identity, not a new shopping website header.

## Implemented conversation tools

- `browse_products`: plain structured/text results for explicitly approved purchasable products.
- `review_purchase`: catalog-priced items estimate; never calls an estimate a final payable total.
- `get_my_account`: connected customer profile, delegated to existing checkout identity checks.
- `update_my_account`: customer-confirmed profile/address changes, delegated to customer-profile.
- `list_my_orders`: connected customer history using the existing customer-orders handler.
- `check_my_payment`: verified payment state from the existing checkout service.
- `continue_in_whatsapp`: canonical Orders, Submit Request or Leave Review conversation entry;
  no automatic message send. The WhatsApp backend retains form rendering and Flow table storage.
- `request_whatsapp_payment`: absent by default. With explicit release activation, delegates
  the approved basket to existing checkout `create`, with a stable idempotency key. No caller
  phone number, customer identity, client price or arbitrary Lambda target is accepted.

Private tools use the host's account connection and the customer bearer token in the HTTP
Authorization header. Tokens, passwords and authentication OTPs are not tool arguments.
Existing customer handlers verify the customer issuer, token validity and resource ownership.
The source does not grant a staff identity customer authority or expose the staff gateway.

## Run verification

From the existing repository root:

```sh
python3 tools/customer-commerce/verify.py
python3 -m compileall -q amplify/functions/ecommerce/customer-commerce-mcp
```

Checks use stubs and synthetic input only. No customer messages, credentials or payments are
used. They cover no-UI behavior, exact schemas, deny-by-default product approval, money/stock
integrity, account connection challenges, identity injection, downstream refusal, provider-error
redaction, native payment gating and optional WhatsApp request idempotency payloads.

## Existing source of truth

Products/prices remain in ProductsTable. Customer identity/profile/address remain in the existing
customer authentication system and ContactsTable. Payment attempts, confirmed money and orders
remain in their existing shared tables. WhatsApp Flows remain in WhatsApp and write their current
FlowSubmissionTable/draft/log records. No replacement commerce or customer database is created.

## Runtime configuration

Package the single handler.py as the Lambda entrypoint. Runtime boto3 comes from Lambda.

- `CUSTOMER_COMMERCE_ORIGIN`: the actual reviewed HTTPS MCP origin. No invented live endpoint.
- `CHATGPT_APPROVED_PRODUCT_IDS`: JSON array of explicitly approved IDs; defaults `[]`, maximum 50.
  Each approved row still requires active status, valid INR integer pricing, verified stock metadata
  and available tracked inventory. Product names alone never establish platform eligibility.
- `PRODUCTS_TABLE`: defaults to the existing stack-wecare-digital-ProductsTable.
- `CUSTOMER_AUTHORIZATION_SERVER`: actual customer OAuth authorization-server issuer verified
  during host connection setup. Unconfigured discovery returns ACCOUNT_CONNECTION_NOT_CONFIGURED;
  the source does not invent an authorization server or claim that existing CUSTOM_AUTH is OAuth.
- `WHATSAPP_PAYMENT_REQUESTS_ENABLED`: defaults disabled. Enable only after template, live sender,
  merchant binding, customer ownership, published product approval and explicit send-intent checks.

Expose POST `/mcp` and GET `/.well-known/oauth-protected-resource` using the existing AWS
infrastructure workflow. Apply bounded API Gateway throttles before public exposure.
The role needs only ProductsTable GetItem and InvokeFunction on exact existing :live aliases:
wecare-checkout, wecare-customer-profile and wecare-customer-orders, plus logs. It needs no staff,
Secrets Manager, direct contact/order write, database scan, payment capture or refund permission.
Original gateway source IP is preserved during handler delegation.

## Remaining live activation gates

1. Production MCP routing, least-privilege role, throttles and approved product IDs are not deployed.
2. Complete and test ChatGPT/Claude customer OAuth linking with the existing customer identity system.
   Existing WhatsApp CUSTOM_AUTH sign-in is not itself proof of a compatible host OAuth flow.
   Registration source exists, but the live API audit on 2026-10-25 found no customer-registration
   route. Resolve that established service before promising new-account creation.
3. Razorpay for ChatGPT Apps onboarding and product eligibility remain unconfirmed. This source
   does not embed Razorpay.js, fabricate delegated-payment tokens, capture funds or claim that
   ChatGPT's payment sheet is activated. Native charge completion is intentionally not a tool.
4. Verify real tools in both hosts, including expired/revoked/cross-customer tokens, address updates,
   payment failure/retry/duplicate callback and exactly one paid purchase in the shared OrderTable.
5. Register the actual remote endpoint and finish publisher/reviewer materials and directory review.

This directory is a source implementation, not an installed plugin or a submission-ready public
archive. A source export must not contain a made-up mcp.json URL or reuse the privileged internal
WECARE plugin's staff connections. The customer connector is a separate public product surface.

## Latest verification

23 focused offline checks pass. Python compilation passes. The repository production website build
passed with network access; the first sandboxed attempt could not fetch public blog data. No website
source changes remain in this task. Repository-wide lint has one existing unrelated error in
src/components/ElsewhereTravelAssistant.tsx:462 (an internal /cart anchor), plus existing warnings.
No lint rules or build gates were disabled and that unrelated source was not edited.
