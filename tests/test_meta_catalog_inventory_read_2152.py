"""Meta product inventory reads must never turn partial/invalid Graph data into 0.

Issue #2152. Tests extract and execute the exact production reader without AWS,
Meta credentials, product writes or external HTTP.
Run: python -m unittest discover -s tests -p 'test_meta_catalog_inventory_read_2152.py'
"""
import ast
from pathlib import Path
import typing
import unittest

SOURCE = (Path(__file__).resolve().parents[1]
          / "amplify/functions/ecommerce/meta-catalog-sync/handler.py")


class ReadFailure(RuntimeError):
    status = None
    errorKind = None


def load_reader(max_pages=50):
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(SOURCE))
    fn = [item for item in tree.body
          if isinstance(item, ast.FunctionDef) and item.name == "_existing_items"]
    if len(fn) != 1:
        raise AssertionError("Production inventory reader not found")
    ns = {
        "List": typing.List, "Dict": typing.Dict, "Any": typing.Any,
        "Mapping": typing.Mapping,
        "MAX_PAGES": max_pages, "META_PRODUCT_FIELDS": "id,retailer_id",
        "META_PAGE_LIMIT": "100",
        "MetaCatalogReadError": ReadFailure,
    }
    exec(compile(ast.Module(body=fn, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns["_existing_items"]


class FakeMeta:
    def __init__(self, responses):
        self.responses, self.params = responses, []

    def __call__(self, path, *, method, params, token, app_secret):
        self.params.append({"path": path, "method": method, "params": params,
                            "token": token, "app_secret": app_secret})
        if len(self.params) > len(self.responses):
            raise AssertionError("unexpected extra Meta page fetch")
        return self.responses[len(self.params) - 1]


def read(responses, *, max_pages=50):
    fake = FakeMeta(responses)
    result = load_reader(max_pages)(
        fake, token="test-not-a-real-token", app_secret="",
        catalog_id="test-catalog")
    return result, fake


class InventoryReadSafetyTests(unittest.TestCase):
    def test_legitimate_empty_catalog_is_distinct_from_missing_data(self):
        result, fake = read([{"data": []}])
        self.assertEqual(result, [])
        self.assertEqual(len(fake.params), 1)

    def test_missing_data_does_not_propose_twenty_two_creates(self):
        for result in ({}, {"paging": {"cursors": {}}}, {"data": None},
                       {"data": {}}, "not a mapping"):
            with self.subTest(result=result):
                with self.assertRaises(ReadFailure) as captured:
                    read([result])
                self.assertEqual(captured.exception.errorKind,
                                 "InvalidGraphRoot" if isinstance(result, str)
                                 else "InvalidProductsData")

    def test_invalid_item_row_fails_closed(self):
        with self.assertRaises(ReadFailure) as captured:
            read([{"data": [{"id": "valid"}, "not-an-item"]}])
        self.assertEqual(captured.exception.errorKind, "InvalidProductRow")

    def test_complete_paginated_read(self):
        results, fake = read([
            {"data": [{"id": "one"}],
             "paging": {"cursors": {"after": "cursor-1"}, "next": "next-page"}},
            {"data": [{"id": "two"}, {"id": "three"}]},
        ])
        self.assertEqual(len(results), 3)
        self.assertEqual(fake.params[1]["params"]["after"], "cursor-1")

    def test_early_empty_page_with_next_is_not_complete(self):
        with self.assertRaises(ReadFailure) as captured:
            read([{"data": [], "paging": {"next": "more-data",
                                          "cursors": {"after": "1"}}}])
        self.assertEqual(captured.exception.errorKind, "EmptyPageHasNext")

    def test_missing_cursor_with_next_is_not_complete(self):
        with self.assertRaises(ReadFailure) as captured:
            read([{"data": [{"id": "one"}], "paging": {"next": "more-data"}}])
        self.assertEqual(captured.exception.errorKind, "MissingAfterCursor")

    def test_stuck_cursor_is_not_an_empty_catalog(self):
        with self.assertRaises(ReadFailure) as captured:
            read([
                {"data": [{"id": "one"}], "paging": {"cursors": {"after": "x"}}},
                {"data": [{"id": "two"}], "paging": {"cursors": {"after": "x"}}},
            ])
        self.assertEqual(captured.exception.errorKind, "RepeatedAfterCursor")

    def test_budget_exhaustion_never_returns_partial_inventory(self):
        pages = [{"data": [{"id": str(i)}],
                  "paging": {"cursors": {"after": str(i)}}}
                 for i in range(1, 4)]
        with self.assertRaises(ReadFailure) as captured:
            read(pages, max_pages=3)
        self.assertEqual(captured.exception.errorKind, "CatalogPageLimitExceeded")

    def test_graph_errors_preserve_status_but_not_secret(self):
        with self.assertRaises(ReadFailure) as captured:
            read([{"error": {"status": 403, "type": "HTTPError"}}])
        self.assertEqual(captured.exception.status, 403)
        self.assertEqual(captured.exception.errorKind, "HTTPError")

    def test_zero_inventory_on_background_sync_never_auto_applies(self):
        source = SOURCE.read_text(encoding="utf-8")
        no_auto = source.index("if not action and desired and not existing:")
        auto = source.index("if not action and _safe_auto_apply(")
        self.assertLess(no_auto, auto)
        section = source[no_auto:auto]
        self.assertIn('"empty_provider_inventory_requires_review"', section)
        self.assertIn('"applied": 0', section)
        self.assertIn('"autoApplied": False', section)


if __name__ == "__main__":
    unittest.main()
