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

## One small, mobile-safe action toast — Public and Workspace (1 November 2026)

Both apps now use **one global class and one global host rule** from
`src/styles/inner-ux.css`: `.wc-action-toast` and
`.wc-action-toast-host`. The same tokens in `src/styles/tokens.css`
control their presentation. Do not reimplement toast colors/padding/sizing
inside `PublicNotice.tsx` or an independent Workspace `.toast` rule.

The shared design: pale-lime `#f6fce4` background, dark `#1a1a1a` text,
bright lime `#d8f382` **3px** inline-start stripe, **13px** semibold text,
**6px × 10px** padding, **8px** corners, and maximum width **288px**.
No status icons, checkmarks, dots, or stacked toasts.

Both notifications appear at the **physical top-right** of the available
page content, with 12px safe-area-aware right spacing:
- **Public:** below the shared 108px desktop header (116px from top); below
  the 96px mobile header (104px from top).
- **Workspace:** below that same header **and its additional action bar**
  (180px desktop; 162px mobile). On extremely narrow devices the Workspace
  action-bar clearance grows to allow the buttons to wrap.

On phones, the host uses safe-area-aware left/right insets, keeps the toast
right-aligned, wraps long/unbroken text, and constrains height with
scrolling when needed. Forced-colors and reduced-motion preferences retain
functional feedback. Inline/payment/authentication/Vault errors are **not**
changed into transient toasts.

The PublicShare Copy-link action routes through the public toast host on
public routes and the Workspace toast host inside Workspace. Its old
local fallback is used only if **neither** provider is available.
Both hosts keep only the latest action toast; lifecycle and ARIA roles
remain distinct where they serve different authentication scopes.
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

- **Orders:** Subscribe and Leave Review share `Processing…`,
  `Sent to WhatsApp.`, and `Couldn't confirm. Check WhatsApp.`.
  The accepted toast describes **provider acceptance**, not delivery.
  Invoice/order errors stay persistent; copy success clears after 2.5 seconds,
  while the keyboard-copy fallback persists.
- **Cart/Checkout:** Action notices remain persistent, with error severity
  announced assertively. Quote, price and payment confirmation remain on
  their existing inline screens.
- **Checkout profile + Auth:** Validation and save errors are persistent; the
  auth error retains its `auth-error` ID used by `aria-describedby`.
- **Vault:** Access, missing-file and payment-action failures remain persistent
  inline. Paid/unverified access stays visible with its `Do not pay again`
  guidance; no conversion to a disappearing toast.
- **PublicShare:** Copy shows one brief `Link copied.` toast, while the
  same live region is visually hidden before copying.

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

For Contribute, the internal `CONTRIBUTE_TEMPLATE_NOT_CONFIGURED` response
must display the same customer-facing failure message as other unconfirmed
WhatsApp actions: **`Couldn't confirm. Check WhatsApp.`** It is a
**persistent inline warning**, not a success or an auto-dismissing toast.
This internal response means **Contribute did not send any message**; the
generic wording is a consistent customer-facing fallback, not evidence
that WhatsApp accepted or received anything. Do not retry automatically.
Keep technical context in staff logs and engineering tools; preserve
actionable, payment-safe inline error messages.

## WhatsApp action boundary

Only **Subscribe** and **Leave Review** currently initiate an authenticated
WhatsApp send in the Orders action menu. Submit Request, Request Amendment,
Drop Docs, Vault, Shipments > Track, and Shipments > Pickup Request are
navigation entries there; a click must not invent a `Sent to WhatsApp.`
success. Shipped Orders is excluded. No WhatsApp sending behavior, provider
state machine or payment logic is altered by this UI migration.

## Testing

`node --test tests/public_toast_before_style_contract.test.mjs`
checks the shared compact styles, top-right positions and one-toast behavior.
`node --test tests/public_customer_notification_copy.test.mjs`
checks plain-language Contribute messaging and acceptance boundaries.
Run browser QA for keyboard, small screens, RTL and long error strings
before release.
