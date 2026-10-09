"""
Preset WhatsApp message-template definitions.

These are ready-to-edit starting points that pass the validation service.
Variables use positional ({{1}}) placeholders with example values so they
can be submitted to Meta as-is (after filling real example text).

Flow presets include a FLOW button; callers must set flow_id/flow_name
before submitting.
"""
from typing import Any, Dict, List, Optional

from .whatsapp_types import LTO_COMPONENT_TYPE


def _preset_seasonal_promotion() -> Dict[str, Any]:
    return {
        'name': 'seasonal_promotion',
        'language': 'en',
        'category': 'MARKETING',
        'message_send_ttl_seconds': 86400,
        'components': [
            {'type': 'HEADER', 'format': 'TEXT', 'text': '{{1}} Sale is here',
             'example': {'header_text': ['Summer']}},
            {'type': 'BODY',
             'text': 'Hi {{1}}, enjoy {{2}} off your next order. Use code {{3}} before it ends!',
             'example': {'body_text': [['Asha', '20%', 'SUMMER20']]}},
            {'type': 'FOOTER', 'text': 'Reply STOP to opt out'},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'URL', 'text': 'Shop now', 'url': 'https://wecare.digital/shop'},
                {'type': 'QUICK_REPLY', 'text': 'Not interested'},
            ]},
        ],
    }


def _preset_limited_time_offer() -> Dict[str, Any]:
    """A limited-time-offer (LTO) starting point.

    The offer code is a Meta coupon-code string, not a payment instrument: no amount
    and no discount arithmetic live here. The expiry is NOT part of the template -- it
    travels per message as `ltoExpirationTimeMs` on the send request.
    """
    return {
        'name': 'limited_time_offer',
        'language': 'en',
        'category': 'MARKETING',
        'message_send_ttl_seconds': 86400,
        'components': [
            {'type': 'HEADER', 'format': 'IMAGE',
             'example': {'header_url': ['https://wecare.digital/get/o/public/wa-tpl/img/wecarepay-header.png']}},
            {'type': 'BODY',
             'text': 'Hi {{1}}, your offer on {{2}} ends soon. Use the code below to claim it.',
             'example': {'body_text': [['Asha', 'studio sessions']]}},
            {'type': LTO_COMPONENT_TYPE,
             'limited_time_offer': {'text': 'Expiring offer!', 'has_expiration': True}},
            {'type': 'FOOTER', 'text': 'Reply STOP to opt out'},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'COPY_CODE', 'example': 'SUMMER20'},
                {'type': 'URL', 'text': 'Shop now', 'url': 'https://wecare.digital/shop'},
            ]},
        ],
    }


def _preset_order_confirmation() -> Dict[str, Any]:
    return {
        'name': 'order_confirmation',
        'language': 'en',
        'category': 'UTILITY',
        'message_send_ttl_seconds': 43200,
        'components': [
            {'type': 'BODY',
             'text': 'Hi {{1}}, your order {{2}} is confirmed. Total: {{3}}. We will notify you when it ships.',
             'example': {'body_text': [['Asha', 'WD-ORD-K4M7PQR9', 'INR 1499']]}},
            {'type': 'FOOTER', 'text': 'Thank you for shopping with us'},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'URL', 'text': 'View order', 'url': 'https://wecare.digital/orders/?orderId={{1}}',
                 'example': ['https://wecare.digital/orders/?orderId=WD-ORD-K4M7PQR9']},
            ]},
        ],
    }


def _preset_order_delivery_update() -> Dict[str, Any]:
    return {
        'name': 'order_delivery_update',
        'language': 'en',
        'category': 'UTILITY',
        'message_send_ttl_seconds': 43200,
        'components': [
            {'type': 'BODY',
             'text': 'Hi {{1}}, your order {{2}} is now {{3}}. Expected by {{4}}.',
             'example': {'body_text': [['Asha', 'WD-ORD-K4M7PQR9', 'out for delivery', 'today 6 PM']]}},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'URL', 'text': 'Track', 'url': 'https://wecare.digital/orders/?orderId={{1}}',
                 'example': ['https://wecare.digital/orders/?orderId=WD-ORD-K4M7PQR9']},
            ]},
        ],
    }


def _preset_flow_lead_generation() -> Dict[str, Any]:
    return {
        'name': 'flow_lead_generation',
        'language': 'en',
        'category': 'MARKETING',
        'message_send_ttl_seconds': 86400,
        'components': [
            {'type': 'BODY',
             'text': 'Hi {{1}}, tell us what you need and our team will reach out.',
             'example': {'body_text': [['Asha']]}},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'FLOW', 'text': 'Get started',
                 'flow_name': 'REPLACE_WITH_FLOW_NAME', 'flow_action': 'navigate',
                 'navigate_screen': 'WELCOME'},
            ]},
        ],
    }


def _preset_flow_appointment_booking() -> Dict[str, Any]:
    return {
        'name': 'flow_appointment_booking',
        'language': 'en',
        'category': 'UTILITY',
        'message_send_ttl_seconds': 43200,
        'components': [
            {'type': 'BODY',
             'text': 'Hi {{1}}, book your appointment in a few taps.',
             'example': {'body_text': [['Asha']]}},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'FLOW', 'text': 'Book now',
                 'flow_name': 'REPLACE_WITH_FLOW_NAME', 'flow_action': 'navigate',
                 'navigate_screen': 'BOOKING'},
            ]},
        ],
    }


def _preset_flow_support_request() -> Dict[str, Any]:
    return {
        'name': 'flow_support_request',
        'language': 'en',
        'category': 'UTILITY',
        'message_send_ttl_seconds': 43200,
        'components': [
            {'type': 'BODY',
             'text': 'Hi {{1}}, need help? Open a support request and we will assist you.',
             'example': {'body_text': [['Asha']]}},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'FLOW', 'text': 'Open request',
                 'flow_name': 'REPLACE_WITH_FLOW_NAME', 'flow_action': 'navigate',
                 'navigate_screen': 'SUPPORT'},
            ]},
        ],
    }


_PRESETS = {
    'seasonal_promotion': _preset_seasonal_promotion,
    'limited_time_offer': _preset_limited_time_offer,
    'order_confirmation': _preset_order_confirmation,
    'order_delivery_update': _preset_order_delivery_update,
    'flow_lead_generation': _preset_flow_lead_generation,
    'flow_appointment_booking': _preset_flow_appointment_booking,
    'flow_support_request': _preset_flow_support_request,
}


def list_presets() -> List[Dict[str, Any]]:
    """Return a summary list of available presets."""
    out = []
    for name, fn in _PRESETS.items():
        d = fn()
        out.append({
            'name': name,
            'category': d['category'],
            'language': d['language'],
            'hasFlowButton': any(
                (b.get('type') or '').upper() == 'FLOW'
                for c in d['components'] if (c.get('type') or '').upper() == 'BUTTONS'
                for b in c.get('buttons', [])
            ),
        })
    return out


def get_preset(name: str) -> Optional[Dict[str, Any]]:
    """Return a deep-ish copy of a preset template definition, or None."""
    fn = _PRESETS.get((name or '').strip())
    return fn() if fn else None
