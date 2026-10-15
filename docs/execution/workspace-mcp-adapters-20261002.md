# Workspace MCP provider verification - 2026-10-02

Source c0243538; stack wecare-workspace-mcp UPDATE_COMPLETE, live version 2,
Active/Successful. Bundle SHA256
62b28cc8a25d67e09edebdd8877e17fcefb716a1ba62758d87aaaec39b3a02b0.
Amplify stack job 1204 SUCCEED for the same source. Build and test CI passed.

| Connection | Cloud result | Verification |
|---|---|---|
| AWS | verified | Account 775261844268, region us-east-1, workspace live 2; public MCP live 9 |
| GitHub | verified | wecare-digital/wecare-digital, default stack |
| Razorpay | verified, read-only | Orders collection, count 1; no order/customer data returned |
| Plivo | documentation_verified | MCP initialization/discovery, 3 tools; no live account access |
| Sinch | documentation_verified | MCP initialization/discovery, 2 tools; no live account access; RCS restriction retained |
| Meta Social | blocked | Custom MCP client registration refused by Meta |
| WhatsApp | blocked | Business-app authorization is not an MCP credential; approved MCP client needed |
| Meta Ads | blocked | Custom MCP client registration refused; account verification not available |
| Google Cloud | consent_required | Cloud OAuth grant absent for this principal |
| Google Ads | consent_required | Cloud OAuth grant absent for this principal |

Fresh native Codex Meta Social app-list returned WECARE.DIGITAL app
2238810740192680. Native WhatsApp business-list returned two businesses:
Wecare.Digital (382642103987922) and Manish Agarwal (125951953587391).
These desktop authorizations were not copied into AWS. The native Google Ads
accessible-customer read returned 8367589699 and 4270412231. Google Cloud's
existing CLI project read succeeded, but the loaded native MCP process's lint
step failed; this is not an AWS cloud OAuth verification.

## Why the reported errors occurred

The prior cloud flow supplied the WECARE business App ID to Meta's MCP scope
request. Meta rejected developer_tools_mcp_app_read for that client. The WhatsApp
flow accepted ordinary business permissions and saved a Graph token, but the MCP
server refused it. The registered callback was confirmed valid in Meta's validator.
Current code requires the client issued by the MCP registration endpoint and
binds saved tokens to that client. Registration for all three cloud Meta providers
currently returns a clear restriction before producing a broken login URL.

Official setup: https://developers.facebook.com/documentation/mcp/devtools-mcp
says client config no longer needs a business App ID or App Secret and notes
supported-client/gradual-rollout restrictions. Public metadata advertises dynamic
client registration; the cloud request returned invalid_client_metadata with
Dynamic registration is not available for this client. This is a provider-side
client restriction, not evidence that the user's developer app is broken.

## Validation and rollback

6036 Python passed, one skipped; 705 frontend passed; final focused checks
59 Python/seven frontend passed; typecheck and production build passed.
cfn-lint 1.40.2 and AWS ValidateTemplate passed. Dedicated cfn-guard was not run;
focused IAM/authentication tests and reviewed service change sets provide the
recorded security checks, not a comprehensive compliance certification.

Applied a retention-only change set before replacing the Lambda version. The
final change set reported ReplaceAndRetain; old version 1 was independently
confirmed present afterward. Roll back by setting the dedicated live alias to
retained version 1, then reconcile CloudFormation with the previous code artifact.
No code jobs were enabled. No payment, ad, WhatsApp send, registration or webhook
mutation was performed. Customer pools and their endpoints were not changed.

The first route-auth CI run flagged three routes because its marker scanner did
not recognize customer_auth.require_customer or customer_auth.authenticate.
Reviewed handlers already verify the caller; the scanner is corrected without a
public exemption. A fresh 365-route AWS snapshot classified 335 handler-authenticated,
2 gateway-authorized and seven expected-public routes, with zero open, dangling or
unresolved routes. Inert live probes: checkout status 401, session refresh with
allowed Origin 401, staff MCP 401, unsigned IAM MCP 403; missing session Origin 403.

Google's owner verification subsequently completed. The cloud callback has been
entered in the existing web client's Console; saving it and issuing the separate
AWS cloud grants remain pending at-action-time browser confirmation. Staff
dashboard and desktop IAM connections belong to different principals and must
each receive their own consent.

## Meta Ads use-case clarification

The blanket statement that all Meta integrations require an approved dynamic
client was too broad for Meta Ads. Meta's official 2026-07-16 announcement supports
an existing developer app after adding Create & manage ads with ads MCP server,
using Facebook Login for Business OAuth. Added that use case to WECARE.DIGITAL
app 2238810740192680 and inspected its permissions: ads_mcp_management is Ready
for testing. The owner also confirmed the cloud callback passes Meta's Redirect
URI Validator. This establishes app setup, not an issued or verified MCP grant.
The deployed version 2 still uses dynamic registration for Ads; its own-app OAuth
adapter and account verification are pending. Meta Social's rejected MCP scope
and WhatsApp's rejected business-app token remain separate, measured limitations.

Source: https://developers.facebook.com/blog/post/2026/07/16/meta-ads-mcp-server/
Advanced Access/App Review is required when managing other businesses. The
ads_mcp_management permission is not intrinsically read-only; the workspace's
server-side tool allowlist enforces its current read-only operations.
