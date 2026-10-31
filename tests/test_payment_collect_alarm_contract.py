"""Offline regression that critical payment APIs stay in the human-paged alarm set.

Only parses repo source; never calls AWS, Razorpay, Meta, or a customer API.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALARMS = ROOT / "scripts/provision_lambda_alarms.py"
RECONCILE = ROOT / "scripts/reconcile_invoice_sequence.py"


def _always():
    module = ast.parse(ALARMS.read_text(encoding="utf-8"))
    declaration = next(
        node.value for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ALWAYS"
                for target in node.targets)
    )
    return ast.literal_eval(declaration)


def test_payment_money_paths_are_always_alarmed_at_any_volume():
    always = _always()
    expected = {
        "wecare-commerce",
        "wecare-razorpay-webhook",
        "wecare-outbound-whatsapp",
        "wecare-payments-read",
        "wecare-customer-invoice",
    }
    assert expected <= set(always), sorted(expected - set(always))
    for name in expected:
        assert "payment" in always[name].lower() or any(
            token in always[name].lower()
            for token in ("invoice", "ledger", "paid", "collection", "receipt", "send")
        )


def test_error_alarms_notify_confirmed_humans_and_quiet_functions_do_not_page():
    source = ALARMS.read_text(encoding="utf-8")
    assert 'TreatMissingData="notBreaching"' in source
    assert "assert_topic_reaches_a_human(sns)" in source
    assert "AlarmActions=[ALARM_TOPIC], OKActions=[ALARM_TOPIC]" in source
    assert "if name in ALWAYS:" in source


def test_invoice_reconciliation_remains_forward_only_and_report_only_by_default():
    source = RECONCILE.read_text(encoding="utf-8")
    parsed = ast.parse(source)
    apply_flags = [
        node for node in ast.walk(parsed)
        if isinstance(node, ast.Call) and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "--apply"
        and any(kw.arg == "action" and isinstance(kw.value, ast.Constant)
                and kw.value.value == "store_true" for kw in node.keywords)
    ]
    assert len(apply_flags) == 1, "Only an explicit --apply flag may write the counter"
    assert 'ConditionExpression="attribute_not_exists(last_seq) OR last_seq < :floor"' in source
    assert 'if not args.apply:' in source
