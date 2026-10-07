# MCP connection verification and persistence - 2026-10-07

Base: 88f1a087e2e5e876ee3b100522b496142d5b0839, stack.
Account: 775261844268; region us-east-1; runtime live version 10.

A0_READ: all eleven providers checked through the owner's signed-in dashboard.
AWS, GitHub, Wix, Razorpay, Google Cloud and Google Ads passed account reads.
Google access tokens renewed automatically. Plivo and Sinch passed documentation
discovery only. Meta Social, WhatsApp and Meta Ads returned remote HTTP 401
authorization challenges. No permission expansion or new provider credential was
performed. Those grants remain unverified for their remote MCP endpoints.

Registry metadata confirms saved connections have no DynamoDB ttl attribute; the
table expires only one-use OAuth flow rows. Cognito subject and IAM principal,
rather than browser sessions, select isolated connection namespaces. Signing out
does not delete authorizations. Revocation/provider token limits still apply.

A1_LOCAL: preserve verification on automatic renewal, persist a non-sensitive
refresh-capability flag, distinguish renewal checks from lost consent, clarify
account persistence, add per-provider failures and View data links to Playground.
Tests cover stable account scoping, no credential TTL, lease-conditional renewal
and provider selection. No credential values were retrieved or logged.

A2_REMOTE_CODE: empty draft branch codex/mcp-persistence-20261007 was created.
Initial publication was rejected while broader release gates were not green.
The owner explicitly authorized publishing on a separate branch on 2026-10-07
because the active branch is in use. Publication is restricted to a draft PR;
no merge, deployment or stack push is authorized by this action.
Rollback: close the draft; discard the isolated patch.

Validation: 76 focused Python tests and 16 frontend tests passed; TypeScript
passed. Broader frontend suite: 1186 passed, 1 OrdersPage retry-timing failure,
11 skipped. The Orders implementation/test files are unchanged by this patch.
Production build and TypeScript passed. OrdersPage passes in isolation (119 tests),
but its full-suite retry-timing failure remains a release-gate limitation.

Meta authorization is still provider-blocked. Login-for-Business configuration
and a grant accepted by the relevant MCP resource must be verified before marking
these connected. Do not add advertising write scopes merely to silence a challenge.
