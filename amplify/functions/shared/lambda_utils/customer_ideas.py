"""Private endpointless WhatsApp ideas, linked to the authenticated sender.

One row in FlowSubmissionTable (flowCode WD_IDEA) is the idea: the flow-response table is the
single store for every submitted form, and ReviewTable was folded into it (see
`lambda_utils.flow_records`). The row carries the review fields the staff reviews page and
the contact timeline read (`reviewId`, `reviewText`, `category`, `reviewType`,
`visibility`), so both keep working against the one table.

The write is a single conditional claim keyed on (contact, message id). A retry or a replayed
webhook finds the row already there and changes nothing, so neither the customer's text nor a
staff moderation decision can be overwritten. This path never sends a message or creates a
public review or sales lead.
"""
import hashlib

from lambda_utils import flow_completion

FLOW_KEY = 'wd_leave_review_v2'
FLOW_ID = '1578178897413815'
FLOW_CODE = 'WD_IDEA'
TOPICS = {
    'feature_request': 'A feature I would love',
    'improvement': 'Something to improve',
    'worked_well': 'Something I liked',
    'other': 'Another thought',
}


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


def save_idea(data, *, contact_id, phone, sender_name, message_id, dynamodb=None,
              request_id=''):
    """Claim the idea's one row. Raises when it could not be stored, so the webhook retries.

    `dynamodb` is accepted for the existing call site and unused: the claim goes through the
    one flow-response writer, which owns its table handle.
    """
    del dynamodb
    idea = data.get('idea')
    if not isinstance(idea, str) or not idea.strip():
        raise ValueError('A customer idea is required')
    if not contact_id or not phone or not message_id:
        raise ValueError('Customer idea requires a sender and message id')
    topic = data.get('topic', '')
    if not isinstance(topic, str) or topic not in TOPICS:
        topic = 'other'
    digest = hashlib.sha256(f'{contact_id}\x1f{message_id}'.encode()).hexdigest()
    review_id = 'WD-IDEA-' + digest[:16].upper()
    text = idea.strip()
    form = {'topic': topic, 'idea': text, 'schema_version': '4'}
    result = flow_completion.claim_completion(
        flow_token=message_id, screen='REVIEW', submission_id=review_id,
        reference_prefix='WD-IDEA', flow_code=FLOW_CODE, flow_type='customer_idea',
        phone=phone, contact_id=contact_id, sender_name=sender_name, form_data=form,
        # The review vocabulary: the staff reviews page shows `submitted` as `pending`.
        status='submitted',
        extra={'flowId': FLOW_ID, 'reviewId': review_id,
               'subject': TOPICS.get(topic, TOPICS['other']), 'description': text,
               'customerPhone': phone, 'customerName': sender_name,
               'reviewText': text, 'category': topic,
               'reviewType': 'customer_idea', 'visibility': 'private',
               'source': 'whatsapp', 'schemaVersion': '4',
               'whatsappMessageId': message_id},
        # A customer's idea is a business record, not a transport log.
        ttl_seconds=0,
        request_id=request_id, channel=flow_completion.CHANNEL_WHATSAPP)
    if result.status == 'error':
        raise RuntimeError('Customer idea could not be saved')
    return result
