# Toast, status and error surfaces — 31 October 2026

> Source snapshot: `wecare-digital/wecare-digital`, default branch `wecare.digital`, inspected on 31 October 2026. The implementation changes described below live in `fix/lime-toasts-surface-audit-20261031` pending review. This is a source-reference inventory, not a live browser test or proof that every runtime branch was exercised.

## What the screenshots show

| Screen / action | UI implementation | Backend path | Evidence / next check |
| --- | --- | --- | --- |
| Public `/orders/`: person icon “Update profile on WhatsApp” | `src/components/orders/OrdersPage.tsx` custom local toast; previously white/red on failure | `POST /api/customer/profile` → `wecare-customer-profile` → `wecare-whatsapp-business-api` → Meta | On 2026-10-31 at 02:08:15 and 02:08:24 UTC, Meta responded HTTP 400, code 131009, message “Parameter value is not valid.” Sender logged `flow_funnel launch_failed graph_error`; profile Lambda logged `customer_profile_update_send_failed`. Check approved `service_details` Flow button action and parameter contract. |
| `/auth/` at initial load | `src/pages/auth.tsx` inline `auth-error`, not a toast | `GET /auth/state` → customer-commerce MCP | API Gateway access log at 2026-10-31 02:07:29.868 UTC returned 400. Server collapses validation failures to `invalid_request`; frontend collapses all errors into “temporarily unavailable.” Check sanitized request query/state; do not assume a service outage. |
| Authenticated workspace pages | `src/contexts/ToastContext.tsx` and `src/components/Toast.tsx`; styled by `src/styles/inner-ux.css` | Each screen has its own action | Workspace-only provider in `src/pages/_app.tsx`. Shared notifications have severity types: success/error/warning/info. |

## Styling changes in this branch

- Orders: failure feedback uses the same lime/forest palette as success and appears **inline beneath the action buttons**, not as a fixed toast over the page; existing four-second dismissal and alert/status semantics remain.
- Authenticated workspace: shared toast notifications use the same lime/forest palette across severities, keep distinct symbols and ARIA role to convey error or warning, and use fade-only motion with no elevated shadow. The small fixed notification rail remains non-modal; it does not block other interactions outside the toast.
- Public forms (including auth) and inline validation messages are **not** converted to toasts: turning a persistent, actionable form error into a four-second message would hurt usability.
- `src/styles/Layout.css` also defines `.toast-container`, but `src/styles/inner-ux.css` is imported later by `_app.tsx` and owns the effective toast styling. Avoid editing only the earlier rule.

## Scope and scan method

- Recursive GitHub tree of `src/`: 386 files, including 74 page TS/TSX modules and 217 component modules.
- Search terms: `useToastContext`, `toast.success`, `toast.error`, `toast.warning`, `toast.info`, `role="alert"`, `role="status"`, `<ErrorState`, `setNotice`, `ord-profile-toast`.
- Results (source files containing search hits): 72 import/definition references, 56 success, 66 error, 5 warning, 5 info, 16 inline alert, 28 inline status; 103 distinct UI source files in combined scan excluding the infrastructure providers themselves.
- Search-index coverage is not a guarantee that every notification variant or indirect child-component usage was detected. Components used inside route wrappers are mapped by **source component**, not assumed URL. No dynamic/live pages or native apps were executed.

## Which source file uses which feedback surface

The first column is the actual source file to change. “Shared toast” means the authenticated `ToastContext` mechanism (changing `src/styles/inner-ux.css` changes its color everywhere); “local”/“inline” means the page owns its own styling.


### Customer checkout / cart (2 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/cart/CartPage.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/cart/CartPage.tsx) | Inline status; Local notice |
| [`src/components/cart/CheckoutPriceBreakdown.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/cart/CheckoutPriceBreakdown.tsx) | Inline status |

### Customer file delivery (1 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/get/GetPage.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/get/GetPage.tsx) | Inline status |

### Customer orders (3 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/orders/OrderDetail.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/orders/OrderDetail.tsx) | Inline status |
| [`src/components/orders/OrdersPage.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/orders/OrdersPage.tsx) | Local Orders toast (sent/failed); inline status |
| [`src/components/orders/RequestsPanel.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/orders/RequestsPanel.tsx) | Inline status |

### Dashboard (2 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/dashboard/tabs/DataTab.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/dashboard/tabs/DataTab.tsx) | Shared toast: success, error |
| [`src/components/dashboard/tabs/PayTab.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/dashboard/tabs/PayTab.tsx) | Shared toast: success, error |

### Other direct page routes (2 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/pages/auth.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/pages/auth.tsx) | Inline alert; Inline status |
| [`src/pages/checkout/status.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/pages/checkout/status.tsx) | Inline status |

### Other UI components (14 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/AddressFields.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/AddressFields.tsx) | Inline alert |
| [`src/components/CheckoutProfile.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/CheckoutProfile.tsx) | Inline status |
| [`src/components/ElsewhereTravelAssistant.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/ElsewhereTravelAssistant.tsx) | Inline status |
| [`src/components/ErrorState.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/ErrorState.tsx) | ErrorState component |
| [`src/components/FloatingAgent.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/FloatingAgent.tsx) | Shared toast: warning |
| [`src/components/Header.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/Header.tsx) | Inline status |
| [`src/components/PhoneField.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/PhoneField.tsx) | Inline status |
| [`src/components/ProductBlogPanel.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/ProductBlogPanel.tsx) | Inline status |
| [`src/components/PublicShare.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/PublicShare.tsx) | Inline status |
| [`src/components/PushOptIn.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/PushOptIn.tsx) | Inline status |
| [`src/components/ServiceBuyBox.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/ServiceBuyBox.tsx) | Inline alert; Inline status |
| [`src/components/SupportWidget.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/SupportWidget.tsx) | Inline status |
| [`src/components/VayuLokLive.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/VayuLokLive.tsx) | Inline status |
| [`src/components/VayuLokWeatherInsights.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/VayuLokWeatherInsights.tsx) | Inline status |

### Public services (1 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/service/ServiceDataState.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/service/ServiceDataState.tsx) | Inline alert; Inline status; ErrorState component |

### Workspace — channels (4 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/channels/RcsSend.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/channels/RcsSend.tsx) | Shared toast: success, error |
| [`src/components/workspace/channels/RcsTemplates.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/channels/RcsTemplates.tsx) | Shared toast: success, error |
| [`src/components/workspace/channels/Sms.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/channels/Sms.tsx) | Shared toast: success, error |
| [`src/components/workspace/channels/Voice.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/channels/Voice.tsx) | Shared toast: success, error |

### Workspace — commerce (3 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/commerce/Catalog.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/commerce/Catalog.tsx) | Inline alert; Inline status |
| [`src/components/workspace/commerce/CommerceEngine.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/commerce/CommerceEngine.tsx) | Shared toast: success, error |
| [`src/components/workspace/commerce/Orders.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/commerce/Orders.tsx) | Shared toast: success, error; Inline alert; ErrorState component |

### Workspace — customers (2 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/customers/ConsentPanel.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/customers/ConsentPanel.tsx) | Shared toast: success, error |
| [`src/components/workspace/customers/ManageData.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/customers/ManageData.tsx) | Shared toast: success, error |

### Workspace — MCPPlayground.tsx (1 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/MCPPlayground.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/MCPPlayground.tsx) | Inline alert |

### Workspace — messaging (10 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/messaging/Analytics.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/Analytics.tsx) | Shared toast: error |
| [`src/components/workspace/messaging/Automation.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/Automation.tsx) | Shared toast: success, error |
| [`src/components/workspace/messaging/Contact360.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/Contact360.tsx) | Shared toast hook (no direct send in search) |
| [`src/components/workspace/messaging/Content.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/Content.tsx) | Shared toast: error |
| [`src/components/workspace/messaging/Cost.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/Cost.tsx) | Shared toast: error |
| [`src/components/workspace/messaging/DocsScraper.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/DocsScraper.tsx) | Shared toast: success, error, info |
| [`src/components/workspace/messaging/Links.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/Links.tsx) | Shared toast: success, error |
| [`src/components/workspace/messaging/MetaAgent.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/MetaAgent.tsx) | Shared toast: success, error |
| [`src/components/workspace/messaging/Scheduled.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/Scheduled.tsx) | Shared toast: success, error |
| [`src/components/workspace/messaging/Search.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/messaging/Search.tsx) | Shared toast: error |

### Workspace — pay (2 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/pay/InvoiceRecords.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/pay/InvoiceRecords.tsx) | Shared toast: error |
| [`src/components/workspace/pay/PayFlow.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/pay/PayFlow.tsx) | Inline alert |

### Workspace — platform (6 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/platform/CodeRepo.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/platform/CodeRepo.tsx) | Shared toast hook (no direct send in search) |
| [`src/components/workspace/platform/CorsSettings.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/platform/CorsSettings.tsx) | Shared toast: success, error |
| [`src/components/workspace/platform/LambdaFunctions.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/platform/LambdaFunctions.tsx) | Shared toast: success, error, info |
| [`src/components/workspace/platform/MCPConnections.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/platform/MCPConnections.tsx) | Inline alert; Inline status |
| [`src/components/workspace/platform/SystemArchitecture.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/platform/SystemArchitecture.tsx) | Shared toast: error |
| [`src/components/workspace/platform/WaGraphTools.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/platform/WaGraphTools.tsx) | Shared toast: success, error |

### Workspace — seo (1 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/seo/BlogManager.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/seo/BlogManager.tsx) | Inline alert |

### Workspace — service (14 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/service/AmendRequest.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/AmendRequest.tsx) | Shared toast: error |
| [`src/components/workspace/service/Appointments.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/Appointments.tsx) | Shared toast: success, error |
| [`src/components/workspace/service/CustomerServiceHub.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/CustomerServiceHub.tsx) | Shared toast: success |
| [`src/components/workspace/service/Documents.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/Documents.tsx) | Shared toast: success, error, warning; Inline status |
| [`src/components/workspace/service/Enterprise.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/Enterprise.tsx) | Shared toast: success, error |
| [`src/components/workspace/service/Faq.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/Faq.tsx) | Shared toast: success, error |
| [`src/components/workspace/service/FormResponses.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/FormResponses.tsx) | Shared toast: error |
| [`src/components/workspace/service/Reviews.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/Reviews.tsx) | Shared toast: success, error |
| [`src/components/workspace/service/SecureFiles.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/SecureFiles.tsx) | Shared toast: success, error, warning, info; Inline alert; Inline status |
| [`src/components/workspace/service/SehatAppointments.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/SehatAppointments.tsx) | Shared toast: success, error |
| [`src/components/workspace/service/SubmitRequest.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/SubmitRequest.tsx) | Shared toast: success, error |
| [`src/components/workspace/service/TrackRequest.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/TrackRequest.tsx) | Shared toast: error; Inline alert; ErrorState component |
| [`src/components/workspace/service/VaultLogs.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/VaultLogs.tsx) | Inline alert |
| [`src/components/workspace/service/VaultMessageTimeline.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/service/VaultMessageTimeline.tsx) | Inline status |

### Workspace — whatsapp (29 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/components/workspace/whatsapp/ai-agent.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/ai-agent.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/auto-response.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/auto-response.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/bsuid.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/bsuid.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/business-profile.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/business-profile.tsx) | Shared toast: success, error, warning |
| [`src/components/workspace/whatsapp/calling.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/calling.tsx) | Shared toast: success, error, info |
| [`src/components/workspace/whatsapp/campaign.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/campaign.tsx) | Shared toast: error |
| [`src/components/workspace/whatsapp/catalog-builder.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/catalog-builder.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/connected-accounts.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/connected-accounts.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/conversions-api.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/conversions-api.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/cost-controls.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/cost-controls.tsx) | Shared toast: error |
| [`src/components/workspace/whatsapp/ctwa-ads.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/ctwa-ads.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/embedded-signup.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/embedded-signup.tsx) | Shared toast: success |
| [`src/components/workspace/whatsapp/flow-funnel.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/flow-funnel.tsx) | Inline alert; Inline status |
| [`src/components/workspace/whatsapp/flow-hub.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/flow-hub.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/flow-publish.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/flow-publish.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/flow-responses.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/flow-responses.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/flows.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/flows.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/groups.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/groups.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/interactive-lists.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/interactive-lists.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/migration.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/migration.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/my-account.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/my-account.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/scripts.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/scripts.tsx) | Shared toast hook (no direct send in search) |
| [`src/components/workspace/whatsapp/send-test.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/send-test.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/subscribe-settings.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/subscribe-settings.tsx) | Shared toast: success, error; Inline alert; Inline status |
| [`src/components/workspace/whatsapp/template-builder.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/template-builder.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/templates.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/templates.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/waba-dashboard.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/waba-dashboard.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/webhooks.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/webhooks.tsx) | Shared toast: success, error |
| [`src/components/workspace/whatsapp/welcome.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/components/workspace/whatsapp/welcome.tsx) | Shared toast: success, error |

### Workspace page routes (6 files)

| Source file | Feedback mechanism |
| --- | --- |
| [`src/pages/workspace/customers/index.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/pages/workspace/customers/index.tsx) | Shared toast: success, error, warning; Inline alert |
| [`src/pages/workspace/engage/broadcast/index.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/pages/workspace/engage/broadcast/index.tsx) | Shared toast: error |
| [`src/pages/workspace/engage/inbox/index.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/pages/workspace/engage/inbox/index.tsx) | Shared toast: success, error, info |
| [`src/pages/workspace/engage/logs/index.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/pages/workspace/engage/logs/index.tsx) | Shared toast: success, error |
| [`src/pages/workspace/settings/internal-agent.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/pages/workspace/settings/internal-agent.tsx) | Inline status |
| [`src/pages/workspace/task/index.tsx`](https://github.com/wecare-digital/wecare-digital/blob/fix/lime-toasts-surface-audit-20261031/src/pages/workspace/task/index.tsx) | Shared toast: success, error |

## Source-of-truth files

| To change | Edit |
| --- | --- |
| All authenticated workspace toasts | `src/styles/inner-ux.css` for design; `src/components/Toast.tsx` for lifecycle/ARIA; `src/contexts/ToastContext.tsx` for the public `toast.success/error/warning/info` API |
| Public Orders WhatsApp send button and local feedback | `src/components/orders/OrdersPage.tsx` |
| Public sign-in messaging | `src/pages/auth.tsx` plus `amplify/functions/ai/customer-commerce-mcp/customer_oauth_authorize.py`, `customer_oauth_web.py`, `customer_oauth_config.py` |
| Orders send backend | `amplify/functions/auth/customer-profile/handler.py` and `amplify/functions/messaging/whatsapp-business-api/handler.py` |
| WhatsApp F001/template activation runbook | `docs/operations/f001-subscribe.md` |
| Individual public form errors / status boxes | Their component source files in the inventory above, **not** `ToastContext` |

## Outstanding functional investigations (not resolved by the appearance patch)

1. Verify the Meta-approved `service_details` template status and FLOW button mode, and reconcile `NAVIGATE` versus `DATA_EXCHANGE` with `flow_token` and any optional `flow_action_data` parameter. The backend currently forwards a template action that Meta rejected with code 131009. Do not claim the message was sent or retry in a loop.
2. Capture the **redacted** `GET /auth/state` URL and HTTP 400 response, including only parameter **names** (not values/cookies/tokens). The backend intentionally does not reveal a more specific cause through its public response. Improve frontend error text for invalid requests separately from temporary HTTP 5xx failures after determining whether the request was invalid, the authorization state stale, or another validation rejected it.
3. Optional future work: move public notifications behind a shared public-only feedback provider if needed; ensure all persistent validation errors stay inline. Reconcile the duplicated `.toast-container` styles in `Layout.css` and `inner-ux.css` without disrupting import order.

## Verification checklist

- Run the existing `tests/test_checkout_profile_lime_contract.py` and the focused toast consistency test from this branch.
- Check desktop and mobile: the Orders status appears under the profile action, never covers an order/invoice control, and vanishes after four seconds or dismissal.
- Workspace toast types: success/error/warning/info all lime-green; symbols and alert semantics still distinguish severity; keyboard focus and reduced-motion exit work.
- Verify `/auth/?return=/orders/` with the browser Network panel; do not mark the authentication defect fixed based solely on toast styling.
- Confirm Meta template status and safely test a single authorized WhatsApp send only after parameter compatibility is verified.

No live production send or authentication-state mutation was performed during this audit.
