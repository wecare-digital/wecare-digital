"""No-network tests for private-to-public AWS product image migration guards."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "migrate_wix_product_images_to_s3",
    ROOT / "scripts/migrate_wix_product_images_to_s3.py",
)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

SOURCE = "https://static.wixstatic.com/media/478bf9_example~mv2.png"
ROW = {
    "id": "p-1", "slug": "anew",
    "status": "active",
    "updatedAt": "2026-10-11T11:00:00.000Z",
    "imageRefs": [SOURCE],
    "variants": [{"sku": "abc", "inventory": 5}],
}


def test_url_allowlist_blocks_untrusted_servers():
    assert migration._parse_uri(SOURCE).hostname == "static.wixstatic.com"
    for url in [
        "http://static.wixstatic.com/media/a.png",
        "https://evil.example/media/a.png",
        "https://static.wixstatic.com.evil.example/media/a.png",
        "https://static.wixstatic.com/other/a.png",
        "https://static.wixstatic.com:444/media/a.png",
        "https://user@static.wixstatic.com/media/a.png",
    ]:
        with pytest.raises(ValueError):
            migration._parse_uri(url)


def test_file_magic_filters_non_image_and_svg():
    assert migration._image_type(b"\x89PNG\r\n\x1a\n" + b"x" * 64) == ("image/png", ".png")
    assert migration._image_type(b"\xff\xd8\xff" + b"x" * 64) == ("image/jpeg", ".jpg")
    assert migration._image_type(b"RIFF" + b"x" * 4 + b"WEBP" + b"x" * 64) == ("image/webp", ".webp")
    with pytest.raises(ValueError):
        migration._image_type(b"<svg onload='alert(1)'>")


def test_audit_counts_only_whitelisted_wixstatic():
    stats = migration.audit([ROW, {**ROW, "id": "p-2", "imageRefs": []}])
    assert stats["products_scanned"] == 2
    assert stats["products_with_wix_cdn"] == 1
    assert stats["unique_urls"] == 1


class S3:
    def __init__(self):
        self.saved = {}

    def put_object(self, **kwargs):
        self.saved[kwargs["Key"]] = kwargs

    def head_object(self, **kwargs):
        row = self.saved[kwargs["Key"]]
        return {
            "ContentLength": len(row["Body"]),
            "ContentType": row["ContentType"],
            "Metadata": row["Metadata"],
        }


class Table:
    def __init__(self):
        self.writes = []

    def update_item(self, **kwargs):
        self.writes.append(kwargs)


def test_s3_validation_precedes_atomic_catalog_update(monkeypatch):
    data = b"\x89PNG\r\n\x1a\n" + b"x" * 64
    table, s3 = Table(), S3()
    checked = []
    monkeypatch.setattr(
        migration, "_download", lambda url: (data, "image/png", ".png"),
    )
    monkeypatch.setattr(
        migration, "_public_check", lambda url: checked.append(url),
    )
    result = migration.apply(table, [ROW], s3)
    assert result["updated_products"] == 1
    assert len(checked) == 1
    assert len(table.writes) == 1
    write = table.writes[0]
    assert "imageRefs = :original" in write["ConditionExpression"]
    assert "#u = :old" in write["ConditionExpression"]
    assert write["ExpressionAttributeValues"][":original"] == [SOURCE]
    assert write["ExpressionAttributeValues"][":new"] == checked
    assert write["Key"] == {"id": "p-1"}


def test_missing_image_never_updates_products(monkeypatch):
    table, s3 = Table(), S3()
    monkeypatch.setattr(
        migration, "_download", lambda _: (_ for _ in ()).throw(RuntimeError("CDN inaccessible")),
    )
    with pytest.raises(RuntimeError, match="CDN inaccessible"):
        migration.apply(table, [ROW], s3)
    assert table.writes == []
