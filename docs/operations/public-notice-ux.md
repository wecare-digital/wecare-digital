# Public/customer notification system

Public pages do not mount the authenticated Workspace `ToastProvider`.
They use `src/components/public/PublicNotice.tsx` and the one-at-a-time
`PublicToastProvider` instead. Both use the **same global action-toast CSS
classes and design tokens**; their authentication scope and lifecycle remain
separate.
The [31 October 2026 inventory](../audits/public-notification-surface-inventory-20261031.md)
records **61 original render sites across 16 files**, not 61 unique toasts.
Its source links and counts describe that audit snapshot; do not replace them
with claims of current runtime coverage.

## Final public API/action wording (1 November 2026)

All customer-facing **action feedback** now selects a trusted status key from
`src/lib/publicActionNotices.ts`, never a raw API, Meta or provider message.
The shared `PublicToastProvider.showToast` accepts *only* a typed status key
and rejects unrecognized/WhatsApp-failure values at runtime. Only **one** readable, content-aligned toast is shown at a time.

| Outcome | Exact public text | Where |
|---|---|---|
| `processing` | `Processing…` | Low-risk action toast; page-local progress where necessary |
| `success` | `Done.` | Non-WhatsApp action toast, e.g. copy |
| `failure` | `Couldn't complete. Try again.` | Low-risk toast or persistent page error |
| `blocked` | `This action is unavailable right now.` | Low-risk toast or persistent page error |
| `whatsappAccepted` | `Sent to WhatsApp.` | ONLY when explicit sender acceptance is known |
| `whatsappFailed` | `Couldn't confirm. Check WhatsApp.` | Persistent inline warning, NEVER an auto-dismissed toast |

For API failures, classify known HTTP statuses / domain outcomes to
`blocked` or `failure`; do not show `response.message`,
`failure.message`, HTTP error text, exception strings or configuration
details. Sign-in uses the already-approved `signInMessages.ts` text for
recognized code/number states, and generic feedback for unknown API text.

**Vault WhatsApp payments are sensitive:** HTTP `202` is a successful HTTP
response but can carry `PAYMENT_REQUEST_UNCONFIRMED`. Show
`Sent to WhatsApp.` only for the **exact**
`PAYMENT_REQUEST_SENT` outcome; all other successful HTTP outcomes get a
persistent `Couldn't confirm. Check WhatsApp.` warning and status refresh.
Do not start a second payment request automatically.

This is **not** permission to replace payment uncertainty, `Do not pay
again.` guidance, address/OTP field validation, Vault paid-access state or
weather/search result information with generic fleeting popups. Those stay
inline/on-panel with the context needed for a safe decision. Unifying action
language does not mean discarding financial facts or important recovery
instructions. Workspace has the same toast CSS, but its operational message
vocabulary is intentionally separate.

## One readable, mobile-safe action toast — Public and Workspace (1 November 2026)

Both apps now use **one global class and one global host rule** from
`src/styles/inner-ux.css`: `.wc-action-toast` and
`.wc-action-toast-host`. The same tokens in `src/styles/tokens.css`
control their presentation. Do not reimplement toast colors/padding/sizing
inside `PublicNotice.tsx` or an independent Workspace `.toast` rule.

The shared design: pale-lime `#f6fce4` background, dark `#1a1a1a` text,
lime `#d8f382` **4px** inline-start stripe, **16px** semibold text
on desktop and mobile, **12px × 16px** padding, **12px** corners,
minimum width **264px**, and maximum width **360px**. A quiet shadow
improves visibility. No status icons, checkmarks, dots, or stacked toasts.

Both notifications align with the **right edge of the shared content
measure**, not the extreme viewport corner:
- **Public:** below the 108px desktop header (116px from top); below
  the 96px mobile header (104px from top).
- **Workspace:** below that same header **and its additional action bar**
  (180px desktop; 162px mobile). On extremely narrow devices the Workspace
  action-bar clearance grows to allow the buttons to wrap.

On phones, the host uses safe-area-aware **16px** horizontal clearance,
wraps long/unbroken text, and constrains height with scrolling when needed.
Ordinary action success stays visible for **5 seconds** (Workspace included);
low-risk public copy failures explicitly allow **6.5 seconds**. Processing
can remain pinned and critical WhatsApp/payment uncertainty stays inline.
Forced-colors and reduced-motion preferences retain functional feedback.
Inline/payment/authentication/Vault errors are **not** changed into
transient toasts.

The PublicShare Copy-link action routes through the public toast host on
public routes and the Workspace toast host inside Workspace. Its label,
icon and accessible name stay "Copy link" instead of becoming a second
"Copied" confirmation. No independent share-local toast or live region
is mounted. The Workspace host receives the same canonical "Done." /
"Couldn't complete. Try again." copy outcome, rather than separate
"Link copied." wording. Both hosts replace the previous toast: only the
host appropriate to the current route is mounted, never both at once.
The Workspace dismiss button stays keyboard-accessible and unobtrusive.

## Three public modes

| Mode | Used for | Lifespan | Accessibility |
|---|---|---|---|
| `toast` | Copy success, accepted WhatsApp invitation, short action feedback | Caller controls; only low-risk success auto-clears | Polite `role=status`, except error `role=alert` |
| `inline` | Order failures, auth errors, checkout and profile errors, Vault payment/access uncertainty | Persistent until resolved, navigated away or superseded | `role=alert` for errors; polite for information |
| `screen-reader` | Results and progress already evident in adjacent visible controls | State-driven, not timed | One visually hidden polite live region |

The appearance is the same WECARE.DIGITAL lime/forest treatment across the three
modes. Severity is conveyed through the wording, role and weight, not a
red-versus-green signal. Never dismiss payment uncertainty or field errors
after a fixed timeout. A component render is not proof that an operation
completed.

### First migration

- **Orders:** Subscribe, Leave Review and explicit Contribute payment requests
  share `Processing…`, `Sent to WhatsApp.` and
  `Couldn't confirm. Check WhatsApp.`. Only the endpoint's exact accepted
  outcome permits the success; acceptance never proves WhatsApp delivery
  or that a Contribute payment was completed.
  Invoice/order errors stay persistent; generic copy success `Done.` clears
  after 2.5 seconds, while the keyboard-copy fallback persists.
- **Cart/Checkout:** Action notices remain persistent, with error severity
  announced assertively. Quote, price and payment confirmation remain on
  their existing inline screens.
- **Checkout profile + Auth:** Validation and save errors are persistent; the
  auth error retains its `auth-error` ID used by `aria-describedby`.
- **Vault:** Access, missing-file and payment-action failures remain persistent
  inline. Paid/unverified access stays visible with its `Do not pay again`
  guidance; no conversion to a disappearing toast.
- **PublicShare:** Public and Workspace copy actions show one brief
  canonical `Done.` toast via the already-mounted host, with no
  second changing "Copied" button label or local toast fallback.
- **Requests panel (dormant):** The clipboard helper now delegates
  success/failure to the public toast. The selected-ID keyboard-copy
  instruction remains next to the affected control if Clipboard API
  rejects the write; its legacy success live region was removed.
- **Product checkout CTA:** The "No charge made" recovery error now uses
  the common `PublicNotice` inline renderer instead of bespoke alert
  styling. No checkout, cart or payment logic changed.

The other notification locations from the 61-site inventory are **not
automatically changed**. In particular, header/search counts, translation,
VayuLok live/map/weather readings, VayuLok history, Blog, Elsewhere,
Checkout Result and field-level address validation keep their existing
on-screen or assistive-technology status behavior.

## Customer-facing wording

Public notices must describe what a **customer can do or expect**, not an
internal setup/configuration state. Do not display backend status codes,
WhatsApp template identifiers, API names, WABA, Lambda, or provider/debug
errors in a toast.

Contribute's current native payment-request path is **not** a template
configuration placeholder: it can submit an authenticated, fixed-amount
WhatsApp Review & Pay request. The exact `PAYMENT_REQUEST_SENT` result with
the verified ₹300 amount, INR currency and payment-attempt ID is the ONLY
successful Contribute response. It may display `Sent to WhatsApp.`, which
means acceptance, never payment or delivery. A 409 release block
(`AMOUNT_NOT_SETTLED` or `CONTRIBUTION_TAXABLE_NOT_RELEASED`) and any
uncertain send both show `Couldn't confirm. Check WhatsApp.` as a
**persistent inline warning**. Neither a 409 nor an unknown outcome may be
presented as a successful send, and there is no automatic retry.

Keep technical context in staff logs and engineering tools; preserve
actionable, payment-safe inline error messages.

## WhatsApp action boundary

**Subscribe** and **Leave Review** can send authenticated WhatsApp
invitations from the Orders action menu. An explicit **Contribute** action
can initiate the authenticated native WhatsApp payment-request path described
above. Submit Request, Request Amendment, Drop Docs, Vault, Shipments >
Track, and Shipments > Pickup Request are navigation entries; they must not
invent a `Sent to WhatsApp.` success. Shipped Orders is excluded.
This UI change does not alter send endpoints, payment amounts, retry rules or
provider state machines.

## Testing

`node --test tests/public_toast_before_style_contract.test.mjs`
checks the shared compact styles, top-right positions and one-toast behavior.
`node --test tests/public_customer_notification_copy.test.mjs`
checks plain-language Contribute messaging and acceptance boundaries.
`node --test tests/public_action_feedback_contract.test.mjs`
checks canonical action wording, refusal of raw API strings and the Vault
HTTP-202 acceptance guard.
`node --test tests/public_single_action_feedback_contract.test.mjs`
checks duplicate Share/Requests success texts were retired, Product
checkout uses the existing inline notice surface, and payment/OTP/Vault
safety instructions remain visible.
Run full TypeScript build, tests, and browser QA for keyboard, Clipboard
API failure, small screens, RTL and long error strings before release.
These checks are not replaced by CodeQL or a source-only audit.
