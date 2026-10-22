from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/consolidate_invoice_routes_to_checkout.py"


def test_invoice_route_cutover_is_dry_run_by_default():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'parser.add_argument("--apply", action="store_true")' in source
    assert "if not args.apply" in source
    assert "delete_function" not in source.lower()


def test_cutover_proves_deployed_checkout_contains_complete_invoice_runtime():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'get_alias(FunctionName=NEW_FUNCTION, Name="live")' in source
    assert "get_function(" in source
    assert '"invoice_engine.py"' in source
    assert '"receipt_layout.py"' in source
    assert '"fonts/DotGothic16-Regular.ttf"' in source
    assert "_live_has_pillow_layer(lam)" in source


def test_cutover_requires_live_invoice_iam_before_routes():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'PolicyName=POLICY_NAME' in source
    assert "REQUIRED_SIDS - sids" in source
    assert source.index("_role_has_invoice_authority(iam)") < source.index("changes, target_id, count = plan(api)")


def test_cutover_verifies_route_readback():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "remaining, _, _ = plan(api)" in source
    assert "invoice route migration incomplete" in source


def test_cutover_grants_invoice_route_permissions_before_moving_routes():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "_ensure_route_permissions(lam" in source
    permission = source.index("_ensure_route_permissions(lam, [row")
    update = source.index("api.update_route(")
    assert permission < update
    assert "SourceArn=_route_source_arn(route_key)" in source
