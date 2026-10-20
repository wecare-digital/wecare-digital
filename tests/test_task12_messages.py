"""Safety tests for canonical message item routes."""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / 'amplify' / 'functions' / 'shared'
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))


@pytest.fixture
def messages_handler():
    path = ROOT / 'amplify/functions/core/messages-read/handler.py'
    spec = importlib.util.spec_from_file_location('task12_messages_read', path)
    module = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(module)
    module.dynamodb = MagicMock()
    return module


def test_get_message_reads_canonical_table_only(messages_handler):
    table = MagicMock()
    table.get_item.return_value = {'Item': {'id': 'message-1', 'content': 'hello'}}
    messages_handler.dynamodb.Table.return_value = table
    response = messages_handler._read_one_message('message-1', 'req-1')
    assert response['statusCode'] == 200
    messages_handler.dynamodb.Table.assert_called_once_with(messages_handler.MESSAGES_TABLE)
    table.get_item.assert_called_once_with(Key={'id': 'message-1'})
    table.delete_item.assert_not_called()


def test_private_customer_media_returns_short_lived_signed_url(messages_handler):
    key = 'secure/u/whatsapp/incoming/customer-document.pdf'
    messages_handler.s3_client.generate_presigned_url.return_value = 'https://signed.example/document'
    with patch.object(messages_handler, '_find_actual_s3_key', return_value=key):
        result = messages_handler._convert_from_dynamodb({'id': 'message-private', 's3Key': key, 'messageType': 'document'})
    assert result['mediaUrl'] == 'https://signed.example/document'
    messages_handler.s3_client.generate_presigned_url.assert_called_once_with(
        'get_object', Params={'Bucket': messages_handler.MEDIA_BUCKET, 'Key': key}, ExpiresIn=300)


def test_payment_update_denied_before_write(messages_handler):
    event = {'body': json.dumps({'status': 'paid'})}
    denied = {'statusCode': 403, 'body': '{}'}
    with patch('lambda_utils.middleware.require_auth', return_value=denied):
        response = messages_handler._update_payment_message('message-1', event, 'req-2')
    assert response is denied
    messages_handler.dynamodb.Table.assert_not_called()


def test_payment_update_rejects_non_allowlisted_fields(messages_handler):
    event = {'body': json.dumps({'content': 'replace message', 'direction': 'outbound'})}
    with patch('lambda_utils.middleware.require_auth', return_value=None):
        response = messages_handler._update_payment_message('message-1', event, 'req-3')
    assert response['statusCode'] == 400
    messages_handler.dynamodb.Table.assert_not_called()


def test_payment_update_writes_only_allowlisted_fields(messages_handler):
    table = MagicMock()
    messages_handler.dynamodb.Table.return_value = table
    event = {'body': json.dumps({'paymentPurpose': 'invoice', 'content': 'blocked'})}
    with patch('lambda_utils.middleware.require_auth', return_value=None):
        response = messages_handler._update_payment_message('message-1', event, 'req-4')
    assert response['statusCode'] == 200
    kwargs = table.update_item.call_args.kwargs
    assert kwargs['Key'] == {'id': 'message-1'}
    assert set(kwargs['ExpressionAttributeNames'].values()) == {'paymentPurpose'}
    assert kwargs['ConditionExpression'] == 'attribute_exists(id)'


def test_flow_documents_refresh_only_for_the_same_contact(messages_handler):
    messages_handler.dynamodb.Table.return_value.get_item.return_value = {'Item': {
        'contactId': 'another-customer', 'attachments': [{'key': 'secure/other.pdf'}]}}
    result = messages_handler._convert_from_dynamodb({
        'id': 'flow-1', 'contactId': 'customer-1', 'messageType': 'flow_response',
        'flowSubmissionId': 'untrusted-hint', 'flowAttachments': []})
    assert result['flowAttachments'] == []
    messages_handler.s3_client.generate_presigned_url.assert_not_called()


def test_late_uploaded_documents_merge_with_original_attachments(messages_handler):
    original = {'key': 'secure/original.pdf', 'filename': 'Original.pdf'}
    linked = {'key': 'secure/late.pdf', 'filename': 'Late.pdf'}
    messages_handler.dynamodb.Table.return_value.get_item.return_value = {'Item': {
        'contactId': 'customer-1', 'attachments': [linked]}}
    messages_handler.s3_client.generate_presigned_url.return_value = 'https://signed.example/file'
    result = messages_handler._convert_from_dynamodb({
        'id': 'flow-1', 'contactId': 'customer-1', 'messageType': 'flow_response',
        'flowSubmissionId': 'submission-1', 'flowAttachments': [original]})
    assert [a['filename'] for a in result['flowAttachments']] == ['Original.pdf', 'Late.pdf']
    assert all(a['url'].startswith('https://signed') for a in result['flowAttachments'])


def test_complete_legacy_flow_json_is_rendered_as_fields(messages_handler):
    result = messages_handler._convert_from_dynamodb({
        'id': 'legacy', 'content': '[Flow Response: {"rating":5}]', 'messageType': 'interactive'})
    assert result['messageType'] == 'flow_response'
    assert result['flowAnswers'] == [{'question': 'Rating', 'answer': '5'}]
    assert result['content'] == 'Flow response'


def test_truncated_legacy_flow_json_is_not_invented_or_displayed(messages_handler):
    result = messages_handler._convert_from_dynamodb({
        'id': 'legacy', 'content': '[Flow Response: {"flow_key":"wd_leave_review_v2","schema_...]'})
    assert result['messageType'] == 'flow_response'
    assert result['flowAnswers'] == []
    assert result['content'] == 'Flow response'
