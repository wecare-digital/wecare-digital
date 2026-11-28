"""OPS-1: the analytics provisioning script keeps a retention rule on both prefixes."""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[2]
       / "scripts/provision_whatsapp_operational_analytics.py").read_text()


def test_both_prefixes_get_the_400_day_rule():
    assert 'GATED_PREFIX = "secure/d/analytics/whatsapp/operational"' in SRC
    assert '"wecare-whatsapp-operational-analytics-gated-retention",GATED_PREFIX' in SRC
    assert '"wecare-whatsapp-operational-analytics-retention",PREFIX' in SRC
