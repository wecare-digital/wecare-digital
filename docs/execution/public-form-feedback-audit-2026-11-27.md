# Shared public form and feedback follow-up — 2026-11-27

This complements PR #2434's shared search fields, support viewport, cards,
pagination and actions. Merge and deploy #2434 first for the normal-flow search
layout. This follow-up touches independent files; no new backend or infrastructure.

- Voice search now guards the asynchronous start, catches unsupported constructors,
  permits cancellation, reports permission/audio/network/language/no-speech failure
  with a text-search fallback, and exposes a live status. It does not log or send
  speech transcripts beyond the existing route-owned search callback.
- Customer sign-in gains visible keyboard focus, IME-safe country-search Escape,
  focus recovery, narrow reflow and reduced-motion handling.
- Checkout profile/address gain visible focus, saving-state input protection,
  wrapped copy, linked field errors and an actionable PIN format hint using the
  existing PublicNotice. Authentication, required fields, validation, API payloads,
  private-file and payment authority are unchanged.
- The existing PublicNotice/PublicToastProvider and ActionNotificationProvider already
  define shared feedback roles, persistent errors and typed success keys. Do not
  replace them with raw provider messages or duplicate toast systems.
- Existing PageMeta, public route catalogue and export verification own metadata,
  canonical URLs and discovery; preserve them. Per-page live metadata, performance,
  slow-network and accessibility checks remain necessary.

## Acceptance

Run typecheck, lint and regression tests with the existing Node 24 CI. Use the
existing production build and read-only browser runner. Verify voice start/cancel,
permission denial, missing microphone, no speech and offline on supported real
browsers; no voice permissions or actual customer submissions should be triggered
by automated public smoke tests. Check auth country picker focus/Escape/reflow
without submitting OTP, and checkout validation in a safe test environment.

No physical device, real permission dialog, checkout submission, performance
measurement or screen-reader run is claimed here. No new release gate or native
app build is introduced.
