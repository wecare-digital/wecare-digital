# WD-F002-LEAVE-REVIEW

Design reference: **WD-F001-SUBSCRIBE-PROFILE**.

## Customer screen order

1. PROFILE
2. ADDRESS
3. REVIEW
4. COMPLETE

The order intentionally matches F001 so customers learn one WECARE.DIGITAL pattern.

## PROFILE

Fields, in F001 order:
- Full name — required
- WhatsApp username — optional
- Organization — optional
- Job title — optional

## ADDRESS

Fields, in F001 order:
- Street address — required
- Apartment / suite / unit — optional
- Landmark / neighborhood — optional
- City — required
- State / region — required
- Postal code — required
- Country — required

The country selector reuses the same 195-country data source as F001.

## REVIEW

The page first shows the entered profile and address, then asks:
- What is this about?
- Your review

Topics remain:
- Something I liked
- Something to improve
- A feature I would love
- Another thought

The review remains private.

## COMPLETE

The final screen shows the review and submits:
- flow_key = wd_leave_review_v2
- schema_version = 5
- all profile fields
- all address fields
- topic
- idea

## Compatibility

The currently published review Flow remains unchanged in this branch.

The new draft is:
`amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/f002-leave-review.json`

Backend review storage accepts both:
- existing schema 4 payloads from the published review;
- schema 5 payloads from WD-F002-LEAVE-REVIEW.

For schema 5, full name, street address, city, state/region, postal code and country are
required. Profile/address are stored as review snapshots. Trusted WhatsApp sender identity
(phone, contact id, WhatsApp display name and customer UUID when present) remains server-owned;
customer-entered name/address do not overwrite identity.
