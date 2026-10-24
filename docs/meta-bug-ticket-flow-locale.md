# Meta Bug Report — WhatsApp Flows System UI Text Showing Wrong Language

**Date:** 2026-04-15
**Reporter:** WECARE.DIGITAL
**Priority:** High
**Category:** WhatsApp Flows — Localization / System UI Rendering Bug

---

## Summary

WhatsApp Flows system-rendered UI text (e.g., "(optional)" field markers and "Managed by" footer) is displaying in **Portuguese (pt_BR)** instead of **English (India / en_IN)** on a device where the user's WhatsApp language is set to English (India). Developer-defined text from the Flow JSON renders correctly in English.

## Affected Flow

- **Flow ID:** `1262971692700761`
- **Flow Name:** Subscribe / Profile
- **WABA ID:** `2094615664435155` (WECARE.DIGITAL)
- **WABA Phone:** +91 93309 94400 (Phone Number ID: `1016149501586345`)
- **Flow JSON Version:** 7.3
- **Data API Version:** 4.0
- **Flow Status:** PUBLISHED
- **Data Endpoint:** `https://wecare.digital/api/wa-business/flow-data`

## Environment

- **Device OS Language:** English (India)
- **WhatsApp App Language:** English (India) — as reported by user
- **WABA 2 (also affected):** Flow ID `951987930811295`, WABA ID `2513394156072604` (Manish Agarwal), Phone: +91 99033 00044

## Bug Description

### What is happening:
When a user opens the Subscribe flow (ID: `1262971692700761`), the following system-rendered UI elements appear in **Portuguese** instead of English:

1. **"(opcional)"** — The optional field indicator on non-required TextInput components. Should display as **(optional)** in English.
2. **"Gerenciada por Manish Agarwal. Saiba mais"** — The flow footer attribution text. Should display as **"Managed by Manish Agarwal. Learn more"** in English.

### What should be happening:
All system-rendered UI text should respect the user's WhatsApp app language setting (English India / en_IN) and display in English.

### What IS working correctly:
All developer-defined text from the Flow JSON renders in English as expected:
- Screen title: "Subscribe" ✅
- Field labels: "Phone Number", "WhatsApp Username", "Email Address", "Organization", "Job Title" ✅
- Helper text: "Include country code: +1 555 123 4567", "Your WhatsApp username", "Enter your email address", etc. ✅
- Button text: "Next" ✅

## Evidence

### Screenshot
The attached screenshot shows the PERSONAL_INFO screen of the Subscribe flow where:
- All developer-defined labels and text are in English
- The "(opcional)" marker on the WhatsApp Username field is in Portuguese
- The footer "Gerenciada por Manish Agarwal. Saiba mais" is in Portuguese

### Flow JSON Verification
The Flow JSON does NOT contain any Portuguese text. All text is hardcoded in English. The system-rendered strings ("optional", "Managed by", "Learn more") are NOT part of the Flow JSON — they are rendered by the WhatsApp client.

## Technical Analysis — Confirmed NOT from Endpoint or Webhook

### Full data flow trace:

1. **Flow trigger message (outbound webhook):** The flow is sent via `POST /messages` with `interactive.type=flow`. The payload contains `flow_id`, `flow_cta`, `flow_action`, `flow_token`, `body.text`, and `footer.text`. There is NO `language` or `locale` parameter in the WhatsApp Flows interactive message spec (unlike message templates which have `language.code`). The footer text sent is "WECARE.DIGITAL" (English). **No Portuguese text is sent.**

2. **Data endpoint INIT response:** When the user opens the flow, Meta sends an encrypted INIT request to `https://wecare.digital/api/wa-business/flow-data`. The handler decrypts it and calls `subscribe.handle_init()` which returns:
   ```json
   {"screen": "PERSONAL_INFO", "data": {}}
   ```
   The response contains NO text at all — just a screen navigation instruction with empty data. **No Portuguese text is returned.**

3. **Flow JSON (subscribe-flow.json):** All developer-defined text is in English. The field `wa_username` has `"required": false` which triggers the WhatsApp client to auto-render the "(optional)" marker. The word "opcional" does NOT exist anywhere in the flow JSON. **No Portuguese text exists in the flow definition.**

4. **Intermediate screen navigation:** For screens between PERSONAL_INFO and REVIEW, the router returns `{'data': data}` (pass-through of the user's own form data). **No system text is injected.**

### Conclusion:
The two Portuguese strings — `(opcional)` and `Gerenciada por Manish Agarwal. Saiba mais` — are **WhatsApp client-side system UI strings** rendered automatically by the WhatsApp app. They are NOT served by the data endpoint, NOT in the flow JSON, and NOT in the webhook payload. The business has zero control over these strings.

The `(opcional)` marker is triggered when a TextInput component has `"required": false`. The "Managed by" footer is always rendered by the client using the WABA verified name.

### Root cause hypothesis:
The WhatsApp client is using the wrong locale for Flow system UI rendering. Possible causes:
- **Bug in WhatsApp client locale detection** — The client is not correctly reading the app language for Flow system UI rendering
- **WABA-level locale override** — The WABA or Business Manager account locale (owner: "Manish Agarwal") may be set to Portuguese, and the Flow renderer is incorrectly inheriting the WABA owner's locale instead of the end-user's WhatsApp app language
- **Facebook/Meta account language** — The personal Facebook account of the WABA owner may have Portuguese as its language, which is leaking into the Flow system UI

### Verified: All business settings are correct (NOT the cause)
Confirmed via both Meta Business Manager UI and Graph API:
- WABA2 (Manish Agarwal): Currency = INR, Time Zone = Asia/Calcutta, Business verification = Verified, Account status = Approved
- WABA1 (WECARE.DIGITAL): Currency = INR, timezone_id = 71 (Asia/Kolkata)
- Business Manager (Wecare.Digital, ID: 382642103987922): timezone_id = 71
- App (WECARE.DIGITAL): category = Utilities, no locale field exposed
- System User: Manish Agarwal (ID: 871324399114953), no locale field exposed
- Both flows (1262971692700761 and 951987930811295): PUBLISHED, no locale/language field exists in Flows API

There are ZERO Portuguese or Brazilian settings anywhere in the WABA, Business Manager, App, or Flow configuration. All settings are correctly configured for India/English.

### Flows API has no language parameter (confirmed from official docs)
Per Meta's official documentation:
- Flows API (https://developers.facebook.com/docs/whatsapp/flows/reference/flowsapi): Create/update parameters are `name`, `categories`, `flow_json`, `endpoint_uri`, `application_id`, `publish`. NO `language` or `locale` parameter exists.
- Flow interactive message (https://developers.facebook.com/docs/whatsapp/flows/guides/sendingaflow): Send parameters are `flow_message_version`, `flow_token`, `flow_id`, `flow_cta`, `flow_action`, `mode`. NO `language` parameter. Only message templates have `"language": {"code": "..."}` — Flows do not.
- Flow JSON spec (https://developers.facebook.com/docs/whatsapp/flows/reference/flowjson): Top-level fields are `version`, `data_api_version`, `routing_model`, `screens`. NO `language` field.
- Flow data endpoint response: Returns `screen` + `data`. NO locale field accepted or processed.

There is NO way for a business to control or override the language of system-rendered UI text in WhatsApp Flows. This is entirely a Meta client-side rendering issue.

## Steps to Reproduce

1. Set WhatsApp app language to English (India) on an Android device
2. Open a conversation with +91 93309 94400 (WECARE.DIGITAL) or +91 99033 00044 (Manish Agarwal)
3. Trigger the Subscribe flow (send "subscribe" keyword)
4. Open the flow when the CTA button appears
5. Observe the PERSONAL_INFO screen
6. Note that "(optional)" shows as "(opcional)" and footer shows in Portuguese

## Expected Behavior

- "(optional)" should display in English
- "Managed by Manish Agarwal. Learn more" should display in English
- All system-rendered UI text should match the user's WhatsApp app language

## Actual Behavior

- "(opcional)" displays in Portuguese
- "Gerenciada por Manish Agarwal. Saiba mais" displays in Portuguese
- System-rendered UI text does NOT match the user's WhatsApp app language

## Impact

- **User confusion:** Indian users with English language settings see mixed-language UI
- **Trust issue:** Users may question the legitimacy of the flow when system text appears in an unexpected language
- **Accessibility:** Users who don't read Portuguese cannot understand system UI elements

## Requested Action

1. Investigate why Flow system UI strings are rendering in Portuguese when the user's WhatsApp language is English (India)
2. Confirm whether the WABA owner's Business Manager locale is incorrectly influencing end-user Flow rendering
3. If this is a known behavior, provide documentation on how to control the locale for system-rendered Flow UI text
4. Fix the bug so system UI text always follows the end-user's WhatsApp app language setting

## Additional Context

- The same issue likely affects all flows on this WABA, not just the Subscribe flow
- The WABA 2 clone (Flow ID: `951987930811295`) on WABA `2513394156072604` may also be affected
- No locale or language parameters are available in the Flow JSON spec or Flows API to control system UI language

---

**To file this with Meta:**
- Meta Business Help Center: https://business.facebook.com/help
- Meta Developer Support: https://developers.facebook.com/support/bugs/
- Direct API Bug Report: POST to `https://graph.facebook.com/v25.0/bugs` with access token
