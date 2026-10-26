# WECARE customer connector — deployment review

Prepared 25 October 2026. This is a reviewable build, not an executed deployment or public listing.

Status, 26 October 2026: this review predates the deployment. The stack `wecare-customer-commerce-mcp`
(HTTP API `mtx59syrt6`) is deployed. Its v4 (`shopping-chatgpt-20261026-v4`) runs with
`WhatsAppPaymentsEnabled` `true`, the template default since `13f5ab6f4`.
`amplify/functions/ai/customer-commerce-mcp/README.md` has the current release steps.
Owner direction: conversation-only customer experience; WhatsApp template payment fallback;
all available listing countries; review/improve the build before publication.

## Proposed deployment

Target: existing WECARE AWS account 775261844268, us-east-1.
Suggested stack/function name: wecare-customer-commerce-mcp (new customer surface).
The reviewed template creates 17 resources: one dedicated customer HTTP API, seven explicit
protocol routes, one customer Lambda, one published version/live alias, one integration,
one execution role, two retained log groups, one throttled default stage and one invoke permission.
This separate API is the customer security boundary; it does not replace the staff API or public
content MCP, and creates no new database, Cognito pool/client, KMS key, S3 bucket or payment account.

Reuse:
- Existing customer Cognito pool and public CUSTOM_AUTH client, verified live through AWS Core.
- ProductsTable for current approved products and prices.
- CustomerSessionsTable with only mcp:commerce:* keys accessible to the new role.
- Existing customer-session KMS custody key with a separate fixed encryption context.
- Exact published checkout, customer-profile and customer-orders handlers for customer authority.
- Existing customer-registration :live only if that established service is restored and enabled.

The role cannot scan tables, read staff credentials or provider secrets, directly write contacts
or orders, capture payments, issue refunds, choose arbitrary upstream functions, or touch website
session keys. Request logs exclude query strings, bodies and credentials. The API is throttled.

## Default deployment behavior

- No product is published: ApprovedProductIds defaults to [].
- WhatsApp payment messages are disabled.
- New-account registration is disabled until the established service is restored and verified.
- OAuth clients default empty; only explicitly configured exact HTTPS callbacks are accepted.
- Native ChatGPT payment collection remains unavailable.

Thus deploying the default build is for host connection setup, not a launch announcement.
Exact ChatGPT and Claude callback URIs must come from their actual connection configuration;
none are guessed or hardcoded into this release. No existing website or provider credentials
are copied into either host. The adapter issues its own opaque resource-bound tokens and keeps
Cognito access/refresh custody encrypted in the existing session store.

## Verification completed

- 25 conversation-tool contract checks and 22 OAuth/security checks against readable source.
- The same 47 checks pass against the exact single-file packaged Lambda runtime.
- Python compilation passes.
- Package assembly compares Python ASTs to prove whitespace compaction changes no semantics.
- Runtime ZIP is deterministic and contains only index.py.
- AWS CloudFormation ValidateTemplate succeeded for the exact full generated template.
  It returned CAPABILITY_IAM and all eight expected parameters. No stack/change set was created.
- The template is under the 51,200-byte inline limit; the builder refuses a larger template.
- Existing website production build passed earlier; no website source is modified by this release.
- Existing repository-wide lint remains blocked by the unrelated /cart anchor in
  src/components/ElsewhereTravelAssistant.tsx:462. It is unchanged from HEAD.

These checks do not prove live host OAuth, actual KMS/IAM access, Meta delivery or real purchases.
All of those require the controlled deployment and live checks below.

## Activation sequence

1. Review and authorize this exact AWS deployment; create a CloudFormation change set first.
2. Bump DeploymentRevision on every code or configuration update so the live alias receives
   a new published version. Execute only the reviewed change set, then verify the actual endpoint, version, role, routes,
   discovery documents, initial tools/list and fail-closed defaults.
3. Create the development customer connection in ChatGPT and Claude. Configure the actual public
   client IDs and exact callback URIs with PKCE and token endpoint authentication method none.
4. Verify dedicated customer sign-in, expired/revoked sessions, denied staff tokens, read/write
   scopes, two-customer isolation, address save and order reads. Restore the existing registration
   service before enabling new-account creation and test its two-code sequence.
5. Select only platform-approved product IDs and recheck price/stock from ProductsTable.
6. Verify the live approved WhatsApp payment template, sender and merchant binding, then enable
   request sending for a controlled test customer. Check failure/retry/idempotency and exactly
   one paid order after provider verification. Never use a template send as payment proof.
7. Finish the public listing: verified publisher, plugin-specific documentation URL, policy
   coverage confirmation, dedicated reviewer access and a real host demo recording.
8. Execute the five positive and three negative host review cases, preserving evidence and
   keeping reviewer credentials exclusively in the secure portal fields.
9. Submit to OpenAI and Anthropic through their supported portals. Review and approval are external;
   submission does not mean approval or publication. Global listing does not imply global shipping.

## Publication preparation status

The listing draft uses WECARE branding and a real 256 x 256 PNG icon. publication.countries is []
to deliberately remove listing-country restrictions, per the owner's 'any country' instruction.
The support, privacy and terms pages were opened and identify WECARE; policy coverage of this
specific integration still needs owner confirmation. The homepage identifies the publisher but
is not treated as complete plugin-specific documentation. All host review cases are NOT RUN.
No demo recording, reviewer login, verified publisher selection or public MCP URL is fabricated.
A public-upload ZIP cannot be finalized until its real MCP endpoint exists; current archives are
source/runtime/deployment artifacts, not submission-ready plugins.
