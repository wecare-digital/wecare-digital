"""Public delivery for approved catalog artwork stored under secure/d/public/catalog-deploy/catalog/products/.

Only exact lowercase *-4096.png filenames are accepted. The Lambda has read-only
S3 permission scoped to that one prefix and returns image bytes through API Gateway.
"""
from __future__ import annotations

import base64
import os
import re

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET = os.environ.get("CATALOG_BUCKET", "wecare-digital-get")
PREFIX = "secure/d/public/catalog-deploy/catalog/products/"
# Canonical catalog masters live under secure/d/public; do not fall back to retired paths.
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-4096[.]png$")
S3 = boto3.client("s3", region_name=REGION)


def _response(status: int, body: str = "", *, content_type: str = "text/plain",
              encoded: bool = False, extra_headers: dict | None = None) -> dict:
    headers = {
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
        "Access-Control-Allow-Origin": "*",
        "X-Content-Type-Options": "nosniff",
    }
    if extra_headers:
        headers.update(extra_headers)
    return {
        "statusCode": status,
        "headers": headers,
        "isBase64Encoded": encoded,
        "body": body,
    }


def handler(event, context):
    rc = event.get("requestContext", {})
    method = str(rc.get("http", {}).get("method") or event.get("httpMethod") or "GET").upper()
    path = str(event.get("rawPath") or rc.get("http", {}).get("path") or event.get("path") or "")

    if method == "OPTIONS":
        return _response(204, "", extra_headers={
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Access-Control-Allow-Headers": "content-type",
        })
    if method != "GET":
        return _response(405, "METHOD_NOT_ALLOWED")

    # Amplify rewrites /api/* to the named API Gateway /prod/* stage.
    # HTTP API v2 rawPath can retain that stage prefix. Accept only the
    # known delivery paths; never turn an arbitrary path into an S3 key.
    markers = ("/catalog-media/", "/prod/catalog-media/", "/api/catalog-media/")
    marker = next((prefix for prefix in markers if path.startswith(prefix)), None)
    if marker is None:
        return _response(404, "NOT_FOUND")
    name = path[len(marker):].strip("/")
    if "/" in name or "\\" in name or not NAME.fullmatch(name):
        return _response(404, "NOT_FOUND")

    try:
        obj = S3.get_object(Bucket=BUCKET, Key=PREFIX + name)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code") or "")
        if code in {"NoSuchKey", "NoSuchObject", "404", "NotFound"}:
            return _response(404, "NOT_FOUND")
        return _response(503, "CATALOG_MEDIA_TEMPORARILY_UNAVAILABLE")

    body = obj["Body"].read()
    headers = {"Content-Length": str(len(body))}
    if obj.get("ETag"):
        headers["ETag"] = str(obj["ETag"])
    return _response(
        200,
        base64.b64encode(body).decode("ascii"),
        content_type="image/png",
        encoded=True,
        extra_headers=headers,
    )
