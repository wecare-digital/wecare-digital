"""Private endpointless WhatsApp ideas, linked to the authenticated sender.

The FlowSubmission is authoritative. The existing contact timeline reads flow_log
rows from SubmitRequestsTable; retries repair that projection before inbox dedup.
This path never sends a message or creates a public review or sales lead.
"""
import hashlib
import json

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


def save_idea(data, *, contact_id, phone, sender_name, message_id, dynamodb,
              activity_table, request_id=''):
    """Persist once by trusted sender + message id; repair a failed activity write."""
    idea = data.get('idea')
    if not isinstance(idea, str) or not idea.strip():
        raise ValueError('A customer idea is required')
    if not contact_id or not phone or not message_id:
        raise ValueError('Customer idea requires a sender and message id')
    topic = data.get('topic', '')
    if not isinstance(topic, str) or topic not in TOPICS:
        topic = 'other'
    consent = data.get('follow_up_opt_in') is True
    form = {'topic': topic, 'idea': idea.strip(), 'follow_up_opt_in': consent,
            'schema_version': str(data.get('schema_version', '3'))}
    # Never let a handset-provided token/contact id choose another customer's row.
    digest = hashlib.sha256(f'{contact_id}\x1f{message_id}'.encode()).hexdigest()
    submission_id = 'WD-IDEA-' + digest[:16].upper()
    result = flow_completion.claim_completion(
        flow_token=str(data.get('flow_token') or message_id), screen='REVIEW',
        submission_id=submission_id, reference_prefix='WD-IDEA',
        flow_code=FLOW_CODE, flow_type='customer_idea', phone=phone,
        contact_id=contact_id, sender_name=sender_name, form_data=form,
        status='open', extra={'flowId': FLOW_ID, 'subject': TOPICS[topic],
                            'description': form['idea'], 'source': 'whatsapp',
                            'whatsappMessageId': message_id}, request_id=request_id)
    if result.status == 'error':
        raise RuntimeError('Customer idea could not be saved')
    item = result.item
    if result.duplicate:
        item = dynamodb.Table(flow_completion.FLOW_SUBMISSIONS_TABLE).get_item(
            Key={'submissionId': submission_id}, ConsistentRead=True).get('Item')
        if not item:
            raise RuntimeError('Saved customer idea could not be read')
    # Stable key + original contents make retries safe, including a failure between
    # the authoritative write and this contact-timeline projection.
    dynamodb.Table(activity_table).put_item(Item={
        'id': 'idea-log-' + submission_id, 'type': 'flow_log',
        'action': 'customer_idea', 'flowCode': FLOW_CODE, 'flowId': FLOW_ID,
        'submissionId': submission_id, 'contactId': item['contactId'],
        'phone': item['phone'], 'subject': item['description'],
        'flowData': item['formData'], 'createdAt': item['createdAt'],
        'ttl': item['ttl'],
    })
    return result
