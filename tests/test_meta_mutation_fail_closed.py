from __future__ import annotations

from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify' / 'functions' / 'shared'))

from lambda_utils.meta_result import mutation_succeeded


def test_meta_mutation_unknown_shape_fails_closed():
    assert mutation_succeeded({}) is False
    assert mutation_succeeded({'id': '123'}) is False
    assert mutation_succeeded([]) is False


def test_meta_mutation_explicit_success_and_failure_are_respected():
    assert mutation_succeeded({'success': True}) is True
    assert mutation_succeeded({'success': False}) is False
    assert mutation_succeeded({'error': {'message': 'bad'}}) is False


def test_meta_mutation_can_require_named_positive_evidence():
    assert mutation_succeeded({'id': '123'}, evidence_keys=('id',)) is True
    assert mutation_succeeded({'id': ''}, evidence_keys=('id',)) is False


def test_whatsapp_handlers_do_not_default_missing_success_to_true():
    files = [
        ROOT / 'amplify/functions/messaging/partner-onboarding/handler.py',
        ROOT / 'amplify/functions/messaging/whatsapp-business-api/handler.py',
    ]
    for path in files:
        source = path.read_text(encoding='utf-8')
        assert "get('success', True)" not in source
        assert 'mutation_succeeded' in source
