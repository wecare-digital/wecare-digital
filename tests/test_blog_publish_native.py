"""Native blog publish: BLOG_SOURCE=aws writes a published blogPost record via
storage.create_blog_post (the record the native read path serves), returning the
same {postId, postUrl} shape as the Wix writer — and never calling Wix.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEO = ROOT / "amplify/functions/operations/seo-tools"
sys.path.insert(0, str(SEO))
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

import blog_publish  # noqa: E402
import storage  # noqa: E402


def test_blog_source_flag_resolution(monkeypatch):
    monkeypatch.delenv("BLOG_SOURCE", raising=False)
    assert blog_publish._blog_source_is_aws() is False
    for val in ("aws", "AWS", "dynamodb", "native"):
        monkeypatch.setenv("BLOG_SOURCE", val)
        assert blog_publish._blog_source_is_aws() is True
    monkeypatch.setenv("BLOG_SOURCE", "wix")
    assert blog_publish._blog_source_is_aws() is False


def test_write_native_persists_published_post_and_returns_shape(monkeypatch):
    saved = {}

    def fake_create_blog_post(body, actor):
        saved["body"] = body
        saved["actor"] = actor
        assert body["status"] == "published"
        return {"postId": "blog_abc", "slug": body["slug"], "title": body["title"],
                "status": "published", "url": f"https://wecare.digital/post/{body['slug']}",
                "rebuildRequired": True}

    monkeypatch.setattr(storage, "create_blog_post", fake_create_blog_post)
    # If the native writer ever imported/called wix, the test would surface it; we assert
    # the result shape and the mapping instead.
    record = {"category": "Conversations"}
    draft = {"title": "A Native Post", "slug": "a-native-post",
             "contentMarkdown": "# Heading\n\nBody.", "seoTitle": "A Native Post | WeCare",
             "metaDescription": "A native post.", "tagLabels": ["x"], "hashtags": ["y"]}

    result = blog_publish._write_native(record, draft, actor="editor-1")

    assert result == {"postId": "blog_abc", "postUrl": "https://wecare.digital/post/a-native-post"}
    assert saved["body"]["title"] == "A Native Post"
    assert saved["body"]["content"] == "# Heading\n\nBody."
    assert saved["body"]["category"] == "Conversations"
    assert saved["body"]["tags"] == ["x"]
    assert saved["actor"] == "editor-1"
