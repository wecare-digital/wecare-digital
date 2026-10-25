# Chat MCP authentication implementation plan

> Execute inline in this session. Repository policy retires reviewer-agent ceremonies and test-suite automation; use a focused verification script and targeted compile/schema checks.

**Goal:** Make the existing fixed-read workspace MCP connectable from ChatGPT through individual staff Cognito authorization.

**Architecture:** Reuse the current Cognito user pool and managed login with one dedicated public OAuth client. A dedicated HTTP API with a default stage fronts the existing Lambda and supplies standard root discovery, PKCE/resource-enforcing authorization and token endpoints, and an authenticated MCP route. Existing staff/IAM/provider callback routes and encrypted per-subject provider grants remain unchanged.

**Decisions:** No custom token issuer, new credential store, shared provider identity, new model, frontend redesign, write adapter, or change to existing staff-client settings. Current Admin membership and Cognito token revocation remain required. The OAuth client callback is a deployment parameter copied exactly from ChatGPT's connection page; no wildcard redirect.

**Alternatives:** Reusing the raw staff endpoint fails MCP discovery; sharing a staff token breaks account isolation. A custom authorization broker adds unnecessary token custody. Reusing Cognito provides native code/PKCE/refresh support already available in the live Essentials pool and managed login version 2.

## Tasks
- [x] Add scripts/verify_chat_mcp_auth.py; prove missing adapter fails.
- [x] Add chat_oauth.py with bounded exact-route dispatch, public metadata, fixed Cognito delegation, strict client/redirect/resource/scope/PKCE validation, and live Cognito/current-group checks.
- [x] Factor the existing authenticated JSON-RPC path without changing old authentication, then route the dedicated API through the adapter and add OAuth tool metadata.
- [x] Add explicit CloudFormation Chat API/client/branding/routes/invoke permissions, disabled by default until an exact callback is supplied. Update reproducible packaging.
- [x] Verify positive and denied paths, old-route isolation, per-user identity, resource binding, token redaction/error behavior, and template/package preservation. Compile touched Python and run cfn-lint/AWS ValidateTemplate.
- [x] Commit exact paths locally and prepare a reviewable patch. Production requires merge to wecare.digital and the existing reviewed CloudFormation deployment process; do not push or deploy without the required owner authorization.

## Activation gates
Exact ChatGPT callback; reviewed change set; production-branch release; individual staff sign-in/consent; live initialize/tools-list and Google Cloud/Ads reads through the new host connection. A second member requires their own identity and provider grant. Workspace plugin visibility is not staff/provider authority.
