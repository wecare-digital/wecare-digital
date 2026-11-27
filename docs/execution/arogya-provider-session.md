# Arogya provider session continuation

This change supplies the missing Google consent entry and server renewal core.
It does not activate public booking submission by itself.

## Google authorization

Use the existing staff Admin connection manager:
https://wecare.digital/workspace/platform/?view=mcp-connections

After the matching workspace-MCP backend release and frontend release:
1. Select Gmail · Apollo OTP, then Connect.
2. Continue with Google as wecare.digital.bw@gmail.com and approve Gmail read-only access.
3. Return to the connection manager and select Verify.

This is a separate per-staff-account grant in the existing encrypted registry,
not a ChatGPT connector token or an exported browser session. The existing web
OAuth client and callback are reused. The callback checks the required Gmail
scope and actual Gmail API profile before saving. Granting a different Google
account fails closed. Verification exposes only a success marker, not messages,
tokens or other mail. No arbitrary Gmail read tool is added.

The grant needs explicit service binding before customer requests can use it.
A staff connection alone does not delegate mailbox access to public customers.
No such service binding is silently created by consent or by this change.

## Renewal core

- apollo_client.py uses only the fixed Apollo IC origin, normal Login/SendOtp/
  VerifyOtp/GetProfile contracts, and bounded catalogue/schedule reads.
- apollo_session.py advances one stage per request without sleeping or a
  scheduled keepalive. A cached valid session makes no new sign-in/Gmail call.
- A 90-second renewal lease prevents concurrent challenges; the owning Lambda
  runtime timeout must be configured at no more than 60 seconds. Gmail polling is bounded;
  the same message is never used for another verification attempt. Three
  expired challenges or verification failures require administrator attention.
- Account/password-update policies and profile mismatches stop automation.
- Malformed persisted state is quarantined for administrator attention. A
  candidate token is encrypted before profile verification, so a transient
  profile read retries without consuming another OTP or repeating sign-in.
- Ambiguous OTP sends retain the pending challenge instead of resending.
- A stale provider 401 cannot invalidate a newer successfully renewed session.
- SessionResult.public_status() omits the provider bearer token.
- session_store.py supports encrypted custody in the existing registry table,
  fixed service-record keys, KMS encryption-context binding and fenced leases.
  Its separate arogya-provider context requires explicit runtime IAM wiring;
  the existing workspace-mcp purpose policy is not assumed to permit it.
- Direct KMS plaintext is bounded to 4096 bytes. No new secret/table/key,
  provisioned instance, scheduler or always-on worker is created here.

The remaining integration is the authenticated customer API, explicit business
service delegation/custody, provider catalogue/schedule projection, owned
paid-order binding, exactly-once request submission and outcome reconciliation.
Those need the authorized runtime grant and credentials entered through a secure
Admin interface. Credentials must not be pasted into chats, source or logs.

## Release boundary

The booking Lambda also accepts an IAM-authorized native SDK Invoke with exactly
`{"internalAction":"checkProviderCatalogue","catalogue":{"action":"catalog","kind":"hospitals"}}`.
This read-only operator check delegates to the same strict catalogue reader. It
can advance normal on-demand session renewal but cannot read patients, drafts or
submit bookings. It returns normalized public catalogue choices or a sanitized
renewing/unavailable status. Other catalogue kinds use the same validated ID
fields as customer catalogue requests.

This is not an HTTP action. Function URL events always include `requestContext`
and must pass genuine customer WhatsApp authentication, even when their body or
envelope contains the operator action. The URL resource policy's native invoke
permission is restricted to invocations via the Function URL. Direct SDK Invoke
requires an independently authorized AWS IAM operator; no fabricated HTTP
authorizer identity or customer token is used.

scripts/deploy_workspace_mcp.py requires merged wecare.digital source before
activation. Build and review the deterministic workspace-MCP archive first;
preserve all existing stack parameters. The current change adds an OAuth
provider using existing code resources, not another stack or credential family.
