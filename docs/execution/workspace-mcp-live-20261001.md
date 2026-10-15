# Administrative MCP merge and live verification

Owner instruction: MERGE PULL AND TEST IT. PR #179 was confirmed merged into
stack at d24c0250777a08d2669ed51f3f131a2ad1dd9435 before deployment. Every applicable
PR CI check passed; the two live drift jobs were skipped on the PR and CodeQL's
aggregate result was neutral with its language analyses successful.

The clean isolated checkout was detached at that exact merged commit. The merged
tree matches the reviewed feature tree. Fresh verification: 6022 tests under
tests/ passed, one skipped; 56 focused MCP/media-gate tests passed. Earlier release
validation also passed frontend tests, typecheck, production build and export
checks, and the final PR build passed remotely.

The reproducible 16,579,156-byte Lambda bundle has SHA-256
711c209c1a1c8d6b4c7a0cfd3e3f40eec806e7fb683acaa99aa2be37fa361803.
AWS MCP validated the template, uploaded the bundle through its presigned S3
upload facility, created and reviewed change set merged-d24c0250, and executed
17 Add actions. Stack wecare-workspace-mcp reached CREATE_COMPLETE in account
775261844268, us-east-1. Its live alias points to version 1, Active/Successful,
with the expected code checksum. The existing public MCP alias remains version 9.

## Live evidence

- Existing wecare-prod IAM credentials successfully initialize the cloud MCP,
  discover eight tools and read the eleven-provider registry through the actual
  signed HTTP endpoint and stdio bridge.
- aws_status confirms the account, region and both live aliases.
- github_status verifies wecare-digital/wecare-digital, default branch stack,
  and authenticated repository permissions using runtime secret resolution.
- Unsigned IAM requests return 403. Unsigned staff requests return 401.
  Invalid OAuth state returns 400.
- Both Meta OAuth initiation paths successfully write encrypted pending state
  and return S256 PKCE authorization requests. A deliberate access_denied callback
  reaches the Lambda through the main domain, returns 400 and consumes its nonce;
  replay returns 400. No provider token was issued during these guard tests.
- Provider verification correctly refuses both providers pending cloud consent.
  Unknown tools and WhatsApp message sends are rejected by policy.
- Registry TTL is enabled. CODE_JOBS_ENABLED is false. GitHub repository variable
  WORKSPACE_MCP_PATCH_READ_ROLE_ARN now references the scoped deployed read role.
  No supplied patch workflow was dispatched and no public component was changed.

Full sanitized metadata and result evidence is in
snapshots/workspace-mcp-deployment-20261001.json. No credentials, authorization
codes, active OAuth URLs or raw Lambda environment were retained in this report.

## Client activation and remaining verification

Enabled wecare-workspace in ~/.kiro/settings/mcp.json and ~/.codex/config.toml,
preserving all existing MCP entries and private backups. Both use the existing
wecare-prod profile and the verified stdio proxy in this retained isolated checkout:
/Users/wecaredigital/wecare-store/.scratch/workspace-mcp-build/scripts/workspace_mcp_proxy.py.
Reload the clients to load their new server; actual GUI reload/tool availability
has not been independently observed. Keep this checkout while configurations
reference it, or update the path after safely pulling the merged scripts locally.

Meta Social and WhatsApp cloud authorization remain consent_required. Register
https://wecare.digital/api/workspace/mcp/oauth/callback for app 2238810740192680,
then run connection_authorize and complete the owner's browser consent separately
for meta-social and whatsapp. Run connection_verify afterward. Existing native
Codex provider sessions are separate from this cloud identity. Staff Cognito login,
real provider token exchange/refresh and a successful supplied-patch workflow
were not live-tested. Their fixture tests passed. Keep code-job dispatch disabled
until workflow authorization and the bounded write path are deliberately tested.

Razorpay, Google Cloud, Google Ads and Meta Ads remain pending cloud adapters;
Plivo and Sinch remain documentation-only entries. Registry presence is not an
authenticated cloud connection.

## Rollback

Disable only the new local wecare-workspace entries if its client fails. Keep
CODE_JOBS_ENABLED false. Initial rollout rollback is a reviewed IaC change to the
new stack routes and resources, with retained DDB/KMS data; destructive stack/key/
table deletion is not authorized as a routine rollback. A later Lambda release can
restore live version 1 after capturing its pre-change alias. No existing customer
checkout, OTP pool, public MCP routing, provider number or certificate was changed.
