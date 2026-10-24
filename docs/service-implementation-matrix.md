# Service implementation matrix

**Generated** by `scripts/generate_service_matrix.py` from `docs/execution/runtime-inventory.json` (`2026-10-08T22:39:47+00:00`), region `us-east-1`.

Do not hand-edit. Regenerate:

```bash
python scripts/generate_runtime_inventory.py
python scripts/generate_service_matrix.py
```

## Totals

| | Measured |
|---|---:|
| functions | 74 |
| routes | 381 |
| tables | 82 |
| functions with a `live` alias | 67 |
| functions in the deploy map | 69 |

## Read this before drawing conclusions

* **Deploy owner** is who *can* ship a change, not evidence that a deploy happened.
* **Frontend callers** is a textual join on the route path appearing in `src/**/*.ts(x)`. It under-reports paths built by concatenation and over-reports ones only mentioned in a comment.
* **Zero invocations** marks a review candidate, not a defect. A provider webhook can be legitimately idle.
* There is deliberately **no test-coverage column**. Test-to-function mapping is not derivable from this data, and a fabricated column would be worse than its absence.

## Functions

| Function | Source | Deploy owner | `live` | Routes | Inv 7d | Err 7d | Log ret. | Event sources |
|---|---|---|:-:|--:|--:|--:|--:|---|
| `stack-wecare-url-shortener` | `amplify/functions/core/url-shortener` | `deploy_all_lambdas.py` | yes | 6 | 50 | 0 | 30 | — |
| `wecare-agent-action-group` | `amplify/functions/ai/agent-action-group` | `deploy_all_lambdas.py` | yes | 1 | 0 | 0 | 30 | — |
| `wecare-ai-config-management` | `amplify/functions/ai/ai-config-management` | `deploy_all_lambdas.py` | yes | 17 | 0 | 0 | 30 | — |
| `wecare-ai-generate-response` | `amplify/functions/ai/ai-generate-response` | `deploy_all_lambdas.py` | yes | 3 | 4 | 0 | 30 | — |
| `wecare-ai-query-kb` | `amplify/functions/ai/ai-query-kb` | `deploy_all_lambdas.py` | yes | 1 | 0 | 0 | 30 | — |
| `wecare-auth-middleware` | `amplify/functions/core/auth-middleware` | `deploy_all_lambdas.py` | yes | 1 | 0 | 0 | 30 | — |
| `wecare-automation-rules` | `amplify/functions/core/automation-rules` | `deploy_all_lambdas.py` | yes | 6 | 40 | 0 | 90 | — |
| `wecare-billing` | `amplify/functions/operations/billing` | `deploy_all_lambdas.py` | yes | 2 | 464 | 0 | 30 | — |
| `wecare-bulk-job-control` | `amplify/functions/operations/bulk-job-control` | `deploy_all_lambdas.py` | yes | 2 | 0 | 0 | 30 | — |
| `wecare-bulk-job-create` | `amplify/functions/operations/bulk-job-create` | `deploy_all_lambdas.py` | yes | 5 | 0 | 0 | 30 | — |
| `wecare-bulk-worker` | `amplify/functions/operations/bulk-worker` | `deploy_all_lambdas.py` | yes | 1 | 0 | 0 | 30 | stack-wecare-digital-bulk-queue |
| `wecare-catalog-management` | `amplify/functions/ecommerce/catalog-management` | `deploy_all_lambdas.py` | yes | 0 | 4 | 0 | 30 | — |
| `wecare-checkout` | `amplify/functions/ecommerce/checkout` | `deploy_all_lambdas.py` | yes | 5 | 242 | 0 | 30 | — |
| `wecare-cognito-custom-message` | `amplify/functions/auth/cognito-custom-message` | `deploy_all_lambdas.py` | yes | 0 | 10 | 0 | 30 | — |
| `wecare-contacts` | `amplify/functions/core/contacts` | `deploy_all_lambdas.py` | yes | 7 | 3098 | 0 | 30 | — |
| `wecare-conversation-meta` | `amplify/functions/core/conversation-meta` | `deploy_all_lambdas.py` | yes | 7 | 199 | 0 | 90 | — |
| `wecare-coupons` | `amplify/functions/ecommerce/coupons` | `deploy_all_lambdas.py` | yes | 7 | 15 | 0 | 30 | — |
| `wecare-crm` | `amplify/functions/core/crm` | `deploy_all_lambdas.py` | yes | 12 | 0 | 0 | 30 | — |
| `wecare-customer-orders` | `amplify/functions/ecommerce/customer-orders` | `deploy_all_lambdas.py` | yes | 1 | 10 | 0 | 30 | — |
| `wecare-customer-profile` | `amplify/functions/auth/customer-profile` | `deploy_all_lambdas.py` | yes | 2 | 4 | 0 | 30 | — |
| `wecare-customer-session` | `amplify/functions/ecommerce/customer-session` | `deploy_all_lambdas.py` | yes | 1 | 46 | 0 | 30 | — |
| `wecare-customer-whatsapp-auth` | `amplify/functions/auth/customer-whatsapp-auth` | `deploy_all_lambdas.py` | yes | 0 | 55 | 0 | 30 | — |
| `wecare-dlq-replay` | `amplify/functions/operations/dlq-replay` | `deploy_all_lambdas.py` | yes | 3 | 0 | 0 | 30 | — |
| `wecare-docs-scraper` | `—` | GitHub Actions (container image) | **no** | 4 | 7 | 0 | 90 | — |
| `wecare-email-verification` | `amplify/functions/auth/email-verification` | `deploy_all_lambdas.py` | yes | 2 | 50 | 0 | 30 | — |
| `wecare-faq-handler` | `amplify/functions/core/faq-handler` | `deploy_all_lambdas.py` | yes | 1 | 0 | 0 | 30 | — |
| `wecare-get-miss-redirect` | `—` | own deployer (Lambda@Edge, associates by version) | **no** | 0 | 0 | 0 | 30 | — |
| `wecare-inbound-whatsapp` | `amplify/functions/messaging/inbound-whatsapp-handler` | `deploy_all_lambdas.py` | yes | 1 | 1360 | 0 | 30 | — |
| `wecare-invoice-engine` | `amplify/functions/payments/invoice-engine` | `deploy_all_lambdas.py` | yes | 17 | 39 | 0 | 30 | — |
| `wecare-marketing-ads` | `amplify/functions/messaging/marketing-ads` | `deploy_all_lambdas.py` | yes | 2 | 2 | 0 | 90 | — |
| `wecare-mcp` | `—` | **none — unpatchable** | yes | 1 | 39 | 0 | 30 | — |
| `wecare-media-cleanup` | `amplify/functions/messaging/media-cleanup` | `deploy_all_lambdas.py` | yes | 1 | 7 | 0 | 30 | — |
| `wecare-messages-delete` | `amplify/functions/core/messages-delete` | `deploy_all_lambdas.py` | yes | 3 | 0 | 0 | 30 | — |
| `wecare-messages-read` | `amplify/functions/core/messages-read` | `deploy_all_lambdas.py` | yes | 1 | 3517 | 0 | 30 | — |
| `wecare-meta-business-agent` | `amplify/functions/messaging/meta-business-agent` | `deploy_all_lambdas.py` | yes | 2 | 0 | 0 | 90 | — |
| `wecare-meta-catalog-sync` | `amplify/functions/ecommerce/meta-catalog-sync` | `deploy_all_lambdas.py` | yes | 0 | 1376 | 0 | 30 | — |
| `wecare-notification-worker` | `amplify/functions/messaging/notification-worker` | `deploy_all_lambdas.py` | yes | 0 | 0 | 0 | 30 | — |
| `wecare-outbound-email` | `amplify/functions/messaging/outbound-email` | `deploy_all_lambdas.py` | yes | 1 | 0 | 0 | 30 | — |
| `wecare-outbound-sms` | `amplify/functions/messaging/outbound-sms` | `deploy_all_lambdas.py` | yes | 1 | 0 | 0 | 30 | — |
| `wecare-outbound-whatsapp` | `amplify/functions/messaging/outbound-whatsapp` | `deploy_all_lambdas.py` | yes | 1 | 1215 | 0 | 30 | — |
| `wecare-partner-onboarding` | `amplify/functions/messaging/partner-onboarding` | `deploy_all_lambdas.py` | yes | 21 | 0 | 0 | 90 | — |
| `wecare-partner-token-refresh` | `amplify/functions/messaging/partner-token-refresh` | `deploy_all_lambdas.py` | **no** | 0 | 7 | 0 | 90 | — |
| `wecare-payments-read` | `amplify/functions/payments/payments-read` | `deploy_all_lambdas.py` | yes | 2 | 0 | 0 | 30 | — |
| `wecare-plivo-answer` | `amplify/functions/messaging/plivo-answer` | `deploy_all_lambdas.py` | yes | 5 | 108 | 0 | 30 | — |
| `wecare-product-image-gen` | `amplify/functions/ecommerce/product-image-gen` | `deploy_all_lambdas.py` | yes | 3 | 0 | 0 | 30 | — |
| `wecare-pstn-softphone` | `amplify/functions/messaging/pstn-softphone` | `deploy_all_lambdas.py` | yes | 5 | 0 | 0 | 30 | — |
| `wecare-push-notifications` | `amplify/functions/messaging/push-notifications` | `deploy_all_lambdas.py` | yes | 2 | 0 | 0 | 30 | — |
| `wecare-razorpay-webhook` | `amplify/functions/payments/razorpay-webhook` | `deploy_all_lambdas.py` | yes | 1 | 18 | 0 | 30 | — |
| `wecare-rcs-dlr` | `amplify/functions/messaging/rcs-dlr` | `deploy_all_lambdas.py` | yes | 2 | 1390 | 0 | 90 | — |
| `wecare-rcs-send` | `amplify/functions/messaging/rcs-send` | `deploy_all_lambdas.py` | yes | 3 | 1095 | 0 | 90 | — |
| `wecare-scheduled-messages` | `amplify/functions/messaging/scheduled-messages` | `deploy_all_lambdas.py` | yes | 3 | 2016 | 0 | 30 | — |
| `wecare-secure-files` | `amplify/functions/core/secure-files` | `deploy_all_lambdas.py` | yes | 10 | 4 | 0 | 30 | — |
| `wecare-seo-tools` | `—` | `scripts/deploy_seo_tools.py` | **no** | 2 | 592646 | 0 | 30 | wecare-blog-ingest |
| `wecare-service-api` | `amplify/functions/core/service-api` | `deploy_all_lambdas.py` | yes | 0 | 0 | 0 | 30 | — |
| `wecare-service-requests` | `amplify/functions/ecommerce/service-requests` | `deploy_all_lambdas.py` | yes | 2 | 6 | 0 | 30 | — |
| `wecare-site-language` | `amplify/functions/core/site-language` | `deploy_all_lambdas.py` | yes | 3 | 88190 | 0 | 30 | — |
| `wecare-sms-aws` | `amplify/functions/messaging/sms-aws` | `deploy_all_lambdas.py` | yes | 9 | 49 | 0 | 30 | — |
| `wecare-system-cleanup` | `amplify/functions/operations/system-cleanup` | `deploy_all_lambdas.py` | yes | 3 | 14 | 0 | 30 | — |
| `wecare-template-analytics` | `amplify/functions/messaging/template-analytics` | `deploy_all_lambdas.py` | yes | 3 | 0 | 0 | 30 | — |
| `wecare-url-shortener` | `amplify/functions/core/url-shortener` | `deploy_all_lambdas.py` | **no** | 0 | 0 | 0 | 90 | — |
| `wecare-voice-aws` | `amplify/functions/messaging/voice-aws` | `deploy_all_lambdas.py` | yes | 8 | 0 | 0 | 30 | — |
| `wecare-voice-cdr-read` | `amplify/functions/messaging/voice-cdr-read` | `deploy_all_lambdas.py` | yes | 2 | 0 | 0 | 30 | — |
| `wecare-voice-in-c2c` | `amplify/functions/messaging/voice-in/c2c` | `deploy_all_lambdas.py` | yes | 4 | 0 | 0 | 30 | — |
| `wecare-voice-in-obd` | `amplify/functions/messaging/voice-in/obd` | `deploy_all_lambdas.py` | yes | 12 | 0 | 0 | 30 | — |
| `wecare-waba-management` | `amplify/functions/messaging/waba-management` | `deploy_all_lambdas.py` | yes | 14 | 0 | 0 | 30 | — |
| `wecare-whatsapp-business-api` | `amplify/functions/messaging/whatsapp-business-api` | `deploy_all_lambdas.py` | yes | 94 | 110 | 0 | 30 | — |
| `wecare-whatsapp-calling` | `amplify/functions/messaging/whatsapp-calling` | `deploy_all_lambdas.py` | yes | 11 | 1278 | 0 | 30 | — |
| `wecare-whatsapp-template-management` | `amplify/functions/messaging/whatsapp-template-management` | `deploy_all_lambdas.py` | yes | 5 | 0 | 0 | 30 | — |
| `wecare-whatsapp-templates` | `amplify/functions/messaging/whatsapp-templates` | `deploy_all_lambdas.py` | yes | 12 | 25 | 0 | 30 | — |
| `wecare-whatsapp-voice` | `amplify/functions/messaging/whatsapp-voice` | `deploy_all_lambdas.py` | yes | 9 | 40 | 0 | 30 | — |
| `wecare-workspace-mcp` | `—` | **none — unpatchable** | yes | 3 | 633 | 0 | 14 | — |

## Routes, and the frontend that calls them

Grouped by target function. `auth` is the API Gateway `authorizationType`; `NONE` there does **not** mean unauthenticated - this fleet authenticates in the handler, which `scripts/audit_route_auth.py --gate` is what actually proves (0 OPEN at both layers).

### `stack-wecare-url-shortener`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /links/{code}` | live | NONE | `design-reference.tsx`, `index.tsx` |
| `GET /links` | live | NONE | `design-reference.tsx`, `index.tsx` |
| `GET /links/{code}` | live | NONE | `design-reference.tsx`, `index.tsx` |
| `GET /r/{code}` | live | NONE | `client.ts`, `seo.ts`, `BottomNav.tsx`, `FloatingAgent.tsx` +169 |
| `POST /links` | live | NONE | `design-reference.tsx`, `index.tsx` |
| `PUT /links/{code}` | live | NONE | `design-reference.tsx`, `index.tsx` |

### `wecare-agent-action-group`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /ai/agent` | live | NONE | `code-repo.tsx`, `system-architecture.tsx` |

### `wecare-ai-config-management`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /ai/botflow` | live | NONE | `index.tsx` |
| `GET /ai/botflow` | live | NONE | `index.tsx` |
| `GET /ai/config` | live | NONE | `client.ts`, `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |
| `GET /ai/fallbacks` | live | NONE | `client.ts` |
| `GET /ai/fallbacks/{lang}` | live | NONE | `client.ts` |
| `GET /ai/interactions` | live | NONE | `client.ts` |
| `GET /ai/internal/config` | live | NONE | `index.tsx`, `internal-agent.tsx` |
| `GET /ai/languages` | live | NONE | `client.ts` |
| `GET /ai/prompts` | live | NONE | `client.ts` |
| `GET /ai/prompts/{lang}` | live | NONE | `client.ts` |
| `GET /ai/stats` | live | NONE | `client.ts` |
| `POST /ai/test` | live | NONE | `client.ts` |
| `PUT /ai/botflow` | live | NONE | `index.tsx` |
| `PUT /ai/config` | live | NONE | `client.ts`, `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |
| `PUT /ai/fallbacks/{lang}` | live | NONE | `client.ts` |
| `PUT /ai/internal/config` | live | NONE | `index.tsx`, `internal-agent.tsx` |
| `PUT /ai/prompts/{lang}` | live | NONE | `client.ts` |

### `wecare-ai-generate-response`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /ai/approvals` | live | NONE | `InternalChatTab.tsx`, `InternalChatApproval.test.tsx` |
| `POST /ai/approvals/status` | live | NONE | — none |
| `POST /ai/generate` | live | NONE | `client.ts`, `FloatingAgent.tsx`, `InfraTab.tsx`, `InternalChatTab.tsx` +3 |

### `wecare-ai-query-kb`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /ai/query` | live | NONE | `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |

### `wecare-auth-middleware`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /auth/validate` | live | NONE | `client.ts` |

### `wecare-automation-rules`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /automation/rules/{id}` | live | NONE | `client.ts` |
| `GET /automation/rules` | live | NONE | `client.ts` |
| `OPTIONS /automation/rules` | live | NONE | `client.ts` |
| `OPTIONS /automation/rules/{id}` | live | NONE | `client.ts` |
| `POST /automation/rules` | live | NONE | `client.ts` |
| `PUT /automation/rules/{id}` | live | NONE | `client.ts` |

### `wecare-billing`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /billing` | live | NONE | `client.ts`, `InfraTab.tsx`, `code-repo.tsx`, `index.tsx` +5 |
| `POST /billing` | live | NONE | `client.ts`, `InfraTab.tsx`, `code-repo.tsx`, `index.tsx` +5 |

### `wecare-bulk-job-control`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /bulk/control` | live | NONE | `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |
| `POST /bulk/control` | live | NONE | `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |

### `wecare-bulk-job-create`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /bulk/jobs/{jobId}` | live | NONE | `client.ts` |
| `GET /bulk/jobs` | live | NONE | `client.ts` |
| `POST /bulk/create` | live | NONE | `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |
| `POST /bulk/jobs` | live | NONE | `client.ts` |
| `PUT /bulk/jobs/{jobId}` | live | NONE | `client.ts` |

### `wecare-bulk-worker`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /bulk/worker` | live | NONE | — none |

### `wecare-checkout`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /ecommerce/service-prices` | live | NONE | `services.ts`, `servicePricing.ts`, `ServiceRequestPurchase.test.tsx` |
| `POST /ecommerce/checkout` | live | NONE | `contribution.ts`, `cart.ts`, `cart.tsx`, `status.tsx` +1 |
| `POST /ecommerce/checkout/status` | live | NONE | `status.tsx`, `success.tsx` |
| `POST /ecommerce/prepare-checkout` | live | NONE | `BlogContribution.tsx`, `contribution.ts`, `services.ts`, `whatsappBasket.ts` +4 |
| `POST /ecommerce/verify-callback` | live | NONE | `BlogContribution.tsx`, `cart.tsx`, `CartCheckout.test.tsx` |

### `wecare-contacts`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /contacts` | live | NONE | `client.ts`, `RichTextEditor.tsx`, `SearchModal.tsx`, `InfraTab.tsx` +24 |
| `DELETE /contacts/{contactId}` | live | NONE | `client.ts`, `RichTextEditor.tsx`, `SearchModal.tsx`, `InfraTab.tsx` +24 |
| `GET /contacts` | live | NONE | `client.ts`, `RichTextEditor.tsx`, `SearchModal.tsx`, `InfraTab.tsx` +24 |
| `GET /contacts/search` | live | NONE | — none |
| `POST /contacts` | live | NONE | `client.ts`, `RichTextEditor.tsx`, `SearchModal.tsx`, `InfraTab.tsx` +24 |
| `PUT /contacts` | live | NONE | `client.ts`, `RichTextEditor.tsx`, `SearchModal.tsx`, `InfraTab.tsx` +24 |
| `PUT /contacts/{contactId}` | live | NONE | `client.ts`, `RichTextEditor.tsx`, `SearchModal.tsx`, `InfraTab.tsx` +24 |

### `wecare-conversation-meta`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /inbox/meta` | live | NONE | `client.ts`, `index.tsx` |
| `GET /inbox/meta/{conversationId}` | live | NONE | `client.ts`, `index.tsx` |
| `OPTIONS /inbox/meta` | live | NONE | `client.ts`, `index.tsx` |
| `OPTIONS /inbox/meta/{conversationId}` | live | NONE | `client.ts`, `index.tsx` |
| `OPTIONS /inbox/meta/{conversationId}/note` | live | NONE | — none |
| `POST /inbox/meta/{conversationId}/note` | live | NONE | — none |
| `PUT /inbox/meta/{conversationId}` | live | NONE | `client.ts`, `index.tsx` |

### `wecare-coupons`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /coupons` | live | NONE | — none |
| `GET /coupons/{code}` | live | NONE | — none |
| `POST /coupons` | live | NONE | — none |
| `POST /coupons/hold` | live | NONE | — none |
| `POST /coupons/release` | live | NONE | — none |
| `POST /coupons/validate` | live | NONE | — none |
| `POST /coupons/{code}/deactivate` | live | NONE | — none |

### `wecare-crm`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /crm/activities` | live | NONE | — none |
| `GET /crm/contacts/{contactId}/360` | live | NONE | — none |
| `GET /crm/leads` | live | NONE | — none |
| `GET /crm/leads/{leadId}` | live | NONE | — none |
| `GET /crm/opportunities` | live | NONE | — none |
| `GET /crm/opportunities/{opportunityId}` | live | NONE | — none |
| `GET /crm/pipelines` | live | NONE | — none |
| `PATCH /crm/leads/{leadId}` | live | NONE | — none |
| `PATCH /crm/opportunities/{opportunityId}` | live | NONE | — none |
| `POST /crm/activities` | live | NONE | — none |
| `POST /crm/leads` | live | NONE | — none |
| `POST /crm/leads/{leadId}/convert` | live | NONE | — none |

### `wecare-customer-orders`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /ecommerce/my-orders` | live | NONE | `orders.tsx`, `OrdersPage.test.tsx` |

### `wecare-customer-profile`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `OPTIONS /customer/profile` | live | NONE | `CheckoutProfile.tsx`, `CheckoutProfile.test.tsx`, `CheckoutProfileModes.test.tsx` |
| `POST /customer/profile` | live | NONE | `CheckoutProfile.tsx`, `CheckoutProfile.test.tsx`, `CheckoutProfileModes.test.tsx` |

### `wecare-customer-session`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /ecommerce/customer-session` | live | NONE | `customerAuth.ts`, `CustomerSessionRestore.test.ts`, `SignInMessages.test.tsx` |

### `wecare-dlq-replay`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /dlq` | live | NONE | `client.ts`, `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` +1 |
| `GET /dlq/replay` | live | NONE | `client.ts`, `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |
| `POST /dlq/replay` | live | NONE | `client.ts`, `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |

### `wecare-docs-scraper`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /docs/changelog` | $LATEST | NONE | `index.tsx` |
| `GET /docs/sources` | $LATEST | NONE | `index.tsx` |
| `POST /docs/scrape` | $LATEST | NONE | `index.tsx` |
| `POST /docs/sources` | $LATEST | NONE | `index.tsx` |

### `wecare-email-verification`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `OPTIONS /auth/email-verification` | live | NONE | `CheckoutProfile.tsx`, `CheckoutProfile.test.tsx`, `CheckoutProfileModes.test.tsx` |
| `POST /auth/email-verification` | live | NONE | `CheckoutProfile.tsx`, `CheckoutProfile.test.tsx`, `CheckoutProfileModes.test.tsx` |

### `wecare-faq-handler`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /faq` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `code-repo.tsx` +7 |

### `wecare-inbound-whatsapp`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /whatsapp/inbound` | live | NONE | — none |

### `wecare-invoice-engine`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /invoices/clear-all` | live | NONE | `index.tsx` |
| `DELETE /invoices/{invoiceId}` | live | NONE | `client.ts`, `InfraTab.tsx`, `index.tsx`, `lambda-functions.tsx` +2 |
| `GET /invoices` | live | NONE | `client.ts`, `InfraTab.tsx`, `index.tsx`, `lambda-functions.tsx` +2 |
| `GET /invoices/{invoiceId}` | live | NONE | `client.ts`, `InfraTab.tsx`, `index.tsx`, `lambda-functions.tsx` +2 |
| `GET /invoices/{invoiceId}/delivery-log` | live | NONE | — none |
| `POST /invoices` | live | NONE | `client.ts`, `InfraTab.tsx`, `index.tsx`, `lambda-functions.tsx` +2 |
| `POST /invoices/clear-all` | live | NONE | `index.tsx` |
| `POST /invoices/from-payment` | live | NONE | — none |
| `POST /invoices/next-sequence` | live | NONE | — none |
| `POST /invoices/send-pending-by-phone` | live | NONE | — none |
| `POST /invoices/{invoiceId}/cancel` | live | NONE | — none |
| `POST /invoices/{invoiceId}/generate-image` | live | NONE | — none |
| `POST /invoices/{invoiceId}/generate-pdf` | live | NONE | — none |
| `POST /invoices/{invoiceId}/remark` | live | NONE | — none |
| `POST /invoices/{invoiceId}/send-payment-link` | live | NONE | — none |
| `POST /invoices/{invoiceId}/send-whatsapp` | live | NONE | — none |
| `PUT /invoices/{invoiceId}` | live | NONE | `client.ts`, `InfraTab.tsx`, `index.tsx`, `lambda-functions.tsx` +2 |

### `wecare-marketing-ads`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `ANY /marketing-ads` | live | NONE | `client.ts`, `ctwa-ads.tsx` |
| `OPTIONS /marketing-ads` | live | NONE | `client.ts`, `ctwa-ads.tsx` |

### `wecare-mcp`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `ANY /mcp` | live | NONE | `WorkflowTerminal.tsx`, `navigation.ts`, `workspace-mcp.test.ts`, `workspace-mcp.ts` +4 |

### `wecare-media-cleanup`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /media/cleanup` | live | NONE | — none |

### `wecare-messages-delete`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /messages` | live | NONE | `client.ts`, `AddressMessageComposer.tsx`, `ContactMessageComposer.tsx`, `LocationRequestComposer.tsx` +18 |
| `DELETE /messages/clear-all` | live | NONE | `index.tsx` |
| `DELETE /messages/{messageId}` | live | NONE | `client.ts`, `AddressMessageComposer.tsx`, `ContactMessageComposer.tsx`, `LocationRequestComposer.tsx` +18 |

### `wecare-messages-read`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /messages` | live | NONE | `client.ts`, `AddressMessageComposer.tsx`, `ContactMessageComposer.tsx`, `LocationRequestComposer.tsx` +18 |

### `wecare-meta-business-agent`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `ANY /meta-agent` | live | NONE | `client.ts`, `navigation.ts`, `index.tsx`, `ai-agent.tsx` +3 |
| `POST /agent-tool` | live | NONE | — none |

### `wecare-outbound-email`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /email/send` | live | NONE | `client.ts`, `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |

### `wecare-outbound-sms`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /sms/send` | live | NONE | `client.ts`, `InfraTab.tsx`, `lambda-functions.tsx`, `system-architecture.tsx` |

### `wecare-outbound-whatsapp`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /whatsapp/send` | live | NONE | `client.ts`, `InfraTab.tsx`, `SystemTab.tsx`, `navigation.ts` +3 |

### `wecare-partner-onboarding`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /partners/tenants` | live | NONE | `connected-accounts.tsx` |
| `GET /partners/billing` | live | NONE | `connected-accounts.tsx`, `my-account.tsx` |
| `GET /partners/billing/analytics` | live | NONE | `my-account.tsx` |
| `GET /partners/me` | live | NONE | `my-account.tsx` |
| `GET /partners/messages` | live | NONE | `my-account.tsx` |
| `GET /partners/tenants` | live | NONE | `connected-accounts.tsx` |
| `OPTIONS /partners/billing` | live | NONE | `connected-accounts.tsx`, `my-account.tsx` |
| `OPTIONS /partners/billing/analytics` | live | NONE | `my-account.tsx` |
| `OPTIONS /partners/billing/settings` | live | NONE | `connected-accounts.tsx` |
| `OPTIONS /partners/billing/topup` | live | NONE | `connected-accounts.tsx`, `my-account.tsx` |
| `OPTIONS /partners/billing/topup-order` | live | NONE | `my-account.tsx` |
| `OPTIONS /partners/embedded-signup` | live | NONE | `EmbeddedSignupPanel.tsx` |
| `OPTIONS /partners/me` | live | NONE | `my-account.tsx` |
| `OPTIONS /partners/messages` | live | NONE | `my-account.tsx` |
| `OPTIONS /partners/send` | live | NONE | `my-account.tsx` |
| `OPTIONS /partners/tenants` | live | NONE | `connected-accounts.tsx` |
| `POST /partners/billing/settings` | live | NONE | `connected-accounts.tsx` |
| `POST /partners/billing/topup` | live | NONE | `connected-accounts.tsx`, `my-account.tsx` |
| `POST /partners/billing/topup-order` | live | NONE | `my-account.tsx` |
| `POST /partners/embedded-signup` | live | NONE | `EmbeddedSignupPanel.tsx` |
| `POST /partners/send` | live | NONE | `my-account.tsx` |

### `wecare-payments-read`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /payments` | live | NONE | `InfraTab.tsx`, `code-repo.tsx`, `index.tsx`, `lambda-functions.tsx` +2 |
| `GET /payments/{paymentId}` | live | NONE | `InfraTab.tsx`, `code-repo.tsx`, `index.tsx`, `lambda-functions.tsx` +2 |

### `wecare-plivo-answer`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /plivo/answer` | live | NONE | — none |
| `POST /plivo/dial-events` | live | NONE | — none |
| `POST /plivo/events` | live | NONE | — none |
| `POST /plivo/fallback` | live | NONE | — none |
| `POST /plivo/hangup` | live | NONE | — none |

### `wecare-product-image-gen`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /store/preview-product-image` | live | NONE | `catalog.tsx` |
| `POST /store/convert-flag` | live | NONE | `catalog.tsx` |
| `POST /store/generate-product-image` | live | NONE | `catalog.tsx` |

### `wecare-pstn-softphone`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /pstn/diagnostics` | live | NONE | — none |
| `GET /pstn/session` | live | NONE | — none |
| `POST /pstn/session/events` | live | NONE | — none |
| `POST /pstn/session/presence` | live | NONE | — none |
| `POST /pstn/token` | live | NONE | — none |

### `wecare-push-notifications`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /push/devices` | live | NONE | `index.tsx` |
| `POST /push/send` | live | NONE | `index.tsx` |

### `wecare-razorpay-webhook`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /razorpay-webhook` | live | NONE | `code-repo.tsx`, `index.tsx`, `system-architecture.tsx` |

### `wecare-rcs-dlr`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /webhook/sinch-rcs` | live | NONE | — none |
| `POST /webhook/sinch-rcs` | live | NONE | — none |

### `wecare-rcs-send`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /rcs/send` | live | NONE | `client.ts`, `SystemTab.tsx`, `index.tsx` |
| `OPTIONS /rcs/send` | live | NONE | `client.ts`, `SystemTab.tsx`, `index.tsx` |
| `POST /rcs/send` | live | NONE | `client.ts`, `SystemTab.tsx`, `index.tsx` |

### `wecare-scheduled-messages`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /scheduled` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +4 |
| `GET /scheduled` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +4 |
| `POST /scheduled` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +4 |

### `wecare-secure-files`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /secure-files` | live | NONE | `client.ts`, `navigation.ts`, `ConfirmContext.test.tsx`, `NativeDialogs.test.tsx` |
| `GET /secure-files/dropdocs/{requestId}/documents` | live | NONE | — none |
| `GET /secure-files/mine` | live | NONE | `client.ts` |
| `GET /secure-files/{fileId}/download` | live | NONE | — none |
| `POST /secure-files/dropdocs/attach` | live | NONE | — none |
| `POST /secure-files/upload-init` | live | NONE | `client.ts` |
| `POST /secure-files/{fileId}/confirm` | live | NONE | — none |
| `POST /secure-files/{fileId}/order` | live | NONE | — none |
| `POST /secure-files/{fileId}/revoke` | live | NONE | — none |
| `POST /secure-files/{fileId}/whatsapp-pay` | live | NONE | — none |

### `wecare-seo-tools`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `ANY /seo-tools` | $LATEST | NONE | `seo.ts`, `InstructionsContent.tsx`, `public-blog.ts`, `index.tsx` +5 |
| `ANY /seo-tools/{proxy+}` | $LATEST | NONE | `seo.ts`, `InstructionsContent.tsx`, `public-blog.ts`, `index.tsx` +5 |

### `wecare-service-requests`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `POST /services/my-requests` | live | NONE | `serviceRequests.ts`, `OrdersRequests.test.tsx`, `ServiceRequestPurchase.test.tsx` |
| `POST /services/request-intent` | live | NONE | `serviceRequests.ts`, `ServiceRequestPurchase.test.tsx` |

### `wecare-site-language`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /site-language/languages` | live | NONE | `rtlLanguage.test.tsx` |
| `OPTIONS /site-language/{proxy+}` | live | NONE | `SupportWidget.tsx`, `rtlLanguage.test.tsx` |
| `POST /site-language/translate` | live | NONE | — none |

### `wecare-sms-aws`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /sms-aws/clear-logs` | live | NONE | `index.tsx`, `index.tsx` |
| `DELETE /sms-aws/templates` | live | NONE | — none |
| `GET /sms-aws/messages` | live | NONE | `client.ts`, `index.tsx` |
| `GET /sms-aws/send` | live | NONE | `client.ts`, `SystemTab.tsx`, `index.tsx`, `calling.tsx` |
| `GET /sms-aws/templates` | live | NONE | — none |
| `OPTIONS /sms-aws/templates` | live | NONE | — none |
| `POST /sms-aws/send` | live | NONE | `client.ts`, `SystemTab.tsx`, `index.tsx`, `calling.tsx` |
| `POST /sms-aws/templates` | live | NONE | — none |
| `PUT /sms-aws/templates` | live | NONE | — none |

### `wecare-system-cleanup`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /system-cleanup` | live | NONE | `client.ts`, `capacitor.ts`, `code-repo.tsx`, `index.tsx` +1 |
| `OPTIONS /system-cleanup` | live | NONE | `client.ts`, `capacitor.ts`, `code-repo.tsx`, `index.tsx` +1 |
| `POST /system-cleanup` | live | NONE | `client.ts`, `capacitor.ts`, `code-repo.tsx`, `index.tsx` +1 |

### `wecare-template-analytics`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `GET /templates/analytics` | live | NONE | `client.ts` |
| `GET /templates/analytics/{templateName}` | live | NONE | `client.ts` |
| `POST /templates/analytics` | live | NONE | `client.ts` |

### `wecare-voice-aws`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /voice-aws/calls/{callId}` | live | NONE | `client.ts`, `index.tsx` |
| `DELETE /voice-aws/clear-logs` | live | NONE | `index.tsx`, `index.tsx` |
| `DELETE /voice/calls` | live | NONE | `client.ts` |
| `GET /voice-aws/calls` | live | NONE | `client.ts`, `index.tsx` |
| `GET /voice-aws/send` | live | NONE | — none |
| `GET /voice/calls` | live | NONE | `client.ts` |
| `POST /voice-aws/call` | live | NONE | `client.ts`, `index.tsx` |
| `POST /voice-aws/send` | live | NONE | — none |

### `wecare-voice-cdr-read`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /voice-cdr-read` | live | NONE | `SystemTab.tsx`, `index.tsx` |
| `GET /voice-cdr-read` | live | NONE | `SystemTab.tsx`, `index.tsx` |

### `wecare-voice-in-c2c`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /voice-in/c2c` | live | NONE | `index.tsx`, `system-architecture.tsx`, `index.tsx`, `webhooks.tsx` |
| `DELETE /voice-in/c2c/clear-logs` | live | NONE | — none |
| `GET /voice-in/c2c` | live | NONE | `index.tsx`, `system-architecture.tsx`, `index.tsx`, `webhooks.tsx` |
| `POST /voice-in/c2c` | live | NONE | `index.tsx`, `system-architecture.tsx`, `index.tsx`, `webhooks.tsx` |

### `wecare-voice-in-obd`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /voice-in/obd` | live | NONE | `index.tsx`, `system-architecture.tsx`, `index.tsx`, `webhooks.tsx` |
| `DELETE /voice-in/obd/audio-library` | live | NONE | `index.tsx` |
| `DELETE /voice-in/obd/clear-logs` | live | NONE | — none |
| `GET /voice-in/obd` | live | NONE | `index.tsx`, `system-architecture.tsx`, `index.tsx`, `webhooks.tsx` |
| `GET /voice-in/obd/audio-library` | live | NONE | `index.tsx` |
| `OPTIONS /voice-in/obd/audio-library` | live | NONE | `index.tsx` |
| `POST /voice-in/obd` | live | NONE | `index.tsx`, `system-architecture.tsx`, `index.tsx`, `webhooks.tsx` |
| `POST /voice-in/obd/audio-library` | live | NONE | `index.tsx` |
| `POST /voice-in/obd/create` | live | NONE | — none |
| `POST /voice-in/obd/tts` | live | NONE | — none |
| `POST /voice-in/obd/upload-audio` | live | NONE | — none |
| `POST /voice-in/obd/upload-csv` | live | NONE | — none |

### `wecare-waba-management`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /waba/media/{mediaId}` | live | NONE | `client.ts` |
| `DELETE /waba/tags` | live | NONE | `client.ts` |
| `GET /waba` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `code-repo.tsx` +6 |
| `GET /waba/events` | live | NONE | `client.ts` |
| `GET /waba/media/{mediaId}` | live | NONE | `client.ts` |
| `GET /waba/phone/{phoneNumberId}` | live | NONE | `client.ts` |
| `GET /waba/tags` | live | NONE | `client.ts` |
| `GET /waba/{wabaId}` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `code-repo.tsx` +6 |
| `POST /waba` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `code-repo.tsx` +6 |
| `POST /waba/conversational-components` | live | NONE | `client.ts` |
| `POST /waba/media` | live | NONE | `client.ts` |
| `POST /waba/tags` | live | NONE | `client.ts` |
| `PUT /waba` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `code-repo.tsx` +6 |
| `PUT /waba/{wabaId}/events` | live | NONE | — none |

### `wecare-whatsapp-business-api`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `ANY /wa-business/{proxy+}` | live | NONE | `client.ts`, `ProductMessageComposer.tsx`, `InfraTab.tsx`, `index.tsx` +5 |
| `DELETE /wa-business/assigned-users` | live | NONE | — none |
| `DELETE /wa-business/faq/{faqId}` | live | NONE | — none |
| `DELETE /wa-business/flows` | live | NONE | — none |
| `DELETE /wa-business/groups` | live | NONE | — none |
| `DELETE /wa-business/service/drafts/{flowCode}` | live | NONE | — none |
| `DELETE /wa-business/username` | live | NONE | — none |
| `DELETE /wa-business/webhooks` | live | NONE | — none |
| `GET /wa-business/appointments` | live | NONE | — none |
| `GET /wa-business/assigned-users` | live | NONE | — none |
| `GET /wa-business/assigned-wabas` | live | NONE | — none |
| `GET /wa-business/bot` | live | NONE | — none |
| `GET /wa-business/calling-settings` | live | NONE | — none |
| `GET /wa-business/catalog-flow-map` | live | NONE | — none |
| `GET /wa-business/conversational-automation` | live | NONE | — none |
| `GET /wa-business/direct-send/templates` | live | NONE | — none |
| `GET /wa-business/documents` | live | NONE | — none |
| `GET /wa-business/documents/{documentId}` | live | NONE | — none |
| `GET /wa-business/documents/{documentId}/download` | live | NONE | — none |
| `GET /wa-business/enterprise-assist` | live | NONE | — none |
| `GET /wa-business/faq` | live | NONE | — none |
| `GET /wa-business/flow-customer-journey` | live | NONE | — none |
| `GET /wa-business/flow-logs` | live | NONE | `client.ts` |
| `GET /wa-business/flow-registry` | live | NONE | `index.tsx` |
| `GET /wa-business/flow-submissions` | live | NONE | `index.tsx` |
| `GET /wa-business/flow-submissions/export` | live | NONE | — none |
| `GET /wa-business/flow-submissions/stats` | live | NONE | — none |
| `GET /wa-business/flows` | live | NONE | — none |
| `GET /wa-business/groups` | live | NONE | — none |
| `GET /wa-business/mm-onboarding-status` | live | NONE | — none |
| `GET /wa-business/orders` | live | NONE | `index.tsx` |
| `GET /wa-business/orders/{orderId}` | live | NONE | `index.tsx` |
| `GET /wa-business/orders/{orderId}/submissions` | live | NONE | — none |
| `GET /wa-business/payment-config/check` | live | NONE | — none |
| `GET /wa-business/phone-settings` | live | NONE | — none |
| `GET /wa-business/profile` | live | NONE | — none |
| `GET /wa-business/reviews` | live | NONE | — none |
| `GET /wa-business/rx-slots` | live | NONE | — none |
| `GET /wa-business/schedules` | live | NONE | — none |
| `GET /wa-business/service/drafts/{flowCode}` | live | NONE | — none |
| `GET /wa-business/service/history` | live | NONE | — none |
| `GET /wa-business/service/track/{orderId}` | live | NONE | — none |
| `GET /wa-business/submit-requests` | live | NONE | `client.ts` |
| `GET /wa-business/throughput` | live | NONE | — none |
| `GET /wa-business/username` | live | NONE | — none |
| `GET /wa-business/username/suggestions` | live | NONE | — none |
| `GET /wa-business/webhooks` | live | NONE | — none |
| `GET /whatsapp/business-api` | live | NONE | — none |
| `PATCH /wa-business/orders/{orderId}` | live | NONE | `index.tsx` |
| `POST /wa-business/appointments` | live | NONE | — none |
| `POST /wa-business/assigned-users` | live | NONE | — none |
| `POST /wa-business/calling-settings` | live | NONE | — none |
| `POST /wa-business/catalog-flow-map` | live | NONE | — none |
| `POST /wa-business/direct-send` | live | NONE | — none |
| `POST /wa-business/direct-send/samples` | live | NONE | — none |
| `POST /wa-business/documents` | live | NONE | — none |
| `POST /wa-business/enterprise-assist` | live | NONE | — none |
| `POST /wa-business/faq` | live | NONE | — none |
| `POST /wa-business/flow-clone` | live | NONE | — none |
| `POST /wa-business/flow-data` | live | NONE | — none |
| `POST /wa-business/flow-registry` | live | NONE | `index.tsx` |
| `POST /wa-business/flow-sla-check` | live | NONE | — none |
| `POST /wa-business/flow-submissions/update-status` | live | NONE | — none |
| `POST /wa-business/flows` | live | NONE | — none |
| `POST /wa-business/flows/deprecate` | live | NONE | — none |
| `POST /wa-business/flows/preview` | live | NONE | — none |
| `POST /wa-business/flows/publish` | live | NONE | — none |
| `POST /wa-business/groups` | live | NONE | — none |
| `POST /wa-business/groups/participants` | live | NONE | — none |
| `POST /wa-business/groups/send` | live | NONE | — none |
| `POST /wa-business/interactive-list` | live | NONE | — none |
| `POST /wa-business/marketing-message` | live | NONE | — none |
| `POST /wa-business/orders` | live | NONE | `index.tsx` |
| `POST /wa-business/orders/sync` | live | NONE | — none |
| `POST /wa-business/phone-settings` | live | NONE | — none |
| `POST /wa-business/profile` | live | NONE | — none |
| `POST /wa-business/reviews` | live | NONE | — none |
| `POST /wa-business/rx-slots` | live | NONE | — none |
| `POST /wa-business/schedules` | live | NONE | — none |
| `POST /wa-business/service/amend` | live | NONE | — none |
| `POST /wa-business/service/drafts` | live | NONE | — none |
| `POST /wa-business/service/submit` | live | NONE | — none |
| `POST /wa-business/username` | live | NONE | — none |
| `POST /wa-business/webhooks` | live | NONE | — none |
| `POST /whatsapp/business-api` | live | NONE | — none |
| `PUT /wa-business/appointments/{appointmentId}` | live | NONE | — none |
| `PUT /wa-business/documents/{documentId}` | live | NONE | — none |
| `PUT /wa-business/enterprise-assist/{caseId}` | live | NONE | — none |
| `PUT /wa-business/faq/{faqId}` | live | NONE | — none |
| `PUT /wa-business/flow-registry` | live | NONE | `index.tsx` |
| `PUT /wa-business/flows` | live | NONE | — none |
| `PUT /wa-business/groups` | live | NONE | — none |
| `PUT /wa-business/reviews/{reviewId}` | live | NONE | — none |
| `PUT /wa-business/rx-slots/{slotId}` | live | NONE | — none |

### `wecare-whatsapp-calling`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /whatsapp` | live | NONE | `client.ts`, `EmbeddedSignupPanel.tsx`, `Layout.tsx`, `SearchModal.tsx` +50 |
| `DELETE /whatsapp/calling` | live | NONE | `navigation.ts`, `system-architecture.tsx` |
| `DELETE /whatsapp/{proxy+}` | live | NONE | `client.ts`, `EmbeddedSignupPanel.tsx`, `Layout.tsx`, `SearchModal.tsx` +50 |
| `GET /whatsapp` | live | NONE | `client.ts`, `EmbeddedSignupPanel.tsx`, `Layout.tsx`, `SearchModal.tsx` +50 |
| `GET /whatsapp-calling` | live | NONE | `code-repo.tsx`, `lambda-functions.tsx`, `system-architecture.tsx`, `calling.tsx` |
| `GET /whatsapp/calling` | live | NONE | `navigation.ts`, `system-architecture.tsx` |
| `GET /whatsapp/{proxy+}` | live | NONE | `client.ts`, `EmbeddedSignupPanel.tsx`, `Layout.tsx`, `SearchModal.tsx` +50 |
| `POST /whatsapp` | live | NONE | `client.ts`, `EmbeddedSignupPanel.tsx`, `Layout.tsx`, `SearchModal.tsx` +50 |
| `POST /whatsapp-calling` | live | NONE | `code-repo.tsx`, `lambda-functions.tsx`, `system-architecture.tsx`, `calling.tsx` |
| `POST /whatsapp/calling` | live | NONE | `navigation.ts`, `system-architecture.tsx` |
| `POST /whatsapp/{proxy+}` | live | NONE | `client.ts`, `EmbeddedSignupPanel.tsx`, `Layout.tsx`, `SearchModal.tsx` +50 |

### `wecare-whatsapp-template-management`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /whatsapp/template-management` | live | NONE | — none |
| `GET /whatsapp/template-library` | live | NONE | `client.ts` |
| `GET /whatsapp/template-management` | live | NONE | — none |
| `POST /whatsapp/template-from-library` | live | NONE | `client.ts` |
| `POST /whatsapp/template-management` | live | NONE | — none |

### `wecare-whatsapp-templates`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /whatsapp/templates` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +3 |
| `DELETE /whatsapp/templates/send-media` | live | NONE | `client.ts` |
| `DELETE /whatsapp/templates/{templateName}` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +3 |
| `GET /whatsapp/templates` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +3 |
| `GET /whatsapp/templates/send-media` | live | NONE | `client.ts` |
| `GET /whatsapp/templates/{templateId}` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +3 |
| `POST /whatsapp/templates` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +3 |
| `POST /whatsapp/templates/carousel` | live | NONE | `client.ts` |
| `POST /whatsapp/templates/carousel-media` | live | NONE | `client.ts` |
| `POST /whatsapp/templates/media` | live | NONE | `client.ts` |
| `POST /whatsapp/templates/send-media` | live | NONE | `client.ts` |
| `PUT /whatsapp/templates/{templateId}` | live | NONE | `client.ts`, `InfraTab.tsx`, `navigation.ts`, `lambda-functions.tsx` +3 |

### `wecare-whatsapp-voice`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `DELETE /whatsapp-voice/clear-logs` | live | NONE | `index.tsx` |
| `GET /whatsapp-voice/language-config` | live | NONE | `client.ts` |
| `GET /whatsapp-voice/logs` | live | NONE | `client.ts` |
| `GET /whatsapp-voice/voices` | live | NONE | `client.ts` |
| `GET /whatsapp/voice` | live | NONE | — none |
| `POST /whatsapp-voice/send` | live | NONE | `client.ts` |
| `POST /whatsapp-voice/tts` | live | NONE | `client.ts`, `SystemTab.tsx` |
| `POST /whatsapp/voice` | live | NONE | — none |
| `PUT /whatsapp-voice/language-config` | live | NONE | `client.ts` |

### `wecare-workspace-mcp`

| Route | Qualifier | Gateway auth | Frontend files |
|---|---|---|---|
| `ANY /workspace/mcp` | live | JWT | `workspace-mcp.test.ts`, `workspace-mcp.ts`, `MCPConnections.test.tsx` |
| `GET /workspace/mcp/oauth/callback` | live | NONE | `workspace-mcp.test.ts`, `workspace-mcp.ts`, `MCPConnections.test.tsx` |
| `POST /workspace/mcp-iam` | live | AWS_IAM | — none |

## Anomalies carried from the inventory

Counts only. The inventory holds the detail and the justifications.

| Anomaly | Count |
|---|--:|
| `errors7d` | 0 |
| `liveButNotInDeployMap` | 5 |
| `logRetentionUnknown` | 0 |
| `logsNeverExpire` | 0 |
| `noLiveAliasButHasRoutes` | 2 |
| `noRoutesNoEventSourceNoTraffic` | 7 |
| `routesTargetingLatest` | 6 |
| `routesToAbsentFunction` | 0 |
| `routesWithoutFrontendCaller` | 118 |
| `zeroInvocations7d` | 33 |

