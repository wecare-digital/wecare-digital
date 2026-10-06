---
inclusion: manual
---

# Emails to Meta: Enable Beta Features on Both WABAs

> **Editor's note, 2026-09-30 — this is a historical record of emails as sent; the
> email text below is NOT edited.** Two values in it are now stale against the live
> Meta payment configurations, and are kept only because rewriting a sent email would
> falsify the record:
>
> - **MCC.** The email states `4722 (Travel Agencies and Tour Operators)`. The live
>   configs on both WABAs report **`7392` (Management, consulting and public relations
>   services)**, verified against Graph `/{waba}/payment_configurations` on 2026-08-23.
>   The authoritative live value lives in `src/config/constants.ts` (`PAYMENT_DETAILS.mcc`).
> - **PayU.** The email requests TPV for PayU. PayU is **retired** — it is no longer a
>   payment gateway on either WABA and its secret is permanently gone. Razorpay is the
>   only gateway. See `.kiro/steering/whatsapp-payments-india-reference.md`.
>
> Open compliance question, unchanged: MCC `7392` describes consulting while purpose
> code `03` is Travel. That mismatch is flagged in `docs/protected-resource-register.md`
> and `bw-crm.md` as needing Meta/Razorpay/business confirmation — it is not something
> to silently "fix" in config.

---

## EMAIL 1 — MAIN REQUEST (Send This First)

**To:** whatsappindia-bizpayments-support@meta.com
**Subject:** Enable Enhanced Payment Links + Checkout Endpoint + Coupons + TPV + Bot API — Both WABAs — WECARE.DIGITAL

---

Dear WhatsApp India Business Payments Team,

We are WECARE.DIGITAL, an active WhatsApp Payments merchant processing live payments via Razorpay and PayU on two WABAs. We request enablement of the following beta features on BOTH our WhatsApp Business Accounts.

### WABAs to Enable

| # | WABA ID | Phone Number | Display Name | API Mode | Payment Status |
|---|---|---|---|---|---|
| 1 | 2094615664435155 | +91 93309 94400 | WECARE.DIGITAL | Cloud API (Direct) | Active — processing payments |
| 2 | 2513394156072604 | +91 99033 00044 | Manish Agarwal | Cloud API (Direct) | Active — processing payments |

### Payment Configurations (Active on Both WABAs)

| Config Name | WABA | Gateway | Merchant ID |
|---|---|---|---|
| WECARE-RAZOR-PAY | 2094615664435155 | Razorpay | [retired Razorpay account] |
| WECARE-PAYU | 2094615664435155 | PayU | 8629516 |
| Razorpay_ManishAgarwal | 2513394156072604 | Razorpay | [retired Razorpay account] |
| PayU_ManishAgarwal | 2513394156072604 | PayU | 8629516 |

### Features Requested (Enable on BOTH WABAs)

#### 1. Enhanced Payment Links (EPL)

Please allowlist both WABAs for Enhanced Payment Links.

We want to use EPL as a fallback for out-of-session payment reminders. Our primary flow is PG Deep Integration (interactive order_details), but EPL gives better UX than plain links for template-based reminders outside the 24-hour window.

- Preferred PGs: Razorpay, PayU
- Sample Razorpay link format: https://rzp.io/i/{link_id}
- Sample PayU link format: https://pmny.in/PAYUMN/{link_id}
- We will provide live sample links upon request
- Template ready: no-header, single dynamic URL button

#### 2. Checkout Endpoint (Coupons + Address Collection + Real-time Pricing)

Please enable the checkout endpoint (data_exchange) feature and link it to all four payment configurations listed above.

We need this for:
- Native address collection during checkout for physical goods (apply_shipping)
- Coupon support (get_coupons, apply_coupon, remove_coupon)
- Real-time inventory and serviceability checks
- Shipping cost recalculation based on customer-selected address

Our checkout endpoint is ready and deployed:
- URL: https://api.wecare.digital/wa-business/checkout-data
- Encryption: RSA + AES-128-GCM (same as WhatsApp Flows)
- All sub-actions fully implemented: get_coupons, apply_coupon, remove_coupon, apply_shipping
- Coupon system: percentage + flat discounts, min order, max discount, free shipping
- Shipping: pin-code-based zone calculation (local/regional/metro/national/remote)

Please link this endpoint to these payment configurations:
1. WECARE-RAZOR-PAY (WABA 2094615664435155)
2. WECARE-PAYU (WABA 2094615664435155)
3. Razorpay_ManishAgarwal (WABA 2513394156072604)
4. PayU_ManishAgarwal (WABA 2513394156072604)

#### 3. Third Party Validation (TPV)

Please enable TPV for both Razorpay and PayU on both WABAs.

We process travel bookings (MCC 4722) and need to validate that high-value payments come from specific customer bank accounts. We understand this is in alpha and are ready to work with Razorpay/PayU to obtain the public encryption keys.

#### 4. WhatsApp Business Bot API

Please enable the WhatsApp Business Bot API on both WABAs listed above.

We need access to the Bot API endpoints to configure automated bot responses, commands, prompts, and welcome messages programmatically via the Graph API. Specifically:

- `GET /{WABA-Bot-ID}?fields=id,prompts,commands,enable_welcome_message` — to retrieve and audit bot configuration
- Bot command management — to set up structured commands (e.g. [retired public path 47a81ed9], /help, /status, /request) that customers can use
- Welcome message configuration — to enable/disable and customize the automated welcome message
- Bot prompts — to configure AI-powered automated responses

We currently handle 65+ payment trigger keywords, AI-powered responses (via Amazon Bedrock), and structured WhatsApp Flows. The Bot API would allow us to:
1. Define discoverable slash commands for customers ([retired public path 47a81ed9], /help, [retired public path 282d0fd5], /request)
2. Configure welcome messages that guide new customers
3. Set up bot prompts for common queries
4. Manage bot state programmatically from our admin dashboard

We verified that the Bot API fields (`prompts`, `commands`, `enable_welcome_message`) are currently returning "nonexisting field" errors on both our WABAs, confirming the feature is not yet enabled for our accounts.

### Business Details

| Field | Value |
|---|---|
| Business Name | WECARE.DIGITAL |
| GSTIN | 19AAFFW7196L1Z8 |
| PAN | AAFFW7196L |
| MCC | 4722 (Travel Agencies and Tour Operators) |
| Purpose Code | 03 (Travel) |
| Address | The W.B.S.I.D.C. Building, Unit 1/20, 81/2/7, Phears Ln, Kolkata, WB 700012 |
| Website | https://wecare.digital |
| App ID | 2238810740192680 |
| App Name | WECARE.DIGITAL |

### What We Have Built (Live in Production)

Our complete integration includes:

- PG Deep Integration with payment_settings (migrated from legacy payment_type)
- Checkout Button Templates with order_details buttons (template: wecare_checkout_v1, APPROVED)
- Interactive order_details messages for in-session payments
- order_status messages for payment confirmation
- Payment Lookup API verification on every capture
- Meta Refund API integration
- Dual webhook processing: Meta webhooks (primary) + direct PG webhooks (backup)
- HMAC-SHA256 signature verification (Razorpay) + SHA-512 reverse hash (PayU)
- Idempotent webhook processing with DynamoDB audit trail
- GST-compliant invoice generation (PNG + PDF) with auto-send on WhatsApp
- 65+ payment trigger keywords (English, Hindi, Hinglish)
- Physical-goods support with beneficiaries
- Order expiration, quick_pay mode, preferred UPI app, UPI limit auto-switch
- WhatsApp Cloud API v25.0 (Direct API with appsecret_proof)

### Technical Stack

- AWS Lambda (Python 3.12) — 44 serverless functions
- DynamoDB — 8 tables with GSIs
- Next.js admin dashboard on AWS Amplify
- S3 + CloudFront for media/invoice delivery

### Contact

| Name | Role | Email | Phone |
|---|---|---|---|
| Manish Agarwal | Owner / Technical Lead | one@wecare.digital | +91 93309 94400 |

We can provide sample payloads, a live demo, or a technical walkthrough at your convenience.

Thank you,
Manish Agarwal
WECARE.DIGITAL

---

## EMAIL 2 — WEBHOOK SUBSCRIPTION CONFIRMATION (Send if needed)

**To:** whatsappindia-bizpayments-support@meta.com
**Subject:** Confirm Webhook Subscription for Payment Status — WECARE.DIGITAL (Both WABAs)

---

Dear Team,

We noticed that payment status webhooks (statuses with type="payment") are not arriving for our WABAs even though we have subscribed to the "messages" field via the subscribed_apps API.

We confirmed via Payment Lookup API that payments are being captured successfully (status: CAPTURED), but the corresponding payment webhook with hasPaymentData=true is not being delivered to our webhook endpoint.

Details:
- WABA 1: 2094615664435155 (+91 93309 94400)
- WABA 2: 2513394156072604 (+91 99033 00044)
- App ID: 2238810740192680
- Webhook URL: Configured via Meta Business Manager
- API: Cloud API (Direct)
- We called POST /{waba_id}/subscribed_apps with subscribed_fields=["messages"] and received success:true

Recent test payments that were captured but no Meta payment webhook received:
- Reference: WD-CT2-84251 — Captured via Razorpay (order_SXUI964OVzHEF4)
- Reference: WD-PAY-CT1-83563 — Captured via Razorpay (order_SXTzve5ASNg0Gp)

Both payments were confirmed captured via GET /{phone_id}/payments/{config}/{reference_id}.

Could you please verify that:
1. Payment status webhooks are enabled for both WABAs
2. The "messages" webhook field subscription includes payment status events
3. There are no configuration issues preventing payment webhook delivery

Thank you,
Manish Agarwal
WECARE.DIGITAL
one@wecare.digital | +91 93309 94400

---

## EMAIL 3 — CHECKOUT TEMPLATE CREATION ON WABA 1 (Send after Email 1)

**To:** (internal note — do this yourself via API or Meta Business Manager)

Create the same checkout button template on WABA 1 (2094615664435155):

Template name: wecare_checkout_v1
Language: en
Category: MARKETING
Body: "Your order for {{1}} is ready to ship! Total: {{2}}. Tap below to complete payment and confirm delivery address."
Footer: "WECARE.DIGITAL"
Button: type=order_details, text="Review and Pay"

Run this command:
```
python scripts/_create_checkout_template.py
```
(Modify the script to use WABA1 ID: 2094615664435155)

---

## SENDING INSTRUCTIONS

1. Send EMAIL 1 first — this is the main request for all beta features on both WABAs
2. Send EMAIL 2 only if payment webhooks continue to not arrive after 24 hours
3. Do EMAIL 3 yourself via API — create the checkout template on WABA 1
4. Follow up in 5 business days if no response
5. CC your Meta representative or BSP contact if you have one

## AFTER META ENABLES THE FEATURES

### Enhanced Payment Links:
- Create templates with dynamic URL button (Razorpay: https://rzp.io/i/ prefix, PayU: https://pmny.in/PAYUMN/ prefix)
- Send template messages with payment link suffix in button parameter
- Payment renders as rich native checkout bubble

### Checkout Endpoint (Coupons + Address):
- Meta links your endpoint URL to payment configurations
- Upload public encryption key via Cloud API
- Implement get_coupons, apply_coupon, remove_coupon, apply_shipping in /wa-business/flow-data
- Customers see "Apply a savings offer" and "Add shipping address" in checkout

### TPV:
- Get public encryption key from Razorpay/PayU
- Encrypt customer bank account details
- Pass encrypted_payment_gateway_data in payment_settings

### WhatsApp Business Bot API:
- Query bot config: `GET /{bot_id}?fields=prompts,commands,enable_welcome_message`
- Set up slash commands: [retired public path 47a81ed9], /help, [retired public path 282d0fd5], /request, /invoice
- Enable welcome message for new customers
- Configure bot prompts for automated responses
- Integrate with existing AI automation (Bedrock) and keyword detection
- Manage bot state from admin dashboard
