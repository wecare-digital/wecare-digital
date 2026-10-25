# WhatsApp Feature Build Matrix

Evidence-based as of 2026-06-10. "Live verified" means a real message was sent/received and confirmed — almost everything below is **not** live-verified because no QA recipient (`WA_QA_RECIPIENT`) is configured.

| # | Feature | Status | Evidence (file / resource) | Live verified |
|---|---------|--------|----------------------------|---------------|
| 1 | Cloud API client (Graph v25, appsecret_proof) | IMPROVED_AND_TESTED | `outbound-whatsapp/handler.py`, `inbound-whatsapp-handler/handler.py` `_send_direct_api_*` | No |
| 2 | Outbound text | BUILT_AND_TESTED (unit) | `outbound-whatsapp` `_build_message_payload`; `tests/test_outbound_whatsapp.py` | No |
| 3 | Media: image/audio/video/document | IMPROVED_AND_TESTED | `_upload_media`, media branch; presigned S3 upload | No |
| 4 | Template messages | IMPROVED_AND_TESTED | `whatsapp-templates` list fix + `outbound-whatsapp` template builder | No |
| 4a | **Template media header (image/video/document)** | **BUILT_AND_TESTED (this session)** | `outbound-whatsapp` `template_header_media` + `TemplateSender` upload UI | No (needs QA) |
| 4b | **Template → new/unsaved number** | **BUILT_AND_TESTED (this session)** | `TemplateSender` `enableManualRecipient`; inbox "New template message"; backend `_get_or_create_contact_by_phone` | No (needs QA) |
| 5 | Interactive buttons | BUILT (present) | `_handle_interactive_send`, `InteractiveMessageComposer.tsx` | No |
| 6 | Interactive lists | BUILT (present) | `inbound`/`outbound` interactive list senders; `interactive-lists.tsx` | No |
| 7 | Contacts/location messages | BUILT (present) | `handleSendLocationRequest`, interactive `location_request` | No |
| 8 | Mark message as read | BUILT (present) | `_send_direct_api_read_receipt` | No |
| 9 | Typing indicator | IMPROVED_AND_TESTED | `outbound-whatsapp` `_send_typing_indicator` (native `status=read`+`typing_indicator`); client `sendTypingIndicator` | No |
| 10 | Media upload/download/storage | BUILT (present) | `_download_media_direct_api` → S3 `secure/d/public/whatsapp/`; `MediaFilesTable` | No |
| 11 | Webhook verification (GET) | NOT_APPLICABLE (AWS-managed) | AWS End User Messaging handles GET verify | n/a |
| 12 | Webhook signature validation | NOT_APPLICABLE (AWS-managed) | SNS delivery from AWS End User Messaging | n/a |
| 13 | Inbound message processing | BUILT (present) | `inbound-whatsapp-handler` `_process_message` | Partial (5 items in `WhatsAppInboundTable`) |
| 14 | Status webhook processing | BUILT (present) | `_process_status` | No |
| 15 | Failed message handling | BUILT (present) | `_error_response`, DLQ writes | No |
| 16 | Idempotency / dup webhook protection | PARTIAL_FIXED | dedup + timeout-guard + DLQ in inbound handler | No |
| 17 | Inbox/conversation persistence | BUILT (present) | `WhatsAppInboundTable`/`WhatsAppOutboundTable`, `messages-read` | Yes (data present) |
| 18 | Templates list/create/sync/send | IMPROVED_AND_TESTED | `whatsapp-templates` (list fix verified live via direct invoke) | List: Yes; send: No |
| 19 | Flows create/update/publish/send | FEATURE_FLAGGED_META_GATED (`WA_FLOWS_ENABLED`) | `whatsapp-business-api/flows`, `FlowRegistry/Submission/Log` tables, routes `/wa-business/flows*` | No |
| 20 | Flow JSON validation | PARTIAL | flows module in `whatsapp-business-api` | No |
| 21 | Flow endpoint/data exchange | BUILT (present) | route `POST /wa-business/flow-data`, `wecare/flow-private-key` secret | No |
| 22 | Flow encryption handling | BUILT (present) | `wecare/flow-private-key` (RSA) used by flows module | No |
| 23 | Flow health monitoring | PARTIAL | route `GET /wa-business/flow-version-health` | No |
| 24 | Flow webhook handling | BUILT (present) | inbound handler flow fields | No |
| 25 | Catalog/product messages | FEATURE_FLAGGED_META_GATED | `catalog-management`, `CatalogCacheTable`; needs `WA_CATALOG_ID` | No |
| 26 | Payments India / UPI | FEATURE_FLAGGED_META_GATED (`WA_PAYMENTS_ENABLED=false`) | payment template + order_details button in `outbound-whatsapp`; `payu`/`razorpay` webhooks | No |
| 27 | Marketing Messages API | FEATURE_FLAGGED_META_GATED (`WA_MARKETING_MESSAGES_ENABLED=false`) | template categories | No |
| 28 | Calling API | FEATURE_FLAGGED_META_GATED (`WA_CALLING_ENABLED=false`) | `whatsapp-calling`, `WhatsAppCallingTable` | No |
| 29 | Groups API | FEATURE_FLAGGED_META_GATED (`WA_GROUPS_ENABLED=false`) | `WhatsAppGroupTable`, group webhook fields, `/wa-business/groups*` | No |
| 30 | Business phone/admin helpers | BUILT (present) | `waba-management`, `/wa-business/phone-settings` | No |
| 31 | Business profile helpers | BUILT (present) | `/wa-business/profile` | No |
| 32 | QR/admin helpers | PARTIAL | not separately surfaced | No |
| 33 | Observability (logs/metrics) | BUILT (present) | structured JSON logs; `_emit_delivery_metric`; CloudWatch alarms | n/a |
| 34 | DLQ/replay | BUILT (present) | `dlq-replay`, SQS `*-dlq` queues | No |
| 35 | Smoke test script | PARTIAL (plan only) | `LIVE_SMOKE_TEST_PLAN.md`; gated by `WA_LIVE_SMOKE_TEST` | No |

## On-Premises API
`DEPRECATED_NOT_BUILT` — repo uses Cloud API only. See `ON_PREM_SUNSET_NOTE.md`.
