from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/retire_whatsapp_templates_lambda.py"


def test_retirement_is_dry_run_by_default_and_checks_all_reachability():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'parser.add_argument("--apply", action="store_true")' in source
    assert "if not args.apply" in source
    assert "get_routes" in source
    assert "list_event_source_mappings" in source
    assert "get_function_url_config" in source
    assert "delete_function" in source
    assert source.index("problems = blockers") < source.index("delete_function")


def test_retirement_verifies_absence_after_delete():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'lam.get_function(FunctionName=OLD_FUNCTION)' in source
    assert "delete returned but function still exists" in source
