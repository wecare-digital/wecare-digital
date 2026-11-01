# F008 Referral — Meta draft-only asset upload (review gate)

**Target:** Existing Meta Flow `1933489271340286` (`WD-F008- Referal`) on primary messaging account `2094615664435155`.

**Scope:** Enable an authenticated **Admin** to update this one **DRAFT** Flow JSON using the existing Workspace POST `/wa-business/flows/assets?flowId=1933489271340286` path. Never publish, alter templates, send messages, create a new Flow, or register F008 as a published customer capability.

## Exact draft UX

- `REFER`: Required **Their name**, **WhatsApp number** and **Anything we should know?** (required textarea, displayed as heading with label `Tell us more`).
- `REVIEW`: Echo all three inputs; require explicit permission confirmation.
- `CONFIRMATION`: **You're all set.** / **Thanks for the intro! We've received your referral.** / Done.
- Same WECARE.DIGITAL embedded branded imagery, single-column layout and typography as the existing F006 design.
- No dropdown, optional field, referral reference number, rewards or marketing-consent inference.

JSON: `docs/whatsapp/drafts/f008-referral-preview.json` (Flow JSON v7.3).

## Security controls

The existing seven canonical PUBLISHED Flow identities, Meta list filters, and FlowRegistry rules remain unchanged.

For the **noncanonical** F008 ID only, the asset route requires **Admin** authentication and a fresh server-to-Meta Graph read that proves: exact Flow ID and name, DRAFT status, ownership by primary account, and attachment to the configured WECARE Meta app. Fail closed if anything differs; refuse arbitrary asset names/types or WABA identifiers. Only `flow.json` / `FLOW_JSON` is allowed. The upload does not call Meta Publish.

Other unregistered drafts still return 404. The draft GET assets endpoint is also Admin-only.

## Verification / release checklist

1. Run `python -m pytest -q tests/test_f008_draft_asset_policy.py`.
2. Review and deploy the scoped handler and policy module only after authenticated routing and rollback checks; do not change customer-routing or publishing controls.
3. An authenticated Admin sends the prepared JSON to the existing asset-upload endpoint or uses the Workspace staff asset upload control, providing the exact F008 ID. **Never invoke the Lambda with a forged HTTP authorizer context or bypass the Admin check.**
4. Require Meta upload success and **zero validation errors**. Read back the Flow details and assets through authenticated staff APIs.
5. Open `https://business.facebook.com/latest/whatsapp_manager/flow_edit/?business_id=382642103987922&tab=flow-edit&id=1933489271340286&asset_id=2094615664435155`, check every screen in Meta Run, and verify **Draft** status.
6. Do **not** publish F008 until referral submissions are securely processed and stored by the correct backend; the visual review JSON does not implement that server-side intake.

## Current state

This PR prepares a safe draft upload pathway; merging code or creating a GitHub asset **does not automatically save anything in Meta**. Live Meta save and on-platform validation must be evidenced separately.
