# WhatsApp Template Builder

Backend: `amplify/functions/messaging/whatsapp-template-management`. Validation service:
`amplify/functions/shared/lambda_utils/template_validation.py`. TTL:
`lambda_utils/template_ttl.py`.

## Components
- **HEADER** (optional): `TEXT` (≤60 chars, ≤1 variable, example required if variable),
  or media `IMAGE/VIDEO/GIF/DOCUMENT` (header_handle from media upload), or `LOCATION`
  (UTILITY/MARKETING only — not AUTHENTICATION).
- **BODY** (required): ≤1024 chars, multiple variables allowed, examples required.
- **FOOTER** (optional): ≤60 chars, no variables.
- **BUTTONS** (optional): see button rules.

## Variable rules
- Positional `{{1}}` must be sequential from `{{1}}`.
- Named `{{name}}` supported, but **do not mix** named + positional in one component.
- `detect_parameter_format()` returns `POSITIONAL | NAMED | MIXED | NONE`.

## Examples
If a component has variables it must provide example values (`example.body_text`,
`example.header_text`, named-param variants). Validation flags missing/short examples.

## Button rules
- ≤10 buttons total; ≤1 COPY_CODE; ≤1 PHONE_NUMBER; ≤2 URL; ≤10 QUICK_REPLY.
- Button text ≤25 chars; URL ≤2000; COPY_CODE example ≤20; phone ≤20.
- Quick replies must be contiguous (one group).
- 4+ buttons → warning (may truncate on desktop).
- Types: QUICK_REPLY, URL, PHONE_NUMBER, COPY_CODE, VOICE_CALL, FLOW (+ OTP/MPM/SPM/
  CATALOG placeholders).

## Flow buttons
`validate_flow_button()` requires `text` and one of `flow_id | flow_name | flow_json`;
`flow_action` ∈ {navigate, data_exchange}; `navigate` requires `navigate_screen`.

## TTL rules (`message_send_ttl_seconds`)
- AUTHENTICATION: 30–900s, `-1` allowed (30 days). Recommend ≤ OTP/code expiry.
- UTILITY: 30–43200s, `-1` allowed.
- MARKETING: 43200–2592000s, `-1` **not** allowed.
Routes: `GET /wa-business/template-ttl/rules`, `POST /wa-business/template-ttl/validate`,
`POST /wa-business/templates/{id}/ttl`. A `template_ttl_cleared` SystemEvent is raised
if a category change clears TTL.

## Validate / send-test / refresh
- `POST /whatsapp/templates/validate` → `{ ok, errors, warnings }`.
- `POST /whatsapp/templates/{id}/send-test` → send to a test recipient.
- `POST /whatsapp/templates/{id}/refresh` → re-fetch live status/category/quality.

## Common Meta errors
- 132000 parameter count mismatch · 132001 template does not exist / wrong language ·
  132005 translation mismatch · 100 invalid parameter · 131009 parameter format.
The UI shows a safe message + `fbtrace_id` via `MetaErrorPanel`.

## UI
Builder wizard (Basics → Header → Body → Footer → Buttons → Flow button → TTL →
Preview → Submit) with live `WhatsAppChatPreview`/`TemplatePreviewCard`, variable
detector, button-grouping validator, payload + cURL preview, save draft, duplicate,
import/export JSON.
