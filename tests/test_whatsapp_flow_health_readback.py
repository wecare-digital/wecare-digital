"""Read-only Meta Flow endpoints must expose platform health for registry audits.

The operator-only bulk sync may register unrelated historic flows. The ordinary
GET endpoints give us per-Flow health without creating or republishing assets.
"""
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1]
          / "amplify/functions/messaging/whatsapp-business-api/handler.py").read_text()


def _section(start: str, end: str) -> str:
    return SOURCE.split(start, 1)[1].split(end, 1)[0]


def test_meta_flow_list_get_includes_health_and_validation():
    source = _section("def _list_flows(", "def _get_flow(")
    assert "health_status" in source
    assert "validation_errors" in source
    assert "json_version" in source
    assert "data_api_version" in source
    assert "_graph_api(f'{waba_id}/flows', params=params, waba_id=waba_id)" in source
    assert "method='POST'" not in source
    assert "method='DELETE'" not in source


def test_single_flow_get_includes_live_health_and_endpoint():
    source = _section("def _get_flow(", "def _create_flow(")
    assert "health_status" in source
    assert "validation_errors" in source
    assert "endpoint_uri" in source
    assert "'flow': result" in source
    assert "method='POST'" not in source
    assert "method='DELETE'" not in source


def test_existing_operator_sync_is_unchanged_and_preserves_registry_status():
    source = _section("def _sync_flows(", "def _" )
    assert "health_status" in source
    assert "'status': existing.get('status') or 'DRAFT'" in source
    assert "'metaStatus': str(f.get('status') or '')" in source
