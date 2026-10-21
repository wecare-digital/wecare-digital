# Subscribe profile Flow

Selected Meta Flow: `1386523953464380` (`WD_Subscribe_Design_v1`), WABA1 only.
Owner-confirmed **PUBLISHED on 2026-10-21**. The canonical Flow registry now exposes it to the
existing Subscribe keyword/send path; the published Flow itself is immutable from draft tooling.

Definition: `flows/design-drafts/subscribe.json` in the WhatsApp business API package.
Screens: PROFILE -> ADDRESS -> REVIEW -> COMPLETE. No Preferences screen.
The existing WECARE app and `https://wecare.digital/api/wa-business/flow-data`
endpoint remain attached. For controlled QA, use the existing send API with the published Flow,
`flowAction: data_exchange`, and a unique `subscribe-<uuid>-waba-1-ph-<phone>` token.
Use the existing internal `/wa-business/messages/send/flow` API; no new send path is needed.

INIT uses the canonical ContactsTable lookup, displays the derived compact Customer ID,
and prefills only the current structured address. It never reconstructs a deleted address
from old submissions or legacy shipping strings. Missing IDs are assigned on save.

Version 3 includes an optional Username field stored as `profileUsername`. It is customer-entered, not a verified Meta handle; the provider-owned `username`, BSUID, phone and Customer ID are not changed by this field. The username is limited to 50 characters and included in the inbox response table.

Version 3 saves profile fields and the shared `checkoutDeliveryAddress` map with derived
legacy fields through `contact_address`. It preserves customerUuid, permanent ownership,
phone and consent. It neither grants marketing consent nor sends a welcome marketing message.
Name and the core address fields are required. Subscribe does not collect email or email OTP. Address line 2 and landmark are optional.
Country is displayed from the saved address (India for new profiles); its ISO code stays internal.
All addresses must pass the same structural validator as the website. Website payment eligibility checks still apply at payment time.

A profile revision and updatedAt compare protect against stale saves. Retrying the same token
finishes its idempotent Flow submission without repeating the profile update. The Flow does
not create an invoice, order or payment. Existing legacy Subscribe payloads remain isolated.

Validation: local schema plus Meta asset validation, profile/address unit tests, Flow completion,
crypto, inbox projection, canonical routing and business API regression tests.
Handset submission is a separate verification step; sending a draft is not proof of submission.

The confirmation distinguishes a new profile (details saved) from one with a saved address (details updated), preserving the result on retry. Opening messages are edited in Communications -> Manage -> WhatsApp -> Auto response. That editor does not publish this draft or grant subscription consent.

The IAM-only `serviceDesignDrafts` prepare action now refuses `service: subscribe` mutations because this Flow is published. New published Flow IDs belong in the canonical registry instead of the draft builder.

## Workspace Subscribe settings

Communications -> Manage -> WhatsApp -> Auto response -> Subscribe edits separate new/returning opening bodies, button labels and in-Flow confirmations. `subscribe_messages_config` stores the copy. The selected Flow send API uses this copy when no explicit one-off body/button is provided; the profile save handler uses the configured confirmation. Customer ID remains a separate display field, never editable copy. Read failures prevent the workspace editor from overwriting unseen settings; runtime defaults keep confirmations usable on a failed copy-setting read.

Customer search opens the existing canonical ConsentPanel, recording channel, state, source, purpose and reference in the customer's consent ledger. Profile saves and copy changes do not write consent. This records evidence; the existing outbound WhatsApp sender does not consistently enforce this ledger, so these controls must not be described as a universal delivery block. Identity-change acknowledgment is also separate and is not enabled here.

No Preferences screen is restored. The Flow is Published; runtime/backend deployment remains a separate controlled release.
