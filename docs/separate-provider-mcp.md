# Separate provider connections

The optional separate endpoints provide independent ChatGPT plugin entries for
Google Cloud, Google Ads, Plivo and Sinch India RCS. They reuse the existing
administrative Lambda, staff Cognito authority, encrypted per-user Google grants
and approved Plivo/Sinch runtime references. They do not share another person's
provider grants, create provider credentials or enable provider writes.

Each endpoint is a distinct API Gateway resource with a distinct OAuth resource
audience. The API ID selects the provider on the server. Its MCP schemas contain
no provider selector. `connection_status` reads only that provider's registry row,
and `connection_verify` performs only that provider's fixed account read. The two
Google endpoints also expose `connection_authorize`. AWS, GitHub, Meta and the other
providers' tools cannot be invoked through these endpoints. The original gateway,
staff route, IAM bridge, provider callback and secret IAM policies are preserved.

## Release and register

1. Run `scripts/verify_chat_mcp_auth.py` and
   `scripts/verify_separate_provider_mcp.py` with the pinned adapter dependencies.
   Compile the changed Python and lint `amplify/infra/workspace-mcp.json`.
2. Build with `scripts/build_workspace_mcp.py --dependencies PATH --output PATH
   --separate-providers`. Deploy through the existing reviewed CloudFormation
   change-set process from the merged production revision. The deployer preserves
   the original callback and any already configured provider callbacks.
3. Read `GoogleCloudEndpoint`, `GoogleAdsEndpoint`, `PlivoEndpoint` and
   `SinchIndiaEndpoint` from the stack outputs. Verify each endpoint's public
   OAuth metadata and anonymous 401 challenge.
4. Register one workspace plugin per endpoint. Use OAuth public-client mode with
   the existing `ChatClientId` and scope `aws.cognito.signin.user.admin`. Each
   plugin has its own connection and audience. Retrieve its exact ChatGPT callback
   from connection setup. Do not guess callbacks or use wildcards.
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
