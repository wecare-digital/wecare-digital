"""The shared-role S3 scoper must narrow WRITE without losing any legitimate prefix.

These are offline, logic-only checks (no AWS): they pin the generated policy shape so a future
edit cannot silently re-broaden writes to the bucket root or drop the legacy-write Deny guard.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "scope_shared_lambda_s3.py"


def _mod():
    spec = importlib.util.spec_from_file_location("scope_shared_lambda_s3", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_write_is_scoped_to_the_three_roots_not_the_bucket_root():
    m = _mod()
    stmts = {s["Sid"]: s for s in m.proposed_s3_statements()}
    write = stmts["SharedMediaS3Write"]
    assert set(write["Action"]) == {"s3:PutObject", "s3:DeleteObject"}
    # exactly the three legitimate write roots, each a prefix wildcard
    assert sorted(write["Resource"]) == sorted([
        "arn:aws:s3:::wecare-digital-get/secure/d/public/*",
        "arn:aws:s3:::wecare-digital-get/o/*",
        "arn:aws:s3:::wecare-digital-get/secure/u/*",
    ])
    # the bucket root and bare secure/ must NOT be writable
    for r in write["Resource"]:
        assert not r.endswith("wecare-digital-get/*"), "write must not cover the bucket root"
        assert "/secure/*" not in r, "write must not cover bare secure/"


def test_reads_stay_broad():
    m = _mod()
    stmts = {s["Sid"]: s for s in m.proposed_s3_statements()}
    read = stmts["SharedMediaS3ReadList"]
    assert set(read["Action"]) == {"s3:GetObject", "s3:ListBucket"}
    assert f"arn:aws:s3:::{m.BUCKET}/*" in read["Resource"]


def test_legacy_write_deny_guard_is_preserved_verbatim():
    m = _mod()
    stmts = {s["Sid"]: s for s in m.proposed_s3_statements()}
    deny = stmts["DenyLegacyMediaWrites"]
    assert deny["Effect"] == "Deny"
    assert set(deny["Action"]) == {"s3:PutObject", "s3:DeleteObject"}
    assert set(deny["Resource"]) == {
        "arn:aws:s3:::wecare-digital-get/secure/Invoice/customer_invoice/*",
        "arn:aws:s3:::wecare-digital-get/secure/Invoice/fonts/*",
        "arn:aws:s3:::wecare-digital-get/o/stack/whatsapp-media/*",
        "arn:aws:s3:::wecare-digital-get/stack/whatsapp-media/*",
    }


def test_proposed_full_keeps_non_s3_statements():
    m = _mod()
    live = {"Version": "2012-10-17", "Statement": [
        {"Sid": "PinpointSMSVoice", "Effect": "Allow", "Action": ["sms-voice:SendTextMessage"],
         "Resource": "*"},
        {"Sid": "OldS3", "Effect": "Allow", "Action": ["s3:PutObject"],
         "Resource": "arn:aws:s3:::wecare-digital-get/*"},
    ]}
    new = m.proposed_full(live)
    sids = {s.get("Sid") for s in new["Statement"]}
    assert "PinpointSMSVoice" in sids            # non-S3 preserved
    assert "OldS3" not in sids                   # old broad S3 statement dropped
    assert "SharedMediaS3Write" in sids          # new scoped write added
    assert "DenyLegacyMediaWrites" in sids       # deny guard present


def test_catalog_image_key_canonicalization_is_safe():
    """The sibling migrator must only rewrite valid legacy keys, never traverse or mis-name."""
    spec = importlib.util.spec_from_file_location(
        "migrate_catalog_image_keys", ROOT / "scripts" / "migrate_catalog_image_keys.py")
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    assert mk.canonicalize("secure/public/catalog-deploy/catalog/products/anew-4096.png") == \
        "secure/d/public/catalog-deploy/catalog/products/anew-4096.png"
    assert mk.canonicalize("/secure/public/catalog-deploy/catalog/products/ritva-4096.png") == \
        "secure/d/public/catalog-deploy/catalog/products/ritva-4096.png"
    # already canonical -> no rewrite (returns None so it is skipped)
    assert mk.canonicalize("secure/d/public/catalog-deploy/catalog/products/x-4096.png") is None
    # traversal / bad name / empty -> refused
    assert mk.canonicalize("secure/public/catalog-deploy/catalog/products/a/../b-4096.png") is None
    assert mk.canonicalize("secure/public/catalog-deploy/catalog/products/x.jpg") is None
    assert mk.canonicalize("") is None


def test_scoper_does_not_put_lambda_utils_on_sys_path():
    _mod()
    dangerous = str(ROOT / "amplify" / "functions" / "shared" / "lambda_utils")
    assert dangerous not in sys.path
