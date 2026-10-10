"""Private endpointless WhatsApp ideas, linked to the authenticated sender.

ReviewTable is authoritative. FlowSubmission is a tracking projection; the
contact timeline queries review records. Retries repair tracking before inbox dedup.
This path never sends a message or creates a public review or sales lead.
"""
import hashlib
import json
import os
import time

from botocore.exceptions import ClientError

from lambda_utils import flow_completion

FLOW_KEY = 'wd_leave_review_v2'
FLOW_ID = '2352304845587149'
FLOW_CODE = 'WD_IDEA'
REVIEWS_TABLE = os.environ.get('REVIEWS_TABLE', 'stack-wecare-digital-ReviewTable')
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
              request_id=''):
    """Claim the ReviewTable record first; retries repair its Flow tracking row."""
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
    now = int(time.time())
    item = {
        'reviewId': review_id, 'contactId': contact_id,
        'customerPhone': phone, 'customerName': sender_name,
        'reviewText': idea.strip(), 'category': topic,
        'reviewType': 'customer_idea', 'visibility': 'private',
        'source': 'whatsapp', 'status': 'submitted',
        'flowId': FLOW_ID, 'flowCode': FLOW_CODE,
        'schemaVersion': '4', 'whatsappMessageId': message_id,
        'createdAt': now, 'updatedAt': now,
    }
    table = dynamodb.Table(REVIEWS_TABLE)
    try:
        table.put_item(Item=item, ConditionExpression='attribute_not_exists(reviewId)')
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
        item = table.get_item(Key={'reviewId': review_id}, ConsistentRead=True).get('Item')
        if not item:
            raise RuntimeError('Saved customer review could not be read')
    # ReviewTable is authoritative. Rehydrate the original content on retries so
    # a repeated completion cannot overwrite text or staff moderation decisions.
    form = {'topic': item['category'], 'idea': item['reviewText'], 'schema_version': '4'}
    result = flow_completion.claim_completion(
        flow_token=message_id, screen='REVIEW', submission_id=review_id,
        reference_prefix='WD-IDEA', flow_code=FLOW_CODE, flow_type='customer_idea',
        phone=item['customerPhone'], contact_id=item['contactId'],
        sender_name=item['customerName'], form_data=form, status='open',
        extra={'flowId': FLOW_ID, 'reviewId': review_id,
               'subject': TOPICS.get(item['category'], TOPICS['other']),
               'description': item['reviewText'], 'source': 'whatsapp'},
        request_id=request_id)
    if result.status == 'error':
        raise RuntimeError('Customer review tracking could not be saved')
    return result
