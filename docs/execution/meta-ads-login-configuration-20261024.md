# Meta Ads login configuration repair - 2026-10-24

The staff Platform MCP Connections page reproduced HTTP 401 during Meta Ads
verification. Its server-generated HTTPS consent URL used Login for Business
configuration 1718783392517600. The consent screen opened Messenger Marketing
Messages onboarding. Inspection of that configuration showed General login,
a non-expiring system-user token and 32 selected permissions.

Created WECARE Ads MCP under the existing app 2238810740192680, configuration
2007033440253686. An independent read of the saved configuration confirmed
General login, User access token, and exactly ads_mcp_management, ads_read and
business_management. The shared configuration remains unchanged.

Policy version 8 changes only the Ads login configuration and its diagnostic
note. The registered HTTPS callback, existing app, PKCE/state custody, provider
scope list, authentication checks and empty advertising-tool allowlist remain
unchanged. New consent must be initiated through the deployed server after
activation; an old authorization URL must not be edited or reused.

Meta's live privilege read still reports ads_read and ads_mcp_management as
REJECTED with no access level. A current review submission is pending. These
facts do not establish whether an app-admin own-account login will succeed.
No authenticated Ads MCP discovery or account read has succeeded in this run.

The local wecare-prod profile identifies as account root, which the IAM bridge
correctly refuses because it permits wecare-admin only. The staff dashboard
session is the usable connection namespace. No authentication guard was changed.

The HTTP loopback callback cannot be registered: Meta's dashboard explicitly
reports New HTTP Redirect URIs are not allowed. The cloud HTTPS callback is not
a relay for the local Codex OAuth listener. This repair targets the staff cloud
connection, not a direct desktop Meta Ads MCP registration.

Activation requires the repository's reviewed production deployment path. Live
alias observed before repair: version 13. Re-read alias and deployment state
before activation and record the actual rollback version. Do not deploy a stale
bundle over concurrent changes. No deployment, push or merge is included here.

Validation: deterministic release builder passed against the exact seven pinned
dependencies; backend compile and git diff checks passed. Compared both handler
source files against deployed live version 13: byte-for-byte identical. The new
bundle includes the pinned SDK dependencies required by the current builder;
the deployed archive currently contains only the three application files.
Bundle policy inspection confirmed the corrected login ID, exact three scopes,
empty advertising execution allowlist and unchanged other provider settings.
