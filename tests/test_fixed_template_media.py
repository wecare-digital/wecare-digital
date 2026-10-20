import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


def load_management():
    source = Path(__file__).resolve().parents[1] / 'amplify/functions/messaging/whatsapp-template-management/handler.py'
    spec = importlib.util.spec_from_file_location('fixed_media_management', source)
    module = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(module)
    return module


def test_saved_review_header_cannot_be_deleted_by_library():
    module = load_management()
    key = 'o/public/wa-tpl/img/wecare-digital-cebc83f1_img.png'
    with patch.object(module.s3, 'delete_object') as delete:
        assert module._delete_send_media({'s3Key': key})['statusCode'] == 409
        assert module._delete_send_media({'s3Key': f'https://wecare.digital/get/{key}'})['statusCode'] == 409
    delete.assert_not_called()


def test_media_library_classifies_image_under_public_root():
    module = load_management()
    with patch.object(module.s3, 'list_objects_v2', return_value={'Contents': [
        {'Key': 'o/public/wa-tpl/img/wecare-digital-cebc83f1_img.png', 'Size': 10}]}):
        response = module._list_send_media({})
    item = json.loads(response['body'])['items'][0]
    assert item['folder'] == 'img'
    assert item['category'] == 'image'
