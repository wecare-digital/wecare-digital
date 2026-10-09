import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'amplify/functions/shared'))
sys.path.insert(0,str(Path(__file__).parent))
from coupon_fake_dynamo import FakeTable
from lambda_utils.ecommerce.document_source import owned_message_source, PRIVATE_INCOMING_PREFIX

@pytest.mark.parametrize('damage', [None, 'customer', 'phone', 'outbound', 'file', 'missing'])
def test_private_message_requires_matching_owner_phone_direction_and_exact_file(damage):
    messages, contacts = FakeTable(key_attr='id'), FakeTable(key_attr='id')
    key=PRIVATE_INCOMING_PREFIX+'owned.pdf'
    message={'id':'m','contactId':'c','channel':'whatsapp','direction':'inbound','s3Key':key}
    contact={'id':'c','phone':'+919000000000','checkoutCustomerId':'owner'}
    if damage=='customer': contact['checkoutCustomerId']='other'
    elif damage=='phone': contact['phone']='+919999999999'
    elif damage=='outbound': message['direction']='outbound'
    elif damage=='file': message['s3Key']=key+'different'
    messages.seed(message); contacts.seed(contact)
    assert owned_message_source(messages,contacts,SimpleNamespace(phone='+919000000000',customer_id='owner'),key,'' if damage=='missing' else 'm') is (damage is None)

def test_private_arrival_promotion_requires_proof_and_never_reports_public_exposure():
    from test_dropdocs_document_privacy import FakeS3, SOURCE_KEY, BUCKET
    from lambda_utils.ecommerce import dropdocs_storage, document_errors
    s3=FakeS3(); key=PRIVATE_INCOMING_PREFIX+'owned.pdf'
    s3.objects[key]=s3.objects[SOURCE_KEY]
    with pytest.raises(document_errors.DocumentRejected):
        dropdocs_storage.promote_to_secure(s3,bucket=BUCKET,source_key=key)
    result=dropdocs_storage.promote_to_secure(s3,bucket=BUCKET,source_key=key,verified_private_source=True)
    assert result['storageKey'].startswith('secure/u/dropdocs/')
    assert result['publicSourceRetained'] is False
