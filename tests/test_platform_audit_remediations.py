"""Regression tests for the 2026-10-27 platform-audit remediations."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlatformAuditRemediationTests(unittest.TestCase):
    def test_amplify_caches_npm_downloads_not_node_modules(self) -> None:
        buildspec = (ROOT / "amplify.yml").read_text(encoding="utf-8")
        self.assertIn("npm ci --cache .npm --prefer-offline --no-audit --no-fund", buildspec)
        self.assertIn("- .npm/**/*", buildspec)
        self.assertNotIn("- node_modules/**/*", buildspec)

    def test_hashed_next_assets_are_immutable_cached(self) -> None:
        headers = (ROOT / "customHttp.yml").read_text(encoding="utf-8")
        marker = '- pattern: "/_next/static/**/*"'
        block = headers.split(marker, 1)[1]
        self.assertIn('value: "public, max-age=31536000, immutable"', block)

    def test_existing_seo_table_reconciles_pitr(self) -> None:
        source = (ROOT / "scripts" / "deploy_seo_tools.py").read_text(encoding="utf-8")
        ensure_table = source.split("def ensure_table() -> None:", 1)[1].split(
            "def ensure_bedrock_inference_profile_perms()", 1
        )[0]
        self.assertIn("describe_continuous_backups", ensure_table)
        self.assertIn("update_continuous_backups", ensure_table)
        self.assertIn("DeletionProtectionEnabled=True", ensure_table)
        self.assertNotIn("already exists — skipping create", ensure_table)


if __name__ == "__main__":
    unittest.main()
