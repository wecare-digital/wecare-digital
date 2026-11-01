"""Regression checks for the Meta -> AWS WhatsApp template/Flow mapping snapshot.

No AWS account or Meta network access is used by these tests.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/template_flow_sync.py"
spec = importlib.util.spec_from_file_location("test_target_template_flow_sync", MODULE)
sync = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(sync)

FLOW_IDS = (
    "2413873616105042",  # Subscribe / Profile
    "993862443003108",  # Leave Review
    "39581903361452878",  # Drop Docs (retain exact string ID)
    "993516553092471",  # Submit Request
    "2408621596338289",  # Request Amendment
    "2988393421499259",  # Pickup Request
    "1804165164183485",  # Track Shipment
    "1933489271340286",  # F008 Referral
)
TEMPLATE_LINKS = (
    ("1428669922724280", "wecare_pdf_direct_download", FLOW_IDS[0]),
    ("2419125382263851", "service_details", FLOW_IDS[0]),
    ("1782246473079550", "wecare_default_invoice_image_template", FLOW_IDS[1]),
    ("1801972550682516", "wecare_leave_review", FLOW_IDS[1]),
    ("1041974032198332", "_dropdoc_flow", FLOW_IDS[2]),
    ("30181571061431980", "submit_request_flow", FLOW_IDS[3]),
    ("4034771700165582", "request_amendment_flow", FLOW_IDS[4]),
    ("1449099850671553", "pickup_request_flow", FLOW_IDS[5]),
    ("1107523855531222", "track_ship_flow", FLOW_IDS[6]),
    ("1596216325046969", "wecare_referal_update", FLOW_IDS[7]),
)


def data():
    flows = [
        {
            "id": flow_id,
            "name": "test-flow-" + str(index),
            "status": "PUBLISHED",
            "validation_errors": [],
            "health_status": {"can_send_message": "AVAILABLE"},
        }
        for index, flow_id in enumerate(FLOW_IDS)
    ]
    templates = [
        {
            "id": template_id,
            "name": name,
            "status": "APPROVED",
            "category": "UTILITY",
            "language": "en",
            "components": [
                {
                    "type": "BUTTONS",
                    "buttons": [
                        {
                            "type": "FLOW",
                            "text": "Update Referral" if flow_id == FLOW_IDS[7] else "Continue",
                            "flow_id": flow_id,
                            "flow_action": "DATA_EXCHANGE",
                        }
                    ],
                }
            ],
        }
        for template_id, name, flow_id in TEMPLATE_LINKS
    ]
    return flows, templates


def graph_get(flows, templates):
    def get(edge, params):
        if edge.endswith("/flows"):
            return {"data": flows}
        if edge.endswith("/message_templates"):
            return {"data": templates}
        raise AssertionError("Unexpected Meta edge " + edge)
    return get


class TemplateFlowEightFlowTests(unittest.TestCase):
    def test_all_eight_canonical_flows_and_ten_buttons_map(self):
        flows, templates = data()
        links, counts = sync.snapshot(
            graph_get(flows, templates), "2094615664435155",
            lambda flow_id: flow_id in FLOW_IDS,
        )
        self.assertEqual(counts, {"templateCount": 10, "retainedFlowCount": 8})
        self.assertEqual(len(links), 10)
        self.assertIn((FLOW_IDS[7], "1596216325046969"), links)
        self.assertEqual(links[(FLOW_IDS[7], "1596216325046969")]["templateCategory"], "UTILITY")
        self.assertEqual(links[(FLOW_IDS[7], "1596216325046969")]["buttonLabel"], "Update Referral")
        self.assertIn((FLOW_IDS[2], "1041974032198332"), links)

    def test_missing_one_retained_flow_fails_closed(self):
        flows, templates = data()
        with self.assertRaisesRegex(ValueError, "Retained Meta Flow inventory changed"):
            sync.snapshot(graph_get(flows[:-1], templates), "2094615664435155",
                          lambda flow_id: flow_id in FLOW_IDS)

    def test_non_sendable_flow_fails_closed(self):
        flows, templates = data()
        flows[-1]["health_status"]["can_send_message"] = "BLOCKED"
        with self.assertRaisesRegex(ValueError, "health/status is not AVAILABLE"):
            sync.snapshot(graph_get(flows, templates), "2094615664435155",
                          lambda flow_id: flow_id in FLOW_IDS)

    def test_unknown_flow_button_fails_closed(self):
        flows, templates = data()
        templates[-1]["components"][0]["buttons"][0]["flow_id"] = "123456789012345"
        with self.assertRaisesRegex(ValueError, "unregistered Meta Flow"):
            sync.snapshot(graph_get(flows, templates), "2094615664435155",
                          lambda flow_id: flow_id in FLOW_IDS)


if __name__ == "__main__":
    unittest.main()
