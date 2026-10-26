import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("env_manifest", ROOT / "scripts" / "env_manifest.py")
env_manifest = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(env_manifest)


class AliasEnvironmentAuditTests(unittest.TestCase):
    def test_tracks_both_catalog_alias_identities(self):
        lam = Mock()

        def cfg(*, FunctionName, Qualifier):
            self.assertEqual(FunctionName, "wecare-meta-catalog-sync")
            rows = {
                "live": {
                    "META_CATALOG_ID": "1457045652952851",
                    "META_TOKEN_FIELD": "access_token",
                    "IGNORED": "not recorded",
                },
                "waba2": {
                    "META_CATALOG_ID": "1317472650427643",
                    "META_TOKEN_FIELD": "access_token_waba2",
                },
            }
            return {"Environment": {"Variables": rows[Qualifier]}}

        lam.get_function_configuration.side_effect = cfg
        self.assertEqual(
            env_manifest.live_alias_env(lam),
            {
                "wecare-meta-catalog-sync:live": {
                    "META_CATALOG_ID": "1457045652952851",
                    "META_TOKEN_FIELD": "access_token",
                },
                "wecare-meta-catalog-sync:waba2": {
                    "META_CATALOG_ID": "1317472650427643",
                    "META_TOKEN_FIELD": "access_token_waba2",
                },
            },
        )

    def test_manifest_contains_current_catalog_alias_contract(self):
        doc = __import__("json").loads((ROOT / "config" / "lambda-env-manifest.json").read_text())
        self.assertEqual(
            doc["aliases"]["wecare-meta-catalog-sync:live"]["META_CATALOG_ID"],
            "1457045652952851",
        )
        self.assertEqual(
            doc["aliases"]["wecare-meta-catalog-sync:waba2"]["META_CATALOG_ID"],
            "1317472650427643",
        )


if __name__ == "__main__":
    unittest.main()
