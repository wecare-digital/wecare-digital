# WhatsApp media storage

Bucket: `wecare-digital-get`. Use the existing keys and shared `media_paths` helpers; moving existing files breaks URLs in issued messages.

| Purpose | Location | Reuse |
| --- | --- | --- |
| Public reusable template assets | `o/public/wa-tpl/{img,docs,vid,aud,stk}/` | Upload once, select from the media library for later sends |
| Fixed Leave Review image | `o/public/wa-tpl/img/wecare-digital-cebc83f1_img.png` | Automatically enforced by `lambda_utils.template_media`; deletion through the library is blocked |
| Customer WhatsApp uploads | `secure/u/whatsapp/incoming/` | Private customer records; resolve signed links on read |
| Generated invoices | `secure/stack/invoices/` | Individual transaction outputs; never replace with the brand image |
| Historical public WhatsApp media | `o/stack/whatsapp-media/` | Retain referenced files at their existing URLs |
| Calling audio | `o/whatsapp-media/whatsapp-calling/` | Separate operational assets; retain configured greeting files |
| Storage audits and rollback manifests | `secure/stack/storage-audits/` | Operational records |

The Leave Review header is supplied at send time. It does not require editing the Meta-approved template or uploading another S3 copy per message. The template listing exposes `fixedHeaderMedia`, the sender displays that saved image, and outbound sends enforce the same asset.

Other template headers use the existing **Choose from library** action. Reuse that file instead of uploading the same bytes again. Payment headers remain purpose-specific; invoice headers remain the customer's generated invoice.

The 20 October 2026 audit found 412 current objects before cleanup, including 62 public template assets. Equal ETag and size identified duplicate candidates, but old URLs may remain in sent messages. Those candidates were preserved. Six three-byte WhatsApp folder placeholders were removed with versioned delete markers after saving original version IDs. No actual media, customer document, invoice, blog, or product file was deleted. Removing placeholders does not remove prefixes with real files or materially reduce storage charges.
