"""Runtime regression: the seven published Meta Flows must be Python dict entries.

A source-text audit is insufficient: literal backslash-n sequences embedded in a
comment once hid Submit Request and Request Amendment without deleting their text.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils import canonical_flows  # noqa: E402

EXPECTED = (
    "subscribe",
    "leave_review",
    "drop_docs",
    "submit_request",
    "amend_request",
    "request_pickup",
    "shipments",
)


def test_all_seven_are_actual_published_runtime_entries():
    rows = []
    for capability in EXPECTED:
        flow = canonical_flows.published_flow(capability)
        assert flow is not None, f"{capability} missing from live Python dict"
        assert flow["status"] == "PUBLISHED"
        assert flow["flowId"] and flow["flowId"].isascii() and flow["flowId"].isdigit()
        assert canonical_flows.published_flow_by_id(flow["flowId"]) == flow
        rows.append(flow["flowId"])
    assert len(rows) == len(set(rows)) == 7


def test_retain_filter_works_for_all_seven_without_exposing_drafts():
    for capability in EXPECTED:
        flow_id = canonical_flows.canonical_flow_id(capability)
        assert canonical_flows.published_flow_by_id(flow_id)
    assert canonical_flows.published_flow_by_id("not-a-flow") is None
    assert canonical_flows.published_flow("orders") is None
    assert canonical_flows.published_flow("vault") is None
