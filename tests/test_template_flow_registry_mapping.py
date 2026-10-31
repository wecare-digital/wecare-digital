"""Read-only Flow Registry template mapping contract.

Tests only the isolated handler function with fake DynamoDB scans: no Meta calls,
payment, messages, customer records or AWS writes are permitted.
"""
from __future__ import annotations

import ast
import copy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Dict
import unittest

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
REGISTRY = "stack-wecare-digital-FlowRegistryTable"
MAPPINGS = "stack-wecare-digital-WhatsAppTemplateFlowMappingTable"


def isolated_registry_function(flows, mapping_rows, *, complete=True, mapping_error=False):
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "_list_flow_registry")
    scans = []

    def drain(table, operation):
        assert operation == "scan"
        scans.append(table)
        if table == REGISTRY:
            return copy.deepcopy(flows), True
        if table == MAPPINGS:
            if mapping_error:
                raise RuntimeError("injected AWS failure")
            return copy.deepcopy(mapping_rows), complete
        raise AssertionError("Unexpected table: " + str(table))

    scope = {
        "__builtins__": __builtins__,
        "Dict": Dict,
        "Decimal": Decimal,
        "FLOW_REGISTRY_TABLE": REGISTRY,
        "TEMPLATE_FLOW_MAPPING_TABLE": MAPPINGS,
        "dynamodb": SimpleNamespace(Table=lambda name: name),
        "_drain": drain,
        "_resp": lambda status, body: {"statusCode": status, "body": body},
        "logger": SimpleNamespace(error=lambda _msg: None),
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(HANDLER), "exec"), scope)
    return scope["_list_flow_registry"], scans


class TemplateFlowRegistryMappingTests(unittest.TestCase):
    def setUp(self):
        self.subscribe_id = "2413873616105042"
        self.docs_id = "39581903361452878"
        self.flows = [
            {"flowId": self.subscribe_id, "flowCode": "F001", "updatedAt": Decimal("1793448123")},
            {"flowId": self.docs_id, "flowCode": "F003"},
        ]
        self.mapping_rows = [
            {"flowId": self.subscribe_id, "templateId": "2419125382263851",
             "templateName": "service_details", "buttonLabel": "View Details",
             "flowButtonAction": "DATA_EXCHANGE", "metaTemplateStatus": "APPROVED",
             "lastVerifiedAt": Decimal("1793448123")},
            {"flowId": self.subscribe_id, "templateId": "1428669922724280",
             "templateName": "wecare_pdf_direct_download", "buttonLabel": "Subscribe",
             "flowButtonAction": "DATA_EXCHANGE", "metaTemplateStatus": "APPROVED"},
            {"flowId": self.docs_id, "templateId": "1041974032198332",
             "templateName": "_dropdoc_flow", "buttonLabel": "Drop Docs",
             "flowButtonAction": "DATA_EXCHANGE", "metaTemplateStatus": "APPROVED"},
        ]

    def test_default_read_does_not_touch_new_mapping_table(self):
        handler, scans = isolated_registry_function(self.flows, self.mapping_rows)
        result = handler({})
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(scans, [REGISTRY])
        self.assertEqual(result["body"]["count"], 2)
        self.assertNotIn("templateFlowMappings", result["body"]["flows"][0])

    def test_opt_in_returns_both_subscribe_templates_and_exact_ids(self):
        handler, scans = isolated_registry_function(self.flows, self.mapping_rows)
        result = handler({"includeTemplateMappings": "true"})
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(scans, [REGISTRY, MAPPINGS])
        by_flow = {f["flowId"]: f for f in result["body"]["flows"]}
        subscribe = by_flow[self.subscribe_id]["templateFlowMappings"]
        self.assertEqual([x["templateName"] for x in subscribe],
                         ["service_details", "wecare_pdf_direct_download"])
        self.assertEqual(subscribe[0]["flowId"], self.subscribe_id)
        self.assertEqual(subscribe[0]["templateId"], "2419125382263851")
        self.assertEqual(subscribe[0]["lastVerifiedAt"], 1793448123)
        docs = by_flow[self.docs_id]["templateFlowMappings"]
        self.assertEqual(docs[0]["flowId"], self.docs_id)
        self.assertEqual(docs[0]["templateId"], "1041974032198332")

    def test_mapping_scan_incomplete_fails_closed(self):
        handler, _ = isolated_registry_function(self.flows, self.mapping_rows, complete=False)
        result = handler({"includeTemplateMappings": "1"})
        self.assertEqual(result["statusCode"], 503)
        self.assertIn("incomplete", result["body"]["error"])

    def test_orphan_flow_fails_closed(self):
        invalid = self.mapping_rows + [{"flowId": "111111", "templateId": "555555"}]
        handler, _ = isolated_registry_function(self.flows, invalid)
        result = handler({"includeTemplateMappings": "true"})
        self.assertEqual(result["statusCode"], 503)

    def test_template_linked_to_two_flows_fails_closed(self):
        invalid = self.mapping_rows + [{"flowId": self.docs_id,
                                       "templateId": "2419125382263851"}]
        handler, _ = isolated_registry_function(self.flows, invalid)
        result = handler({"includeTemplateMappings": "true"})
        self.assertEqual(result["statusCode"], 503)

    def test_mapping_read_failure_does_not_fake_empty_links(self):
        handler, _ = isolated_registry_function(self.flows, self.mapping_rows,
                                                mapping_error=True)
        result = handler({"includeTemplateMappings": "true"})
        self.assertEqual(result["statusCode"], 500)
        self.assertEqual(result["body"]["error"], "List flow registry failed")


if __name__ == "__main__":
    unittest.main()
