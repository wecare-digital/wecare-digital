"""Safety contract for the scoped, commit-pinned Vault payment Lambda releaser.

No AWS API calls, file uploads, customer messages or payments.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy_vault_workspace_release.py"


def allowed_names():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for assigned in node.targets:
                if isinstance(assigned, ast.Name) and assigned.id in (
                        "RELEASE_ORDER", "ALLOWED_EXTRA_FUNCTIONS"):
                    values[assigned.id] = ast.literal_eval(node.value)
    return values


class ReleaseScopeTests(unittest.TestCase):
    def test_explicit_vault_and_native_payment_allowlist(self):
        names = allowed_names()
        all_names = set(names["RELEASE_ORDER"]) | set(
            names["ALLOWED_EXTRA_FUNCTIONS"])
        required = {"wecare-checkout", "wecare-commerce",
                    "wecare-secure-files", "wecare-service-requests",
                    "wecare-whatsapp-business-api"}
        self.assertTrue(required.issubset(all_names))
        self.assertNotIn("wecare-meta-catalog-sync", all_names)
        self.assertNotIn("wecare-invoice-engine", all_names)
        self.assertEqual(len(names["RELEASE_ORDER"]), len(set(names["RELEASE_ORDER"])))
        self.assertEqual(len(names["ALLOWED_EXTRA_FUNCTIONS"]),
                         len(set(names["ALLOWED_EXTRA_FUNCTIONS"])))

    def test_source_is_pinned_and_alias_rollback_is_encoded(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"SOURCE_COMMIT"', source)
        self.assertIn('r"[0-9a-f]{40}"', source)
        self.assertIn('RevisionId=latest["RevisionId"]', source)
        self.assertIn('RevisionId=alias["RevisionId"]', source)
        self.assertIn('CodeSha256', source)
        self.assertIn('for entry in reversed(promoted)', source)
        self.assertIn('"phase": "rolled-back"', source)

    def test_no_config_or_flag_mutations(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("update_function_configuration(", source)
        self.assertNotIn("put_parameter(", source)
        self.assertNotIn("put_secret_value(", source)
        self.assertNotIn("put_item(", source)
        self.assertNotIn("STAFF_CONTRIBUTE_NATIVE_SEND_ENABLED", source)
        self.assertNotIn("CONTRIBUTE_TAXABLE_NATIVE_PAYMENT_ENABLED", source)

    def test_dry_run_stops_before_any_deployment(self):
        source = SCRIPT.read_text(encoding="utf-8")
        dry = source.index("    if dry_run:")
        mutation = source.index("client.update_function_code(")
        self.assertLess(dry, mutation)
        self.assertIn("        return", source[dry:mutation])


if __name__ == "__main__":
    unittest.main()
