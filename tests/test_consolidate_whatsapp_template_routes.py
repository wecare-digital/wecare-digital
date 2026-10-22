from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/consolidate_whatsapp_template_routes.py"


def test_template_route_migration_is_dry_run_by_default_and_keeps_deletion_separate():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'parser.add_argument("--apply", action="store_true")' in source
    assert "if not args.apply" in source
    assert "delete_function" not in source.lower()
    assert 'OLD_FUNCTION = "wecare-whatsapp-templates"' in source
    assert 'NEW_FUNCTION = "wecare-whatsapp-template-management"' in source


def test_template_route_migration_requires_live_alias_to_match_latest_code():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'get_alias(FunctionName=NEW_FUNCTION, Name="live")' in source
    assert 'served["CodeSha256"] != latest["CodeSha256"]' in source
    assert "route migration incomplete" in source
