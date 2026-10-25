"""Reusable send-time media for WhatsApp templates with fixed headers.

Header contract
---------------
* Generic image-header templates use whatsapp-header.png.
* Native order/catalog payment uses wecare-catalog-icon.png.
* Paid invoices never use either fixed image; the generated invoice PNG is the header.
"""

SHARED_TEMPLATE_HEADER = (
    "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"
)
ORDER_CATALOG_HEADER = (
    "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/wecare-catalog-icon.png"
)

# The names these two had before #1567, kept because they are still imported: outbound-whatsapp
# imports ORDER_CATALOG_HEADER_IMAGE at module scope (removing it makes every cold start an
# ImportError, so no WhatsApp message can be sent) and the invoice engine reads it when it sends
# a payment request.
DEFAULT_HEADER_IMAGE = SHARED_TEMPLATE_HEADER
ORDER_CATALOG_HEADER_IMAGE = ORDER_CATALOG_HEADER

FIXED_IMAGE_HEADERS = {
    "wecare_leave_review": SHARED_TEMPLATE_HEADER,
}

# Runtime dependencies, not disposable media-library uploads.
RETAINED_MEDIA_KEYS = frozenset({
    "secure/d/public/whatsapp/wa-tpl/whatsapp-header.png",
    "secure/d/public/whatsapp/wa-tpl/wecare-catalog-icon.png",
})


def fixed_image_header(template_name: str) -> str:
    return FIXED_IMAGE_HEADERS.get(template_name, "")
