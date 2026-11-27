# Public acceptance repair — 27 November 2026

Builds 729 and 730 failed: the exact CI diagnostic is
RotatingPill.tsx react-hooks/set-state-in-effect 0 -> 1. Build 728 was the
last successful deployment when this audit began. The desktop Chromium
artifact from run 45936059435 (revision dcaf7fcaf824) reports 37 failed
routes and one gated, including label-content-name-mismatch on 37,
color-contrast on Activities and aria-hidden-focus (323 nodes) on Anew.
That artifact lacks node selectors; the source changes address concrete
candidate defects, not a claimed new axe pass.

This repair keeps the warning ratchet unchanged, includes the visible
language code in the disclosure label, suppresses focus in hidden editorial
pages, strengthens Activities contrast/focus, and adds bounded axe selectors
and actual pause/resume acceptance. Rerun the full acceptance workflow
against the verified next production revision; its earlier report was
against an older deployed revision. Review lab metrics, particularly the
climate route's main-thread work, and slow-network and physical devices.

Website-only contribution applies to the public checkout API's create arm.
The existing customer-profile sendContribute hook already refuses payment.
Native catalog and staff paths retain their separate authorization. Verify
the backend artifact through the owning customer-commerce release. Website
Razorpay quote, capture verification, order/receipt authority and payment
idempotency remain intact. Status recheck only asks about the existing
attempt. Test authenticated capture, receipt download and failure/recovery
in an approved provider test environment before certifying end-to-end.
No real payment, OTP or message send in anonymous acceptance.
