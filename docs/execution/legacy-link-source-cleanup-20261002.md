# Legacy link-source cleanup - 2026-10-02

Owner requested a deep purge of retired website references from current files and a Git push, followed by reconciliation of the local stack checkout.

## Runtime source corrections

- SEO page inventory now reads the generated public-page catalogue rather than an obsolete external list. The catalogue is packaged with the SEO Lambda; CI watches catalogue changes and tests its parity without making upstream requests.
- AI, inbound WhatsApp, voice follow-up, notification, and RCS link defaults use current customer destinations.
- Product URLs in the seven-product snapshot point at current shop pages. The fetcher now generates those canonical destinations, so a refresh cannot restore the retired storefront URLs.
- Product normalization no longer invents legacy product pages. SEO instruction examples, catalogue-builder placeholders, and page-manager inventories use current pages.
- The payment link generator shares its existing UPI deep link directly instead of advertising a missing website wrapper. The payee and amount calculation are unchanged.
- RCS template artifacts use current request/order, media and short-link destinations. This is repository cleanup, not a claim that provider-approved remote templates were changed.
- Apple associated-domain paths refer to current workspace routes. Existing API paths and bot commands are preserved; a command or backend route with the same word is not a retired public page.
- Retired URL lists were removed from probe/test files; tests use synthetic missing paths and assert the universal missing-page behavior. Current dated audit records and historical snapshots use readable redactions for obsolete public URL references. Git history is not rewritten.

## Validation and limits

Full frontend tests and production build passed. Focused Python tests passed, including catalogue parity, no upstream page-list call, hosting rules, product normalization, notifications and voice fallback handling. Current public page catalogue remains generated from the actual source pages.

Repository link-source cleanup does not by itself prove the contents of every deployed Lambda, DynamoDB override, provider template, or previously delivered customer message. The push triggers the existing frontend and SEO deployment workflows. No live provider templates, messages, payments, DNS, certificates or secrets are changed by this cleanup.

## Local stack

The screenshot was older than the live Git state. At inspection local stack already matched origin/stack. The remaining Meta request draft and OTP diagnosis evidence were checked, committed and pushed explicitly; newer in-progress OTP findings were preserved for the final reconciliation.
