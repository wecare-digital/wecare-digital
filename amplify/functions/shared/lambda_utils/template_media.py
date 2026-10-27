"""Reusable send-time media for WhatsApp templates with fixed headers.

Header contract
---------------
* The native payment-template header uses the square WECARE bag asset. Meta renders this header
  as the order-details message thumbnail; manual/service item rows themselves carry no image.
* Generic fixed image-header templates use whatsapp-header.png.
* Paid invoices use neither fixed image; the generated invoice PNG is their header.
"""

SHARED_TEMPLATE_HEADER = (
    "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"
)
PAYMENT_TEMPLATE_HEADER = (
    "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/wecare-catalog-icon.png"
)
# Backwards compatibility only. Manual/service rows no longer use this image; true catalog
# products keep their catalog-managed imagery.
ORDER_ITEM_IMAGE = PAYMENT_TEMPLATE_HEADER

# Backwards-compatible names used by packaged Lambdas. ORDER_CATALOG_HEADER now resolves to the
# single square payment-message thumbnail; generic fixed-header templates stay on the wide art.
DEFAULT_HEADER_IMAGE = SHARED_TEMPLATE_HEADER
ORDER_CATALOG_HEADER = PAYMENT_TEMPLATE_HEADER
ORDER_CATALOG_HEADER_IMAGE = PAYMENT_TEMPLATE_HEADER

# Every live template whose IMAGE header is the same picture on every send. Outbound forces
# this header over any caller-supplied one, and template management advertises it as
# `fixedHeaderMedia` so the Inbox sender and scheduled sends carry it. The Vault download
# template belongs here: without it a manual or scheduled download send has no header and
# Meta refuses it.
FIXED_IMAGE_HEADERS = {
    "wecare_whatapp_native_pay_template": PAYMENT_TEMPLATE_HEADER,
    "wecare_leave_review": SHARED_TEMPLATE_HEADER,
    "wecare_default_download": SHARED_TEMPLATE_HEADER,
    "wecare_valut_49": SHARED_TEMPLATE_HEADER,
}

# Runtime dependencies, not disposable media-library uploads.
RETAINED_MEDIA_KEYS = frozenset({
    "secure/d/public/whatsapp/wa-tpl/whatsapp-header.png",
    "secure/d/public/whatsapp/wa-tpl/wecare-catalog-icon.png",
})


def fixed_image_header(template_name: str) -> str:
    return FIXED_IMAGE_HEADERS.get(template_name, "")
