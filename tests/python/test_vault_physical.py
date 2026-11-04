"""Vault physical-goods payload and pre-send address guard; no AWS or messages."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from lambda_utils.ecommerce import catalog_service_checkout as catalog, service_requests
from lambda_utils.ecommerce import order_delivery, payment_address

ROOT = Path(__file__).resolve().parents[2]
HANDLER = ROOT / 'amplify/functions/ecommerce/checkout/handler.py'
ADDRESS = {'addressLine1':'Example street','city':'Kolkata','state':'West Bengal',
           'postalCode':'700012','countryCode':'IN'}


def function(name, **extra):
    node = next(n for n in ast.parse(HANDLER.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    env = {'Dict':dict,'Any':object,'service_requests':service_requests,
           'CONTRIBUTION_PRODUCT_IDS':set(),'order_delivery':order_delivery,
           # `_payment_shipping_info` now calls the shared Meta-shipping guard before returning.
           'payment_address':payment_address, **extra}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HANDLER), 'exec'), env)
    return env[name]


def test_vault_physical_template_keeps_exact_quote_and_saved_address():
    # profile carries `phone`: Meta requires phone_number on the shipping address, and a real
    # Vault payment always has the owner's verified phone (see the Meta-shipping guard).
    shipping = function('_payment_shipping_info')(
        {'name':'Example Customer','phone':'+918100640044'}, ADDRESS)
    quote = SimpleNamespace(collection_before_convenience_paise=8254,
                            convenience_fee_paise=206, convenience_gst_paise=37,
                            total_payable_paise=8497)
    lines = {'lines':[{'unitPricePaise':4900,'quantity':1}], 'supplyGstPaise':882,
             'discountPaise':28, 'deliveryPaise':2500}
    result = catalog.payment_details({'kind':'VAULT'}, quote, 'WD-PAY-EXAMPLE',
        'WECAREDIGITAL', 1800000000, invoice_lines=lines, shipping_info=shipping)
    assert result['type'] == 'physical-goods'
    assert result['shipping_info']['addresses'][0]['name'] == 'Example Customer'
    assert result['shipping_info']['addresses'][0]['in_pin_code'] == '700012'
    assert result['total_amount']['value'] == 8497
    assert result['order']['shipping']['value'] == 2500
    assert result['order']['tax']['value'] == 919
    assert result['order']['discount']['value'] == 28
    assert 'interactive' not in result


def test_vault_packet_refuses_missing_shipping_instead_of_digital_fallback():
    quote = SimpleNamespace(collection_before_convenience_paise=8254,
        convenience_fee_paise=206, convenience_gst_paise=37,total_payable_paise=8497)
    with pytest.raises(ValueError, match='verified shipping'):
        catalog.payment_details({'kind':'VAULT'}, quote, 'WD-PAY-EXAMPLE','WECAREDIGITAL',1800000000)
    assert catalog.payment_details({'kind':'DROP_DOCS'}, quote,'WD-PAY-EXAMPLE',
        'WECAREDIGITAL',1800000000)['type'] == 'digital-goods'


def test_server_basket_classifies_vault_as_physical_and_other_services_unchanged():
    needs = function('_basket_requires_delivery')
    def cart(kind):
        variant=service_requests.SERVICE_VARIANT_BY_KIND[kind]
        product=service_requests.SERVICE_PRODUCT_BY_VARIANT[variant]
        return [{'catalogReference':{'catalogItemId':product},'quantity':1}]
    assert needs(cart('VAULT'))
    assert not needs(cart('DROP_DOCS'))


def test_payment_shipping_info_includes_meta_required_phone_number():
    """Regression for the live 400: Meta rejects shipping_info.addresses[0] with no phone_number.

    The native (AWS_NATIVE) Vault send failed at Meta because this builder omitted phone_number.
    Pin that a complete profile produces every Meta-required field.
    """
    shipping = function('_payment_shipping_info')(
        {'name':'Example Customer','phone':'+918100640044'}, ADDRESS)
    addr = shipping['addresses'][0]
    for field in payment_address.META_SHIPPING_ADDRESS_REQUIRED_FIELDS:
        assert str(addr.get(field) or '').strip(), f'missing Meta-required field {field}'
    assert addr['phone_number'] == '918100640044'  # bare E.164 digits, no '+'


def test_meta_shipping_guard_refuses_a_missing_required_field():
    """The shared guard must fail fast on a dropped field instead of shipping a bad payload."""
    good = {'country':'IN','addresses':[{'name':'A','phone_number':'918100640044',
            'address':'Street','city':'Kolkata','state':'West Bengal','in_pin_code':'700012'}]}
    payment_address.assert_meta_shipping_info(good)  # complete: no raise
    for drop in payment_address.META_SHIPPING_ADDRESS_REQUIRED_FIELDS:
        bad = {'country':'IN','addresses':[{k:v for k,v in good['addresses'][0].items()
                                            if k != drop}]}
        with pytest.raises(payment_address.UnpayableAddress):
            payment_address.assert_meta_shipping_info(bad)


def test_missing_saved_address_is_refused_before_prepare_claim_or_provider():
    keys = SimpleNamespace(get_item=lambda **kw:{'Item':{
        'status':'PREPARING_PAYMENT','expiresAt':9999999999,'kind':'VAULT',
        'customerId':'owner','contactId':'contact','phone':'+919000000001',
        'phoneNumberId':'sender'}})
    fn = function('_native_catalog_service', os=SimpleNamespace(environ={
        'WHATSAPP_CATALOG_SERVICES_ENABLED':'true'}),time=__import__('time'),
        _keys_table=lambda:keys,_table=lambda name:SimpleNamespace(
            get_item=lambda **kw:{'Item':{'name':'Example Customer'}}),
        CONTACTS_TABLE='contacts',_native_whatsapp_identity=lambda *args:(
            SimpleNamespace(customer_id='owner'),{'name':'Example Customer'}),
        wa_payment_request=SimpleNamespace(PAYMENT_SENDERS={'sender'}),
        contact_address=SimpleNamespace(from_contact=lambda contact:None),
        payment_address=payment_address,customer_auth=SimpleNamespace(
            CustomerNotAuthorized=ValueError),customer_identity=SimpleNamespace(InvalidPhoneNumber=ValueError))
    result = fn({'internalAction':'prepareNativeCatalogService','catalogToken':'a'*24},'')
    assert result == {'outcome':'PAYMENT_REQUEST_REFUSED','reason':'DELIVERY_DETAILS_REQUIRED'}


def test_native_vault_and_cart_require_explicit_delivery_confirmation():
    requires = function('_native_delivery_confirmation_required',
        contact_address=SimpleNamespace(address_message_reaches=lambda phone: True))
    owner = SimpleNamespace(customer_id='owner-sub', phone='+919000000001')
    session = {'origin': 'STAFF_VAULT', 'kind': service_requests.VAULT,
               'vaultFileId': 'file-1', 'customerId': 'owner-sub'}
    # A saved complete address, matching owner and exact-file metadata are
    # NEVER sufficient on their own to confirm this physical-goods shipment.
    assert requires(owner, {}, {'id': 'contact'}, session, ADDRESS) is True
    assert requires(owner, {}, {'id': 'contact'}, None, ADDRESS) is True
    assert requires(owner, {}, {'id': 'contact'}, {**session, 'customerId': 'other'}, ADDRESS) is True
    assert requires(owner, {}, {'id': 'contact'}, session, None) is True
    # Only the trusted caller may mark the freshly checked address confirmed.
    assert requires(owner, {'deliveryConfirmed': True}, {'id': 'contact'}, session, ADDRESS) is False
    assert requires(owner, {'deliveryConfirmed': True}, {'id': 'contact'}, None, ADDRESS) is False
    assert requires(owner, {}, None, session, ADDRESS) is False


def test_vault_physical_goods_still_refuse_other_country_or_missing_address():
    # Payment payability remains separate and must refuse non-India shipping.
    with pytest.raises(payment_address.UnpayableAddress):
        payment_address.assert_payable({**ADDRESS, 'countryCode': 'US'},
                                       channel=payment_address.WHATSAPP_ORDER_DETAILS)
    with pytest.raises(payment_address.UnpayableAddress):
        payment_address.assert_payable({**ADDRESS, 'postalCode': ''},
                                       channel=payment_address.WHATSAPP_ORDER_DETAILS)


def test_explicit_vault_delivery_review_is_bound_to_saved_payable_address():
    from decimal import Decimal
    from lambda_utils.ecommerce import contact_address
    current = {'checkoutDeliveryAddress': ADDRESS, 'checkoutAddressUpdatedAt': Decimal('1793690000')}
    review = {'confirmed': True, 'checkoutAddressUpdatedAt': 1793690000}
    proof = catalog.confirmed_vault_shipping_address(current, review)
    assert proof == {'checkoutAddressUpdatedAt': 1793690000,
                     'addressDigest': proof['addressDigest']}
    assert len(proof['addressDigest']) == 64
    assert catalog.confirmed_vault_shipping_address(current, None) is None
    assert catalog.confirmed_vault_shipping_address(current, {**review, 'confirmed': False}) is None
    assert catalog.confirmed_vault_shipping_address(current, {**review, 'checkoutAddressUpdatedAt': 1793690001}) is None
    assert catalog.confirmed_vault_shipping_address(current, {**review, 'checkoutAddressUpdatedAt': True}) is None
    assert catalog.confirmed_vault_shipping_address(
        {**current, 'checkoutDeliveryAddress': {**ADDRESS, 'postalCode': 'wrong'}}, review) is None
    assert catalog.confirmed_vault_shipping_address(
        {**current, 'checkoutDeliveryAddress': {**ADDRESS, 'countryCode': 'US'}}, review) is None

    # A corrected address carrying the same second-level revision is still
    # detected at commerce by comparing its canonical digest before claiming.
    changed = {**current, 'checkoutDeliveryAddress': {**ADDRESS, 'addressLine1': 'Another street'}}
    other = catalog.confirmed_vault_shipping_address(changed, review)
    assert other is not None and other['addressDigest'] != proof['addressDigest']
