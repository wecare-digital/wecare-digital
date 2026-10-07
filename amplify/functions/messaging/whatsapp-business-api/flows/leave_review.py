"""
Leave Review Flow — Customer feedback and ratings.
Screens: REVIEW_FORM → CONFIRM (terminal)
Saves to ReviewTable + FlowSubmissionTable.
"""
import json, time, uuid, logging
from decimal import Decimal
from typing import Dict
from flows.common import (
    dynamodb, get_phone_from_token, find_contact_by_phone,
    get_contact_name, record_completion, restore_draft, clear_draft,
)

logger = logging.getLogger(__name__)
REVIEWS_TABLE = 'stack-wecare-digital-ReviewTable'
FLOW_CODE = 'WD_REV'

#: Draft suffix the inbound handler parks the order reference under, as
#: `{phone}#WD_REV_REF` in FlowDraftTable. Phase R deliberately carries the
#: reference in a draft row rather than in the flow token: the token shape is
#: `{flow_key}-{uuid}-waba-{1|2}-ph-{phone}`, `router._extract_flow_key` breaks the
#: prefix at the first segment longer than 10 characters, and
#: `common.get_phone_from_token` splits on `-ph-`, so a reference containing `-` or
#: longer than 10 characters would silently reroute the flow or de-attribute it.
#: A draft row is the mechanism already built for carrying state between an inbound
#: message and a Flow callback, and it has a 7-day TTL for free.
REF_DRAFT_CODE = 'WD_REV_REF'

#: Shown on the first screen when we do not know what is being reviewed. The caption is
#: UNCONDITIONAL in the Flow JSON, so this fallback is what stops the screen rendering a
#: blank line — cheaper and more robust than an `If`/visibility construct.
UNATTRIBUTED_LABEL = 'General feedback'


def _stored_order_id(review_id: str) -> str:
    """The `orderId` already on this review row, or ''.

    THE RETRY PATH, and it is not optional. The draft is consumed by whichever call wins the
    claim, so a Meta retry of that same completion finds NO draft - and because the domain
    write is a `put_item`, which replaces the whole item rather than merging, the retry would
    rewrite the row with `orderId` gone. Attribution would be lost on precisely the path the
    derived `review_id` exists to make safe.

    Reading the row back closes that, and it is cheap: `review_id` is derived from the
    completion key, so "is there already a row for this completion" is answerable before the
    claim is attempted. This is consulted ONLY when the draft is absent, so the first-time
    path costs no extra read.

    Not solved by simply never clearing the draft: it carries a 7-day TTL, so a stale
    reference would silently attribute a later, unrelated review to an old order.
    """
    if not review_id:
        return ''
    try:
        item = dynamodb.Table(REVIEWS_TABLE).get_item(
            Key={'reviewId': review_id}).get('Item') or {}
    except Exception:
        return ''
    stored = item.get('orderId', '')
    return stored.strip() if isinstance(stored, str) else ''


def _pending_reference(phone: str) -> str:
    """The order/product reference this customer asked to review, or ''.

    Written by the inbound handler when the customer arrives via the website's
    `wa.me/...?text=review <REF>` door. Absent for someone who simply typed
    `review`, which is a normal, fully supported path — not an error.
    """
    if not phone:
        return ''
    try:
        draft = restore_draft(phone, REF_DRAFT_CODE)
    except Exception:
        return ''
    if not draft:
        return ''
    reference = (draft.get('formData') or {}).get('reference', '')
    return reference.strip() if isinstance(reference, str) else ''


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    reference = _pending_reference(get_phone_from_token(flow_token))
    return {
        'screen': 'REVIEW_FORM',
        'data': {
            'order_ref': f'Order {reference}' if reference else UNATTRIBUTED_LABEL,
            'ratings': [
                {'id': '5', 'title': '⭐⭐⭐⭐⭐ Excellent'},
                {'id': '4', 'title': '⭐⭐⭐⭐ Good'},
                {'id': '3', 'title': '⭐⭐⭐ Average'},
                {'id': '2', 'title': '⭐⭐ Below Average'},
                {'id': '1', 'title': '⭐ Poor'},
            ],
            'categories': [
                {'id': 'service', 'title': 'Service'},
                {'id': 'product', 'title': 'Product'},
                {'id': 'delivery', 'title': 'Delivery'},
                {'id': 'support', 'title': 'Support'},
                {'id': 'other', 'title': 'Other'},
            ],
        }
    }


def handle_review_form(data: Dict, flow_token: str, request_id: str) -> Dict:
    phone = get_phone_from_token(flow_token)
    contact_id = find_contact_by_phone(phone)
    name = get_contact_name(contact_id)
    # Derived from the completion key rather than random. A Meta retry of
    # this data_exchange recomputes the same id, so the domain write below
    # overwrites an identical row instead of creating a second one, and the
    # conditional put inside record_completion refuses the duplicate.
    from lambda_utils import flow_completion as _fc
    review_id = _fc.reference_for(
        _fc.completion_key(flow_token, 'REVIEW_FORM', data)[0], 'WD-REV')
    now = int(time.time())

    # Clamped to the 1-5 the Review contract declares, not merely parsed. The Dropdown
    # only offers 1-5, but `data` arrives from the handset over the encrypted
    # `/flow-data` endpoint, so the range is an input assumption rather than a fact.
    # Anything outside it degrades to 0, which is what this handler already did for a
    # non-numeric value - an out-of-range number is no more trustworthy than a word.
    rating = 0
    try:
        parsed = int(data.get('rating', '0'))
        rating = parsed if 1 <= parsed <= 5 else 0
    except (ValueError, TypeError):
        pass

    # TWO SOURCES, IN THIS ORDER, and the second is what makes a replay safe.
    # The draft is the first-time path: parked by the inbound handler when the customer came
    # through the website door, and consumed by whichever call wins the claim. The row read
    # is the retry path: the draft is gone by then, and `put_item` REPLACES the item rather
    # than merging, so without this a Meta retry would rewrite the review with `orderId`
    # blank. Short-circuited, so the first-time path performs no extra read.
    reference = _pending_reference(phone) or _stored_order_id(review_id)

    try:
        table = dynamodb.Table(REVIEWS_TABLE)
        table.put_item(Item={k: v for k, v in {
            'reviewId': review_id,
            'customerPhone': phone,
            'customerName': name,
            'contactId': contact_id,
            'rating': rating,
            'reviewText': data.get('review_text', ''),
            'category': data.get('category', 'other'),
            # The order being reviewed, when the customer came through the website door.
            # `Review.orderId` already existed on the wire and the workspace detail modal
            # already renders it; nothing wrote it until now.
            'orderId': reference,
            # WRITTEN FOR THE FIRST TIME HERE, and it fixes a real filter bug rather than
            # filling in a blank. `service_api._list_reviews` reads
            # `i.get('source', i.get('category', 'web'))`, so with no `source` a WhatsApp
            # review borrowed its CATEGORY ('service', 'delivery', ...). The Source column
            # therefore showed a category, and the workspace's `whatsapp` source filter -
            # one of its four options - matched no WhatsApp review at all.
            'source': 'whatsapp',
            # LEFT AS `submitted` DELIBERATELY. `service_api` is the single translator for
            # this field: `_list_reviews` maps `submitted` -> `pending` for the frontend and
            # `_update_review` maps `pending` -> `submitted` back. Writing `pending` here
            # would put two spellings of one state in a table two producers share, which is
            # the vocabulary-fork hazard recorded for payment status. The staff page already
            # renders this row as `pending`, so the moderation gate is satisfied as-is.
            'status': 'submitted',
            'createdAt': Decimal(str(now)),
            'updatedAt': Decimal(str(now)),
        }.items() if v is not None and v != ''})
    except Exception as e:
        logger.warning(f'Review save failed: {e}')

    try:
        result = record_completion(
            flow_code=FLOW_CODE, flow_type='feedback', phone=phone,
            contact_id=contact_id, sender_name=name,
            form_data=data, flow_token=flow_token, request_id=request_id,
            screen='REVIEW_FORM', submission_number=review_id, requires_payment=False, status='submitted',
        )
    except Exception as e:
        logger.warning(f'Review submission save failed: {e}')

    # Only a fresh claim may message the customer. Without this guard a Meta
    # retry of the same completion sent a second confirmation for one submission.
    if result.should_fire_side_effects:
        try:
            from flows.common import send_simple_confirmation
            send_simple_confirmation(phone, flow_token, 'Review Submitted', review_id,
                f'*Rating:* {"⭐" * rating}\n*Category:* {data.get("category", "")}')
        except Exception:
            pass
        # INSIDE the claim guard: only the call that WON consumes the draft, so two
        # concurrent deliveries of one completion cannot have one of them clear the
        # reference out from under the other before it has been stored.
        # A retry does not need the draft any more - `_stored_order_id` recovers the
        # reference from the row that the winner already wrote.
        if reference:
            try:
                clear_draft(phone, REF_DRAFT_CODE)
            except Exception:
                pass

    stars = '⭐' * rating if rating else ''
    return {
        'screen': 'CONFIRM',
        'data': {
            'review_id': review_id,
            'message': f'Thank you for your {stars} feedback! Your review has been submitted.',
        }
    }
