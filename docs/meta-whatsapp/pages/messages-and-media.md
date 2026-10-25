# Build Spec — Messages & Media

Meta refs: /cloud-api/reference/messages, /cloud-api/reference/media, /messages/audio-messages, /messages/interactive-list-messages, /messages/mark-message-as-read

## Message types
text, image, audio, video, document, sticker, location, contacts, interactive (button/list/cta_url/location_request), reaction, template.

## Repo mapping
- Builder: `outbound-whatsapp/handler.py` `_build_message_payload` + `_handle_interactive_send`.
- Media: `_upload_media` (S3 key → WhatsApp media id), download `inbound-whatsapp-handler` `_download_media_direct_api` → S3 `secure/d/public/whatsapp/incoming/`.
- Mark read: `_send_direct_api_read_receipt` (`status=read`).
- Typing: `outbound-whatsapp` `_send_typing_indicator` — native `status=read` + `message_id` + `typing_indicator:{type:text}`.
- Frontend: inbox composer (multi-file presigned S3 upload), `InteractiveMessageComposer.tsx`.

## Status
Built/present; unit tests in `tests/test_outbound_whatsapp.py`. Live send pending QA.
