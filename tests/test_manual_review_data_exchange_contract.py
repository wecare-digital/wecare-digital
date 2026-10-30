"""Ensure both approved F002 templates open FEEDBACK through DATA_EXCHANGE."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_manual_review_template_has_routable_flow_key():
    outbound = (ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py").read_text()
    assert "'wecare_leave_review': 'leave'" in outbound
    assert "_infer_flow_key_from_template(template_name) or 'flow'" in outbound


def test_invoice_and_manual_review_init_use_no_private_customer_data():
    router = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/router.py").read_text()
    assert "if flow_token and flow_token.startswith('review-'):" in router
    assert "review_token.is_review_token(flow_token)" in router
    manual = router.split("if flow_key.startswith('leave'):", 1)[1].split("\n    # ── ORDER NOTES", 1)[0]
    assert "if action == 'INIT':" in manual
    assert "return {'screen': 'FEEDBACK', 'data': {}}" in manual
    assert "return {'data': {'error':" in manual
    flow = json.loads((ROOT / "amplify/functions/messaging/whatsapp-business-api"
                      / "flows/published/f002-leave-review.json").read_text())
    assert flow["screens"][0]["id"] == "FEEDBACK"
    assert not flow["screens"][0].get("data")
