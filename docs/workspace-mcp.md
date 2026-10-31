# AWS administrative MCP

The first release was merged through PR 179 and deployed as the dedicated
`wecare-workspace-mcp` stack. Deployment evidence is recorded in
`docs/execution/workspace-mcp-live-20261001.md`. Desktop provider authorizations
and cloud provider authorizations are separate.

## Who calls what

Kiro or Codex runs `scripts/workspace_mcp_proxy.py` as its stdio MCP client. The
bridge uses the existing `wecare-prod` profile to sign requests to the API Gateway
IAM route. The Lambda calls remote MCP servers only with independently authorized
credentials. Its fixed SDK adapters read AWS, public GitHub repository metadata and Razorpay; Google
Cloud and Ads use separate cloud OAuth grants. GitHub access is read-only status inspection; there is no workflow-backed code-job path.

The reasoning model stays in the client. There is no new Bedrock/OpenAI model,
arbitrary shell tool or unrestricted AWS script runner. Backend infrastructure is activated separately after merge. Production frontend deployment is owned only by Amplify on `wecare.digital`.

```mermaid
flowchart LR
  Client[Kiro / Codex] --> Bridge[Stdio SigV4 bridge]
  Bridge --> IAM[API Gateway IAM route]
  Staff[Workspace staff access token] --> JWT[API Gateway JWT route]
  IAM --> Router[Dedicated MCP Lambda]
  JWT --> Router
  Router --> Registry[DynamoDB connection and job registry]
  Router --> KMS[KMS encrypted OAuth custody]
  Router --> Meta[Meta remote MCP servers]
  Router --> AWS[Scoped AWS SDK reads]
  Router --> GH[GitHub repository status read]
```

## Authentication

* Staff endpoint: `https://wecare.digital/api/workspace/mcp`.
  API Gateway verifies the existing staff pool issuer and client audience. The
  handler accepts access tokens only, rechecks Cognito revocation and current Admin
  membership, and rejects customer tokens. It does not expose a new native MCP
  OAuth authorization server; direct HTTP use needs a current staff bearer token.
* IAM bridge endpoint:
  `https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/workspace/mcp-iam`.
  API Gateway verifies SigV4; the handler permits the established `wecare-admin`
  principal only. Existing developer credentials stay in the local profile.
* Provider callback:
  `https://wecare.digital/api/workspace/mcp/oauth/callback`.
  This is the sole public route in the new stack. A ten-minute one-use random state
  binds a provider and caller. A new consent request invalidates the previous one.
  PKCE verifiers and provider tokens are encrypted with principal/provider KMS
  context. Access-token expiry is not DynamoDB TTL: refresh credentials survive it.
  Refresh uses a per-connection lease, rereads the latest credential after acquiring
  it, and releases only its own lease; a delayed caller cannot clear a newer lock.
* IAM and Cognito identities have separate connection namespaces. Authorize through
  the same client identity that will use the connection.

No existing customer pool, staff client configuration, public `/mcp`, certificates,
Amplify rewrite rules or provider credentials are modified by this stack.

## Included tools and limits

| Tool | Behavior |
|---|---|
| `connections_list` | Reports versioned connection configuration and caller-specific OAuth status; never token values |
| `connection_authorize` | Starts cloud OAuth for Meta Social, WhatsApp, Meta Ads, Google Cloud or Google Ads; unsupported client registration fails before opening a broken login |
| `connection_verify` | Records a successful fixed account read, or separately records documentation MCP discovery |
| `provider_read` | Allows selected Meta app reads for app 2238810740192680, or WhatsApp business-list only |
| `aws_status` | Reads account identity and the two MCP live aliases |
| `github_status` | Reads this public repository's metadata anonymously; no GitHub credential is stored or used |

Meta Social includes app-list, selected app settings and API usage/deprecation reads.
WhatsApp deliberately stops at business-list: business selection and existing-number
reads belong to the next adapter extension. Sending, onboarding, phone verification,
registration, templates, webhook changes, payments and business changes are absent.
Remote endpoints cannot be supplied by callers. HTTP redirects are refused. JSON
and bounded SSE responses are supported; sessions are established separately per
remote call. Provider content is untrusted data, and credential-named fields are
redacted recursively, including JSON carried in text content.

Razorpay verification fetches at most one
order and returns only collection metadata, never customer or order content.
Google Cloud reads only project `wecaredigitalbw`; Google Ads lists accessible
customers using the developer token resolved inside Lambda. Google grants request
offline access and retain encrypted refresh tokens. The Google web client secret
is resolved from `wecare/seo/google-oauth` only inside token exchange/refresh.
Runtime IAM grants name exact secret ARNs. Decryption of the Google Ads secret's
existing CMK is restricted to Secrets Manager and that secret's encryption context.

Plivo and Sinch perform public documentation MCP initialization and tool discovery,
recorded as `documentation_verified`, never live-account access. Sinch remains
RCS-only. Existing desktop connections retain their own authentication.

Meta Social and WhatsApp remote OAuth require a supported MCP client rather
than substituting a business-app Graph token. Their metadata advertises dynamic
registration. The tested
custom cloud registration was rejected with `invalid_client_metadata` and
`Dynamic registration is not available for this client`. The dashboard reports
that restriction. An older business-app token cannot be forwarded as an MCP
credential. Meta Ads uses the existing WECARE app 2238810740192680 after enabling
its Ads MCP use case. The advertised Ads OAuth metadata supports public-client
PKCE (S256, token endpoint auth method none). Its connection check performs
authenticated initialize/tools-list only, recorded as authenticated, not
verified account data. Ad-tool execution remains disabled. Ordinary WhatsApp Graph
authorization saved by the callback is not proof that its MCP is connected.

## Build and deployment

Use Python 3.12 and the existing repository environment. Build the deterministic
Lambda package with `scripts/build_workspace_mcp.py`; no pytest/Vitest or GitHub
workflow is part of this path. Validate with targeted compile/build checks and the
deployer's live verification modes.

The builder verifies all dependency pins, bundles the SDK rather than relying on
the Lambda runtime's unknown SDK version, and produces a deterministic ZIP plus
SHA-256 deployment manifest. All dependencies are portable pure Python. Native
wheels, unexpected distributions and mismatched pins are refused.

## Deployment

Deploy only from the production branch using the reviewed workspace-MCP deployment
script/CloudFormation path. Confirm account 775261844268 and us-east-1, review the
change set, preserve the existing API routes and aliases, and verify `initialize`,
`tools/list`, `aws_status`, `github_status`, and provider reads after deployment.
The workspace MCP does not create, dispatch, or monitor GitHub workflows.

## Retired supplied patch path

The former supplied-patch code-job feature and its GitHub Actions/OIDC path are retired.
`code_job_submit`, `code_job_status`, patch-policy/gate files, patch S3 permissions,
the OIDC read role, and workflow dispatch/status logic must not be recreated.

## Live activation history

PR #179 was merged into the then-production branch. The CloudFormation stack is deployed successfully,
and the administrative MCP live alias points to version 1. IAM-signed initialization,
the original tool discovery, registry reads and AWS/GitHub SDK reads passed live checks.
The new server is enabled in local Kiro and Codex configuration; reload each client.
Meta Social and WhatsApp still require separate cloud browser consent. The later code-job/workflow feature has since been retired. See `execution/workspace-mcp-live-20261001.md` for exact
evidence, remaining verification and the retained proxy path used by local clients.

## Cost, audit and rollback

No provisioned concurrency, always-on compute, NAT gateway, new AI inference or new
certificate is included. Lambda has reserved concurrency 5 (a cap, not paid warmed
instances), 256 MiB memory and a 28-second timeout. DynamoDB uses on-demand billing
and point-in-time recovery. CloudWatch tool audit logs contain only principal hash,
allowlisted tool name and outcome, with 30-day retention. Error and throttle alarms use the
existing human-routed SNS topic. API Gateway already has access logging and stage
throttling. KMS, storage, backup, requests and provider usage can incur charges;
the architecture is not guaranteed free. A dedicated KMS key has a recurring cost.
No WAF or Security Hub is introduced.

For an initial rollout failure, disable the new Kiro/Codex server. Remove only this stack's newly added integrations/routes/authorizer through
its reviewed IaC rollback, subject to destructive-operation rules. Registry/KMS
resources have retain policies. For later code releases, restore the captured prior
live alias version and matching IaC. Never roll back checkout, public `/mcp`, other
provider connections or shared Amplify routing to repair this endpoint.

## Connection persistence and viewing results

Connections are stored server-side under the stable IAM identity or Cognito user
subject, not a browser session identifier. Closing the browser or signing out does
not delete them. Signing in as a different user or using the desktop IAM bridge
selects a different namespace; never copy another user's authorization to bridge it.
Only short-lived OAuth state rows have DynamoDB TTL. Provider access-token expiry
remains separate from registry retention. Automatic refresh retains the existing
verification timestamp and status, rotates the encrypted token payload under the
refresh lease, and records only a non-sensitive refresh-capability flag.

On the dashboard, use Verify/Check connection first, then View data to select the
provider in MCP Playground. Choose a read and Run read; results appear below.
An expired access token means Check renewal, not that the saved grant is lost.
Google offline grants renew on demand while valid. Revocation, changed permissions
or provider refresh-token expiry can still require consent. Meta authorization
errors must be resolved in the approved provider app/client configuration; do not
mark a callback or ordinary Graph token as a verified remote MCP connection.
The prepared Plivo/Sinch account adapters replace documentation discovery with
fixed account reads after the reviewed runtime release. They resolve the existing
`wecare/plivo/api` and `wecare/sinch/rcs` secrets inside the administrative Lambda.
Plivo returns account type and billing mode only; Sinch India authenticates with
the established ACL authority and reads only the configured Conversation app.
No contact details, channel credentials or tokens are returned. This proves account
read access, not RCS sender approval, delivery capability or permission to send.
Each request uses current runtime credentials, so secret rotation takes effect
without copying credentials into Chat. Missing credentials or denied provider
access fail closed. Old documentation verification never counts as account access.


The Meta Social/WhatsApp cloud flow requires Meta to accept its resource-specific
public MCP client registration. An ordinary WECARE Graph-app login is not a fallback
for this registration. If registration is refused, use the separately authorized
desktop Meta Social/WhatsApp connectors; do not copy their tokens into AWS. See
`execution/mcp-connections-20261007.md` for the live provider response and Ads review
limitations. Connection persistence does not override Meta client acceptance,
permission review, consent or revocation.

## Optional ChatGPT OAuth endpoint (prepared, not activated)

The dedicated Chat endpoint reuses the staff Cognito pool through a separate public
authorization-code client with S256 PKCE. The existing web client, staff route, IAM
route and provider callback retain their existing authority. No provider grants
are copied. Each MCP request calls Cognito GetUser to check the actual access token
and revocation, then checks current Admin membership. Its owner hash uses the same
issuer and subject as staff login. Plugin installation and workspace membership
alone do not grant administrative or provider access. General workspace-member
access requires a separately reviewed permission design.

Both ChatRedirectUri and ChatDiscoveryEnabled default to disabled. To obtain a
callback before creating its OAuth client, build with `--chat-discovery` and release
the reviewed discovery stage first. It publishes only public OAuth metadata and
an anonymous 401 challenge; authenticated MCP and OAuth remain unavailable until
the exact client/callback configuration is complete. Obtain the exact callback
from ChatGPT's connection setup, then build with
`--chat-redirect-uri https://chatgpt.com/connector/oauth/CALLBACK_ID` (replace the
placeholder; never use a wildcard). This authorization facade advertises no
authorization-response issuer parameter, so use the callback-specific URL supplied
by ChatGPT rather than its stable legacy redirect. Configure the static public
client ID from the stack output with no client secret. Only the native
`aws.cognito.signin.user.admin` scope is requested for Cognito GetUser. The MCP
resource audience must match the exact ChatEndpoint output.

Conditional resources add a dedicated HTTP API with a default stage, two discovery
routes, fixed Cognito delegation at /authorize and /token, and /mcp. MCP is checked
in the Lambda, even though API Gateway route auth is NONE; no anonymous MCP tools
are served. Metadata is public. Token responses go only to the OAuth host and never
to MCP tool results or logs. The public client has code-only OAuth, token revocation,
15-minute access tokens and seven-day refresh tokens. The API has explicit
throttling and uses the existing bounded Lambda concurrency. Requests can incur
normal AWS charges. The Plivo/Sinch release separately adds GetSecretValue on only
their two existing secret ARNs and KMS decrypt for only the Plivo secret context
through Secrets Manager. No new secret store or provider write tool is introduced.

Manually review the changed authorization/token boundary, compile the changed
Python, and run `cfn-lint amplify/infra/workspace-mcp.json` before deployment.
The retired offline auth test runner must not be restored. Build with the exact
pinned dedicated dependency directory using scripts/build_workspace_mcp.py. The
bundle includes chat_oauth.py and the manifest pins the template checksum. A
callback change also replaces the immutable Lambda version, so the live alias
cannot keep the old callback environment. Later builds that omit the callback
preserve the existing stack parameters; omission does not silently disable Chat.

Activation requires owner approval, merge to wecare.digital, and the existing
reviewed change-set process in scripts/deploy_workspace_mcp.py. After deployment,
use ChatEndpoint and ChatClientId outputs to register the connection and bind it
to the consolidated WECARE.DIGITAL plugin. Validate unauthenticated discovery and
401 challenge, then sign in individually and prove initialize, tools/list,
Google Cloud and Google Ads reads. Repeat with a second authorized identity to
verify isolation. Offline checks and CloudFormation ValidateTemplate do not prove
that live consent, token refresh or provider reads work. Do not describe this
endpoint as active until those checks pass in both Chat and Work.

For rollback, preserve the registry and KMS key and restore the prior Lambda
version with matching reviewed IaC. Clearing ChatRedirectUri removes the client
and invalidates the connection. With ChatDiscoveryEnabled=true, the API remains
for public discovery only; set it false as well to remove the API. These changes
require explicit owner approval.
Do not change existing staff-client settings or copy grants to repair a login.
