"""wix_export: deterministic manifests, stable checksums, reconciliation verdicts.

No network, no secrets - exercises only the pure export/reconcile logic.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.wix_export import export as wx  # noqa: E402


def test_checksum_is_key_order_independent():
    a = {"id": "1", "title": "x", "slug": "y"}
    b = {"slug": "y", "title": "x", "id": "1"}
    assert wx.content_checksum(a) == wx.content_checksum(b)


def test_manifest_is_sorted_and_idempotent():
    items = [{"id": "b"}, {"id": "a"}, {"id": "c"}]
    m1 = wx.manifest_for("blog", items)
    m2 = wx.manifest_for("blog", list(reversed(items)))
    assert [i["sourceId"] for i in m1["items"]] == ["a", "b", "c"]
    assert m1["items"] == m2["items"]  # order of input does not matter


def test_source_id_preserved_from_wix_id():
    m = wx.manifest_for("store-products", [{"id": "x1", "price": {"amount": "1.00"}}])
    assert m["items"][0]["sourceId"] == "x1"
    assert m["items"][0]["data"]["sourceId"] == "x1"


def test_reconcile_detects_count_mismatch():
    m = wx.manifest_for("blog", [{"id": "1"}, {"id": "2"}])
    assert wx.reconcile("blog", m, fresh_count=2)["verdict"] == "RECONCILED"
    assert wx.reconcile("blog", m, fresh_count=3)["verdict"] == "DISCREPANCY"


def test_reconcile_detects_duplicate_ids():
    m = wx.manifest_for("blog", [{"id": "1"}, {"id": "1"}])
    r = wx.reconcile("blog", m, fresh_count=2)
    assert r["duplicate_ids"] == 1 and r["verdict"] == "DISCREPANCY"


def test_dry_mode_runs_and_reconciles():
    reports = wx.export_dry(None)
    assert reports["blog"]["verdict"] == "RECONCILED"
    assert reports["store-products"]["verdict"] == "RECONCILED"
