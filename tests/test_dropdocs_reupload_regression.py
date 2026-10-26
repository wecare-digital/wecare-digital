import ast
from pathlib import Path
import unittest


SOURCE_PATH = Path("amplify/functions/core/service-api/handler.py")


class DropDocsReuploadRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _function(self, name):
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return node
        self.fail(f"{name} not found")

    def test_filename_helper_has_regex_import(self):
        imported = set()
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
        self.assertIn("re", imported, "_extension_for_upload uses re.fullmatch; import re is required")

    def test_reupload_confirm_defines_reference_increment(self):
        fn = self._function("_confirm_document_reupload")
        updates = [
            node for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update_item"
        ]
        self.assertTrue(updates, "replacement confirm must update DocumentTable")

        matched = False
        for call in updates:
            kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg}
            expr = kwargs.get("UpdateExpression")
            values = kwargs.get("ExpressionAttributeValues")
            if not isinstance(expr, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                continue
            expr_text = ast.get_source_segment(self.source, expr) or ""
            if "referenceVersion" not in expr_text or ":one" not in expr_text:
                continue
            self.assertIsInstance(values, ast.Dict)
            keys = [
                key.value for key in values.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
            self.assertIn(":one", keys, "referenceVersion uses :one, so the value must be defined")
            matched = True
        self.assertTrue(matched, "replacement confirm must increment referenceVersion")

    def test_success_response_does_not_return_pending_replacement_fields(self):
        fn = self._function("_confirm_document_reupload")
        text = ast.get_source_segment(self.source, fn) or ""
        self.assertIn("item.pop(field, None)", text)
        for field in (
            "replacementStorageKey",
            "replacementFileName",
            "replacementOriginalFileName",
            "replacementMimeType",
            "replacementFileSize",
            "replacementDocumentRef",
            "replacementRequestedAt",
        ):
            self.assertIn(repr(field), text)


if __name__ == "__main__":
    unittest.main()
