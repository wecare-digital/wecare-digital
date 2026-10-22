# WhatsApp media storage

Bucket: `wecare-digital-get`. Use the existing keys and shared `media_paths` helpers; moving existing files breaks URLs in issued messages.

| Purpose | Location | Reuse |
| --- | --- | --- |
| Public reusable template assets | `o/public/wa-tpl/{img,docs,vid,aud,stk}/` | Upload once, select from the media library for later sends |
| Fixed Leave Review image | `o/public/wa-tpl/img/wecare-digital-cebc83f1_img.png` | Automatically enforced by `lambda_utils.template_media`; deletion through the library is blocked |
| Customer WhatsApp uploads | `secure/u/whatsapp/incoming/` | Private customer records; resolve signed links on read |
| Generated invoices | `secure/Invoice/customer_invoice/` | Individual transaction outputs; never replace with the brand image |
| Historical public WhatsApp media | `o/stack/whatsapp-media/` | Retain referenced files at their existing URLs |
| Calling audio | `o/whatsapp-media/whatsapp-calling/` | Separate operational assets; retain configured greeting files |
| Storage audits and rollback manifests | `secure/stack/storage-audits/` | Operational records |

The Leave Review header is supplied at send time. It does not require editing the Meta-approved template or uploading another S3 copy per message. The template listing exposes `fixedHeaderMedia`, the sender displays that saved image, and outbound sends enforce the same asset.

Other template headers use the existing **Choose from library** action. Reuse that file instead of uploading the same bytes again. Payment headers remain purpose-specific; invoice headers remain the customer's generated invoice.

The 20 October 2026 audit found 412 current objects before cleanup, including 62 public template assets. After the user explicitly approved a reset, 76 old WhatsApp media objects were removed from active keys: 60 old template assets, 13 private incoming files, and three legacy WhatsApp files. Only the review brand image and native-payment header remain in the active template library. Six three-byte folder placeholders were also removed. Original versions and delete-marker IDs are retained in `secure/stack/storage-audits/2026-10-20/` for recovery; this does not purge historical versions or immediately reclaim their storage charges.

The stream audit found 75 objects. Removed the retired `o/stream/code/wecare-wa-widget.js`; the website uses the in-repository SupportWidget. Kept the remaining 74 stream files at their existing working URLs, including brand/catalog assets, invoice fonts, IVR audio, documentation, and report/media assets. No live stream migration was requested. Blogs, products, generated invoices, calling greetings, and website assets were excluded from the WhatsApp reset.
