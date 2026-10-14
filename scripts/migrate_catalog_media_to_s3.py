#!/usr/bin/env python3
"""Migrate *public* legacy product artwork to WECARE's own S3/CloudFront.

Safe defaults:
  python scripts/migrate_catalog_media_to_s3.py
     read-only report from ProductsTable; NO HTTP downloads and NO AWS writes.
  python scripts/migrate_catalog_media_to_s3.py --apply
     fetches ONLY static.wixstatic.com/media images, writes content-hashed
     objects under o/stack/store/products/, validates S3, and conditionally
     updates imageRefs in ProductsTable. Every product update is version-locked.
  python scripts/migrate_catalog_media_to_s3.py --verify
     checks all product imageRefs for external Wix URLs and HEADs native S3 keys.

The script never changes product/variant identity, price, status or inventory.
It does not use any Wix API key, token, OAuth flow or CMS backend.
Use an approved operator role with narrow DynamoDB + S3 scope, not AWS admin.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3

REGION = "us-east-1"
TABLE = "stack-wecare-digital-ProductsTable"
BUCKET = "wecare-digital-get"
PREFIX = "o/stack/store/products/"
PUBLIC = "https://wecare.digital/get/"
MAX_BYTES = 8 * 1024 * 1024
IMAGE_NAME = re.compile(r"^/media/[A-Za-z0-9._~-]+$")
MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def _legacy(url: str) -> bool:
    value = urllib.parse.urlsplit(url)
    return (value.scheme == "https" and value.netloc == "static.wixstatic.com"
            and value.username is None and value.password is None
            and bool(IMAGE_NAME.fullmatch(value.path)) and not value.query
            and not value.fragment)


def _type(blob: bytes) -> str:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return "webp"
    raise ValueError("image is not JPEG, PNG or WebP")


def _download(url: str) -> tuple[bytes, str]:
    if not _legacy(url):
        raise ValueError("unapproved image source hostname or path")
    request = urllib.request.Request(
        url, headers={"User-Agent": "WECARE-CatalogMediaMigration/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        # urlopen's 30x redirect target is not trusted merely because
        # the original host was allowlisted; refuse source redirects entirely.
        if response.geturl() != url:
            raise ValueError("source image redirect refused")
        data = response.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError("source image empty or exceeds 8MiB")
    extension = _type(data)  # sniff magic, not remote MIME or extension
    return data, extension


def _list_products(table):
    opts = {"ConsistentRead": True}
    while True:
        page = table.scan(**opts)
        for row in page.get("Items", []):
            if row.get("id") and row.get("status") in {"active", "draft", "archived"}:
                yield row
        if "LastEvaluatedKey" not in page:
            break
        opts["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _upload_image(s3, url: str) -> str:
    blob, suffix = _download(url)
    digest_bytes = hashlib.sha256(blob).digest()
    digest = digest_bytes.hex()
    key = PREFIX + digest + "." + suffix
    target_url = PUBLIC + key
    try:
        metadata = s3.head_object(Bucket=BUCKET, Key=key)
        if metadata.get("ContentLength") != len(blob):
            raise RuntimeError("existing hash-key image has wrong length")
    except s3.exceptions.ClientError as ex:
        if ex.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
            raise
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=blob,
            ContentType=MIME[suffix],
            ContentLength=len(blob),
            CacheControl="public, max-age=31536000, immutable",
            ServerSideEncryption="AES256",
            ChecksumSHA256=base64.b64encode(digest_bytes).decode("ascii"),
        )
        metadata = s3.head_object(Bucket=BUCKET, Key=key)
        if metadata.get("ContentLength") != len(blob):
            raise RuntimeError("S3 read-back content length mismatch")
    return target_url


def _update_product(table, row, image_refs: list[str]):
    updated_at = str(row.get("updatedAt") or "")
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if not updated_at:
        # Conservative refusal: never overwrite a product with no version lock.
        raise ValueError("product has no updatedAt for optimistic lock")
    table.update_item(
        Key={"id": row["id"]},
        UpdateExpression="SET imageRefs = :new, updatedAt = :now",
        ConditionExpression="attribute_exists(id) AND updatedAt = :old",
        ExpressionAttributeValues={
            ":new": image_refs, ":now": now, ":old": updated_at,
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    exclusive = ap.add_mutually_exclusive_group()
    exclusive.add_argument("--apply", action="store_true")
    exclusive.add_argument("--verify", action="store_true")
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--bucket", default=BUCKET)
    args = ap.parse_args()
    if args.bucket != BUCKET:
        raise ValueError("migration destination is pinned to wecare-digital-get")
    table = boto3.resource("dynamodb", region_name=REGION).Table(args.table)
    s3 = boto3.client("s3", region_name=REGION)
    rows = list(_list_products(table))
    legacy_rows = []
    migrated = 0
    rejected = []
    for row in rows:
        references = row.get("imageRefs") or []
        wix_urls = [x for x in references
                    if isinstance(x, str) and "wixstatic.com" in x]
        if not wix_urls:
            if args.verify:
                for url in references:
                    if not isinstance(url, str) or not url.startswith(PUBLIC + PREFIX):
                        rejected.append({"id": row["id"], "reason": "non-native image ref"})
                        continue
                    key = url.removeprefix(PUBLIC)
                    try:
                        s3.head_object(Bucket=BUCKET, Key=key)
                    except Exception:
                        rejected.append({"id": row["id"], "reason": "missing S3 image"})
            continue
        legacy_rows.append({"id": row["id"], "slug": row.get("slug"),
                            "image_count": len(wix_urls)})
        if not args.apply:
            continue
        try:
            if len(wix_urls) != len(references):
                raise ValueError("mixed native/legacy imageRefs need manual review")
            native_refs = [_upload_image(s3, url) for url in wix_urls]
            if len(native_refs) != len(references):
                raise RuntimeError("image copy incomplete; product unchanged")
            _update_product(table, row, native_refs)
            migrated += 1
        except Exception as ex:
            rejected.append({"id": row["id"], "reason": type(ex).__name__})
    report = {
        "mode": "apply" if args.apply else "verify" if args.verify else "dry-run",
        "products_checked": len(rows),
        "legacy_products": len(legacy_rows),
        "legacy": legacy_rows,
        "products_migrated": migrated,
        "errors": rejected,
    }
    print(json.dumps(report, indent=2, default=str))
    return 1 if rejected or (args.verify and legacy_rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
