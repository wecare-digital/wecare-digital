"""Validate and batch-create WECARE.DIGITAL Wix Blog migration manifests.

Wix Blog is the content source of truth. This script never generates editorial
copy: it accepts only already-approved post manifests. The default mode is
validation-only. Draft creation or publication must be explicitly requested.

Examples:
  python scripts/wix_blog_migrate.py export --output /tmp/wix-source.json
  python scripts/wix_blog_migrate.py apply --manifest /tmp/approved.json
  python scripts/wix_blog_migrate.py apply --manifest /tmp/approved.json --mode draft
  python scripts/wix_blog_migrate.py apply --manifest /tmp/approved.json --mode publish
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List

import boto3

WIX_API = "https://www.wixapis.com"
WIX_ACCOUNT_ID = os.environ.get(
    "WIX_ACCOUNT_ID", "478bf907-96cc-4cab-9220-bb96f1d35cbb"
)
TARGET_SITE_ID = os.environ.get(
    "WIX_SITE_ID", "c993128b-26be-41cd-9fcd-904abe23462f"
)
# The retired Wix Editor source is no longer addressable by this repository.
# Export and apply operate only against the current Headless site.
SOURCE_SITE_ID = TARGET_SITE_ID
SECRET_NAME = os.environ.get(
    "WIX_API_KEY_SECRET", "wecare/wix/headless-api-key"
)
AUTHOR_NAME = "Anew by WECARE.DIGITAL"
AUTHOR_EMAIL = "one@wecare.digital"
CATEGORY_LABEL = "Conversations"
FORBIDDEN_MEDIA_NODES = {"IMAGE", "GALLERY", "GIF", "VIDEO", "AUDIO"}
BULK_LIMIT = 20

_api_key: str | None = None


def load_api_key() -> str:
    """The Wix API key. THE KILL SWITCH IS CHECKED FIRST, before any secret read.

    This is the path that PUBLISHES - `apply_manifest` and, transitively, everything
    `gastronomy_batch.py` does, since it calls `request()` here. Until 2026-09-29 it ignored
    `WIX_CREDENTIALS_DISABLED` completely: the switch was honoured only in
    `ecommerce/wix-store`, so it disabled the store and left blog publication running. An
    operator who set it, read the commit saying it was fixed, and then ran a publish would
    have published.

    Imported from `lambda_utils.wix_guard` rather than reimplemented, so the accepted
    spellings cannot drift between the three credential paths - a test asserts they agree.
    """
    global _api_key
    _shared = Path(__file__).resolve().parents[1] / "amplify" / "functions" / "shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from lambda_utils.wix_guard import refuse_if_disabled
    refuse_if_disabled("wix_blog_migrate publish path")

    if _api_key:
        return _api_key
    raw = boto3.client(
        "secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1")
    ).get_secret_value(SecretId=SECRET_NAME).get("SecretString", "")
    try:
        parsed = json.loads(raw)
        value = (
            parsed.get("api_key")
            or parsed.get("apiKey")
            or parsed.get("key")
            or parsed.get("value")
            or ""
        )
    except (TypeError, ValueError):
        value = raw
    _api_key = str(value).strip()
    if not _api_key:
        raise RuntimeError(f"Wix API key secret {SECRET_NAME!r} is empty")
    return _api_key


def request(
    site_id: str, method: str, path: str, body: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    headers = {
        "Authorization": load_api_key(),
        "wix-account-id": WIX_ACCOUNT_ID,
        "wix-site-id": site_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        WIX_API + path, data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Wix API {method} {path} failed: HTTP {error.code}: {detail[:800]}"
        ) from error


def query_posts(site_id: str, include_content: bool = False) -> List[Dict[str, Any]]:
    fieldsets = ["URL", "SEO"]
    if include_content:
        fieldsets += ["CONTENT_TEXT", "RICH_CONTENT"]
    posts: List[Dict[str, Any]] = []
    cursor = ""
    while True:
        paging: Dict[str, Any] = {"limit": 100}
        if cursor:
            paging["cursor"] = cursor
        data = request(
            site_id,
            "POST",
            "/v3/posts/query",
            {
                "fieldsets": fieldsets,
                "query": {"cursorPaging": paging},
                "skipCount": True,
            },
        )
        posts.extend(data.get("posts", []) or [])
        cursor = str(
            (((data.get("pagingMetadata") or {}).get("cursors") or {}).get("next"))
            or ""
        )
        if not cursor:
            return posts


def export_source(output: Path) -> None:
    posts = query_posts(SOURCE_SITE_ID, include_content=True)
    payload = {
        "sourceSiteId": SOURCE_SITE_ID,
        "count": len(posts),
        "posts": posts,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(posts)} source posts to {output}")


def _inline_nodes(text: str) -> List[Dict[str, Any]]:
    """Convert the small approved Markdown subset to Wix Ricos text nodes."""
    nodes: List[Dict[str, Any]] = []
    pattern = re.compile(r"(\*\*.+?\*\*|\*[^*]+?\*)")
    position = 0
    for match in pattern.finditer(text):
        if match.start() > position:
            nodes.append({
                "type": "TEXT",
                "textData": {"text": text[position:match.start()], "decorations": []},
            })
        token = match.group(0)
        if token.startswith("**"):
            value = token[2:-2]
            decorations = [{"type": "BOLD", "fontWeightValue": 700}]
        else:
            value = token[1:-1]
            decorations = [{"type": "ITALIC", "italicData": True}]
        nodes.append({
            "type": "TEXT",
            "textData": {"text": value, "decorations": decorations},
        })
        position = match.end()
    if position < len(text):
        nodes.append({
            "type": "TEXT",
            "textData": {"text": text[position:], "decorations": []},
        })
    return [node for node in nodes if (node.get("textData") or {}).get("text")]


def markdown_to_rich_content(markdown: str) -> Dict[str, Any]:
    """Compile editorial Markdown into the image-free Ricos subset we render."""
    lines = str(markdown or "").replace("\r\n", "\n").split("\n")
    nodes: List[Dict[str, Any]] = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            if nodes and nodes[-1].get("type") != "PARAGRAPH_EMPTY":
                nodes.append({"type": "PARAGRAPH_EMPTY"})
            index += 1
            continue

        if line.startswith("- "):
            items = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                value = lines[index].strip()[2:].strip()
                items.append({
                    "type": "LIST_ITEM",
                    "nodes": [{
                        "type": "PARAGRAPH",
                        "nodes": _inline_nodes(value),
                        "paragraphData": {"textStyle": {"textAlignment": "AUTO"}},
                    }],
                })
                index += 1
            nodes.append({"type": "BULLETED_LIST", "nodes": items})
            continue

        if re.match(r"^\d+\.\s+", line):
            items = []
            while index < len(lines) and re.match(r"^\d+\.\s+", lines[index].strip()):
                value = re.sub(r"^\d+\.\s+", "", lines[index].strip()).strip()
                items.append({
                    "type": "LIST_ITEM",
                    "nodes": [{
                        "type": "PARAGRAPH",
                        "nodes": _inline_nodes(value),
                        "paragraphData": {"textStyle": {"textAlignment": "AUTO"}},
                    }],
                })
                index += 1
            nodes.append({"type": "ORDERED_LIST", "nodes": items})
            continue

        if line.startswith("> "):
            value = line[2:].strip()
            nodes.append({
                "type": "BLOCKQUOTE",
                "nodes": [{
                    "type": "PARAGRAPH",
                    "nodes": _inline_nodes(value),
                    "paragraphData": {"textStyle": {"textAlignment": "AUTO"}},
                }],
            })
            index += 1
            continue

        if line.startswith("### "):
            nodes.append({
                "type": "HEADING",
                "headingData": {"level": 3},
                "nodes": _inline_nodes(line[4:].strip()),
            })
            index += 1
            continue

        if line.startswith("## "):
            nodes.append({
                "type": "HEADING",
                "headingData": {"level": 2},
                "nodes": _inline_nodes(line[3:].strip()),
            })
            index += 1
            continue

        nodes.append({
            "type": "PARAGRAPH",
            "nodes": _inline_nodes(line),
            "paragraphData": {"textStyle": {"textAlignment": "AUTO"}},
        })
        index += 1

    # Convert editorial blank-line markers to real empty Ricos paragraphs,
    # collapse duplicates, and trim them from the document edges.
    cleaned: List[Dict[str, Any]] = []
    for node in nodes:
        if node.get("type") == "PARAGRAPH_EMPTY":
            if not cleaned or cleaned[-1].get("type") == "PARAGRAPH":
                cleaned.append({"type": "PARAGRAPH"})
            elif cleaned[-1].get("type") not in {"PARAGRAPH", "PARAGRAPH_EMPTY"}:
                cleaned.append({"type": "PARAGRAPH"})
            continue
        cleaned.append(node)
    while cleaned and cleaned[0].get("type") == "PARAGRAPH" and not cleaned[0].get("nodes"):
        cleaned.pop(0)
    while cleaned and cleaned[-1].get("type") == "PARAGRAPH" and not cleaned[-1].get("nodes"):
        cleaned.pop()

    return {"nodes": cleaned}


def normalize_manifest_post(post: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(post)
    if not normalized.get("richContent") and normalized.get("contentMarkdown"):
        normalized["richContent"] = markdown_to_rich_content(
            str(normalized["contentMarkdown"])
        )
    return normalized


def walk_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_nodes(nested)


def validate_manifest_post(post: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = [
        "title",
        "sourceSlug",
        "slug",
        "sourcePublishedDate",
        "seoTitle",
        "metaDescription",
        "tags",
    ]
    for key in required:
        if not post.get(key):
            errors.append(f"missing {key}")
    if not post.get("richContent") and not post.get("contentMarkdown"):
        errors.append("missing richContent or contentMarkdown")

    if str(post.get("sourceSlug") or "").strip() == str(post.get("slug") or "").strip():
        errors.append("new slug must differ from sourceSlug")

    tags = post.get("tags") or []
    if not isinstance(tags, list) or not 1 <= len(tags) <= 3:
        errors.append("tags must contain 1-3 labels")

    for forbidden in ("heroImage", "media", "coverImage"):
        if post.get(forbidden):
            errors.append(f"{forbidden} is forbidden: blog is image-free")

    for node in walk_nodes(post.get("richContent") or {}):
        node_type = str(node.get("type") or "").upper()
        if node_type in FORBIDDEN_MEDIA_NODES:
            errors.append(f"forbidden rich-content media node: {node_type}")

    if str(post.get("authorName") or AUTHOR_NAME) != AUTHOR_NAME:
        errors.append(f"authorName must be {AUTHOR_NAME!r}")
    if str(post.get("category") or CATEGORY_LABEL) != CATEGORY_LABEL:
        errors.append(f"category must be {CATEGORY_LABEL!r}")

    return errors


def load_manifest(path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    posts = raw.get("posts") if isinstance(raw, dict) else raw
    if not isinstance(posts, list):
        raise ValueError("Manifest must be a JSON array or an object with a posts array")
    return [normalize_manifest_post(post) for post in posts]


def validate_manifest(posts: List[Dict[str, Any]]) -> None:
    seen = set()
    failures = []
    for index, post in enumerate(posts):
        slug = str(post.get("slug") or "").strip()
        errors = validate_manifest_post(post)
        if slug in seen:
            errors.append("duplicate slug inside manifest")
        seen.add(slug)
        if errors:
            failures.append((index, slug or "<missing>", errors))
    if failures:
        for index, slug, errors in failures:
            print(f"[{index}] {slug}: " + "; ".join(errors), file=sys.stderr)
        raise ValueError(f"Manifest validation failed for {len(failures)} post(s)")


def ensure_author() -> str:
    data = request(
        TARGET_SITE_ID,
        "GET",
        "/members/v1/members?fieldsets=FULL&paging.limit=100",
    )
    members = data.get("members", []) or []
    for member in members:
        if str((member.get("profile") or {}).get("nickname") or "") == AUTHOR_NAME:
            return str(member["id"])
    for member in members:
        if str(member.get("loginEmail") or "").lower() == AUTHOR_EMAIL.lower():
            updated = request(
                TARGET_SITE_ID,
                "PATCH",
                f"/members/v1/members/{member['id']}",
                {"member": {"profile": {"nickname": AUTHOR_NAME}}},
            )
            return str(updated["member"]["id"])
    created = request(
        TARGET_SITE_ID,
        "POST",
        "/members/v1/members",
        {
            "member": {
                "loginEmail": AUTHOR_EMAIL,
                "contact": {"firstName": "Anew", "lastName": "by WECARE.DIGITAL"},
                "profile": {"nickname": AUTHOR_NAME},
            }
        },
    )
    return str(created["member"]["id"])


def ensure_category() -> str:
    data = request(
        TARGET_SITE_ID, "GET", "/blog/v3/categories?paging.limit=100"
    )
    for category in data.get("categories", []) or []:
        if str(category.get("label") or "").lower() == CATEGORY_LABEL.lower():
            return str(category["id"])
    created = request(
        TARGET_SITE_ID,
        "POST",
        "/blog/v3/categories",
        {
            "category": {
                "label": CATEGORY_LABEL,
                "title": CATEGORY_LABEL,
                "slug": "conversations",
                "language": "en",
            }
        },
    )
    return str(created["category"]["id"])


def ensure_tags(labels: Iterable[str]) -> Dict[str, str]:
    data = request(
        TARGET_SITE_ID,
        "POST",
        "/v3/tags/query",
        {"query": {"cursorPaging": {"limit": 100}}},
    )
    existing = {
        str(tag.get("label") or "").lower(): str(tag.get("id") or "")
        for tag in data.get("tags", []) or []
    }
    resolved: Dict[str, str] = {}
    for label in labels:
        key = label.lower()
        if existing.get(key):
            resolved[label] = existing[key]
            continue
        created = request(
            TARGET_SITE_ID,
            "POST",
            "/v3/tags",
            {"label": label, "language": "en"},
        )
        resolved[label] = str(created["tag"]["id"])
        existing[key] = resolved[label]
    return resolved


def seo_data(post: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tags": [
            {"type": "title", "children": str(post["seoTitle"])},
            {
                "type": "meta",
                "props": {
                    "name": "description",
                    "content": str(post["metaDescription"]),
                },
            },
        ]
    }


def draft_post(
    post: Dict[str, Any],
    member_id: str,
    category_id: str,
    tag_ids: Dict[str, str],
) -> Dict[str, Any]:
    return {
        "title": str(post["title"]).strip(),
        "excerpt": str(post.get("excerpt") or post["metaDescription"]).strip(),
        "featured": False,
        "categoryIds": [category_id],
        "memberId": member_id,
        "tagIds": [tag_ids[label] for label in post.get("tags", [])],
        "hashtags": post.get("hashtags", []) or [],
        "language": "en",
        "richContent": post["richContent"],
        # Intentionally omit firstPublishedDate: these are fresh Anew posts.
        # Wix assigns the new publication date when the post is published.
        "seoSlug": str(post["slug"]).strip(),
        "seoData": seo_data(post),
    }


def chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def apply_manifest(posts: List[Dict[str, Any]], mode: str) -> None:
    validate_manifest(posts)
    existing = {str(post.get("slug") or "") for post in query_posts(TARGET_SITE_ID)}
    pending = [post for post in posts if str(post.get("slug") or "") not in existing]
    skipped = len(posts) - len(pending)
    print(
        f"Validated {len(posts)} posts; {len(pending)} new; {skipped} already exists on target"
    )
    if mode == "validate":
        print("Validation-only mode: no Wix mutation performed.")
        return

    member_id = ensure_author()
    category_id = ensure_category()
    all_labels = sorted({label for post in pending for label in post.get("tags", [])})
    tag_ids = ensure_tags(all_labels)
    prepared = [
        draft_post(post, member_id, category_id, tag_ids) for post in pending
    ]

    publish = mode == "publish"
    successes = 0
    failures = []
    for batch_number, batch in enumerate(chunks(prepared, BULK_LIMIT), start=1):
        data = request(
            TARGET_SITE_ID,
            "POST",
            "/blog/v3/bulk/draft-posts/create",
            {
                "draftPosts": batch,
                "publish": publish,
                "returnFullEntity": False,
            },
        )
        for result in data.get("results", []) or []:
            metadata = result.get("itemMetadata") or {}
            if metadata.get("success"):
                successes += 1
            else:
                failures.append(
                    {
                        "batch": batch_number,
                        "index": metadata.get("originalIndex"),
                        "error": metadata.get("error"),
                    }
                )
        print(
            f"Batch {batch_number}: "
            f"{(data.get('bulkActionMetadata') or {}).get('totalSuccesses', 0)} success, "
            f"{(data.get('bulkActionMetadata') or {}).get('totalFailures', 0)} failure"
        )

    print(f"Completed: {successes} created; {len(failures)} failed; mode={mode}")
    if failures:
        print(json.dumps(failures, indent=2), file=sys.stderr)
        raise RuntimeError("One or more Wix bulk items failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    export_parser = commands.add_parser("export")
    export_parser.add_argument("--output", type=Path, required=True)

    apply_parser = commands.add_parser("apply")
    apply_parser.add_argument("--manifest", type=Path, required=True)
    apply_parser.add_argument(
        "--mode",
        choices=("validate", "draft", "publish"),
        default="validate",
        help="Default is validate: no Wix mutation. Publish must be explicit.",
    )

    args = parser.parse_args()
    if args.command == "export":
        export_source(args.output)
        return
    posts = load_manifest(args.manifest)
    apply_manifest(posts, args.mode)


if __name__ == "__main__":
    main()
