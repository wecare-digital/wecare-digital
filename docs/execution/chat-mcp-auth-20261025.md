# Chat MCP authentication preparation — 2026-10-25

Status: implemented and verified locally; not pushed, merged, deployed or connected
to a ChatGPT host. Base: 7bfb5cc0c9ee8fd2ddad962be5417fa948ec5424. Task branch:
codex/chat-mcp-auth-20261025.

The optional endpoint delegates code/PKCE/refresh to the established Cognito staff
pool. Tokens are resource-bound. Every tool request rechecks token validity via
Cognito GetUser and current Admin membership. Existing staff/IAM/provider callback
routes, runtime IAM policy, encrypted custody and per-subject namespaces remain
unchanged. Workspace plugin access does not grant staff Admin membership.

## Verification evidence

- The initial focused script failed because chat_oauth.py did not yet exist.
- scripts/verify_chat_mcp_auth.py passes 90 offline checks: public discovery,
  anonymous challenge, fixed OAuth destination, exact callback/client/resource,
  PKCE, duplicate/malformed requests, token expiry/type/scope, current membership,
  revoked tokens, subject mismatch, separate owners, token response filtering,
  error redaction, actual handler discovery, origin isolation, existing staff/IAM
  behavior and unchanged infrastructure authority.
- Targeted Python compileall passes for all changed Python files.
- cfn-lint passes with no diagnostics on amplify/infra/workspace-mcp.json.
- AWS CloudFormation ValidateTemplate succeeded through the existing AWS Core
  connection in us-east-1; all six expected parameters were returned. No stack or
  resource was created or updated by this validation.
- Two deterministic builds from the dedicated pinned dependency directory produce
  identical 16,587,109-byte ZIPs, SHA256
  43aa63cbffb3ad259550083b5eba456e12f80e17336268c32f6c89c60ecc9de2.
  The archives contain the exact handler, OAuth module, adapters and policy source
  and no native libraries. Invalid callbacks fail before creating output.
- Template SHA256:
  3aa1969b5cbb89d86287558b683acd322d98e0855de7601da78e6892f0e81cce.
  The manifest pins this checksum. Callback-only changes republish the Lambda
  version; omitted callback parameters preserve the stack's previous value.

## Remaining activation work

Owner authorization to push and prepare a PR; merge to wecare.digital; exact
callback from ChatGPT setup; reviewed production change set; dedicated Cognito
client/API activation; connection registration and consolidated-plugin binding.
Use per-user consent, then verify live discovery, initialize, tools/list, refresh,
Google Cloud/Ads reads and a second authorized user's isolation in Chat and Work.

General workspace users can install the consolidated plugin, but this privileged
gateway still requires staff Admin membership. Do not remove that existing gate
to satisfy broader installation availability. General staff authorization needs
its own permission design and owner-approved access change.

The separately saved consolidated plugin version 0.2.2 includes WebMCP website
authoring guidance and the supplied WECARE.DIGITAL icon and branding. That release
does not assert that this prepared gateway has been deployed or that WebMCP tools
have been installed on any website.
