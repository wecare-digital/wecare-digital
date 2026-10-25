"""Reusable send-time media for templates with a fixed brand header."""

from lambda_utils import media_paths

DEFAULT_HEADER_IMAGE = "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"
ORDER_CATALOG_HEADER_IMAGE = "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/wecare-catalog-icon.png"

FIXED_IMAGE_HEADERS = {
    'wecare_leave_review': DEFAULT_HEADER_IMAGE,
    'wecare_default_download': DEFAULT_HEADER_IMAGE,
}

#: Template media that code sends by URL. They sit in the same wa-tpl/img/ folder as library
#: uploads, so the library delete route must refuse them: deleting the checkout header breaks
#: every payment request (outbound-whatsapp FIXED_CHECKOUT_HEADER and invoice-engine
#: headerImageUrl both name it).
RETAINED_MEDIA_KEYS = frozenset({
    media_paths.WHATSAPP_TEMPLATE_ASSET_ROOT + 'whatsapp-header.png',
    media_paths.WHATSAPP_TEMPLATE_ASSET_ROOT + 'wecare-catalog-icon.png',
})


def fixed_image_header(template_name: str) -> str:
    return FIXED_IMAGE_HEADERS.get(template_name, '')
