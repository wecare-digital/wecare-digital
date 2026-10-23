"""Reusable send-time media for templates with a fixed brand header."""

from lambda_utils import media_paths

FIXED_IMAGE_HEADERS = {
    'wecare_leave_review': media_paths.public_url(
        media_paths.WHATSAPP_TEMPLATE_IMAGE_PREFIX
        + 'wecare-digital-cebc83f1_img.png'
    ),
}


def fixed_image_header(template_name: str) -> str:
    return FIXED_IMAGE_HEADERS.get(template_name, '')
