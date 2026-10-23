"""The plan decoder must classify an inspect payload with the SAME logic as the live sync.

Offline: builds a synthetic inspect payload reproducing the 2026-10-23 plan shape
(create 28 / update 0 / retire 21 / foreign 22) and asserts the decoder's diff agrees -
owned-and-new => create, owned-and-vanished => retire (out of stock, not delete),
non-owned (wix:) => foreign and never touched.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCS_DIR = ROOT / "amplify" / "functions" / "shared" / "lambda_utils" / "ecommerce"


def _load_mcs():
    sys.path.insert(0, str(MCS_DIR))
    spec = importlib.util.spec_from_file_location("meta_catalog_sync", MCS_DIR / "meta_catalog_sync.py")
    m = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass annotation resolution can find the module's own
    # names; re-exec per call breaks @dataclass field resolution (NoneType.__dict__).
    sys.modules["meta_catalog_sync"] = m
    spec.loader.exec_module(m)
    return m


# Load ONCE at import time, not per test, so the dataclass is defined exactly once.
_MCS = _load_mcs()


def _mcs():
    return _MCS


def _v2(mcs, pid: str, vid: str) -> str:
    b = lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    return f"{mcs.RETAILER_PREFIX}:v2:{b(pid)}:{b(vid)}"


def test_plan_shape_matches_the_approved_counts():
    mcs = _mcs()
    desired = [{
        "retailer_id": _v2(mcs, f"prod-{i}", f"var-{i}"), "name": f"Item {i}",
        "price": "100 INR", "availability": "in stock", "currency": "INR",
        "description": "d", "image_url": "u", "url": "u",
    } for i in range(28)]
    existing = []
    for i in range(21):
        existing.append({"retailer_id": _v2(mcs, f"old-{i}", f"oldvar-{i}"),
                         "id": f"meta{i}", "name": f"Old {i}", "availability": "in stock"})
    for i in range(22):
        existing.append({"retailer_id": f"wix:{uuid.uuid4()}", "id": f"wx{i}",
                         "name": f"Wix {i}", "availability": "in stock"})

    plan = mcs.diff(desired, existing)
    c = plan.counts()
    assert (c["create"], c["update"], c["retire"], c["foreign"]) == (28, 0, 21, 22)


def test_retire_is_out_of_stock_never_delete():
    mcs = _mcs()
    existing = [{"retailer_id": _v2(mcs, "p", "v"), "id": "m1", "name": "Gone",
                 "availability": "in stock"}]
    plan = mcs.diff([], existing)  # vanished from desired
    assert len(plan.retire) == 1
    assert plan.retire[0]["availability"] == mcs.OUT_OF_STOCK
    # nothing in the module can emit a delete
    assert not hasattr(plan, "delete")


def test_foreign_is_reported_not_acted_on():
    mcs = _mcs()
    existing = [{"retailer_id": "wix:abc", "id": "w1", "name": "Wix"}]
    plan = mcs.diff([], existing)
    assert plan.foreign == ["wix:abc"]
    assert plan.create == [] and plan.update == [] and plan.retire == []


def test_already_out_of_stock_is_not_re_retired():
    mcs = _mcs()
    existing = [{"retailer_id": _v2(mcs, "p", "v"), "id": "m1", "name": "Gone",
                 "availability": mcs.OUT_OF_STOCK}]
    plan = mcs.diff([], existing)
    assert plan.retire == []  # already retired -> no redundant write
