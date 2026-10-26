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

Private tools use the host's OAuth connection with opaque, resource-bound tokens. The new
customer_oauth.py adapter wraps the existing WhatsApp Cognito CUSTOM_AUTH client without changing
it. Codes and refresh tokens are one-use; KMS-encrypted custody stays in the existing session table
under an isolated key prefix. Existing customer handlers still verify issuer, token validity and
resource ownership. Tokens, passwords and authentication OTPs are not tool arguments. A minimal
secure authorization form is the connection step only, not a shopping website or graphical app.
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

## Payment fallback messages

When native ChatGPT payment is unavailable and the WhatsApp route is activated, purchase review
returns a Pay on WhatsApp choice. The customer must choose it before the payment template is sent.
Only PAYMENT_REQUEST_SENT produces the message that the request was sent and the customer should
complete the transaction in WhatsApp, then return to check status. A prepared or disabled initiation
never claims a message was sent. Sending a payment request never claims that money was collected.

## Existing source of truth

Products/prices remain in ProductsTable. Customer identity/profile/address remain in the existing
customer authentication system and ContactsTable. Payment attempts, confirmed money and orders
remain in their existing shared tables. WhatsApp Flows remain in WhatsApp and write their current
FlowSubmissionTable/draft/log records. No replacement commerce or customer database is created.

## Build and release

```sh
python3 tools/customer-commerce/verify.py
python3 tools/customer-commerce/verify_oauth.py
python3 tools/customer-commerce/prepare_release.py --output /absolute/review/output
python3 tools/customer-commerce/verify_release.py /absolute/review/output/index.py
```

The release builder produces a deterministic runtime ZIP, source-verified single-file handler,
and a complete CloudFormation deployment template using existing state and provider resources.
It performs no upload, deployment, send or publication. The generated template has safe defaults:
no approved products, no registered OAuth clients, no registration sends, no payment messages.
It never fabricates a live endpoint or host callback URI. Read DEPLOYMENT-REVIEW.md before release.

Configuration is carried by the deployment template's eight reviewed parameters. Only the exact
customer OAuth client IDs/callbacks and approved product IDs are selected at activation time.
Existing source resources are defaults, not proof of permission. No provider secret or new Cognito
client is needed by the adapter. New-account creation delegates to the established registration
function only after that service is restored and the release flag enabled.

The listing draft targets all available countries at the owner's request. Indian delivery/address
and INR payment rules remain enforced by the underlying commerce services. Global visibility is
not a claim of worldwide shipping. Countries [], in the publication draft, deliberately removes
listing restrictions; it does not change customer, product or provider eligibility.

## Verification and remaining gates

25 conversation checks plus 24 OAuth checks pass against readable source. The same 49 checks pass
against the exact packaged runtime. Python compilation and CloudFormation ValidateTemplate pass.
No production deployment or live host case has run. The unchanged website build passed earlier;
repository-wide lint still has the existing unrelated internal /cart anchor error at
src/components/ElsewhereTravelAssistant.tsx:462.

Before public release: reviewed deployment, actual host callbacks, live customer/KMS/IAM checks,
restored registration, approved products, provider template/merchant verification, controlled
transaction, verified publisher, plugin documentation, policy confirmation, real host recording,
dedicated secure reviewer access, host test evidence and directory approval. Native ChatGPT charging
is not enabled; WhatsApp is the prepared payment fallback after explicit customer request.

The source export and runtime ZIP are not installable or submission-ready public plugins.
