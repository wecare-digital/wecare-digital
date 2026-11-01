# Public/customer notification system

Public pages do not mount the authenticated Workspace `ToastProvider`.
They use `src/components/public/PublicNotice.tsx` and the one-at-a-time
`PublicToastProvider` instead. **Both toast renderers now share the same
screenshot-verified style tokens**, but their inline messages and application
lifecycle remain separate.
The [31 October 2026 inventory](../audits/public-notification-surface-inventory-20261031.md)
records **61 original render sites across 16 files**, not 61 unique toasts.
Its source links and counts describe that audit snapshot; do not replace them
with claims of current runtime coverage.

## Approved screenshot-matched action-toast design (1 November 2026)

The customer's original screenshot (1526 × 440 pixels) is the visual reference
for **all action toasts**, including public Orders WhatsApp/copy, PublicShare
copy, and authenticated Workspace `ToastContext` messages. It shows a single,
large, bottom-right card with **no status icon or checkmark**.

All toast renderers take their appearance from `src/styles/tokens.css`:
`--wc-toast-surface: #f6fce4`, `--wc-toast-stripe: #d8f382`,
`--wc-toast-ink: #1a1a1a`, 20px radius, 8px inline-start lime stripe,
32px semibold type, and 16px × 24px padding (with mobile-responsive reductions).
The card sits at the lower-right within the page content boundary; at the
reference 1526px width, the CSS's 156px right inset and 20px bottom inset
match the image. On small screens it rises above the WhatsApp floating widget.

**One toast at a time**, with the latest explicit action replacing the last.
Keep the existing timers, ARIA roles, and honest WhatsApp provider-acceptance
wording. Workspace keeps a keyboard-accessible dismiss action that appears on
hover or focus; it does not render a permanent icon.

**Do not** apply the big screenshot toast to inline authentication errors,
address validation, checkout/payment uncertainty, Vault access warnings,
search results, air-quality readings, or other passive status text. Those stay
in place, with their original persistent/assistive semantics.

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
must render as **`Contribute on WhatsApp is unavailable.`**, not the
implementation reason. It does **not** count as a sent/accepted message.
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

`node --test tests/public_notice_contract.test.mjs` checks shared roles,
lifecycle boundaries and the first migrated call sites.
`node --test tests/customer_menu_notice_contract.test.mjs` keeps the
authenticated invitation regression coverage. Add browser QA for keyboard,
small screens, RTL and long error strings before rolling out to remaining
public routes.
