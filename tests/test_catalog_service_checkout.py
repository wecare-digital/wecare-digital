import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("synthetic_service_catalog")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lambda_utils.ecommerce import catalog_service_checkout as catalog


@pytest.mark.parametrize('row', [
    # A finalized order on an attempt that is not paid.
    {'status': 'PAYMENT_PENDING', 'orderId': 'order-1', 'finalizationStage': 'ORDER_FINALIZED'},
    # Paid and staged final, but no order record id on the attempt.
    {'status': 'PAYMENT_PAID', 'finalizationStage': 'ORDER_FINALIZED'},
    # Paid with an order record whose tenders did not reconcile.
    {'status': 'PAYMENT_PAID', 'orderId': 'order-1', 'finalizationStage': 'NEEDS_RECONCILIATION'},
    # Paid with an order record that has not reached the terminal stage yet.
    {'status': 'PAYMENT_PAID', 'orderId': 'order-1', 'finalizationStage': 'INTERNAL_ORDER_CREATED'},
    # Paid, nothing finalized.
    {'status': 'PAYMENT_PAID'},
])
def test_partial_finalization_cannot_unlock_service(row):
    assert catalog.finalization_complete(row) is False


def test_a_paid_attempt_with_a_finalized_native_order_unlocks_service():
    """`finalization.accept_paid` stages INTERNAL_ORDER_CREATED with the orderId and then
    ORDER_FINALIZED, its only terminal success stage; that row is what unlocks the service."""
    assert catalog.finalization_complete({'status': 'PAYMENT_PAID', 'orderId': 'order-1',
                                           'finalizationStage': 'ORDER_FINALIZED'}) is True

from lambda_utils.ecommerce import service_requests
from lambda_utils import customer_auth
from synthetic_service_catalog import PRODUCT


def test_catalog_basket_rejects_mixed_services_and_quantity():
    variant = next(v for v, k in service_requests.SERVICE_KIND_BY_VARIANT.items() if k == 'SUBMIT_REQUEST')
    item = {'productId': PRODUCT, 'variantId': variant, 'quantity': 1}
    assert catalog.service_from_lines([item])['kind'] == 'SUBMIT_REQUEST'
    with pytest.raises(ValueError):
        catalog.service_from_lines([item, dict(item)])
    with pytest.raises(ValueError):
        catalog.service_from_lines([dict(item, quantity=2)])
    assert catalog.service_from_lines([{'productId': 'ordinary', 'quantity': 1}]) is None


def test_readded_contact_cannot_inherit_old_owner_without_verification():
    phone = '+919876543210'
    contact = {'id': 'contact', 'phone': phone, 'checkoutCustomerId': 'owner'}
    users = [{'Enabled': True, 'Attributes': [
        {'Name': 'sub', 'Value': 'owner'}, {'Name': 'phone_number', 'Value': phone},
        {'Name': 'phone_number_verified', 'Value': 'true'}]}]
    assert catalog.verified_identity(contact, users, phone).customer_id == 'owner'
    for changed in [dict(contact, isDeleted=True), dict(contact, checkoutCustomerId='another'),
                    {'id': 'new-contact', 'phone': phone}]:
        with pytest.raises(customer_auth.CustomerNotAuthorized):
            catalog.verified_identity(changed, users, phone)


@pytest.mark.parametrize('suffix', ['https://attacker.example/file', '../other-file', '', 'file?token=secret'])
def test_download_button_refuses_arbitrary_urls_and_tokens(suffix):
    with pytest.raises(ValueError):
        catalog.url_button_component({'suffix': suffix})


def test_dynamic_download_button_uses_file_id_only():
    assert catalog.url_button_component({'suffix': 'file-123'})['parameters'] == [
        {'type': 'text', 'text': 'file-123'}]


def _ready_meta():
    return {'flow': {'id': '1107164111921876', 'status': 'PUBLISHED', 'validation_errors': []},
        'templates': {name: {'name': name, 'status': 'APPROVED', 'language': 'en',
          'components': [{'type': 'BUTTONS', 'buttons': [{'type': 'URL',
                         'url': 'https://wecare.digital/vault/?file={{1}}'}]}]}
          for name in ('wecare_whatapp_native_pay_template', 'wecare_default_download')}}


def test_unpublished_submit_request_or_wrong_download_url_prevents_payment():
    ready = _ready_meta()
    assert catalog.meta_ready(ready, 'SUBMIT_REQUEST')
    ready['flow']['status'] = 'DRAFT'
    assert not catalog.meta_ready(ready, 'SUBMIT_REQUEST')
    assert catalog.meta_ready(ready, 'VAULT')
    ready['templates']['wecare_default_download']['components'][0]['buttons'][0]['url'] = 'https://other.example/{{1}}'
    assert not catalog.meta_ready(ready, 'VAULT')


def test_unapproved_payment_template_prevents_payment():
    ready = _ready_meta()
    ready['templates']['wecare_whatapp_native_pay_template']['status'] = 'PENDING'
    assert not catalog.meta_ready(ready, 'SUBMIT_REQUEST')
    assert not catalog.meta_ready(ready, 'VAULT')
