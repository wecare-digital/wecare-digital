# WhatsApp Media Configuration

## Single Bucket: `wecare-digital-get`

All WhatsApp media uses one bucket with folder-based routing.

## S3 Folder Map

| Prefix | Use Case | Lambda Function | Access |
|--------|----------|-----------------|--------|
| `stack/whatsapp-media/incoming/` | Customer sends media TO you | `wecare-inbound-whatsapp` | Private |
| `stack/whatsapp-media/outgoing/` | You send media TO customer | `wecare-outbound-whatsapp` | Private |
| `stack/whatsapp-media/voice/` | Voice messages + MP3 | `wecare-whatsapp-voice` | Private |
| `stack/whatsapp-media/calling-ai/` | WhatsApp calling AI | `wecare-whatsapp-calling` | Private |
| `stack/whatsapp-media/template-headers/` | Template creation header media (uploaded to Meta) | `wecare-whatsapp-template-management` | Private |
| `stack/whatsapp-media/transcriptions/` | AWS Transcribe output | `wecare-whatsapp-voice` | Private |
| `stack/whatsapp-media/downloads/` | Downloaded media | `wecare-inbound-whatsapp` | Private |
| `public/wa-tpl/docs/` | Template send — document attachments | `wecare-outbound-whatsapp` | Public |
| `public/wa-tpl/img/` | Template send — image attachments | `wecare-outbound-whatsapp` | Public |
| `public/wa-tpl/vid/` | Template send — video attachments | `wecare-outbound-whatsapp` | Public |
| `public/wa-tpl/aud/` | Template send — audio attachments | `wecare-outbound-whatsapp` | Public |
| `public/wa-tpl/stk/` | Template send — sticker attachments | `wecare-outbound-whatsapp` | Public |

## File Naming Convention

All files follow: `wecare-digital-{shortId}_{filename}`

Example: `wecare-digital-a1b2c3d4_Invoice.pdf`

## CDN URL (what WhatsApp/customer sees)

```
https://wecare.digital/get/o/public/wa-tpl/docs/wecare-digital-a1b2c3d4_Invoice.pdf
```

Customer sees the `filename` field in WhatsApp chat (e.g., "Invoice.pdf"), not the URL.

## Supported Media Types (per WhatsApp Cloud API v25.0)

### Documents (max 100MB) → `docs/`
- `application/pdf` (.pdf)
- `application/msword` (.doc)
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (.docx)
- `application/vnd.ms-excel` (.xls)
- `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (.xlsx)
- `application/vnd.ms-powerpoint` (.ppt)
- `application/vnd.openxmlformats-officedocument.presentationml.presentation` (.pptx)
- `text/plain` (.txt)

### Images (max 5MB, 8-bit RGB/RGBA) → `img/`
- `image/jpeg` (.jpeg)
- `image/png` (.png)

### Videos (max 16MB, H.264 Main + AAC) → `vid/`
- `video/mp4` (.mp4)
- `video/3gpp` (.3gp)

### Audio (max 16MB) → `aud/`
- `audio/aac` (.aac)
- `audio/amr` (.amr)
- `audio/mpeg` (.mp3)
- `audio/mp4` (.m4a)
- `audio/ogg` (.ogg, OPUS codec only)

### Stickers (max 500KB animated, 100KB static) → `stk/`
- `image/webp` (.webp)

## WABA Configuration

| WABA | Meta ID | Phone ID | Display | Label |
|------|---------|----------|---------|-------|
| WABA1 | 2094615664435155 | 1016149501586345 | +91 93309 94400 | WECARE.DIGITAL |
| WABA2 | 2513394156072604 | 1055232054343117 | +91 99033 00044 | Manish Agarwal |

Both WABAs use the same system user token (stored in Secrets Manager: `wecare/meta-system-user-token`).
