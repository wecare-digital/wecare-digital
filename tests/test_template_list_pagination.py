import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


def test_template_listing_follows_all_provider_pages():
    source = Path(__file__).resolve().parents[1] / 'amplify/functions/messaging/whatsapp-template-management/handler.py'
    spec = importlib.util.spec_from_file_location('paginated_template_handler', source)
    module = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(module)
    row = lambda ident, name: {'id': ident, 'name': name, 'status': 'APPROVED', 'language': 'en'}
    with patch.object(module, '_resolve_meta_waba_id', return_value='2094615664435155'), patch.object(
        module, '_meta_request', side_effect=[
            {'data': [row('1', 'wecare_otp')], 'paging': {'next': 'https://graph.facebook.com/v25.0/next'}},
            {'data': [row('2', 'wecare_whatapp_native_pay_template')]}]) as graph:
        response = module._list_templates('2094615664435155', {})
    assert response['statusCode'] == 200
    assert graph.call_count == 2
    assert [t['name'] for t in json.loads(response['body'])['templates']] == [
        'wecare_otp', 'wecare_whatapp_native_pay_template']


def test_listing_supplies_fixed_review_header():
    source = Path(__file__).resolve().parents[1] / 'amplify/functions/messaging/whatsapp-template-management/handler.py'
    spec = importlib.util.spec_from_file_location('fixed_header_template_handler', source)
    module = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(module)
    with patch.object(module, '_resolve_meta_waba_id', return_value='2094615664435155'), patch.object(
        module, '_meta_request', return_value={'data': [{'name': 'wecare_leave_review'}]}):
        response = module._list_templates('2094615664435155', {})
    assert json.loads(response['body'])['templates'][0]['fixedHeaderMedia'] == (
        'https://wecare.digital/get/o/public/wa-tpl/img/wecare-digital-cebc83f1_img.png')
