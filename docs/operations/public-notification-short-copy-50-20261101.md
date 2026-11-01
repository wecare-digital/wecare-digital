# Remaining public notification copy — 50-position checklist

**Source scope:** The 31 October 2026 [public render-site inventory](../audits/public-notification-surface-inventory-20261031.md) counted 61 explicit status/alert positions. PR #2085 migrated 11 of those, leaving **50 positions across 14 files**. They are **render positions, not 50 different message strings**. Line links below refer to the frozen audit snapshot, not current line numbers.

This pass shortens verbose customer copy while retaining short existing messages, contextual progress, data values, and every payment/access safeguard. **These are not all transient toast notifications**; loading statuses and persistent errors remain inline or screen-reader-only. No WhatsApp send, payment, routing, AWS or delivery status behavior changes.

| # | Public source (audit line) | Concise displayed copy / pattern | Result |
|---:|---|---|---|
| 1 | [`AddressFields.tsx:226`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/AddressFields.tsx#L226) | Enter a valid 6-digit PIN. | Shortened |
| 2 | [`CartPage.tsx:1736`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/cart/CartPage.tsx#L1736) | WhatsApp cart guidance; server-owned outcomes (keep until client/server copy is aligned). | Dynamic |
| 3 | [`CartPage.tsx:1854`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/cart/CartPage.tsx#L1854) | Checking prices… | Shortened |
| 4 | [`CartPage.tsx:1855`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/cart/CartPage.tsx#L1855) | Sign in to view final price. / Verified price unavailable. Payment disabled. | Shortened · dynamic |
| 8 | [`ElsewhereTravelAssistant.tsx:441`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/ElsewhereTravelAssistant.tsx#L441) | Comparing options… | Shortened |
| 9 | [`ElsewhereTravelAssistant.tsx:575`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/ElsewhereTravelAssistant.tsx#L575) | Provider confirmation required before checkout. | Shortened |
| 12 | [`GetPage.tsx:647`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L647) | Payment verified / Verifying payment / Access locked | Already concise |
| 13 | [`GetPage.tsx:670`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L670) | Access active until {date}. Download before expiry. / Payment verified. 24-hour access starts on delivery or first download. | Shortened · dynamic |
| 14 | [`GetPage.tsx:677`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L677) | Access expired | Already concise |
| 15 | [`GetPage.tsx:685`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L685) | Payment recorded. Confirming access. Do not pay again. | Shortened |
| 16 | [`GetPage.tsx:692`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L692) | Review & Pay sent to WhatsApp. Check status before retrying. | Shortened |
| 17 | [`GetPage.tsx:743`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/get/GetPage.tsx#L743) | Backend payment status, with local fallback: Review & Pay sent to WhatsApp. Complete it there. | Shortened fallback · dynamic |
| 19 | [`Header.tsx:667`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/Header.tsx#L667) | {count} menu result(s). | Already concise · dynamic |
| 20 | [`OrderActionsMenu.tsx:312`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/orders/OrderActionsMenu.tsx#L312) | No matching actions. | Already concise |
| 21 | [`OrderActionsMenu.tsx:317`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/orders/OrderActionsMenu.tsx#L317) | {count} action(s) | Already concise · dynamic |
| 25 | [`OrdersPage.tsx:902`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/orders/OrdersPage.tsx#L902) | Checking orders… | Shortened |
| 26 | [`ProductBlogPanel.tsx:216`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/ProductBlogPanel.tsx#L216) | Couldn't load more posts. [Try again] / Loading posts… | Shortened |
| 27 | [`ProductBuyBox.tsx:97`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/ProductBuyBox.tsx#L97) | Checkout couldn't start. No charge made. Try again. | Shortened |
| 29 | [`SupportWidget.tsx:1289`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/SupportWidget.tsx#L1289) | English restored. / Translating to {language}… / Translated to {language}. / Translation unavailable. | Shortened · dynamic |
| 30 | [`VayuLokLive.tsx:3250`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3250) | Searching places… | Shortened |
| 31 | [`VayuLokLive.tsx:3251`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3251) | Place not found. | Already concise |
| 32 | [`VayuLokLive.tsx:3252`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3252) | Search unavailable. | Already concise |
| 33 | [`VayuLokLive.tsx:3354`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3354) | Loading air quality… | Already concise |
| 34 | [`VayuLokLive.tsx:3369`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3369) | Loading weather… | Already concise |
| 35 | [`VayuLokLive.tsx:3586`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3586) | Air forecast unavailable. | Shortened |
| 36 | [`VayuLokLive.tsx:3589`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3589) | No air forecast for this place. | Shortened |
| 37 | [`VayuLokLive.tsx:3841`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3841) | {time}, AQI {value} | Keep measurements |
| 38 | [`VayuLokLive.tsx:3875`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3875) | Loading air quality… / Air quality unavailable. / Choose a place for air quality. | Shortened · dynamic |
| 39 | [`VayuLokLive.tsx:3941`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L3941) | Alerts unavailable. | Already concise |
| 40 | [`VayuLokLive.tsx:4208`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4208) | Loading weather… / Weather unavailable. / Choose a place for weather. | Shortened · dynamic |
| 41 | [`VayuLokLive.tsx:4225`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4225) | {place/address} · Couldn't load map / Map unavailable | Shortened · dynamic |
| 42 | [`VayuLokLive.tsx:4242`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4242) | Loading map | Already concise · accessible |
| 43 | [`VayuLokLive.tsx:4331`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4331) | Searching places… | Already concise |
| 44 | [`VayuLokLive.tsx:4332`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4332) | Place not found. | Already concise |
| 45 | [`VayuLokLive.tsx:4333`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4333) | Search unavailable. | Already concise |
| 46 | [`VayuLokLive.tsx:4378`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4378) | Searching places… | Already concise |
| 47 | [`VayuLokLive.tsx:4379`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4379) | Place not found. | Already concise |
| 48 | [`VayuLokLive.tsx:4380`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4380) | Search unavailable. | Already concise |
| 49 | [`VayuLokLive.tsx:4436`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4436) | Currency unavailable. | Shortened |
| 50 | [`VayuLokLive.tsx:4483`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4483) | Currency unavailable. | Shortened |
| 51 | [`VayuLokLive.tsx:4565`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4565) | Searching places… | Already concise |
| 52 | [`VayuLokLive.tsx:4566`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4566) | Place not found. | Already concise |
| 53 | [`VayuLokLive.tsx:4567`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4567) | Search unavailable. | Already concise |
| 54 | [`VayuLokLive.tsx:4594`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4594) | Route unavailable. | Shortened |
| 55 | [`VayuLokLive.tsx:4596`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokLive.tsx#L4596) | Route unavailable. | Shortened |
| 56 | [`VayuLokWeatherInsights.tsx:199`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokWeatherInsights.tsx#L199) | Loading history… | Shortened |
| 57 | [`VayuLokWeatherInsights.tsx:202`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokWeatherInsights.tsx#L202) | No history here yet. | Shortened |
| 58 | [`VayuLokWeatherInsights.tsx:208`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/components/VayuLokWeatherInsights.tsx#L208) | History unavailable. | Shortened |
| 59 | [`auth.tsx:203`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/pages/auth.tsx#L203) | No countries found. | Already concise |
| 61 | [`status.tsx:166`](https://github.com/wecare-digital/wecare-digital/blob/0b9411dc3ee3ddeaae8cb052ae02730d5f3c3019/src/pages/checkout/status.tsx#L166) | Confirming payment… / Payment received / Payment incomplete / Status unavailable | Shortened · dynamic |

## Guardrails

- **Checkout basket claim (#2):** Copy comes from `src/lib/whatsappBasket.ts`, with server-side claim guidance and regression parity. It is not silently rewritten in a UI-only PR; customers still need the recovery action (empty website cart, reopen link, or retry in WhatsApp). Coordinate both contracts before shortening.
- **Dynamic statuses (#4, #12, #13, #17, #19, #21, #29, #37, #38, #40, #41, #61):** Preserve values, links, provider responses, expiry dates and payment state. The pattern examples are not full sets of runtime variants.
- **Payment and Vault:** Keep `Do not pay again.` when payment is already recorded but access is unverified. `Payment received` does not mean order finalization is complete; `Sent to WhatsApp` is acceptance, not delivery.
- **VayuLok:** Keep weather, air quality, map, currency, route and AQI states scoped to their own UI controls. Use the shared public visual system without converting live data into global auto-dismissing toasts.
- **Already concise:** Locations labelled `Already concise` are deliberately unchanged; shortening them further would remove meaning or context.

## Source-change summary

The short-copy pass updated direct strings or dynamic fallback producers in AddressFields, CartPage, ElsewhereTravelAssistant, GetPage, OrdersPage, ProductBlogPanel, ProductBuyBox, SupportWidget, VayuLokLive, VayuLokWeatherInsights, and the checkout result. Existing menu, search, country and AQI notices remain concise without changing their semantics.

**Verification:** Source-level copy checks and CI/browser testing should be run after merging. The inventory is source-only, not proof of a particular notification appearing to a specific customer.
