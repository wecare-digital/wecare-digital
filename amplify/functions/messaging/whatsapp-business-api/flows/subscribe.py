"""
Subscribe / Profile Flow — FREE, no payment.
Collects: name, phone, email, organization, job title, delivery address.
Billing = same as delivery (single address with checkbox).
Creates/updates contact, saves subscription, sends welcome message.

Flow: 02.WD_Profile
Screens: PERSONAL_INFO → SHIPPING_ADDRESS → REVIEW → COMPLETE
"""
import json
import time
import uuid
import logging
from decimal import Decimal
from typing import Dict

from flows.common import (
    dynamodb, lambda_client, CONTACTS_TABLE, FLOW_SUBMISSIONS_TABLE,
    OUTBOUND_WHATSAPP_FUNCTION, PHONE1_ID,
    get_phone_from_token, get_phone_number_id_for_flow,
    find_contact_by_phone, record_completion,
)

logger = logging.getLogger(__name__)

# ── Flow config ──
FLOW_CODE = 'WD_SUBSCRIBE'
FLOW_NAME = 'Subscribe'
REQUIRES_PAYMENT = False
PAYMENT_AMOUNT = 0


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT → show the current contact/profile values for the new Subscribe design."""
    phone = get_phone_from_token(flow_token)
    contact_id = find_contact_by_phone(phone)
    contact = {}
    if contact_id:
        try:
            contact = dynamodb.Table(CONTACTS_TABLE).get_item(
                Key={'id': contact_id}, ConsistentRead=True
            ).get('Item') or {}
        except Exception as exc:
            logger.warning(f'Subscribe profile prefill failed: {exc}')
    return {
        'screen': 'PROFILE',
        'data': {
            'phone_number': str(contact.get('phone') or phone or ''),
            'full_name': str(contact.get('name') or ''),
            'email_address': str(contact.get('email') or ''),
            'company_name': str(contact.get('companyName') or contact.get('contactBookName') or ''),
            'designation': str(contact.get('designation') or ''),
            'address_line1': str(contact.get('addressLine1') or contact.get('shippingAddress') or ''),
            'city': str(contact.get('city') or ''),
            'state': str(contact.get('state') or ''),
            'postal_code': str(contact.get('postalCode') or ''),
            'country': str(contact.get('country') or 'India'),
            'opt_in_whatsapp': bool(contact.get('optInWhatsApp', False)),
            'opt_in_email': bool(contact.get('optInEmail', False)),
            'opt_in_sms': bool(contact.get('optInSms', False)),
        },
    }


def handle_review(data: Dict, flow_token: str, request_id: str) -> Dict:
    """REVIEW screen → save contact + subscription, return COMPLETE."""
    # New profile/preferences design: update only the customer-editable profile and
    # opt-in fields. allowlist* stays operator/system-owned and is never written here.
    if str(data.get('profile_version') or '') == '2':
        phone = get_phone_from_token(flow_token)
        contact_id = find_contact_by_phone(phone)
        if not contact_id:
            return {'screen': 'COMPLETE', 'data': {
                'subscriber_id': '',
                'message': 'We could not load your contact profile. No changes were saved.'
            }}
        full_name = str(data.get('full_name') or '').strip()
        email = str(data.get('email_address') or '').strip()
        company = str(data.get('company_name') or '').strip()
        designation = str(data.get('designation') or '').strip()
        address_line1 = str(data.get('address_line1') or '').strip()
        city = str(data.get('city') or '').strip()
        state = str(data.get('state') or '').strip()
        postal_code = str(data.get('postal_code') or '').strip()
        country = str(data.get('country') or 'India').strip() or 'India'
        opt_wa = bool(data.get('opt_in_whatsapp', False))
        opt_email = bool(data.get('opt_in_email', False))
        opt_sms = bool(data.get('opt_in_sms', False))
        now_ts = int(time.time())
        try:
            dynamodb.Table(CONTACTS_TABLE).update_item(
                Key={'id': contact_id},
                UpdateExpression=(
                    'SET #nm=:nm, #em=:em, #cmn=:cmn, #des=:des, '
                    '#al1=:al1, #ct=:ct, #st=:st, #pc=:pc, #co=:co, '
                    '#ow=:ow, #oe=:oe, #os=:os, #ua=:ua'
                ),
                ExpressionAttributeNames={
                    '#nm':'name','#em':'email','#cmn':'companyName','#des':'designation',
                    '#al1':'addressLine1','#ct':'city','#st':'state','#pc':'postalCode',
                    '#co':'country','#ow':'optInWhatsApp','#oe':'optInEmail',
                    '#os':'optInSms','#ua':'updatedAt'
                },
                ExpressionAttributeValues={
                    ':nm':full_name, ':em':email, ':cmn':company, ':des':designation,
                    ':al1':address_line1, ':ct':city, ':st':state, ':pc':postal_code,
                    ':co':country, ':ow':opt_wa, ':oe':opt_email, ':os':opt_sms,
                    ':ua':now_ts
                }
            )
        except Exception as exc:
            logger.warning(f'Subscribe profile update failed: {exc}')
            return {'screen': 'COMPLETE', 'data': {
                'subscriber_id': '',
                'message': 'We could not save your profile changes. Please try again.'
            }}
        existing_sub_id = _find_existing_subscriber_id(phone)
        result = record_completion(
            flow_code=FLOW_CODE, flow_type='profile_update', phone=phone,
            contact_id=contact_id, sender_name=full_name, form_data=data,
            flow_token=flow_token, request_id=request_id, screen='REVIEW',
            reference_prefix='WD-SUB', requires_payment=False, payment_amount=0,
            status='completed',
        )
        subscriber_id = existing_sub_id or result.reference
        return {'screen': 'COMPLETE', 'data': {
            'subscriber_id': subscriber_id,
            'message': 'Your profile and contact preferences are saved.'
        }}

    phone = get_phone_from_token(flow_token)
    phone_number_id = get_phone_number_id_for_flow(flow_token)

    # ── Extract form data (matches 02.WD_Profile flow fields exactly) ──
    full_name = data.get('full_name', '')
    phone_number = data.get('phone_number', '')
    email_address = data.get('email_address', '')
    company_name = data.get('company_name', '')
    wa_username = data.get('wa_username', '')
    designation = data.get('designation', '')  # "Job Title" in flow UI

    # ── Extract delivery address (billing = same as delivery) ──
    ship_house = data.get('ship_house', '')
    ship_building = data.get('ship_building', '')
    ship_street = data.get('ship_street', '')  # "Landmark" in flow UI
    ship_city = data.get('ship_city', '')
    ship_state = data.get('ship_state', '')
    ship_pin = data.get('ship_pin', '')  # "Postal Code" in flow UI
    ship_country = data.get('ship_country', '')

    # ── Build address strings ──
    addr_parts = [ship_house, ship_building, ship_street, ship_city,
                  ship_state, ship_pin, ship_country]
    address_str = ', '.join(p for p in addr_parts if p)

    # ── Claim the completion BEFORE any save ──
    # A retry of this data_exchange used to run the whole body again. With no existing
    # contact it minted a fresh `subscriber_uuid` and wrote a **second Contact row with a
    # different id**, then sent a second welcome message. `_find_existing_subscriber_id`
    # was the only thing standing in the way and it reads an eventually-consistent GSI, so
    # a fast redelivery slipped past it.
    #
    # The derived reference removes that dependency entirely: it is a function of the flow
    # token, so it is the same value on every delivery whether or not the index has caught
    # up. The conditional put inside `record_completion` decides who proceeds.
    subscriber_uuid = str(uuid.uuid4())
    contact_id = find_contact_by_phone(phone)
    existing_sub_id = _find_existing_subscriber_id(phone)

    form_payload = {
        'full_name': full_name, 'phone_number': phone_number,
        'email_address': email_address, 'company_name': company_name,
        'wa_username': wa_username, 'designation': designation,
        'ship_house': ship_house, 'ship_building': ship_building,
        'ship_street': ship_street, 'ship_city': ship_city,
        'ship_state': ship_state, 'ship_pin': ship_pin,
        'ship_country': ship_country,
    }
    result = record_completion(
        flow_code=FLOW_CODE, flow_type='subscription', phone=phone,
        contact_id=contact_id, sender_name=full_name,
        form_data=form_payload,
        flow_token=flow_token, request_id=request_id, screen='REVIEW',
        reference_prefix='WD-SUB',
        requires_payment=False, payment_amount=0, status='completed',
    )

    # A returning subscriber keeps the id they already have; a new one gets the derived
    # reference. Note that the claim id is per *completion* (per flow token), not per
    # subscriber - otherwise a subscriber could never update their details a second time.
    subscriber_id = existing_sub_id or result.reference
    is_resubscribe = bool(existing_sub_id)

    # ── SET COMPLETE RESPONSE ──
    welcome_msg = (
        f'Welcome back to WECARE.DIGITAL! Your details have been updated.\nSubscriber ID: {subscriber_id}'
        if is_resubscribe else
        f'Welcome to WECARE.DIGITAL! Your subscriber ID is {subscriber_id}.'
    )
    response_payload = {
        'screen': 'COMPLETE',
        'data': {
            'subscriber_id': subscriber_id,
            'message': welcome_msg,
        }
    }
    logger.info(json.dumps({
        'event': 'subscribe_success_payload',
        'subscriber_id': subscriber_id,
        'is_resubscribe': is_resubscribe,
        'phone_suffix': phone[-4:] if phone else '',
    }))

    if not result.should_fire_side_effects:
        logger.info(json.dumps({
            'event': 'subscribe_no_side_effects',
            'status': result.status, 'submissionId': result.submission_id,
            'reason': 'duplicate completion' if result.duplicate else result.error,
            'requestId': request_id,
        }))
        return response_payload

    # ── Save contact with structured address fields ──
    now_ts = int(time.time())
    try:
        _save_contact(
            contact_id=contact_id,
            subscriber_uuid=subscriber_uuid,
            subscriber_id=subscriber_id,
            phone=phone,
            full_name=full_name,
            email=email_address,
            company=company_name,
            username=wa_username,
            designation=designation,
            ship_house=ship_house,
            ship_building=ship_building,
            ship_street=ship_street,
            ship_city=ship_city,
            ship_state=ship_state,
            ship_pin=ship_pin,
            ship_country=ship_country,
            address_str=address_str,
            now_ts=now_ts,
        )
        if not contact_id:
            contact_id = subscriber_uuid
    except Exception as e:
        logger.warning(f'Subscribe contact save failed: {e}')

    # The submission row was already written by `record_completion` above - it is the claim.
    # It used to be written here instead, after the contact save, which is why a failed
    # claim could not gate anything: there was nothing to gate on yet.

    # ── Send confirmation message (async) ──
    try:
        confirm_text = (
            f'✅ *Subscription {"Updated" if is_resubscribe else "Confirmed"}*\n\n'
            f'👤 *Name:* {full_name}\n📱 *Phone:* {phone_number}\n'
            f'📧 *Email:* {email_address}\n🏢 *Organization:* {company_name}\n'
            f'💼 *Job Title:* {designation}\n'
            f'🆔 *Subscriber ID:* {subscriber_id}\n\n'
            f'Your details have been saved. You will receive order updates, offers, and service news.\n\n'
            f'Type *my id* anytime to retrieve your subscriber ID.\n_WECARE.DIGITAL_'
        )
        lambda_client.invoke(
            FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps({'body': json.dumps({
                'contactId': contact_id, 'recipientPhone': phone,
                'content': confirm_text, 'phoneNumberId': phone_number_id,
            })})
        )
    except Exception as e:
        logger.warning(f'Subscribe confirmation send failed: {e}')

    return response_payload


# ── Private helpers ──

def _find_existing_subscriber_id(phone: str) -> str:
    """Find existing subscriber ID by phone number.
    Queries FlowSubmissions table — if found, reuses the SAME ID (never regenerates).
    """
    if not phone:
        return ''
    try:
        fs_table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        resp = fs_table.query(
            IndexName='phone', KeyConditionExpression='phone = :ph',
            FilterExpression='flowCode = :fc',
            ExpressionAttributeValues={':ph': phone, ':fc': FLOW_CODE},
            ScanIndexForward=False, Limit=1,
        )
        items = resp.get('Items', [])
        if items:
            sub_id = items[0].get('submissionNumber', '') or items[0].get('submissionId', '')
            return sub_id
        return ''
    except Exception as e:
        logger.warning(f'Subscriber ID lookup failed: {e}')
        return ''


def _save_contact(contact_id, subscriber_uuid, subscriber_id, phone,
                  full_name, email, company, username, designation,
                  ship_house, ship_building, ship_street, ship_city,
                  ship_state, ship_pin, ship_country, address_str, now_ts):
    """Save or update contact with structured address fields + subscriber ID tag."""
    ct = dynamodb.Table(CONTACTS_TABLE)

    # Build tags list — include subscriber ID as tag for easy lookup
    sub_tag = f'sub:{subscriber_id}'
    tags = ['subscriber', sub_tag]

    if contact_id:
        # Update existing contact — preserve existing tags, add subscriber tag
        try:
            existing = ct.get_item(Key={'id': contact_id}).get('Item', {})
            existing_tags = existing.get('tags', []) or []
            # Remove old sub: tags, add new one
            tags = [t for t in existing_tags if not t.startswith('sub:')] + [sub_tag]
            if 'subscriber' not in tags:
                tags.append('subscriber')
        except Exception:
            pass

        ct.update_item(
            Key={'id': contact_id},
            UpdateExpression=(
                'SET #nm=:nm, #em=:em, #sa=:sa, #ba=:ba, #ua=:ua, '
                '#cbn=:cbn, #cmn=:cmn, #des=:des, #un=:un, '
                '#hn=:hn, #bn=:bn, #al1=:al1, #ct=:ct, #st=:st, #pc=:pc, #co=:co, '
                '#ow=:ow, #os=:os, #oe=:oe, #tg=:tg'
            ),
            ExpressionAttributeNames={
                '#nm': 'name', '#em': 'email',
                '#sa': 'shippingAddress', '#ba': 'billingAddress',
                '#ua': 'updatedAt', '#cbn': 'contactBookName', '#cmn': 'companyName',
                '#des': 'designation', '#un': 'username',
                '#hn': 'houseNumber', '#bn': 'buildingName',
                '#al1': 'addressLine1', '#ct': 'city', '#st': 'state',
                '#pc': 'postalCode', '#co': 'country',
                '#ow': 'optInWhatsApp', '#os': 'optInSms', '#oe': 'optInEmail',
                '#tg': 'tags',
            },
            ExpressionAttributeValues={
                ':nm': full_name, ':em': email,
                ':sa': address_str, ':ba': address_str,  # billing = delivery
                ':ua': now_ts, ':cbn': company, ':cmn': company,
                ':des': designation, ':un': username,
                ':hn': ship_house, ':bn': ship_building,
                ':al1': ship_street, ':ct': ship_city, ':st': ship_state,
                ':pc': ship_pin, ':co': ship_country or 'India',
                ':ow': True, ':os': True, ':oe': True,
                ':tg': tags,
            },
        )
    else:
        # Create new contact
        norm_phone = phone.replace('+', '').replace(' ', '')
        if norm_phone and not norm_phone.startswith('+'):
            norm_phone = f'+{norm_phone}'
        ct.put_item(Item={
            'id': subscriber_uuid, 'contactId': subscriber_uuid,
            'name': full_name, 'phone': norm_phone, 'email': email,
            'contactBookName': company, 'companyName': company,
            'username': username, 'designation': designation,
            'houseNumber': ship_house, 'buildingName': ship_building,
            'addressLine1': ship_street, 'city': ship_city,
            'state': ship_state, 'postalCode': ship_pin,
            'country': ship_country or 'India',
            'shippingAddress': address_str, 'billingAddress': address_str,
            'optInWhatsApp': True, 'optInSms': True, 'optInEmail': True,
            'tags': tags,
            'createdAt': now_ts, 'updatedAt': now_ts,
        })
