"""Prove a staged WhatsApp attachment belongs to a verified customer."""
from lambda_utils import media_paths

PRIVATE_INCOMING_PREFIX = media_paths.secure('u/whatsapp/incoming/')


def owned_message_source(messages, contacts, identity, source_key, message_id):
    if not message_id or not str(source_key).startswith(PRIVATE_INCOMING_PREFIX):
        return False
    message = messages.get_item(Key={'id': str(message_id)}, ConsistentRead=True).get('Item') or {}
    if (message.get('direction') != 'inbound' or message.get('channel') != 'whatsapp'
            or message.get('s3Key') != source_key or not message.get('contactId')):
        return False
    contact = contacts.get_item(Key={'id': message['contactId']}, ConsistentRead=True).get('Item') or {}
    phone = ''.join(c for c in str(contact.get('phone') or '') if c.isdigit())
    expected = ''.join(c for c in str(identity.phone or '') if c.isdigit())
    return bool(expected and phone == expected and contact.get('deletedAt') is None and not contact.get('isDeleted')
                and contact.get('checkoutCustomerId') == identity.customer_id)
