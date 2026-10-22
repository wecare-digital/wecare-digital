from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
EMBEDDED = ROOT / "amplify/functions/ecommerce/checkout/invoice_engine.py"
CHECKOUT = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
DEPLOY = ROOT / "scripts/deploy_all_lambdas.py"


def test_embedded_invoice_engine_matches_existing_engine_during_strangler():
    """Until old routes/callers are retired there must be one exact invoice implementation."""
    assert EMBEDDED.read_bytes() == OLD.read_bytes()


def test_checkout_delegates_only_invoice_paths_to_embedded_engine():
    source = CHECKOUT.read_text(encoding="utf-8")
    block = source.split("def handler(", 1)[1].split("if event.get('internalAction')", 1)[0]
    assert 'commerce_path.startswith("/invoices")' in block
    assert "import invoice_engine as commerce_invoice_engine" in block
    assert "commerce_invoice_engine.handler(event, context)" in block


def test_checkout_package_contains_invoice_engine_module():
    source = DEPLOY.read_text(encoding="utf-8")
    checkout = source.split('"wecare-checkout"', 1)[1].split("),", 1)[0]
    assert 'extra_files=["invoice_engine.py"]' in checkout
