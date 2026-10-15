# Dashboard MCP playground - 2026-10-02

Built on current stack source 9f5fcb33, including merged PR 180. The existing
staff Admin MCP Connections page now includes MCP Playground and the overview
links to MCP Connections & Playground. No new public route or authentication
exception was added.

Select a connection, select Check connection and view data or a fixed Meta read,
and Run read. Results display the actual response and completion time. Provider
refusals remain failures, not empty data or success. Changing the connection or
read clears previous data. Nested credential-shaped fields, including JSON text
blocks, are redacted; display is bounded to 50,000 characters. Results are kept
only in component memory. A JSON-RPC request example documents the same tool
call for the Kiro/Codex bridge. No arbitrary URL, query, write tool or code job
is exposed.

Fixed remote reads: authorized Meta app list (limit 10), WECARE app basic settings,
WECARE API rate limits (60-minute lookback), WhatsApp business list. The backend
independently validates the provider/tool/action/app/argument limits. These reads
require the staff principal's own verified OAuth grant; native desktop tokens
are not copied into AWS. Other providers expose their current fixed verification
read or documentation discovery, not unrestricted provider data collections.

Fresh IAM-backed live verification: AWS, GitHub and Razorpay passed; Plivo
and Sinch documentation discovery passed. Meta Social, WhatsApp and Meta Ads
remain unverified in AWS; all three current dynamic-client starts were refused
by Meta. Google Cloud and Google Ads still need this cloud principal's consent.
The live router remains version 2. Its read/connection tools are usable for
day-to-day checks through Kiro/Codex; automated code submission remains disabled.

Meta's Ads MCP use case was added to existing app 2238810740192680. Its permission
page showed ads_mcp_management Ready for testing. The owner confirmed the cloud
callback is valid. The subsequent App Review page shows ads_mcp_management in
the submission's allowed-usage requirements; no review submission or terms
acceptance was performed by the agent. Meta Ads supports own-app OAuth after
this setup, unlike the blanket dynamic-client prerequisite previously stated.
The current version 2 Ads adapter still needs that supported OAuth path before
it can be verified. See the correction in workspace-mcp-adapters-20261002.md.

Validation: six playground tests cover real response rendering, refusals, bounded
Meta reads, stale result clearing, operation/app constraints and nested redaction.
Combined focused frontend checks: 10 passed. Full frontend suite: 756 passed.
Typecheck, production export, scoped ESLint and git diff --check passed.

Rollback: ordinary revert of the explicit UI/docs paths and redeploy stack.
The Lambda, provider credentials, authorization policy and code-job flag were
unchanged by this UI release. Deployment result is recorded after Amplify runs.
