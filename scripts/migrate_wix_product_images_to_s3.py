#!/usr/bin/env python3
"""Migrate ONLY public WixStatic product artwork to our existing AWS S3/CloudFront.

Read-only by default. --apply runs a two-phase procedure:
  1. Download *all* authorized image URLs, validate image magic and MIME, upload
     immutable SHA256-keyed S3 objects, verify HeadObject and public CDN access.
  2. ONLY if phase 1 succeeds for all products, conditionally update ProductsTable
     imageRefs (original refs + optimistic version lock). Never touch variants,
     pricing, inventory, orders, customer records or any secret.

A failed download, CDN test or concurrent product edit stops without modifying
that product. It is safe to retry and never deletes the original source assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
TABLE = "stack-wecare-digital-ProductsTable"
BUCKET = "wecare-digital-get"
PREFIX = "o/catalog/products/"
CLOUDFRONT = "https://d1kf2rchz7yras.cloudfront.net"
ALLOWED_HOST = "static.wixstatic.com"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_PRODUCTS = 5000


def _parse_uri(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST or
            parsed.port is not None or not parsed.path.startswith("/media/") or
            parsed.username or parsed.password or parsed.fragment):
        raise ValueError("Refusing external or non-media asset URL")
    return parsed


class SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _parse_uri(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(SafeRedirects())


def _image_type(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\x89PNG\r\n\\x1a\n"):
        return "image/png", ".png"
    if data.startswith(b"\xff\\xd8\\xff"):
        return "image/jpeg", ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise ValueError("Asset has an unsupported or invalid image signature")


def _download(url: str) -> tuple[bytes, str, str]:
    _parse_uri(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "WECARE.DIGITAL-AWS-catalog-migration/1.0",
        "Accept": "image/png,image/jpeg,image/webp,image/gif",
    })
    with _opener().open(req, timeout=25) as response:
        _parse_uri(response.geturl())
        advertised = response.headers.get("Content-Length")
        if advertised and int(advertised) > MAX_IMAGE_BYTES:
            raise ValueError("Asset exceeds 12 MB limit")
        data = response.read(MAX_IMAGE_BYTES + 1)
    if not 64 <= len(data) <= MAX_IMAGE_BYTES:
        raise ValueError("Empty, truncated or oversized image")
    content_type, ext = _image_type(data)
    return data, content_type, ext


def _key(data: bytes, ext: str) -> str:
    return PREFIX + hashlib.sha256(data).hexdigest() + ext


def _table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def _products(table) -> list[dict]:
    items = []
    params = {"ConsistentRead": True}
    while True:
        page = table.scan(**params)
        items.extend(page.get("Items", []))
        if len(items) > MAX_PRODUCTS:
            raise RuntimeError("Unexpectedly large catalog; refusing automatic migration")
        if not page.get("LastEvaluatedKey"):
            break
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return items


def _public_check(url: str) -> None:
    req = urllib.request.Request(url, method="HEAD", headers={
        "User-Agent": "WECARE.DIGITAL-AWS-catalog-migration/1.0",
    })
    # The public CloudFront /o/ path MUST deliver an actual image, not a
    # 302 fallback or an HTML error page.
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError("CloudFront did not return HTTP 200")
        ctype = str(response.headers.get("Content-Type") or "").split(";")[0]
        if ctype not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            raise RuntimeError("CloudFront media path returned non-image content")


def audit(items: list[dict]) -> dict:
    urls = []
    products = []
    for row in items:
        refs = row.get("imageRefs") or []
        if not isinstance(refs, list):
            raise ValueError("Unexpected non-list imageRefs")
        legacy = [x for x in refs if isinstance(x, str) and
                  "wixstatic.com" in urllib.parse.urlparse(x).netloc]
        for url in legacy:
            _parse_uri(url)
        if legacy:
            urls.extend(legacy)
            products.append(str(row.get("slug") or row.get("id")))
    return {
        "products_scanned": len(items),
        "products_with_wix_cdn": len(products),
        "legacy_image_refs": len(urls),
        "unique_urls": len(set(urls)),
        "affected_slugs": products,
    }


def apply(table, items: list[dict], s3) -> dict:
    info = audit(items)
    mapping: dict[str, str] = {}
    original = sorted({
        ref
        for row in items
        for ref in (row.get("imageRefs") or [])
        if isinstance(ref, str) and urllib.parse.urlparse(ref).hostname == ALLOWED_HOST
    })
    # Phase 1: all assets copied and reachable BEFORE any authority changes.
    for url in original:
        data, content_type, ext = _download(url)
        digest = hashlib.sha256(data).hexdigest()
        key = _key(data, ext)
        try:
            s3.put_object(
                Bucket=BUCKET, Key=key, Body=data,
                ContentType=content_type,
                CacheControl="public, max-age=31536000, immutable",
                ServerSideEncryption="AES256",
                Metadata={"sha256": digest, "source": "wixstatic-public-catalog"},
                IfNoneMatch="*",
            )
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise
        head = s3.head_object(Bucket=BUCKET, Key=key)
        if (int(head.get("ContentLength", -1)) != len(data) or
                head.get("Metadata", {}).get("sha256") != digest or
                str(head.get("ContentType")) != content_type):
            raise RuntimeError("S3 integrity check failed")
        public_url = CLOUDFRONT + "/" + key
        _public_check(public_url)
        mapping[url] = public_url
        print(json.dumps({"copied_image": digest[:16], "bytes": len(data)}), flush=True)
    # Phase 2: a product's refs change only while its original metadata version
    # and original image list still match. No partial asset migration.
    updated = []
    for row in items:
        before = row.get("imageRefs") or []
        after = [mapping.get(url, url) for url in before]
        if after == before:
            continue
        version = row.get("updatedAt")
        if not isinstance(version, str) or not version:
            raise RuntimeError("Product has no optimistic version")
        changed = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        table.update_item(
            Key={"id": row["id"]},
            UpdateExpression="SET imageRefs = :new, #u = :changed",
            ConditionExpression="attribute_exists(#id) AND #u = :old AND imageRefs = :original",
            ExpressionAttributeNames={"#u": "updatedAt", "#id": "id"},
            ExpressionAttributeValues={
                ":new": after, ":changed": changed,
                ":old": version, ":original": before,
            },
        )
        updated.append(row.get("slug") or row["id"])
    return {
        **info,
        "copied_unique_images": len(mapping),
        "updated_products": len(updated),
        "updated_slugs": updated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    table = _table()
    items = _products(table)
    if not args.apply:
        print(json.dumps({"mode": "AUDIT_ONLY", **audit(items)}, indent=2))
        return 0
    result = apply(table, items, boto3.client("s3", region_name=REGION))
    print(json.dumps({"mode": "APPLIED", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
