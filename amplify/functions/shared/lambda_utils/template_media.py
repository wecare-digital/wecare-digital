"""Reusable send-time media for WhatsApp templates and ORDER_DETAILS.

Payment item-thumbnail contract
-------------------------------
* Normal ORDER_DETAILS item rows use one default WECARE thumbnail.
* The thumbnail is the owner-supplied 2048 x 2048 PNG in the WhatsApp template media prefix.
* Fee, shipping, GST and Delight rows do not carry an item image.
* This path does not choose catalog/product-specific artwork.
* Paid invoices use their generated invoice PNG as the invoice-template IMAGE header.
"""

SHARED_TEMPLATE_HEADER = (
    "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"
)

DEFAULT_ORDER_ITEM_THUMBNAIL = (
    "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/"
    "WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png"
)

# Legacy name kept for packaged callers while they converge on the explicit constant above.
ORDER_ITEM_IMAGE = DEFAULT_ORDER_ITEM_THUMBNAIL

# The approved native-payment template still declares an IMAGE header at Meta.
# Use the shared default header; item thumbnails are supplied separately in
# ORDER_DETAILS item parameters. Do not replace the header with the item thumbnail.
PAYMENT_TEMPLATE_HEADER = SHARED_TEMPLATE_HEADER

DEFAULT_HEADER_IMAGE = SHARED_TEMPLATE_HEADER
ORDER_CATALOG_HEADER = PAYMENT_TEMPLATE_HEADER
ORDER_CATALOG_HEADER_IMAGE = PAYMENT_TEMPLATE_HEADER

FIXED_IMAGE_HEADERS = {
    "wecare_whatapp_native_pay_template": PAYMENT_TEMPLATE_HEADER,
    "wecare_leave_review": SHARED_TEMPLATE_HEADER,
    "wecare_referal_update": SHARED_TEMPLATE_HEADER,
    "wecare_default_download": SHARED_TEMPLATE_HEADER,
    "service_details": SHARED_TEMPLATE_HEADER,
    "wecare_vault_request_ready": SHARED_TEMPLATE_HEADER,
}

RETAINED_MEDIA_KEYS = frozenset({
    "secure/d/public/whatsapp/wa-tpl/whatsapp-header.png",
    "secure/d/public/whatsapp/wa-tpl/img/wecare-catalog-icon.png",
    "secure/d/public/whatsapp/wa-tpl/WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png",
})


def fixed_image_header(template_name: str) -> str:
    return FIXED_IMAGE_HEADERS.get(template_name, "")
