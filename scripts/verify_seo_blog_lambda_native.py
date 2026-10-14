#!/usr/bin/env python3
"""Read-only AWS-native SEO blog smoke test for the separately deployed SEO Lambda.

Unlike the legacy Wix Headless smoke test, this validates the format that
SeoToolsTable-backed blog posts actually serve: content/contentText. It checks
the *whole* list, so accidental 500-post truncation cannot masquerade as success.

This script invokes Lambda without publishing content or writing any AWS resource.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping


def _event(path: str, *, fields: str = "") -> dict[str, Any]:
    event: dict[str, Any] = {
        "version": "2.0",
        "requestContext": {
            "apiId": "seo-deployment-smoke",
            "http": {"method": "GET", "path": path, "sourceIp": "127.0.0.1"},
        },
        "rawPath": path,
    }
    if fields:
        event["queryStringParameters"] = {"fields": fields}
    return event


def _invoke(function_name: str, region: str, event: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="seo-native-blog-") as directory:
        root = Path(directory)
        event_file, response_file = root / "event.json", root / "response.json"
        event_file.write_text(json.dumps(event), encoding="utf-8")
        command = [
            "aws", "lambda", "invoke",
            "--function-name", function_name,
            "--invocation-type", "RequestResponse",
            "--cli-binary-format", "raw-in-base64-out",
            "--payload", f"fileb://{event_file}",
            "--region", region,
            str(response_file),
        ]
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Lambda invocation failed (AWS CLI exit {proc.returncode})"
            )
        meta = json.loads(proc.stdout)
        if meta.get("FunctionError") or meta.get("StatusCode") != 200:
            raise RuntimeError("Lambda invocation returned a function error")
        envelope = json.loads(response_file.read_text(encoding="utf-8"))
        if envelope.get("statusCode") != 200:
            raise RuntimeError(
                f"SEO blog Lambda returned HTTP {envelope.get('statusCode')}"
            )
        body = envelope.get("body") or {}
        if isinstance(body, str):
            body = json.loads(body)
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise RuntimeError("SEO blog Lambda returned an unsuccessful body")
        return body


def verify_blog(
    invoke: Callable[[Mapping[str, Any]], dict[str, Any]],
    *,
    min_posts: int = 1400,
) -> dict[str, Any]:
    listing = invoke(_event("/seo-tools/blog-public", fields="slug,title"))
    posts = listing.get("posts")
    if not isinstance(posts, list):
        raise AssertionError("public blog listing is not an array")
    count = len(posts)
    if count < min_posts:
        raise AssertionError(f"public blog truncated or empty: {count} < {min_posts}")
    if listing.get("total") != count:
        raise AssertionError(
            f"blog total mismatch: reported {listing.get('total')}, returned {count}"
        )
    slugs = [str(p.get("slug") or "") for p in posts if isinstance(p, dict)]
    if len(slugs) != count or any(not slug for slug in slugs):
        raise AssertionError("blog listing contains entries without slugs")
    if len(set(slugs)) != count:
        raise AssertionError("blog listing contains duplicate slugs")
    # Check beginning, middle and end to catch lookups that only work for the
    # first page or a stale legacy Wix-backed subset. No fixed prose or authors.
    tested = []
    for slug in dict.fromkeys((slugs[0], slugs[count // 2], slugs[-1])):
        detail = invoke(_event("/seo-tools/blog-public/" + slug))
        post = detail.get("post")
        if not isinstance(post, dict) or post.get("slug") != slug:
            raise AssertionError(f"requested slug not resolved: {slug}")
        body = post.get("content") or post.get("contentText") or ""
        if not isinstance(body, str) or len(body.strip()) < 100:
            raise AssertionError(f"AWS article body missing/short for slug: {slug}")
        tested.append({"slug": slug, "characters": len(body)})
    return {"status": "PASS", "published_posts": count,
            "unique_slugs": len(set(slugs)), "sample_posts": tested}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--function", default="wecare-seo-tools")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--min-posts", type=int, default=1400)
    args = parser.parse_args()
    try:
        result = verify_blog(
            lambda event: _invoke(args.function, args.region, event),
            min_posts=args.min_posts,
        )
    except (RuntimeError, AssertionError, ValueError, OSError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
