# Administrative MCP branch build - 2026-10-01

Owner authorized the build and then requested a separate branch with a later merge.
Branch: `feature/workspace-mcp`. Base: `51445762`. Isolated checkout:
`/Users/wecaredigital/wecare-store/.scratch/workspace-mcp-build`.

## Delivered

Versioned eleven-provider registry; administrative JSON MCP router; staff JWT and
IAM gateway routes in additive CloudFormation; KMS context-bound OAuth credential
custody; ten-minute supersedable one-use PKCE callback; bounded read-only Meta
remote MCP client; scoped AWS/GitHub SDK reads; supplied-patch persistence and
disabled gated GitHub workflow; portable deterministic Lambda builder; explicit
change-set deployment entry point; Kiro/Codex example and activation runbook.

CloudFormation template validated successfully through AWS MCP in account
775261844268/us-east-1. Current public MCP alias was read as version 9. The existing
staff pool/client, API `/api/*` rewrite, artifact bucket versioning, alarm SNS topic
and GitHub OIDC provider were rediscovered. No production resources were changed.
Secret field names were inspected only inside an asm-exec child using a dynamic
reference; no provider credential values were printed or entered context.

## Verification

* Complete Python suite on the final source tree: 6059 passed, one skipped.
* Focused administrative MCP tests: 46 passed; ten media-flow regression tests passed.
* 698 frontend tests passed; typecheck and production static build passed.
* Public-page manifest and exported-bundle credential checks passed.
* Workflow YAML parsed successfully. It was not dispatched against production.
* Two deterministic bundle builds returned identical SHA-256. The final manifest
  is generated in scratch, rather than committing a binary release artifact.
* Runtime GitHub credential read, through asm-exec with no value output: HTTP 200
  for `wecare-digital/wecare-digital`, default branch `stack`, repository push
  permission present. Workflow dispatch and the future Lambda IAM grant were not
  tested by that read.

Tests cover unauthorized requests, issuer/client/token-use/expiry/Admin binding,
removed membership, origins, public-route separation, provider allowlists and app
scope, OTP/send denial, OAuth expiration/supersession/replay/PKCE, credential
redaction, remote MCP initialization and session negotiation, bounded SSE handling,
patch path/header policy, job idempotence while disabled, and audit-log sanitizing.

## Activation boundary

No merge or production deployment was performed. Deployment scripts refuse feature
branches. AWS provider OAuth has not been completed; desktop authentication is not
represented as cloud authentication. Native inbound MCP OAuth discovery is not
included: clients use the IAM stdio bridge or a current staff bearer token.

After merge: deploy the new stack, register the HTTPS Meta callback, complete each
cloud consent, run authorized provider reads, verify GitHub runtime permissions,
configure the OIDC artifact-read repository variable and enable code jobs only in
reviewed IaC. Razorpay/Google Cloud/Google Ads/Meta Ads remain pending adapters;
Plivo/Sinch remain documentation-only records. Backend/deployment code changes and
provider mutations are outside the first-release supplied-patch allowlist.

Rollback for branch work is a normal revert. After a future rollout, capture and
restore the administrative live alias version only; retained KMS/DynamoDB resources
must not be destroyed as a shortcut. See `docs/workspace-mcp.md`.

## Follow-up review and connection check

Fresh Codex MCP reads succeeded for AWS account identity, Meta Social app-list
(WECARE.DIGITAL app 2238810740192680) and WhatsApp business-list. AWS returned no
administrative `/workspace/mcp` routes: the newly built backend is not deployed or
authenticated in AWS. Existing desktop connections do not imply cloud connection.

Automated review prompted stricter credential-context/environment validation,
lease-safe token refresh with a fresh read under the lock, bounded in-checkout
patch inputs, explicit empty-chunk refusal and managed commit-runner authentication.
Callback principals remain exclusively server-written state records and KMS context,
never a query parameter. Remote response strings remain untrusted data, never shell
commands or executable expressions; escaping them as shell syntax would not be a
protocol-level command-injection fix.

CI's first build hit HTTP 429 on an existing blog read; rerunning the same commit
passed. Its media source gate also reproduced a baseline false positive on the
receipt suffix `stack/receipts/`, which is wrapped by `media_paths.secure()` before
it is used. The feature fixes the checker rather than changing checkout source:
every local reference must be inside a known rooting helper. Ten regression cases
keep bare, aliased, returned, indirectly transformed and unproven prefixes failing.
