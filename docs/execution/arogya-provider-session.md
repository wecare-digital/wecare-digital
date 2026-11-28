# Arogya provider session continuation

This change supplies the missing Google consent entry and server renewal core.
It does not activate public booking submission by itself.

## Google authorization

The staff connection manager (Platform > MCP Connections) and the workspace-mcp
Lambda that issued and verified Google consent were removed. No new Gmail grant can
be created from the workspace. Existing encrypted grant rows in the
`wecare-workspace-mcp` table are retained and are still read and refreshed by the
Arogya runtime. Issuing a new grant needs a separate reviewed consent flow.

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
  the retained workspace-mcp purpose policy is not assumed to permit it.
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

The workspace-mcp deployment scripts were removed with the Lambda.
