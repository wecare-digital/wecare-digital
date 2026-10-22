from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify' / 'functions' / 'shared'))

from lambda_utils import template_status


def test_template_status_vocabulary_is_fail_closed():
    assert template_status.canonical('APPROVED') == template_status.APPROVED
    assert template_status.is_sendable('APPROVED') is True
    for raw in ('PENDING', 'IN_APPEAL'):
        assert template_status.canonical(raw) == template_status.PENDING
        assert template_status.is_sendable(raw) is False
    for raw in ('REJECTED', 'PAUSED', 'DISABLED', 'FLAGGED', 'PENDING_DELETION'):
        assert template_status.canonical(raw) == template_status.BLOCKED
        assert template_status.is_sendable(raw) is False
    for raw in ('', None, 'SOMETHING_NEW_FROM_META'):
        assert template_status.canonical(raw) == template_status.UNKNOWN
        assert template_status.is_sendable(raw) is False


def test_server_side_template_gates_use_shared_status_helper():
    files = [
        ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/customer_invoice.py',
        ROOT / 'amplify/functions/messaging/outbound-whatsapp/handler.py',
        ROOT / 'amplify/functions/shared/lambda_utils/ecommerce/catalog_service_checkout.py',
        ROOT / 'amplify/functions/shared/lambda_utils/payment_readiness.py',
    ]
    for path in files:
        source = path.read_text(encoding='utf-8')
        assert 'template_status.is_sendable' in source


def test_template_management_exposes_raw_and_canonical_status():
    source = (ROOT / 'amplify/functions/messaging/whatsapp-template-management/handler.py').read_text(
        encoding='utf-8')
    assert "'templateStatus':" in source
    assert "'templateState': template_status.canonical" in source
    assert "'sendable': template_status.is_sendable" in source
