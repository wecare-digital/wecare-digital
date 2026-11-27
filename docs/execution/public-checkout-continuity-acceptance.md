# Checkout continuity and theme acceptance

This change preserves server-priced quotes, verified payment capture, customer authentication, delivery rules, and the existing provider. The website contribution is one INR 300 line, with no WhatsApp payment option. No automatic payment is initiated by opening the page, signing in, or saving a name.

## Review URLs

- https://wecare.digital/shop/
- https://wecare.digital/checkout/?contribute=1
- https://wecare.digital/checkout/
- https://wecare.digital/auth?return=/checkout/
- https://wecare.digital/checkout/status/ (requires a valid attempt)
- https://wecare.digital/checkout/success/ (requires verified capture)
- https://wecare.digital/orders/

## Acceptance before declaring the flow complete

1. On the exact deployed revision, use an isolated browser at 390, 768, 1440 and 280 CSS pixels, plus 160 as a stress case. Check review, sign-in, OTP, profile, quote, payment window, status and orders for responsive layout, focus, contrast and visible/accessibility labels.
2. Verify anonymous contribution review, explicit cart replacement or cancellation, sign-in return, fixed quantity and website-only rail. Use an approved synthetic account or an intercepted browser fixture; do not send OTPs to real customers.
3. With a test account, confirm a contribution requires only verified identity, while physical goods require validated delivery details. Exercise the definitive missing-address bootstrap refusal, name save, expired session and retry. Do not invent addresses or bypass server authorization.
4. Confirm a server quote totals 30000 paise, mismatched or incomplete quotes do not enable payment, and the SDK failure provides retry guidance without a new payment attempt. Exercise modal duplicate clicks and dismissal, status recovery, and verified capture in an approved provider test environment. Never perform real charges during QA.
5. Check ordinary product and service checkout, delivery, and the existing WhatsApp rail for regressions. Capture per-screen screenshots from that exact revision. The success link is not proof of payment.

CI unit tests are not a substitute for browser tests, payment sandbox capture, or physical-device checks. Re-run the public acceptance matrix after deployment and use failing element targets to resolve any remaining accessibility or geometry findings.

Merge repair: retain production PR #2439's hero hydration and language disclosure, its backend website-only rail guard, and its status recheck; the status page now checks the same attempt after a stall or unavailable result. Associate a delayed status handoff with the originally reviewed basket, not a later cart.
