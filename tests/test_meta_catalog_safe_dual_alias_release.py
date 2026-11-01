"""Code-only Meta catalog guard release: alias isolation and no catalog writes.

These tests execute the production release preflight function with dictionaries.
No AWS calls, Meta tokens, catalog operations, or payments.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts/deploy_meta_catalog_safe_release.py"


def reader():
    tree = ast.parse(RELEASE.read_text(encoding="utf-8"))
    selected = []
    env = {"frozenset": frozenset}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in (
                    "FUNCTION", "TARGETS", "TARGET_SELECTORS", "SAFETY_FLAGS")
                for target in node.targets):
            selected.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "fail_if_unsafe":
            selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]),
                 str(RELEASE), "exec"), env)
    return env


def sample():
    common = {
        "META_CATALOG_AUTO_APPLY_SAFE": "false",
        "META_CATALOG_SYNC_ENABLED": "true",
        "META_CATALOG_SYNC_DRY_RUN": "false",
        "PRODUCTS_TABLE": "canonical",
        "META_TOKEN_SECRET": "secret-reference-only",
    }
    w1 = {**common, "META_CATALOG_ID": "1457045652952851",
          "META_TOKEN_FIELD": "access_token"}
    w2 = {**common, "META_CATALOG_ID": "1317472650427643",
          "META_TOKEN_FIELD": "access_token_waba2"}
    aliases = {
        "live": ({"FunctionVersion": "120"}, {"Environment": {"Variables": w1}}),
        "waba2": ({"FunctionVersion": "108"}, {"Environment": {"Variables": w2}}),
    }
    latest = {"Environment": {"Variables": dict(w2)}}
    return aliases, latest


class MetaCatalogSafeReleaseTests(unittest.TestCase):
    def test_only_the_intended_meta_function_and_aliases(self):
        env = reader()
        self.assertEqual(env["FUNCTION"], "wecare-meta-catalog-sync")
        self.assertEqual(tuple(a[0] for a in env["TARGETS"]), ("live", "waba2"))
        self.assertEqual(env["TARGET_SELECTORS"],
                         frozenset({"META_CATALOG_ID", "META_TOKEN_FIELD"}))

    def test_preflight_preserves_both_catalogs_and_unqualified_waba2(self):
        env = reader()
        aliases, latest = sample()
        versions, waba2_config = env["fail_if_unsafe"](aliases, latest)
        self.assertEqual(versions, {"live": "120", "waba2": "108"})
        self.assertEqual(waba2_config["META_CATALOG_ID"], "1317472650427643")
        self.assertEqual(waba2_config["META_TOKEN_FIELD"], "access_token_waba2")

    def test_refuses_catalog_autoapply_even_if_enabled_on_one_alias(self):
        aliases, latest = sample()
        aliases["live"][1]["Environment"]["Variables"]["META_CATALOG_AUTO_APPLY_SAFE"] = "true"
        with self.assertRaises(RuntimeError):
            reader()["fail_if_unsafe"](aliases, latest)

    def test_refuses_ever_changing_waba_identity(self):
        aliases, latest = sample()
        aliases["waba2"][1]["Environment"]["Variables"]["META_TOKEN_FIELD"] = "access_token"
        with self.assertRaises(RuntimeError):
            reader()["fail_if_unsafe"](aliases, latest)

    def test_refuses_other_environment_drift(self):
        aliases, latest = sample()
        aliases["waba2"][1]["Environment"]["Variables"]["PRODUCTS_TABLE"] = "different"
        with self.assertRaises(RuntimeError):
            reader()["fail_if_unsafe"](aliases, latest)

    def test_refuses_latest_pointing_to_waba1(self):
        aliases, latest = sample()
        latest = {"Environment": {"Variables": aliases["live"][1]["Environment"]["Variables"]}}
        with self.assertRaises(RuntimeError):
            reader()["fail_if_unsafe"](aliases, latest)

    def test_refuses_weighted_routing(self):
        aliases, latest = sample()
        aliases["live"][0]["RoutingConfig"] = {"AdditionalVersionWeights": {"119": 0.5}}
        with self.assertRaises(RuntimeError):
            reader()["fail_if_unsafe"](aliases, latest)

    def test_release_is_lambda_code_only_not_meta_product_updates(self):
        source = RELEASE.read_text(encoding="utf-8")
        self.assertIn("lam.update_function_code(", source)
        self.assertIn("lam.publish_version(", source)
        self.assertIn("lam.update_alias(", source)
        self.assertIn("for name, released in reversed(promoted)", source)
        self.assertIn("RevisionId=alias[", source)
        self.assertIn('"catalogWrites": False', source)
        self.assertNotIn("https://graph.facebook.com", source)
        self.assertNotIn("put_item(", source)
        self.assertNotIn("delete_item(", source)
        self.assertNotIn("secretsmanager", source)
        self.assertNotIn("meta_catalog_sync.apply(", source)

    def test_dry_run_returns_before_update(self):
        source = RELEASE.read_text(encoding="utf-8")
        self.assertLess(source.index("    if dry_run:"),
                        source.index("lam.update_function_code("))


if __name__ == "__main__":
    unittest.main()
