# Phase 4 findings inventory — measured, not inspected

Every row below was measured in Chromium against the production export (`npm run build`,
1533 HTML files) at 1280x900, using `tools/browser/lib/{serve,browser}.js`. Where a row says
"source", the value is read from the committed stylesheet and the reason it does not reach the
page is given.

**The reference, read from source** — `src/pages/index.tsx:908` `.home-close-cta`, the home
page's only call to action and therefore the button standard:

```
min-height:52px; padding:0 28px; border:2px solid #1a3a2a; border-radius:50px;
background:#d1f470; color:#1a3a2a; font-size:17px; font-weight:600;
hover: background:#fff; translateY(-2px); box-shadow:0 4px 12px rgba(26,58,42,.12)
focus-visible: outline:3px solid #1a3a2a; outline-offset:3px
```

The home page is NOT edited. It is the baseline.

---

## D1 — `.pf-code` renders completely unstyled on every public phone field  (HIGH)

`src/components/PhoneField.tsx:119` defines `DialCodeSearch` as a **separate component**, and
its `<input className="pf-code">` therefore never receives styled-jsx's scoping hash. Measured
in the built export:

```
out/account/sign-in/index.html
  <input class="pf-code" ...>                      <- no jsx- hash
  <input class="jsx-972b1368ee20e676 pf-num" ...>  <- hashed
```

The rules compiled to `.pf-code.jsx-972b1368ee20e676{...}`, which can never match. So every
declaration in the component for that segment is dead and the browser falls through to the
global `input` skin:

| property | intended (source) | measured on /account/sign-in/ and /get/ |
|---|---|---|
| `border-start-start-radius` | `999px` | `13px` |
| `border` | `0`, plus a 1px `#e5e7eb` inline-end hairline | `2px solid #e5e7eb` on all four sides |
| height | 52px (matches the CTA it feeds) | 50px |
| `font-size` | 17px | 16px |
| `min-inline-size` | 78px | not applied |
| `::-webkit-search-cancel-button` | `display:none` | not applied, so a native clear ✕ shows |

Consequence: the "one field, divided" control the owner asked for renders as **two separate
boxes of different heights with different corner radii**, on `/account/sign-in/`, `/get/`,
`/cart/` (checkout profile) and the blog subscribe block. This is the reported "phone field
does not match home design", and `PillButton.tsx:140` already documents this exact trap
("do not extract them into a helper or a child component: either reintroduces the bug").

**Target:** inline the dial-code input into `PhoneField`'s own return tree so it is stamped,
hoisting the local query state up with it. Pin it with a test that asserts the element carries
the same `jsx-` hash as `.pf-num`.

## D2 — the scrollbar is a different colour in Chromium than in Firefox  (HIGH)

Measured on every public route, identical result on all of them:

```
Firefox  (scrollbar-color)          rgb(209,244,112) rgb(250,250,250)   lime thumb
Chromium (::-webkit-scrollbar-thumb) rgba(26,58,42,0.15) on transparent, width 5px
```

Four competing global declarations exist, and the one that wins in Chromium is the one nobody
intended to be authoritative:

| file:line | declaration | why it wins / loses |
|---|---|---|
| `src/styles/Layout.css:74` | `html{scrollbar-color:rgba(26,58,42,.15) transparent}` | loses, no `!important`, later sheet overrides |
| `src/styles/Layout.css:94-116` | `::-webkit-scrollbar*` 5px, `rgba(26,58,42,.15)` thumb, **every declaration `!important`** | **WINS in Chromium/WebKit/WebView** |
| `src/styles/Pages.css:1481-1531` | `.whatsapp-inbox` + `.page-container` copies, also `!important` | wins inside those containers |
| `src/styles/inner-ux.css:2936-2975` | `#1a3a2a` thumb on `#f5fde0` track, 10px | dead: no `!important` |
| `src/styles/inner-ux.css:2982-3001` | `#d1f470` thumb on `#fafafa` track, 10px | `scrollbar-color` wins in Firefox; the webkit half is dead |

So a customer on Chrome, Safari or an in-app WebView sees a 5px near-invisible grey-green
hairline, and only Firefox shows anything branded. That is the reported "scrollbar does not
match site colours".

**Target:** one declaration, token-sourced, identical in both engines. Thumb `--accent`
(`#1a3a2a`, 12.48:1 on white, so it clears WCAG 1.4.11's 3:1 for a control boundary), track the
house lime state tint `rgba(209,244,112,.22)` — the same tint `.btn-ghost:hover`,
`.co-btn-quiet:hover` and `.si-error` already use. A lime **thumb** was measured and rejected:
`#d1f470` on `#fafafa` is 1.24:1, so the thumb would be the one thing on the page a low-vision
visitor cannot find. Delete the other four copies.

## D3 — no resend affordance on two of the four OTP surfaces  (HIGH)

| surface | send button | resend | cooldown |
|---|---|---|---|
| `/account/sign-in/` `src/pages/account/sign-in.tsx:556` | "Send OTP on WhatsApp" ✓ | **absent** | — |
| `/get/` `src/pages/get.tsx:419` | "Send OTP on WhatsApp" ✓ | **absent** (only "Use a different number") | — |
| `BlogSubscribe.tsx:246` | "Send OTP on WhatsApp" ✓ | "Resend OTP on WhatsApp" ✓ | **absent** |
| `CheckoutProfile.tsx:455` (email verification) | "Send verification code by email" | "Resend email code" ✓ | ✓ 60s |

So three of the four differ, and the two sign-in surfaces have no way to ask for another code
at all — a shopper whose code does not arrive has to abandon the page.

**Target:** one shared `OtpResend` control, styled as the **derived secondary** variant (white
fill, 2px `#1a3a2a`, same 52px/999px/17px geometry), label "Resend OTP on WhatsApp", showing a
consistent 30s cooldown as `Resend OTP on WhatsApp · 29s`. Present on all three WhatsApp OTP
surfaces. `CheckoutProfile`'s email resend keeps its own server-driven cooldown (it is the
one-time email verification, not a sign-in channel) but adopts the same control.

## D4 — two lime fills side by side in the blog subscribe row  (MEDIUM)

`src/components/BlogSubscribe.tsx:329` styles **every** `.verify-row button` as a lime fill, so
the code step renders "Confirm WhatsApp code" and "Resend OTP on WhatsApp" as two equal lime
surfaces, plus the email pair below it — up to four lime fills in one block against the owner's
"a page gets one primary lime surface".

**Target:** confirm stays primary; resend becomes the derived secondary.

**Correction, measured after the fix: `BlogSubscribe` is not rendered on any page.** A repo-wide
search for `<BlogSubscribe` returns only its own test, and `blog-subscribe-phone` appears in zero
of the 1533 exported HTML files. So this was never visible to a customer and the severity above
is wrong as a customer-facing defect. It is still worth fixing — the component is live code that
the next page to mount it would inherit — but it is recorded here as latent, not shipped. It also
means the resend control could not be measured in a browser on this surface; see the verification
notes at the end.

## D5 — `PillButton` label weight and hover shadow drift from the reference  (MEDIUM)

| | home `.home-close-cta` | `.pill` measured |
|---|---|---|
| label font-weight | 600 | **700** |
| hover shadow | `0 4px 12px rgba(26,58,42,.12)` | `0 4px 12px rgba(26,58,42,.18)` |
| radius | 50px | 999px (equivalent at 52px tall) |
| everything else | — | matches |

`.shopd-cta` (shop product), `.co-btn-primary` (/checkout/status/), `.cs-btn-primary`
(/checkout/success/) and the `/blog/` search button all measured 600 and `.12`, so `.pill` is
the single outlier — and it is the control on `/account/sign-in/`, `/cart/`, `/get/`,
`/orders/` and the contribute blocks.

**Target:** 600 and `.12`, matching the reference.

## D6 — the blog search field is the only field on the site that is not a pill  (MEDIUM)

Measured on `/blog/`: `input[type=search]` → `border-radius:12px`,
`border:2px solid rgba(26,58,42,.22)`, height 52px. Every other public field measured
`border-radius:999px` with a `1px #e5e7eb` hairline (`.si-input`, `.sf-input`, `.pf`,
`.blog-subscribe-cell>input`, `.otp`).

**Target:** the site field standard.

A second, smaller delta was found on the same control while re-measuring: `.pill` declared
neither `color` nor `font-weight`, so the control measured `rgb(0,0,0)` / `400` while the label
span inside it painted `#1a3a2a` / `600`. Nothing visible was wrong, because the span holds all
the text — but a glyph or pseudo-element the control rendered directly would have arrived black
at weight 400 on a lime fill. The reference declares both on the control. Now matched.

## D7 — `src/styles/tokens.css:283-350` shadows the button layer  (MEDIUM)

`tokens.css` defines `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-outline` with
`border-radius:var(--radius-btn)` (13px) and `1.5px` borders, and at `@media(max-width:768px)`
flattens all four to `border-radius:12px`. `src/styles/button.css` defines the same four
classes as the home standard (999px, 2px `#1a3a2a`) and is imported **after** `tokens.css`
(`_app.tsx:25` vs `Layout.css:8`'s `@import`), so button.css wins today at equal specificity —
by source order alone. Anything that reorders the imports silently flattens every button on the
site below 768px.

**Target:** delete the duplicate geometry from `tokens.css` so `button.css` is the only button
layer. Measured before and after on a route that renders `.btn`.

## D8 — one `!important` was overriding the field type size on the whole site  (HIGH)

Found while re-measuring D1's fix: the repaired `.pf-code` still painted **16px** where the
component declares 17px. Read with `CSS.getMatchedStylesForNode` on `/account/sign-in/`:

```
input, textarea, select            font-size: var(--text-base) !important   <- Layout.css:132
.pf-code.jsx-972b1368ee20e676      font-size: 17px                          <- loses
```

`src/styles/Layout.css:132` forced 16px onto **every** input, textarea and select on the site.
So `.si-input`, `.sf-input`, both PhoneField segments and `BlogSearch`'s input all declare 17px
— the site's field size, picked so a field matches the 17px CTA it feeds — and **every one of
them rendered at 16px**. Four components, four deliberate declarations, none reaching the page,
and nothing in the suite able to see it.

The rule's purpose is the 16px floor below which iOS Safari zooms the viewport on focus. A floor
written as `!important` is also a ceiling, which is the opposite of what it exists to do.

**Target:** drop the `!important`. The floor still holds twice over — the rule still beats
`tokens.css`'s 14px default on source order, so an input that declares nothing still gets 16px,
and `tokens.css` keeps its `@media (max-width:768px){… !important}`, which is where the iOS
behaviour actually applies. Measured after: every public field paints 17px on desktop and 16px
at ≤768px.

Two inline code boxes were then raised from 15px to 17px (`BlogSubscribe`, `CheckoutProfile`):
15px only ever looked acceptable because the override was hiding it, and with the override gone
it would have become the one field on the card below the floor.

## D9 — `.sf-quiet` is below the 44px tap floor on desktop  (LOW)

`src/pages/get.tsx:595`: `padding:10px` on a 15px line measures ~38px tall. `tokens.css`
forces `min-height:44px` on every button below 768px, so this is a desktop-only miss.

**Target:** 44px at every width.

## Internal wording visible to a customer

Scanned every rendered text node plus `aria-label` / `title` / `placeholder` / `alt` on 32
public routes, against a deliberately narrow word list (word-boundary matched, so
"commitment" does not match "commit"). 18 hits, in exactly two places:

### `WorkflowTerminal` — 7 strings, on `/` AND `/404/`  — NOT CHANGED, owner decision needed

```
"An illustration of one customer request moving through our backend: …"
"api gateway · lambda · tls terminated at the edge"
"cognito · iam · per-account isolation"
"dynamodb · single-table · on-demand capacity"
"sqs · lambda · one queue per channel, shared retry policy"
"dynamodb transaction · eventbridge"
"sqs redrive · exponential backoff · dead-letter queue watched"
```

This is the clearest internal wording a customer sees anywhere on the site. It is also **on the
home page**, which this task forbids changing because it is the design reference. Those two
instructions conflict here and the resolution is a product decision, not a sweep decision: the
terminal may well be a deliberate "look at how this is built" feature rather than leaked dev
prose. Left exactly as it is, and raised.

### `/terms/` — "our commerce backend"  — CHANGED

One phrase, in the coupon clause. "Razorpay" and "server-side" in the same document are
**kept**: naming the payment provider is required disclosure, and "server-side" states who
decides, which is the point of the clause.

## Checked and found already consistent

Recorded so the next sweep does not re-derive it. All measured, not assumed.

- `/checkout/status/`, `/checkout/success/` — `.co-btn` / `.cs-btn` are 52px / 50px radius /
  17px / 600 / `2px #1a3a2a` lime primary with a lime-outline quiet variant. Exact reference match.
- `/shop/<slug>/` `.shopd-cta` — exact reference match.
- `/orders/` — `PillButton` plus links; no bespoke button.
- `/get/` `.sf-input`, `/account/sign-in/` `.si-input`, `BlogSubscribe` `.otp` — all
  999px / 1px `#e5e7eb` / 52px (44px for the inline code box), `#1a3a2a` focus ring.
- `/perks/`, `/shipments/`, `/contact/`, `/vayulok/`, `/refer-and-earn/`, `/leave-review/`,
  `/submit-request/`, `/request-amendment/`, `/drop-docs/`, `/terms/`, `/privacy/` — no
  bespoke button or field renders; they inherit the shared chrome.
- `/grahak-os/` `.pp-tab` (lime active tab, 8px) and `span.pill` (white, 50px) — left alone.
  That page has its own committed contract in `.kiro/steering/grahak-os-design.md`, and an
  active tab is not a primary action.
- OTP button wording is already "Send OTP on WhatsApp" everywhere it exists; no email
  sign-in channel exists anywhere. The only email code is the one-time verification in
  `CheckoutProfile` and `BlogSubscribe`, which is what the owner decision allows.

## Verification, and what is NOT verified

Measured after the changes, against a fresh `npm run build` (1533 HTML files):

| gate | result |
|---|---|
| `npx tsc --noEmit` | clean |
| `npx vitest run` | 82 files, 1098 passed, 2 skipped |
| `node tools/browser/designsweep.js` | PASS, 20 routes x 2 viewports (new gate) |
| `node tools/browser/devicecheck.js` | 390/390 route x posture, incl. every foldable |
| `node tools/browser/uicheck.js` | 96/96 |
| `node tools/browser/typecheck.js` | 3/3 |
| `node tools/browser/seocheck.js` | 11/11 |
| `node tools/browser/animcheck.js` | 18/18 |
| `node tools/browser/rtlcheck.js` | 7531/7531, 125 routes x 6 viewports |
| `node tools/browser/translatecheck.js` | PASS, brand protected on every route |
| `node tools/browser/pageaudit.js` | 209 routes, 0 horizontal overflow, 0 first-line-under-header |
| `scripts/check_design_drift.py` | OK |
| `pytest` tokens + money + payment vocabulary | 214 passed |

Degradation states, measured on `/`, `/account/sign-in/`, `/get/`, `/cart/`, `/orders/`,
`/blog/` at 1280, 390 and 280px: default, **no-JS**, **reduced-motion**, **forced-colors**,
**dark**. Zero horizontal overflow in every combination; the scrollbar, the phone field, the
pill and the search field hold their measured values in all of them, and the resend control's
transitions collapse to `1e-05s` under `prefers-reduced-motion: reduce`.

**The resend control was measured on the live sign-in surface**, not only in unit tests: it only
renders once a code is outstanding, which is client state and therefore absent from the static
export, so Cognito's `InitiateAuth` was stubbed at the network layer with a canned
`CUSTOM_CHALLENGE` response. Nothing left the machine, no OTP was requested and no credential
was used. Measured at 1280 / 390 / 280px: white fill, `#1a3a2a` text, 999px, 2px `#1a3a2a`,
17px/600 (16px at ≤768px, the iOS floor), 52px tall, no overflow, and **exactly one lime surface
on the page** — "Confirm WhatsApp code".

### Not verified, stated rather than implied

- **Firefox does not run on this Mac.** Every `--firefox` harness, pre-existing ones included,
  dies with `Could not find profile folder` against the cached `firefox-1543` build. That is an
  environment gap, not a change from this work. It matters here because `scrollbar-color` is the
  half Firefox reads — mitigated by `designsweep` asserting that property's computed value on
  Chromium too, so the two halves are proved to AGREE even though Firefox's painting is
  unverified.
- **WebKit still cannot run**, as `SKILL.md` records, so iOS and every iOS WebView remain
  unverified for all of this.
- **`CheckoutProfile`'s resend was not measured in a browser.** It lives on `/cart/` behind a
  signed-in session; its behaviour is covered by `CheckoutProfileResend.test.tsx` (13 cases,
  including both 429 shapes and the server-deadline-wins path) and its geometry is the same
  shared component measured on sign-in.
- **Real browser zoom and print** were not checked beyond `rtlcheck`'s `print` and `zoom200`
  passes.
- **The dashboard is unmeasurable from the export.** `.btn` renders only on authenticated
  routes, which ship as auth shells, so D7's change was reasoned from the cascade rather than
  measured. That is why the duplicate block was made to AGREE with `button.css` rather than
  deleted.
