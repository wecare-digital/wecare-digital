# MCP connection verification and persistence - 2026-10-07

Base: 88f1a087e2e5e876ee3b100522b496142d5b0839, stack.
Account: 775261844268; region us-east-1; runtime live version 10.

A0_READ: all eleven providers checked through the owner's signed-in dashboard.
AWS, GitHub, Wix, Razorpay, Google Cloud and Google Ads passed account reads.
Google access tokens renewed automatically. Plivo and Sinch passed documentation
discovery only. Meta Social, WhatsApp and Meta Ads returned remote HTTP 401
authorization challenges. No permission expansion or new provider credential was
performed. Those grants remain unverified for their remote MCP endpoints.

Registry metadata confirms saved connections have no DynamoDB ttl attribute; the
table expires only one-use OAuth flow rows. Cognito subject and IAM principal,
rather than browser sessions, select isolated connection namespaces. Signing out
does not delete authorizations. Revocation/provider token limits still apply.

A1_LOCAL: preserve verification on automatic renewal, persist a non-sensitive
refresh-capability flag, distinguish renewal checks from lost consent, clarify
account persistence, add per-provider failures and View data links to Playground.
Tests cover stable account scoping, no credential TTL, lease-conditional renewal
and provider selection. No credential values were retrieved or logged.

A2_REMOTE_CODE: changes published on codex/mcp-persistence-20261007 as draft PR #241
(https://github.com/wecare-digital/wecare-digital/pull/241).
Initial publication was rejected while broader release gates were not green.
The owner explicitly authorized publishing on a separate branch on 2026-10-07
because the active branch is in use. Publication is restricted to a draft PR;
no merge, deployment or stack push is authorized by this action.
Rollback: close the draft; discard the isolated patch.

Validation: 80 focused Python tests and 17 frontend tests passed; TypeScript
passed. Broader frontend suite: 1186 passed, 1 OrdersPage retry-timing failure,
11 skipped. The Orders implementation/test files are unchanged by this patch.
Production build and TypeScript passed. OrdersPage passes in isolation (119 tests),
but its full-suite retry-timing failure remains a release-gate limitation.

Meta authorization is still provider-blocked. Login-for-Business configuration
and a grant accepted by the relevant MCP resource must be verified before marking
these connected. Do not add advertising write scopes merely to silence a challenge.

## Meta-specific investigation and correction

Native desktop Meta Social read succeeded for WECARE.DIGITAL app
2238810740192680 (admin role). Basic and advanced settings reads succeeded.
Native WhatsApp business listing succeeded: Wecare.Digital (382642103987922)
and Manish Agarwal (125951953587391). No onboarding, number, message, advertising,
credential or app-setting mutation was performed. These desktop grants are
separate from the dashboard cloud callback.

Resource and authorization-server discovery advertise resource-specific public
client registration at https://mcp.facebook.com/.well-known/register/{devtools,
whatsapp_business_tools,ads}. All three rejected the WECARE HTTPS callback with
HTTP 400, invalid_client_metadata, "Dynamic registration is not available for this
client." No client id was issued. Discovery still advertises the existing v26.0
Facebook dialog and Graph token endpoints; those endpoint URLs were not the defect.

The Meta Social/WhatsApp policy now requires the resource-advertised registered
MCP client instead of substituting the WECARE Graph app id. Social requests its
read permission and business_management; WhatsApp requests the server's published
permission set, but callable tools remain restricted to business listing. No live
consent was requested. Refused registration creates no pending OAuth state and
cannot produce a misleading Graph login link. Existing encrypted credentials are
retained. The dashboard displays authorization-start errors on the provider card
and clears a stale consent link. Actual connection verification remains required.

Ads retains the documented existing-app Login for Business flow and disabled
execution allowlist. The cloud endpoint still returned 401. Meta App Review
privileges reports ads_read and ads_mcp_management rejected (no access level),
along with other advertising privileges. Do not assume this alone proves why an
app-admin's own-account token failed: it is an additional provider access issue.
Review status is PENDING, submission 2422724488467970; requirements says a new
submission cannot be made while the previous submission is in review. Its listed
catalog_management screencast and Marketing API Access Tier api_precheck are
incomplete. Rejection reasons were not supplied. No submission was made.

Remaining activation: obtain Meta acceptance of the custom cloud MCP client for
Social/WhatsApp, then authorize and verify each resource under the staff account.
For Ads, resolve the app's rejected MCP/read access and pending review with Meta,
then renew the configured Login for Business grant and verify MCP discovery.
Until those reads succeed, none of the three dashboard integrations is resolved.
Desktop Social/WhatsApp remain usable through their own connected tools.
