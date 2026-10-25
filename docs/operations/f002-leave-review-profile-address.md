# WD-F002-LEAVE-REVIEW

Design and numbering reference: **WD-F001-SUBSCRIBE-PROFILE**.

Published Flow: **Meta Flow 993862443003108** (`WD-F002-LEAVE-REVIEW`, PUBLISHED).

Content origin: Meta Flow 940049388908144 (`01. WECARE REVIEW FLOW`), now **DEPRECATED**. F002
kept its questions; nothing may send or open 940049388908144 any more.

## Contract

F001 is used only for the canonical WECARE.DIGITAL naming/numbering pattern.

F002 customer-facing content keeps the review questions that 940049388908144 carried:

1. FEEDBACK
2. REVIEW

### FEEDBACK

- "What's on your mind?" — optional radio choice
  - A feature I'd love
  - Something to improve
  - Something I liked
  - Another thought
- "Your thought" — required text

### REVIEW

Show the submitted thought and complete the review.

There are no profile fields and no address fields in F002.

## Canonical identity

- Flow number: F002
- Flow code / Meta Flow name: `WD-F002-LEAVE-REVIEW`
- Published Flow: `993862443003108` (the runtime id, `lambda_utils/canonical_flows.py`)
- Historical draft (do not reuse for F002): `2352304845587149` / `WD_Leave_Review_Design_v1`
- Deprecated content origin: `940049388908144`

`wecare_leave_review` and the invoice template's review FLOW button open `993862443003108`.
`scripts/check_f002_leave_review.py` verifies that identity read-only.

## Source asset

`amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/f002-leave-review.json`

This asset uses the F001 visual treatment and keeps the 940049388908144 review fields/content. The word `privately` is intentionally omitted from customer-facing copy.
