import importlib.util
from pathlib import Path
from unittest.mock import Mock
import pytest

SPEC = importlib.util.spec_from_file_location('customer_log_retention', Path(__file__).resolve().parents[1] / 'scripts/configure_customer_log_retention.py')
module = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(module)
NOW = 2_000_000_000_000

def clients(arn=module.EXPECTED_ARN, age_days=5):
    sts = Mock(); sts.get_caller_identity.return_value = {'Account': module.ACCOUNT, 'Arn': arn}
    logs = Mock()
    logs.get_paginator.return_value.paginate.side_effect = lambda **kw: [{'logGroups': [{'logGroupName': kw['logGroupNamePrefix'], 'creationTime': NOW - age_days * 86400000}]}]
    return sts, logs

def test_dry_run_never_changes_logs():
    sts, logs = clients()
    result = module.execute(sts, logs, now_ms=NOW)
    assert all(row['status'] == 'READY' for row in result['plan'])
    logs.put_retention_policy.assert_not_called()

def test_root_cannot_apply():
    sts, logs = clients(f'arn:aws:iam::{module.ACCOUNT}:root')
    with pytest.raises(PermissionError): module.execute(sts, logs, apply=True, now_ms=NOW)
    logs.put_retention_policy.assert_not_called()

def test_old_history_blocks_all_writes():
    sts, logs = clients(age_days=31)
    with pytest.raises(ValueError): module.execute(sts, logs, apply=True, now_ms=NOW)
    logs.put_retention_policy.assert_not_called()

def test_apply_sets_only_exact_groups_and_verifies():
    sts, logs = clients()
    configured = set()
    logs.put_retention_policy.side_effect = lambda **kw: configured.add(kw['logGroupName'])
    logs.get_paginator.return_value.paginate.side_effect = lambda **kw: [{'logGroups': [{'logGroupName': kw['logGroupNamePrefix'], 'creationTime': NOW-86400000, **({'retentionInDays': 30} if kw['logGroupNamePrefix'] in configured else {})}]}]
    result = module.execute(sts, logs, apply=True, now_ms=NOW)
    assert result['applied'] == list(module.GROUPS)
    assert logs.put_retention_policy.call_count == 2
