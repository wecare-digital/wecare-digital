# Meta Business Agent — setup status & checklist

Backend: `wecare-meta-business-agent` (deployed). Actions: `readiness`, `eligibility`,
`onboard`, `settings`/`settings_update`/`enable`/`disable`, `allowlist*`, `entities`.
Auth: Bearer + `appsecret_proof` from `wecare/meta-system-user-token`. Verified reaching Meta.

## Verified status (re-checked live via API 2026-07-10)
| Step | Status | Notes |
|---|---|---|
| 6. App subscribed to WABA | ✅ done | WECARE.DIGITAL (app 2238810740192680) on both WABAs (2094615664435155, 2513394156072604) — confirmed via `GET /{waba}/subscribed_apps` |
| 2–5. System user token | ✅ works | `wecare/meta-system-user-token` authenticates (appsecret_proof required); reaches agent API (403 ToS, not auth error) |
| 7. `messages` webhook field | ✅ | existing integration receives messages |
| 7. `standby` + `messaging_handovers` | ✅ done | Confirmed subscribed on the `whatsapp_business_account` object (callback `https://wecare.digital/api/whatsapp`, active) via `GET /{app_id}/subscriptions` (app access token). No action needed. |
| API route `ANY /meta-agent` | ✅ wired | present in deployed API (`_routes.json`) |
| 1. Meta Business AI ToS | ❌ BLOCKER | WhatsApp Manager → Meta Business Agent tab, per number. `agent_eligibility` + `agent_config/settings` return **403** for BOTH numbers until accepted: _"The Meta Business AI Terms of Service must be accepted…"_ (https://www.facebook.com/legal/meta-business-ai-terms). **No API to accept — UI only.** |

## Remaining manual action (ONLY one left — no code, no API)
1. An authorized Business admin: **WhatsApp Manager → Meta Business Agent tab** (or Overview → Alerts → "Accept terms") → accept the Meta Business AI ToS for +91 93309 94400 and +91 99033 00044. ToS acceptance is legal-gated and cannot be automated via API.

_(The previously-listed webhook-field subscription step is done — verified live 2026-07-10.)_

## After ToS accepted — go-live flow (via the Lambda)
1. `eligibility` → expect `{is_eligible: true}`.
2. `onboard` (channel=whatsapp) → returns `agent_id`; schedules data-prep jobs.
3. Configure knowledge/skills (configure group — add from OpenAPI specs when needed).
4. `enable` (settings rollout.enabled=true) → agent starts responding to NEW conversations.
5. Handle standby routing: inbound arrives on `standby` when agent has control; take control by
   sending a message; hand back via Thread Control (`pass`).

## Not yet wired
- API route `POST /meta-agent` — blocked by the 300-route cap on API `zllr9lrg7j`
  (raise the "Routes per API" quota, or reclaim slots by consolidating redundant routes).
- Configure/Operate endpoints (skills, knowledge, connectors, eval, test, thread-control) —
  add the same way from their per-endpoint OpenAPI specs.
