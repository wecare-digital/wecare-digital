# Public-site notification inventory — WECARE.DIGITAL

Source snapshot: [`0b9411dc3ee3`](https://github.com/wecare-digital/wecare-digital/commit/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019) on 31 October 2026. **Source inspection only, not browser QA**. This file inventories source render sites for explicit `role="status"`/`role="alert"` notifications on public/customer-facing routes. It is separate from the [779 Workspace-style `toast.*` call-site catalog](./toast-message-catalog-20261031.md).

**Important difference:** Public-page rendering in `src/pages/_app.tsx` has **no `ToastProvider`**. Direct `toast.success/error/warning/info` use on this route branch: **0**. The 24 discoverable public URLs share `Header`, `PublicShare`, and `SupportWidget`; there are additional customer-only routes such as `/auth/`, `/checkout/`, `/checkout/status/` and `/vault/?file=`, not counted among the 24 marketing URLs.

**Source counts:** 16 active public-side component/page files contain **61** explicit alert/status render positions: 51 static status, 7 static alert, 3 conditional alert/status. Five additional source files with 9 render positions are inactive or Workspace-only, and are listed separately below. **Render sites are not distinct text strings**: dynamic JSX states may show several different messages. This audit does not claim that other text-only messages without ARIA roles are absent.

## Public marketing URLs (24)

| Route | Group |
|---|---|
| `/` | start |
| `/contact` | start |
| `/blog` | start |
| `/shop` | start |
| `/orders` | start |
| `/grahak-os` | platform |
| `/vayulok` | platform |
| `/sehat` | services |
| `/elsewhere/visa` | services |
| `/elsewhere/trip` | services |
| `/elsewhere/activities` | services |
| `/dastavez/drafting` | services |
| `/dastavez/registration` | services |
| `/dastavez/legal-reference` | services |
| `/ritual-guru/ritva` | services |
| `/ritual-guru/puja-guidance` | services |
| `/ritual-guru/diy-puja-kit` | services |
| `/hunar/kaushal` | services |
| `/hunar/prastuti` | services |
| `/expo-week` | services |
| `/anew` | services |
| `/niji-setu` | services |
| `/privacy` | legal |
| `/terms` | legal |

## All public/customer notification render sites (61)

Full source expressions are linked at the exact lines below. A rendered JSX snippet is included to help copy review; dynamic expressions are not evaluated and may display different strings depending on state.

| Area | Source | ARIA type | Existing JSX / message expression |
|---|---|---|---|
| Checkout address | [`src/components/AddressFields.tsx:226`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/AddressFields.tsx#L226) | alert | <code>&lt;p id="address-postal-help" className="address-help" role="alert"&gt; Enter a six-digit Indian PIN code. &lt;/p&gt; ) }</code> |
| Checkout | [`src/components/cart/CartPage.tsx:1736`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/cart/CartPage.tsx#L1736) | status | <code>&lt;p className="cart-status" role="status" data-wc-basket-claim="true"&gt; { basketClaim } &lt;/p&gt; ) : null;</code> |
| Checkout | [`src/components/cart/CartPage.tsx:1854`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/cart/CartPage.tsx#L1854) | status | <code>{ quoteLoading &amp;&amp; &lt;p className="cart-body" role="status"&gt;Checking current prices…&lt;/p&gt; } { quoteNotice &amp;&amp; &lt;p className="cart-status" role="status"&gt;{ quoteNotice }&lt;/p&gt; } { quoteNotice.startsWith( 'Sign in' ) &amp;&amp; ( &lt;Link className="cart-auth-action" href="/auth?re</code> |
| Checkout | [`src/components/cart/CartPage.tsx:1855`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/cart/CartPage.tsx#L1855) | status | <code>{ quoteNotice &amp;&amp; &lt;p className="cart-status" role="status"&gt;{ quoteNotice }&lt;/p&gt; } { quoteNotice.startsWith( 'Sign in' ) &amp;&amp; ( &lt;Link className="cart-auth-action" href="/auth?return=/checkout/"&gt; Sign in on WhatsApp</code> |
| Checkout | [`src/components/cart/CartPage.tsx:1972`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/cart/CartPage.tsx#L1972) | status | <code>&lt;p className="cart-status" role="status"&gt;{ notice.message }&lt;/p&gt; )} {notice.kind === 'error' &amp;&amp; ( &lt;p className="cart-status cart-status-firm" role="alert"&gt;{ notice.message }&lt;/p&gt;</code> |
| Checkout | [`src/components/cart/CartPage.tsx:1975`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/cart/CartPage.tsx#L1975) | alert | <code>&lt;p className="cart-status cart-status-firm" role="alert"&gt;{ notice.message }&lt;/p&gt; )} {/* THE MIXED-BASKET NOTICE AND ITS "Keep only the contribution" BUTTON WERE HERE.</code> |
| Checkout profile | [`src/components/CheckoutProfile.tsx:213`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/CheckoutProfile.tsx#L213) | status | <code>&lt;p className="checkout-profile-status" role="status" aria-live="polite"&gt;{ message }&lt;/p&gt; ) } &lt;div className="checkout-profile-actions"&gt;</code> |
| Elsewhere activities | [`src/components/ElsewhereTravelAssistant.tsx:441`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/ElsewhereTravelAssistant.tsx#L441) | status | <code>&lt;div className="eta-loading" role="status"&gt; &lt;span className="eta-loading-line" aria-hidden="true" /&gt; &lt;span&gt;Comparing the strongest matches…&lt;/span&gt; &lt;/div&gt;</code> |
| Elsewhere activities | [`src/components/ElsewhereTravelAssistant.tsx:575`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/ElsewhereTravelAssistant.tsx#L575) | status | <code>{ continuationNote &amp;&amp; &lt;p className="eta-continuation" role="status"&gt;{ continuationNote }&lt;/p&gt; } &lt;/div&gt; &lt;style jsx&gt;{`</code> |
| Vault file access | [`src/components/get/GetPage.tsx:600`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L600) | alert | <code>&lt;p role="alert" className="sf-file-error"&gt;{ error }&lt;/p&gt; &lt;button type="button" className="sf-file-action-button sf-secondary-btn" onClick={ () =&gt; { window.location.reload(); } }&gt;Try again&lt;/button&gt; &lt;/div&gt;</code> |
| Vault file access | [`src/components/get/GetPage.tsx:610`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L610) | conditional alert/status | <code>role={ error ? 'alert' : undefined }&gt; { error &#124;&#124; 'There are no files shared with your number right now.' } &lt;/p&gt; &lt;Link className="sf-back-link" href="/orders/"&gt;Back to Orders&lt;/Link&gt;</code> |
| Vault file access | [`src/components/get/GetPage.tsx:647`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L647) | status | <code>&lt;div className="sf-file-status-row" role="status" aria-live="polite"&gt; &lt;span className={ `sf-status-chip ${ isPaid ? 'sf-status-ready' : state === 'PAID_UNVERIFIED' ? 'sf-status-pending' : 'sf-status-locked' }` }&gt; &lt;span className="sf-status-dot" aria-hidden="tr</code> |
| Vault file access | [`src/components/get/GetPage.tsx:670`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L670) | status | <code>&lt;p className="sf-state-note" role="status"&gt; { state === 'OPEN' ? `Access active${ ends ? ` until ${ ends }` : '' }. Download again before it expires.` : 'Payment verified. Your 24-hour access starts on delivery or first download.' }</code> |
| Vault file access | [`src/components/get/GetPage.tsx:677`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L677) | status | <code>&lt;div className="sf-file-action" role="status" aria-live="polite"&gt; &lt;button type="button" className="sf-file-action-button sf-download-button sf-expired-button" disabled&gt;</code> |
| Vault file access | [`src/components/get/GetPage.tsx:685`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L685) | status | <code>&lt;p className="sf-confirming-note" role="status"&gt; Your payment is recorded and access is being confirmed. Do not pay again. &lt;/p&gt; ) : state === 'UNPAID' ? (</code> |
| Vault file access | [`src/components/get/GetPage.tsx:692`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L692) | status | <code>&lt;p className="sf-payment-note" role="status"&gt; { feedback?.message &#124;&#124; 'Review &amp; Pay was sent to WhatsApp. Complete it or check the status before starting another checkout.' } &lt;/p&gt;</code> |
| Vault file access | [`src/components/get/GetPage.tsx:743`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L743) | status | <code>&lt;p className="sf-payment-note" role="status"&gt;{ feedback.message }&lt;/p&gt; ) } { state !== 'EXPIRED' &amp;&amp; feedback?.kind === 'error' &amp;&amp; ( &lt;p className="sf-file-error" role="alert"&gt;{ feedback.message }&lt;/p&gt;</code> |
| Vault file access | [`src/components/get/GetPage.tsx:746`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L746) | alert | <code>&lt;p className="sf-file-error" role="alert"&gt;{ feedback.message }&lt;/p&gt; ) } &lt;/div&gt; );</code> |
