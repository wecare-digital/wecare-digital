"""Regression tests for workspace MCP DynamoDB protection."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceMcpDynamoProtectionTests(unittest.TestCase):
    def test_cloudformation_declares_deletion_protection(self) -> None:
        template = json.loads(
            (ROOT / "amplify" / "infra" / "workspace-mcp.json").read_text(encoding="utf-8")
        )
        registry = template["Resources"]["Registry"]["Properties"]
        self.assertIs(registry.get("DeletionProtectionEnabled"), True)
        self.assertIs(
            registry["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"], True
        )

    def test_protection_script_includes_workspace_registry(self) -> None:
        source = (ROOT / "scripts" / "protect_dynamodb_tables.py").read_text(encoding="utf-8")
        self.assertIn("EXPLICIT_TABLES = {'wecare-workspace-mcp'}", source)
        self.assertIn("name not in EXPLICIT_TABLES", source)


if __name__ == "__main__":
    unittest.main()
