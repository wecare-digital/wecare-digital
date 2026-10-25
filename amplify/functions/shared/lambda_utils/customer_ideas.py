"""Private endpointless WhatsApp ideas, linked to the authenticated sender.

One row in FlowSubmissionTable (flowCode WD-F002-LEAVE-REVIEW) is the idea: the flow-response table is the
single store for every submitted form, and ReviewTable was folded into it (see
`lambda_utils.flow_records`). The row carries the review fields the staff reviews page and
the contact timeline read (`reviewId`, `reviewText`, `category`, `reviewType`,
`visibility`), so both keep working against the one table.

The write is a single conditional claim keyed on (contact, message id). A retry or a replayed
webhook finds the row already there and changes nothing, so neither the customer's text nor a
staff moderation decision can be overwritten. This path never sends a message or creates a
public review or sales lead.

Order attribution
-----------------
The paid-invoice template's "Leave Review" FLOW button carries an order-bound `flow_token` minted
by `lambda_utils.ecommerce.review_token`. Meta echoes it back inside the completion's
`response_json`, so it is the only thing that can tie a review to the ORDER and INVOICE it was
written about. The binding is advisory: the sender's own contact always owns the review. A binding
is applied only when it does not disagree about who the sender is, and a lookup failure never fails
the save.
"""
import hashlib
import logging

from lambda_utils import canonical_flows, flow_completion
from lambda_utils.privacy import mask_contact_id, mask_flow_token

logger = logging.getLogger(__name__)

FLOW_KEY = 'wd_leave_review_v2'
FLOW_ID = canonical_flows.canonical_flow_id('leave_review') or '940049388908144'
FLOW_CODE = canonical_flows.canonical_contract('leave_review')['flowCode']
TOPICS = {
    'feature_request': "A feature I'd love",
    'improvement': 'Something to improve',
    'worked_well': 'Something I liked',
    'other': 'Another thought',
}

def response_answers(data):
    """Readable Inbox/Workspace answers matching the published review Flow."""
    rows = []
    raw_topic = data.get('topic')
    if isinstance(raw_topic, str) and raw_topic in TOPICS:
        rows.append({'question': "What's on your mind?", 'answer': TOPICS[raw_topic]})
    idea = data.get('idea')
    if isinstance(idea, str) and idea.strip():
        rows.append({'question': 'Your thought', 'answer': idea.strip()})
    return rows


def _text(data, key, *, required=False, limit=500):
    value = data.get(key, '')
    if not isinstance(value, str):
        value = ''
    value = value.strip() if key == 'idea' else ' '.join(value.split())
    if required and not value:
        raise ValueError(f'{key} is required')
    if len(value) > limit:
        raise ValueError(f'{key} is too long')
    return value


def idea_payload(message):
    """Recognise only this Flow's completion; other nfm replies retain their routes."""
    import json

    if message.get('type') != 'interactive':
        return None
    interactive = message.get('interactive') or {}
    if interactive.get('type') != 'nfm_reply':
        return None
    raw = (interactive.get('nfm_reply') or {}).get('response_json', '{}')
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get('flow_key') == FLOW_KEY else None


def _order_attribution(flow_token, *, contact_id, customer_uuid_value):
    """Advisory order/invoice attribution for a review from its FLOW `flow_token`.

    Returns extra FlowSubmission fields (orderId, invoiceId, referenceId, and customerUuid when
    the caller passed none) to merge, or an empty dict. A binding is applied only when its
    `contactId` is absent or matches the saving contact; a disagreement is logged (masked) and
    ignored. Any lookup failure returns `{}` so a review is never lost to attribution.
    """
    # Lazy import + resource: attribution is best-effort and must not add a cold-start cost or a
    # hard dependency to the idea path when no order-bound token is present.
    from lambda_utils.ecommerce import order_keys, review_token

    if not review_token.is_review_token(flow_token):
        return {}
    try:
        import boto3

        table = boto3.resource('dynamodb').Table(order_keys.commerce_keys_table_name())
        binding = review_token.resolve(table, flow_token)
    except Exception as error:  # noqa: BLE001 — attribution is advisory; never fail the save
        logger.warning('{"event":"review_token_attribution_failed","error":"%s"}',
                        type(error).__name__)
        return {}
    if not binding:
        return {}
    bound_contact = binding.get('contactId') or ''
    if bound_contact and bound_contact != contact_id:
        logger.warning(
            '{"event":"review_token_contact_mismatch","flowToken":"%s",'
            '"boundContactId":"%s","contactId":"%s"}',
            mask_flow_token(flow_token), mask_contact_id(bound_contact),
            mask_contact_id(contact_id))
        return {}
    attribution = {}
    for field in ('orderId', 'invoiceId', 'referenceId'):
        value = binding.get(field)
        if value:
            attribution[field] = value
    # Only fill the customer id when the caller did not already resolve one from the contact.
    if not customer_uuid_value and binding.get('customerUuid'):
        attribution['customerUuid'] = binding['customerUuid']
    return attribution


def save_idea(data, *, contact_id, phone, sender_name, message_id, dynamodb=None,
              request_id='', customer_uuid_value=''):
    """Claim the idea's one row. Raises when it could not be stored, so the webhook retries.

    `dynamodb` is accepted for the existing call site and unused: the claim goes through the
    one flow-response writer, which owns its table handle.
    """
    del dynamodb
    idea = _text(data, 'idea', required=True, limit=2000)
    if not contact_id or not phone or not message_id:
        raise ValueError('Customer idea requires a sender and message id')
    topic = data.get('topic', '')
    if not isinstance(topic, str) or topic not in TOPICS:
        topic = 'other'
    schema_version = str(data.get('schema_version') or '4')
    digest = hashlib.sha256(f'{contact_id}\x1f{message_id}'.encode()).hexdigest()
    review_id = 'WD-IDEA-' + digest[:16].upper()
    text = idea
    form = {'topic': topic, 'idea': text, 'schema_version': schema_version}
    # Advisory order/invoice attribution from the paid-invoice template's FLOW button token.
    attribution = _order_attribution(
        data.get('flow_token'), contact_id=contact_id,
        customer_uuid_value=customer_uuid_value)
    result = flow_completion.claim_completion(
        flow_token=message_id, screen='REVIEW', submission_id=review_id,
        reference_prefix='WD-IDEA', flow_code=FLOW_CODE, flow_type='customer_idea',
        phone=phone, contact_id=contact_id, sender_name=sender_name, form_data=form,
        # The review vocabulary: the staff reviews page shows `submitted` as `pending`.
        status='submitted',
        extra={'flowId': FLOW_ID, 'reviewId': review_id,
               'subject': TOPICS.get(topic, TOPICS['other']), 'description': text,
               'customerPhone': phone,
               'customerName': sender_name,
               'whatsappDisplayName': sender_name,
               'reviewText': text, 'category': topic,
               'reviewType': 'customer_idea', 'visibility': 'private',
               'source': 'whatsapp', 'schemaVersion': schema_version,
               'whatsappMessageId': message_id,
               **({'customerUuid': customer_uuid_value} if customer_uuid_value else {}),
               **attribution},
        # A customer's idea is a business record, not a transport log.
        ttl_seconds=0,
        request_id=request_id, channel=flow_completion.CHANNEL_WHATSAPP)
    if result.status == 'error':
        raise RuntimeError('Customer idea could not be saved')
    return result
