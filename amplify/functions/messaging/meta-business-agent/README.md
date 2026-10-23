# meta-business-agent — Meta Business AI Agent (WhatsApp)

Backend for onboarding + configuring Meta's Business AI Agent on WhatsApp.
Auth token from Secrets Manager (`wecare/meta-system-user-token`).

## Implemented
- `onboard` — `POST https://api.facebook.com/{entity_id}/agent_onboarding/?channel=whatsapp`
  (entity_id = WhatsApp Business Phone Number ID; body `{}`; → 201).
- `entities` — returns the known WABA phone-number IDs + valid channels.

## To add (from per-endpoint OpenAPI specs)
Meta exposes a spec per endpoint at `…/<endpoint>/v2.0.0.openapi.yaml` and a
clean `…/v2.0.0.md`. Pull those to implement accurately:

| Group | Endpoint (doc) |
|---|---|
| onboard | agent-eligibility, agent-allowlist, agent-settings |
| configure | agent-knowledge-business-info, -faqs, -files, -websites, agent-skills, connectors, connector-tools |
| operate | agent-eval, agent-event, agent-test, thread-control-cloud-api |

The scraped Markdown is in `s3://wecare-digital-get/o/stream/media/docs/meta-business-agent/`
(served as `https://wecare.digital/get/o/stream/media/docs/meta-business-agent/`).
Recommended: extend the docs-scraper to also fetch each endpoint's
`v2.0.0.openapi.yaml` so this handler can be generated/validated against the spec.

## Deploy
Zip deploy (matches other Python lambdas): `aws lambda create-function` /
`update-function-code` with `handler.lambda_handler`, role `wecare-digital-lambda-role`.
Add API route `POST /meta-agent` → this function.

## Frontend
`src/pages/dm/meta-agent/index.tsx` — trigger onboarding per WABA + view response.
