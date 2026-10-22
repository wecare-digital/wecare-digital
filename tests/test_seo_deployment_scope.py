"""Deployment scope follows the actual SEO archive, including full push ranges."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock
import pytest

spec = importlib.util.spec_from_file_location('seo_scope',
    Path(__file__).resolve().parents[1] / 'scripts/seo_deployment_scope.py')
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


@pytest.mark.parametrize('path,expected', [
    ('amplify/functions/shared/lambda_utils/ecommerce/vault_access.py', False),
    ('docs/whatsapp/service-rollout/live-evidence.json', False),
    ('.github/workflows/seo-tools-deploy.yml', False),
    ('tests/test_seo_deployment_scope.py', False),
    ('amplify/functions/shared/lambda_utils/middleware.py', True),
    ('amplify/functions/shared/static_knowledge_base.py', True),
    ('amplify/functions/seo_tools_handler.py', True),
    ('amplify/functions/operations/seo-tools/handler.py', True),
    ('amplify/functions/operations/seo-tools/nested/unused.py', False),
])
def test_scope_matches_packaged_members(path, expected):
    assert scope.packaged_source(path) == expected


def test_scope_compares_entire_push_not_only_last_commit(monkeypatch, capsys):
    command = Mock(return_value='docs/report.md\0amplify/functions/shared/lambda_utils/response.py\0')
    monkeypatch.setattr(scope.subprocess, 'check_output', command)
    base, head = 'a' * 40, 'b' * 40
    scope.main(base, head)
    command.assert_called_once_with(['git', 'diff', '--name-only', '-z', base, head], text=True)
    assert capsys.readouterr().out == 'deploy=true\n'


@pytest.mark.parametrize('base,head', [('0'*40,'b'*40),('--unsafe','b'*40)])
def test_unknown_range_refuses_automatic_deployment(base, head):
    with pytest.raises(ValueError):
        scope.main(base, head)
