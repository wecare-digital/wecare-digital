# Separate provider connections

The optional separate endpoints provide independent ChatGPT control-plane entries
for Google Cloud, Google Ads, Plivo and Sinch India RCS. Google Cloud and Google Ads
are served directly by the WECARE administrative MCP implementation. Plivo and
Sinch are control-plane/status surfaces only: the final provider integrations must
use provider-native MCP servers. Plivo provider references are: website https://www.plivo.com/, documentation MCP https://plivo.com/docs/mcp, and live-action source https://github.com/plivo/mcp. Sinch provider references are: website https://sinch.com/, Agent Tools https://sinch.com/ai/agent-tools/, documentation MCP https://developers.sinch.com/mcp, and live-action source https://github.com/sinch/sinch-mcp-server. They reuse the
existing staff Cognito authority and approved runtime credential custody; no
provider credentials are exposed to ChatGPT.

Each WECARE control-plane endpoint is a distinct API Gateway resource with a distinct
OAuth resource audience. The API ID selects the provider on the server. Its MCP
schemas contain no provider selector. `connection_status` reads only that provider's
registry row and `connection_verify` performs only the provider's fixed verification
read. The two Google endpoints also expose `connection_authorize`.

For Plivo and Sinch, do not publish the control-plane endpoint as if it were the
provider-native MCP server. Plivo's official server is stdio-first and requires a
WECARE-managed remote HTTP adapter before ChatGPT registration. Sinch's official
server supports native Streamable HTTP on `/mcp`; remotely reachable deployments
must use an authenticated multi-tenant mode or an equivalent WECARE auth front door.
Never expose Sinch single-tenant mode publicly because it has no inbound
authentication.

## Release and register

1. Run `scripts/verify_chat_mcp_auth.py` and
   `scripts/verify_separate_provider_mcp.py` with the pinned adapter dependencies.
   Compile the changed Python and lint `amplify/infra/workspace-mcp.json`.
2. Build with `scripts/build_workspace_mcp.py --dependencies PATH --output PATH
   --separate-providers`. Deploy through the existing reviewed CloudFormation
   change-set process from the merged production revision. The deployer preserves
   the original callback and any already configured provider callbacks.
3. Read `GoogleCloudEndpoint`, `GoogleAdsEndpoint`, `PlivoEndpoint` and
   `SinchIndiaEndpoint` from the stack outputs. Treat the Plivo and Sinch values
   as WECARE control-plane/runtime endpoints only. Never use those `execute-api`
   URLs as the provider website/homepage. Display Plivo as https://www.plivo.com/
   and Sinch as https://sinch.com/. The provider documentation MCP endpoints are
   https://plivo.com/docs/mcp and https://developers.sinch.com/mcp respectively.
4. Register Google Cloud and Google Ads directly against their WECARE endpoints.
   For Plivo, deploy a remote HTTP adapter around the official `plivo/mcp` server
   and register that remote MCP URL. For Sinch India, deploy the official
   `sinch/sinch-mcp-server` with the `rcs` tool tag and authenticated remote
   Streamable HTTP, then register its `/mcp` URL. Preserve the WECARE control-plane
   plugin only for status/verification/orchestration.
5. Rebuild with `--provider-redirect google-cloud=EXACT_CALLBACK` and the equivalent
   `google-ads`, `plivo` and `sinch` arguments for the callbacks being configured.
   The builder validates callback formats and pins a configuration revision so a
   callback change publishes a new immutable Lambda version. Review and execute
   that change set. The Cognito public client retains its original callback and
   adds only configured exact callbacks. No client secret is created.
6. Complete staff sign-in separately for each plugin. Google consent follows
   through that plugin's `connection_authorize` if its user's grant is absent.
   Plivo and Sinch India resolve their established credentials only at runtime.
   Repeat the account read through each actual ChatGPT connection. An empty Ads
   list is not proof of advertiser access; a Sinch app read is not sender approval.

Before callback registration, discovery is available but OAuth operations fail
closed with 503. A plugin package upload does not prove sign-in or account access.
Do not describe an endpoint as fully connected until its authenticated live read
passes. Staff administrator membership and per-call revocation checks still apply.

## Rollback

Capture the existing alias version and stack parameters before release. Roll back
with the prior reviewed template, bundle and parameters through CloudFormation.
Preserve the original Chat callback, registry, KMS key and unrelated provider grants.
Disabling `SeparateProvidersEnabled` removes the new APIs, invalidating these new
connections; this is an owner-authorized rollback rather than routine reconnect.
