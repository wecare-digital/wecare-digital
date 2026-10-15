# Phase and requirement dependency graph

Seeded 2026-09-21 at HEAD `4baf4236`.

## Controlling order

```text
Phase 0  identity + secrets + provider ownership + protected snapshot   [COMPLETE]
   |
Phase 1  canonical inventory + documentation queues + MCP/SDK matrix    [NEXT]
   |
   +-- Phase 2  direct Meta ingress + message lifecycle
   |      |
   +-- Phase 3  fresh connected-call notification domain
   |      |        (depends on: one canonical event contract, external-party
   |      |         resolution, consent/policy, idempotency key)
   +-- Phase 4  contacts / CRM / Flow / payments
   |      |        (Contact key repair gates Flow enrichment)
   +-- Phase 5  Plivo PSTN + browser softphone
   |      |        (depends on: Cognito token route, endpoint routing, session
   |      |         lifecycle, browser permissions, /plivo/dial-events)
   +-- Phase 6  internal chatbot + operations service + governed MCP
   +-- Phase 7  growth / presence foundations
          |
Phase 8  frontend route consolidation + tutorials
   |
Phase 9  guarded cleanup  (+ NATIVE work is POST-PROJECT per owner overrides)
   |
Phase 10 authorized cutover + observation window + irreversible cleanup
```

## Hard dependencies

- The notification service depends on **one** canonical connected-event contract.
  Do not enable a second producer first. `NOTIF-OWN-001` gates all of Phase 3.
- `NOTIF-STORE-001` (declared-but-absent `PstnNotificationDelivery`) must be
  resolved before any delivery record is written.
- Browser SDK UI depends on the protected token route, endpoint/user routing,
  session lifecycle, browser permissions and `/plivo/dial-events`.
- Frontend pages cannot be complete while backed by mocks where real APIs are required.
- Provider cleanup cannot remove an asset until readers/writers, retention,
  backup/checksum, rollback and an observation window are proven.
- MCP/dashboard actions ride the same production authorization and audit layer.
  MCP is never a privileged bypass and never a runtime dependency.

## Security work that does not wait for its phase

These three came out of Phase 0 and are **not** gated behind Phase 1 completion,
because they are live unauthenticated surfaces:

```text
SEC-ROUTE-003  extend audit_route_auth.py to both APIs + fix dir↔function mapping
      |            (must run first, or the other two cannot be measured honestly)
      +-- SEC-ROUTE-001  /webhook/sinch-rcs   -> signature verification
      +-- SEC-ROUTE-002  POST /whatsapp/inbound -> close or verify
                |
                +-- PROV-SINCHSMS-001 dangling-route deletion
                       (A4 approval; same change window)
```

`SEC-ROUTE-001` must land before `RCS-001` can be called `LIVE_VERIFIED`, and
`SEC-ROUTE-002` must land before `WA-INGRESS-001` can be.

## Forbidden parallel work

- Do not run two sessions against the same spec, or against the same file paths.
- Do not deploy Lambda code while a provider control-plane apply is in flight.
- Do not touch notification producers and the notification domain concurrently.
- Do not combine the ESLint/TypeScript major upgrades with any provider cutover.
- Do not bundle route deletion with route authentication in one commit; the
  rollback stories are different.
