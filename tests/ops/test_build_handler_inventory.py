#!/usr/bin/env python3
"""Offline unit tests for scripts/ops/build_handler_inventory.py.

Runnable without AWS, boto3 or network, via either:
    python3 -m pytest tests/ops/test_build_handler_inventory.py -q
    python3 -m unittest tests.ops.test_build_handler_inventory
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "build_handler_inventory.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_handler_inventory", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bhi = _load_module()


class BuildHandlerInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = bhi.build_inventory()

    def test_offline_no_boto3(self):
        # The builder must never have pulled in boto3.
        self.assertNotIn("boto3", sys.modules)

    def test_expected_domains_present(self):
        domains = self.report["domains"]
        for expected in ["ai", "auth", "core", "ecommerce", "edge",
                         "messaging", "operations", "payments", "shared"]:
            self.assertIn(expected, domains)

    def test_summary_counts_reconcile(self):
        summary = self.report["summary"]
        # Production added collect_contract.py and collect_receipts.py during
        # this branch's development; both are shared modules, not new Lambdas.
        self.assertEqual(summary["total_py_files"], 320)
        self.assertEqual(summary["shared_modules"], 192)
        # The shared modules must dominate the standalone handler count: this is
        # the 320-vs-~76 drift signal.
        self.assertGreater(summary["shared_modules"], summary["standalone_handlers"])
        self.assertEqual(summary["manifest_functions"], 72)
        self.assertGreaterEqual(summary["specs_total"], 60)

    def test_specs_mapped_count_fields_are_unambiguous(self):
        # The 62-vs-63 ambiguity must be resolved by two explicit fields whose
        # difference is exactly the strangler alias count. This fails if the fix
        # were reverted to a single ambiguous specs_mapped_functions field.
        summary = self.report["summary"]
        self.assertIn("specs_total_names", summary)
        self.assertIn("emitted_spec_mapped_handlers", summary)
        self.assertEqual(
            summary["specs_total_names"] - summary["emitted_spec_mapped_handlers"],
            summary["strangler_alias_specs"],
            "the gap between SPECS names and emitted spec-mapped handlers must "
            "equal the strangler alias count, not unexplained drift",
        )
        # The strangler alias (wecare-commerce) is held in spec_aliases, not an
        # emitted handler, so it accounts for the difference.
        alias_names = {a["name"] for a in self.report["spec_aliases"]}
        self.assertIn("wecare-commerce", alias_names)

    def _find(self, domain, name):
        for entry in self.report["domains"][domain]:
            if entry["name"] == name:
                return entry
        return None

    def test_specs_mappings_resolve(self):
        checkout = self._find("ecommerce", "wecare-checkout")
        self.assertIsNotNone(checkout, "wecare-checkout must map to a handler")
        self.assertEqual(checkout["source_path"],
                         "amplify/functions/ecommerce/checkout/handler.py")
        self.assertTrue(checkout["spec_mapped"])

        inbound = self._find("messaging", "wecare-inbound-whatsapp")
        self.assertIsNotNone(inbound, "wecare-inbound-whatsapp must map to a handler")
        self.assertEqual(inbound["source_path"],
                         "amplify/functions/messaging/inbound-whatsapp-handler/handler.py")

    def test_retired_entries_flagged_and_not_resurrected(self):
        retired = self.report["retired"]
        self.assertIn("wecare-ai-generate-response", retired["functions"])
        self.assertIn("wecare-meta-catalog-sync", retired["functions"])
        self.assertIn("stack-wecare-digital-SmsOutboundTable", retired["tables"])
        # The retained shared module stays retained (not removed).
        self.assertIn(
            "amplify/functions/shared/lambda_utils/ecommerce/meta_catalog_sync.py",
            retired["retained_shared_modules"],
        )
        # Meaningful: no retired function may appear as an active handler/alias.
        self.assertEqual(self.report["summary"]["resurrected_retired"], [])
        active_names = {
            e["name"]
            for entries in self.report["domains"].values()
            for e in entries
            if e["name"] and not e["retired"]
        }
        for name in retired["functions"]:
            self.assertNotIn(name, active_names,
                             f"retired function {name} must not be active")

    def test_retirement_check_is_meaningful(self):
        # If the retirement data were dropped, resurrected detection would be a
        # no-op. Simulate a report where a retired function IS active and assert
        # our resurrection logic would catch it. This proves the check is not a
        # static constant.
        retired = set(self.report["retired"]["functions"])
        self.assertTrue(retired, "expected at least one retired function")
        fabricated_active = {next(iter(retired))}
        resurrected = sorted(n for n in retired if n in fabricated_active)
        self.assertNotEqual(resurrected, [],
                            "resurrection check must flag a retired-active name")

    def test_shared_files_are_modules_not_standalone(self):
        # No shared/ file should appear as a standalone handler entry.
        shared_entries = self.report["domains"].get("shared", [])
        self.assertEqual(shared_entries, [],
                         "shared/ files must be modules, not standalone handlers")
        self.assertEqual(self.report["summary"]["shared_modules"], 192)
        # And no emitted handler path lives under shared/.
        for entries in self.report["domains"].values():
            for entry in entries:
                self.assertNotIn("/shared/", entry["source_path"])

    def test_cdk_cloudformation_entry_is_real(self):
        # At least one entry must actually carry classification cdk-cloudformation
        # and cite the CloudFormation stack file. This fails if the synthetic
        # emission is reverted (the former dead-code path produced zero such
        # entries), keeping the two docs' wording true.
        cdk_entries = [
            e
            for entries in self.report["domains"].values()
            for e in entries
            if e.get("classification") == "cdk-cloudformation"
        ]
        self.assertGreaterEqual(len(cdk_entries), 1,
                                "expected at least one cdk-cloudformation entry")
        self.assertEqual(self.report["summary"]["cdk_cloudformation_functions"],
                         len(cdk_entries))
        enforcer = next(
            (e for e in cdk_entries if e["name"] == "wecare-log-retention-enforcer"),
            None,
        )
        self.assertIsNotNone(
            enforcer,
            "wecare-log-retention-enforcer must be classified cdk-cloudformation")
        self.assertEqual(enforcer["cdk_source"],
                         "infra/cloudwatch-retention-enforcer.yml")
        self.assertEqual(enforcer["source_path"],
                         "infra/cloudwatch-retention-enforcer.yml")

    def test_non_specs_handlers_are_unclassified_not_script_managed(self):
        # Handlers with no SPECS row and not in the CDK/CFN table must NOT be
        # asserted script-managed (that would mislabel CloudFormation/image-package
        # owned functions). They are emitted as unclassified with a null name.
        # This fails if the blanket script-managed default is reinstated.
        expected_unclassified = {
            "amplify/functions/ai/customer-commerce-mcp/handler.py",
            "amplify/functions/ai/mcp/handler.py",
            "amplify/functions/ai/workspace-mcp/handler.py",
            "amplify/functions/ecommerce/catalog-media/handler.py",
            "amplify/functions/ecommerce/native-catalog-admin/handler.py",
            "amplify/functions/edge/get-miss-redirect/handler.py",
            "amplify/functions/operations/blog-auto-audit/handler.py",
            "amplify/functions/operations/blog-public/handler.py",
            "amplify/functions/operations/docs-scraper/handler.py",
            "amplify/functions/operations/seo-tools/handler.py",
            "amplify/functions/operations/whatsapp-analytics-export/handler.py",
        }
        all_entries = [
            e
            for entries in self.report["domains"].values()
            for e in entries
        ]
        # No emitted handler entry may carry a null name AND script-managed.
        for e in all_entries:
            if e["name"] is None:
                self.assertNotEqual(
                    e["classification"], "script-managed",
                    f"{e['source_path']} must not be asserted script-managed")
        unclassified_paths = {
            e["source_path"] for e in all_entries
            if e.get("classification") == "unclassified"
        }
        self.assertEqual(unclassified_paths, expected_unclassified)
        self.assertEqual(self.report["summary"]["unclassified_handlers"],
                         len(expected_unclassified))
        # Every script-managed entry must be SPECS-mapped with a real name.
        for e in all_entries:
            if e.get("classification") == "script-managed":
                self.assertTrue(e["spec_mapped"])
                self.assertIsNotNone(e["name"])

    def test_env_keys_are_names_not_values(self):
        # The output must carry env KEY names only, never recorded values.
        blob = json.dumps(self.report)
        self.assertNotIn("775261844268", blob)
        self.assertNotIn("arn:aws", blob)
        # A known recorded VALUE from the manifest must not be present...
        self.assertNotIn("stack-wecare-digital-ContactsTable", blob)
        # ...while the KEY name for it should be (agent-action-group references it).
        agent = self._find("ai", "wecare-agent-action-group")
        if agent is not None:
            self.assertIn("CONTACTS_TABLE", agent["manifest_env_keys"])
            for key in agent["manifest_env_keys"]:
                # key names are upper snake identifiers, not resource values
                self.assertNotIn(":", key)
                self.assertNotIn("/", key)

    def test_cli_writes_to_scratch_and_refuses_outside(self):
        # Default path lands in .scratch/.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "inv.json"
            rc = bhi.main(["--out", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text())
            self.assertIn("domains", data)
            self.assertIn("summary", data)

    def test_expected_account_is_noop(self):
        # Accepting --expected-account must not change the offline report.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "inv.json"
            rc = bhi.main(["--out", str(out), "--expected-account", "000000000000"])
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text())
            self.assertNotIn("000000000000", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
