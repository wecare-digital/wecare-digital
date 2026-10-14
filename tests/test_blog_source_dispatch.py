"""blog_source dispatches the public blog read to Wix (default) or AWS (flag).

These tests use synthetic stubs - no Wix call, no DynamoDB - and assert only the
routing decision, which is the whole contract of the seam. The default MUST be
Wix so merging the module is non-mutating; `BLOG_SOURCE=aws` MUST route to the
DynamoDB-backed storage reader with published_only, which is the blog cutover.
"""
import sys
from pathlib import Path

import pytest

SEO_DIR = Path(__file__).resolve().parents[1] / "amplify/functions/operations/seo-tools"
sys.path.insert(0, str(SEO_DIR))

import blog_source  # noqa: E402


@pytest.fixture()
def spies(monkeypatch):
    calls = {"wix_list": 0, "wix_slug": 0, "aws_list": None, "aws_slug": None}

    monkeypatch.setattr(blog_source.wix, "list_blog_posts",
                        lambda: calls.__setitem__("wix_list", calls["wix_list"] + 1) or ["wix"])
    monkeypatch.setattr(blog_source.wix, "get_blog_post_by_slug",
                        lambda s: calls.__setitem__("wix_slug", calls["wix_slug"] + 1) or {"src": "wix"})
    monkeypatch.setattr(blog_source.storage, "list_blog_posts",
                        lambda published_only=False, include_content=True:
                        calls.__setitem__("aws_list", (published_only, include_content)) or ["aws"])
    monkeypatch.setattr(blog_source.storage, "get_blog_post",
                        lambda s, published_only=False:
                        calls.__setitem__("aws_slug", (s, published_only)) or {"src": "aws"})
    return calls


def test_default_source_is_wix(monkeypatch, spies):
    monkeypatch.delenv("BLOG_SOURCE", raising=False)
    assert blog_source.source() == "wix"
    assert blog_source.list_blog_posts() == ["wix"]
    assert blog_source.get_blog_post_by_slug("x") == {"src": "wix"}
    assert spies["wix_list"] == 1 and spies["wix_slug"] == 1
    assert spies["aws_list"] is None and spies["aws_slug"] is None


@pytest.mark.parametrize("val", ["aws", "AWS", "dynamodb", "native"])
def test_aws_source_routes_to_storage_published_only(monkeypatch, spies, val):
    monkeypatch.setenv("BLOG_SOURCE", val)
    assert blog_source.using_aws() is True
    assert blog_source.list_blog_posts() == ["aws"]
    assert blog_source.get_blog_post_by_slug("my-slug") == {"src": "aws"}
    # public corpus = published only; list omits heavy content
    assert spies["aws_list"] == (True, False)
    assert spies["aws_slug"] == ("my-slug", True)
    assert spies["wix_list"] == 0 and spies["wix_slug"] == 0


def test_unknown_value_falls_back_to_wix(monkeypatch, spies):
    monkeypatch.setenv("BLOG_SOURCE", "banana")
    assert blog_source.source() == "wix"
    blog_source.list_blog_posts()
    assert spies["wix_list"] == 1 and spies["aws_list"] is None
