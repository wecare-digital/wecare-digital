import json
from lambda_utils.flow_inbox import from_message, project


def test_full_completion_is_readable_without_protocol_fields_or_nested_secrets():
    result = from_message({'interactive': {'nfm_reply': {'response_json': json.dumps({
        'flow_key': 'wd_leave_review_v2', 'schema_version': '2', 'flow_token': 'private',
        'rating': 5, 'review_text': 'Helpful service ' * 20,
        'answers': {'follow_up': True, 'access_token': 'hidden'},
    })}}})
    assert result['messageType'] == 'flow_response'
    assert result['flowCode'] == 'wd_leave_review_v2'
    assert {'question': 'Rating', 'answer': '5'} in result['flowAnswers']
    assert {'question': 'Follow Up', 'answer': 'Yes'} in result['flowAnswers']
    assert 'Helpful service ' * 20 in str(result)
    assert 'private' not in str(result) and 'hidden' not in str(result)
    assert 'Schema Version' not in str(result)


def test_document_and_image_uploads_are_preserved_as_attachments():
    result = project({'documents': [{'s3Key': 'secure/a.pdf', 'filename': 'Receipt.pdf', 'mime_type': 'application/pdf'}],
                      'photo': {'key': 'secure/photo.png', 'name': 'Photo.png', 'type': 'image/png'}})
    assert [a['key'] for a in result['flowAttachments']] == ['secure/a.pdf', 'secure/photo.png']
    assert result['flowAttachments'][0]['filename'] == 'Receipt.pdf'
    assert result['flowAnswers'][0]['answer'] == '1 attachment(s)'


def test_bad_payload_and_native_address_do_not_break_ingestion():
    for value in ('invalid JSON', '[]', None, 42):
        assert project(value) == {}
    assert from_message({'interactive': {'nfm_reply': {'name': 'address_message', 'response_json': '{}'}}}) == {}


def test_untrusted_attachment_schemes_never_become_links():
    result = project({'file': {'url': 'javascript:alert(1)', 'filename': 'Unsafe'}})
    assert result['flowAttachments'] == []


def test_documents_link_to_the_most_recent_explicit_flow_target():
    from lambda_utils.flow_inbox import active_submission
    assert active_submission({'openServiceRequestId': 'older', 'openServiceRequestAt': 900,
                              'pendingDocumentSubmissionId': 'document', 'pendingDocumentSubmissionAt': 990}, 1000) == 'document'
    assert active_submission({'pendingDocumentSubmissionId': 'expired', 'pendingDocumentSubmissionAt': 1}, 10000) == ''
    assert active_submission({'pendingDocumentSubmissionId': 'future', 'pendingDocumentSubmissionAt': 2000}, 1000) == ''
