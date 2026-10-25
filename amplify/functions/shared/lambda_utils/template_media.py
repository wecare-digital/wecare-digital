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
# The name outbound (`FIXED_CHECKOUT_HEADER`) and the invoice engine import. #1567 renamed the
# constant without updating them, which left outbound unable to import (no WhatsApp send at all).
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
