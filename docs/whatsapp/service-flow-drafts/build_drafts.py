"""Produce unpublished, branded design previews; no customer data or API calls."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/design-drafts'
OUT.mkdir(exist_ok=True)
review = json.loads((ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/leave-review-flow-v2.json').read_text())
BRAND = copy.deepcopy(review['screens'][0]['layout']['children'][0])
BRAND['alt-text'] = 'WECARE.DIGITAL'
# The CURRENT public order-number format: WD-ORD- plus 8 symbols of
# order_keys.PUBLIC_ORDER_NUMBER_ALPHABET. Illustrative only - these drafts are unpublished
# previews with no customer data - but an example in the old
# 'WD-ORD - A1B2C3D4 - DD-MM-YYYY - HH:MM:SS - IST' shape shows a reviewer a shape nothing
# mints any more.
ORDER = 'WD-ORD-K4M7PQR9'
ORDERS = [{'id': ORDER, 'title': 'Example order · K4M7PQR9'}, {'id': 'not_found', 'title': 'I cannot find my order'}]

def text(kind, value):
    return {'type': kind, 'text': value}

def schema(values):
    return {k: {'type': 'string', '__example__': v} for k, v in values.items()}

def footer(label, target=None, payload=None):
    action = {'name': 'navigate' if target else 'complete', 'payload': payload or {}}
    if target:
        action['next'] = {'type': 'screen', 'name': target}
    return {'type': 'Footer', 'label': label, 'on-click-action': action}

def screen(id, title, children, data=None, terminal=False):
    result = {'id': id, 'title': title, 'data': data or {},
              'layout': {'type': 'SingleColumnLayout', 'children': [copy.deepcopy(BRAND)] + children}}
    if terminal:
        result.update(terminal=True, success=True)
    return result

def form(children):
    return {'type': 'Form', 'name': 'service_form', 'children': children}

def field(kind, name, label, required=True, **extra):
    return {'type': kind, 'name': name, 'label': label, 'required': required, **extra}

def refs(keys, prefix='data'):
    return {key: '${' + prefix + '.' + key + '}' for key in keys}

def choose(next_screen, heading, body):
    return screen('SELECT_ORDER', heading, [text('TextHeading', heading), text('TextBody', body),
        form([field('Dropdown', 'parent_order', 'Your order', **{'data-source': ORDERS}),
              field('TextInput', 'manual_order_number', 'Order number', False,
                    **{'helper-text': 'Enter the number from your receipt if your order is not listed.'}),
              footer('Next', next_screen, refs(['parent_order', 'manual_order_number'], 'form'))]),
        text('TextCaption', 'Example orders are shown in this unpublished design preview.')])

def document(screens):
    return {'version': '7.3', 'routing_model': {s['id']: [screens[i + 1]['id']] if i + 1 < len(screens) else []
            for i, s in enumerate(screens)}, 'screens': screens}

BASE = {'parent_order': ORDER, 'manual_order_number': ''}
drafts = {}
details = screen('DETAILS', 'Submit Request', [text('TextHeading', 'What needs attention?'),
    text('TextBody', 'Tell us what happened and the outcome you would like for your existing order.'),
    form([field('TextInput', 'subject', 'A short title'),
          field('TextArea', 'description', 'Request details'),
          footer('Review request', 'REVIEW', {**refs(BASE), **refs(['subject', 'description'], 'form')})])], schema(BASE))
request_data = {**BASE, 'subject': 'Help with my order', 'description': 'Please help me resolve this issue.'}
request_review = screen('REVIEW', 'Ready to submit?', [text('TextHeading', 'Your request, clearly connected'),
    text('TextCaption', 'Original order'), text('TextBody', '${data.parent_order}'),
    text('TextCaption', 'Order number supplied'), text('TextBody', '${data.manual_order_number}'),
    text('TextSubheading', '${data.subject}'), text('TextBody', '${data.description}'),
    text('TextBody', 'If your order could not be found, we will verify your reference before taking action.'),
    text('TextCaption', 'Your service payment and original order have separate references.'),
    footer('Submit request', payload={'design_service': 'submit-request', **refs(request_data)})], schema(request_data), True)
drafts['submit-request'] = document([choose('DETAILS', 'Submit Request', 'Choose the existing order you need help with.'), details, request_review])

amend_data = {**BASE, 'request_number': 'WD-SR-A1B2C3D4', 'amendment': 'Please update the delivery instructions.'}
amend = screen('AMENDMENT', 'Request Amendment', [text('TextHeading', 'What would you like to change?'),
    text('TextBody', 'Add a correction or new information to a request already under way.'),
    form([field('TextInput', 'request_number', 'Request number'),
          field('TextArea', 'amendment', 'Describe the change'),
          footer('Review amendment', 'REVIEW', {**refs(BASE), **refs(['request_number', 'amendment'], 'form')})])], schema(BASE))
amend_review = screen('REVIEW', 'Ready to submit?', [text('TextHeading', 'Keep your request moving'),
    text('TextCaption', 'Order'), text('TextBody', '${data.parent_order}'),
    text('TextCaption', 'Request'), text('TextBody', '${data.request_number}'),
    text('TextCaption', 'Your amendment'), text('TextBody', '${data.amendment}'),
    text('TextBody', 'We will review what can be changed and update you here on WhatsApp.'),
    footer('Submit amendment', payload={'design_service': 'request-amendment', **refs(amend_data)})], schema(amend_data), True)
drafts['request-amendment'] = document([choose('AMENDMENT', 'Request Amendment', 'Choose the order linked to your existing request.'), amend, amend_review])

upload = screen('UPLOAD', 'Drop Docs', [text('TextHeading', 'Add the documents we need'),
    text('TextBody', 'Choose your files and tell us what they relate to.'),
    text('TextCaption', 'Linked order'), text('TextBody', '${data.parent_order}'),
    form([field('TextInput', 'request_number', 'Request number'),
          field('TextArea', 'note', 'What should we know?', False),
          {'type': 'DocumentPicker', 'name': 'documents', 'label': 'Choose documents',
           'description': 'PDF, JPG or PNG. Up to 3 files, 10 MB each.',
           'min-uploaded-documents': 1, 'max-uploaded-documents': 3, 'max-file-size-kb': 10240,
           'allowed-mime-types': ['application/pdf', 'image/jpeg', 'image/png']},
          footer('Submit documents', payload={'design_service': 'drop-docs', **refs(BASE),
                 **refs(['request_number', 'note', 'documents'], 'form')})]),
    text('TextCaption', 'Shared with our team for your request.')], schema(BASE), True)
drafts['drop-docs'] = document([choose('UPLOAD', 'Drop Docs', 'Choose the order these documents belong to.'), upload])

# Vault uses catalog selection, a native document list, payment and template delivery.
# Preserve the previously created draft as an unused design record; never route to it.

shipment_data = {**BASE, 'shipment_status': 'Preparing shipment · example',
                 'last_update': 'Your latest shipment update will appear here.',
                 'tracking_number': 'Available after dispatch'}
shipment_choose = choose('STATUS', 'Shipments', 'Choose an order to view its delivery progress.')
shipment_choose['layout']['children'][3]['children'][-1]['on-click-action']['payload'].update(
    {k:v for k,v in shipment_data.items() if k not in BASE})
status = screen('STATUS', 'Your shipment', [text('TextHeading', 'Follow your delivery'),
    text('TextCaption', 'Order'), text('TextBody', '${data.parent_order}'),
    text('TextSubheading', '${data.shipment_status}'), text('TextBody', '${data.last_update}'),
    text('TextCaption', 'Tracking reference'), text('TextBody', '${data.tracking_number}'),
    text('TextCaption', 'This draft shows an example status, not a live shipment.'),
    footer('Done', payload={'design_service': 'shipments', **refs(shipment_data)})], schema(shipment_data), True)
drafts['shipments'] = document([shipment_choose, status])
drafts['leave-review'] = copy.deepcopy(review)

for slug, content in drafts.items():
    (OUT / (slug + '.json')).write_text(json.dumps(content, indent=2) + '\n')
print('Built', len(drafts), 'branded design drafts.')
