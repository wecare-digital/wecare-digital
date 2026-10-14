"""blog_source reads the public blog from AWS only (Wix exit complete).

The Wix branch and the BLOG_SOURCE flag were removed when the Wix blog path was
retired. The contract now: every public read goes to the DynamoDB-backed storage
reader with published_only, the full corpus is never truncated at 500, and no Wix
module is imported at all.
"""
import sys
from pathlib import Path

import pytest

SEO_DIR = Path(__file__).resolve().parents[1] / "amplify/functions/operations/seo-tools"
sys.path.insert(0, str(SEO_DIR))

import blog_source  # noqa: E402


@pytest.fixture()
def spies(monkeypatch):
    calls = {"aws_list": None, "aws_slug": None}
    monkeypatch.setattr(blog_source.storage, "list_blog_posts",
                        lambda published_only=False, limit=500, include_content=True:
                        calls.__setitem__("aws_list", (published_only, limit, include_content)) or ["aws"])
    monkeypatch.setattr(blog_source.storage, "get_blog_post",
                        lambda s, published_only=False:
                        calls.__setitem__("aws_slug", (s, published_only)) or {"src": "aws"})
    return calls


def test_source_is_always_aws(monkeypatch):
    # Even with a legacy BLOG_SOURCE still set in the environment, the source is AWS.
    monkeypatch.setenv("BLOG_SOURCE", "wix")
    assert blog_source.source() == "aws"
    assert blog_source.using_aws() is True


def test_reads_route_to_storage_published_only(spies):
    assert blog_source.list_blog_posts() == ["aws"]
    assert blog_source.get_blog_post_by_slug("my-slug") == {"src": "aws"}
    # public corpus = published only; list omits heavy content and is unbounded
    assert spies["aws_list"] == (True, 0, False)
    assert spies["aws_slug"] == ("my-slug", True)


def test_no_wix_module_imported():
    """The Wix exit removed the dependency entirely."""
    assert not hasattr(blog_source, "wix"), "blog_source must not import the Wix client"


def test_complete_aws_corpus_is_not_truncated_at_500(monkeypatch):
    """Regression: the public blog must see every imported published post."""
    posts = [
        {"id": f"blog_{i}", "recordType": "blogPost", "slug": f"post-{i}",
         "title": f"Post {i}", "status": "published", "content": "Full article"}
        for i in range(1421)
    ]
    posts.append({"id": "draft_1", "recordType": "blogPost", "slug": "secret-draft",
                  "title": "Draft", "status": "draft", "content": "Hidden"})

    def paginate(index_name, key_name, key_value, limit=0, newest_first=False):
        assert (index_name, key_name, key_value) == (
            "recordType-createdAt-index", "recordType", "blogPost")
        assert limit == 0 and newest_first is True
        return posts

    monkeypatch.setattr(blog_source.storage, "query_index", paginate)
    monkeypatch.setattr(
        blog_source.storage, "list_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("public listing must not use 500-item log reader")))

    returned = blog_source.list_blog_posts()
    assert len(returned) == 1421
    assert returned[0]["slug"] == "post-0"
    assert returned[-1]["slug"] == "post-1420"
    assert all(post["slug"] != "secret-draft" for post in returned)
    assert all("content" not in post for post in returned)
