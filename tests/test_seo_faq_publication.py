"""AI-generated FAQ reaches the public site only after a human approved it.

THE CHAIN ALREADY EXISTED AND WAS CUT IN ONE PLACE. `ai.py` has generated FAQPage schema for a
while, `_run_audit` stores it as an `audit` record, the Admin surface approves or rejects it, and
`src/pages/post/[slug].tsx` already renders `post.jsonLd.faqSchema` when it has entries. The only
reason no FAQ ever appeared is that `wix.py::_blog_view` hardcodes `'jsonLd': {}` - Wix is the
post source and carries none of our schema. `faq.py` closes that gap on the `/blog-public/<slug>`
route, which is the seam the static export builds through, so the frontend changes nothing.

THE TESTS THAT MATTER MOST ARE THE REFUSALS. An audit is written with `status: 'pending_review'`.
Serving that publicly would publish unreviewed model output as structured data under the
company's name - a machine's claims about what the business says, asserted to Google and to every
LLM that reads the page. Half of this file exists to make that impossible.

WORTH SETTING EXPECTATIONS: Google deprecated FAQ rich results on 2026-05-07, a date
src/pages/grahak-os/index.tsx already records as its reason for removing FAQPage from that page.
This buys no Google rich result. FAQPage is still valid schema.org and still read by LLMs and AI
answer engines, which is the surface it is for.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEO_DIR = ROOT / "amplify/functions/operations/seo-tools"

for path in (str(SEO_DIR), str(ROOT / "amplify/functions/shared")):
    if path not in sys.path:
        sys.path.insert(0, path)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SEO_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


faq = _load("faq")


def _faq_node(question: str = "Is this a question?", answer: str = "Yes, it is."):
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": question,
             "acceptedAnswer": {"@type": "Answer", "text": answer}},
        ],
    }


def _audit(status: str, created_at: str = "2026-09-30T10:00:00Z", node=None, key="suggestedJsonLd"):
    record = {
        "id": f"audit_{status}_{created_at}",
        "recordType": "audit",
        "slug": "a-post",
        "createdAt": created_at,
        "status": status,
    }
    body = _faq_node() if node is None else node
    if key == "suggestedJsonLd":
        record["suggestedJsonLd"] = {"faqSchema": body}
    elif key == "fullAiResponse":
        record["fullAiResponse"] = {"faqSchema": body}
    elif key == "fullAiResponse.jsonLd":
        record["fullAiResponse"] = {"jsonLd": {"faqSchema": body}}
    return record


# --------------------------------------------------------------------------- #
# the refusals
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("status", ["pending_review", "rejected", "applying", "", "unknown"])
def test_only_human_approved_content_is_published(status):
    """pending_review is where EVERY audit starts, so this is the default-deny case.

    `rejected` matters just as much: a person looked at it and said no. `applying` is a transient
    lock taken mid-write - publishing from it would race a transaction that can still roll back
    to `approved`, so it is excluded rather than treated as good enough.
    """
    assert faq.approved_faq([_audit(status)]) is None


def test_approved_and_applied_are_published():
    # `applied` implies it passed `approved` first, so both mean a human said yes.
    for status in ("approved", "applied"):
        assert faq.approved_faq([_audit(status)]) is not None, status


def test_a_record_that_is_not_an_audit_is_ignored():
    # list_slug_records returns logs, blogPost records and drafts on the same slug.
    log = {**_audit("approved"), "recordType": "log"}
    assert faq.approved_faq([log]) is None


def test_no_records_at_all_is_not_an_error():
    assert faq.approved_faq([]) is None


# --------------------------------------------------------------------------- #
# validation: model output is checked, not trusted
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", [
    None, "", 0, [], {}, {"mainEntity": None}, {"mainEntity": {}}, {"mainEntity": []},
    {"mainEntity": ["not a dict"]},
    {"mainEntity": [{"name": "Q with no answer"}]},
    {"mainEntity": [{"name": "", "acceptedAnswer": {"text": "orphan answer"}}]},
    {"mainEntity": [{"name": "Q", "acceptedAnswer": {"text": ""}}]},
    {"mainEntity": [{"name": "Q", "acceptedAnswer": "a string"}]},
])
def test_unusable_shapes_publish_nothing(bad):
    """`[slug].tsx` only guards on `mainEntity.length`, so a list of unusable objects would
    still produce a script tag. An invalid JSON-LD block is reported against the page, while a
    missing one is simply absent - so the invalid case has to be caught here."""
    assert faq.normalise(bad) is None


def test_partly_valid_entries_are_kept_and_the_rest_dropped():
    node = faq.normalise({"mainEntity": [
        {"name": "Good", "acceptedAnswer": {"text": "An answer."}},
        {"name": "Bad, no answer"},
        {"name": "Also good", "acceptedAnswer": {"@type": "Answer", "text": "Another."}},
    ]})
    assert [entry["name"] for entry in node["mainEntity"]] == ["Good", "Also good"]


def test_the_node_is_rebuilt_rather_than_forwarded():
    """Only the properties named in normalise() reach the page.

    The model's object may carry extra keys or a missing @context. Rebuilding means the published
    node cannot contain anything nobody decided to publish - the same reason recipe_schema builds
    its node instead of forwarding what it found.
    """
    node = faq.normalise({
        "@type": "FAQPage",
        "sneaky": "should not survive",
        "mainEntity": [{
            "name": "Q", "acceptedAnswer": {"text": "A"},
            "upvoteCount": 9999, "author": "someone",
        }],
    })
    assert set(node) == {"@context", "@type", "mainEntity"}
    assert node["@context"] == "https://schema.org"
    assert set(node["mainEntity"][0]) == {"@type", "name", "acceptedAnswer"}
    assert set(node["mainEntity"][0]["acceptedAnswer"]) == {"@type", "text"}


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #

def test_the_newest_approved_audit_wins():
    """Re-running the generator and approving the result REPLACES what is published.

    createdAt is an ISO-8601 string from storage.now_iso(), so a string sort is chronological.
    """
    older = _audit("approved", "2026-01-01T00:00:00Z", _faq_node("Old?", "Old answer."))
    newer = _audit("approved", "2026-09-30T00:00:00Z", _faq_node("New?", "New answer."))
    for order in ([older, newer], [newer, older]):
        node = faq.approved_faq(order)
        assert node["mainEntity"][0]["name"] == "New?"


def test_an_approved_but_unusable_audit_falls_through_to_an_older_valid_one():
    # Otherwise one malformed generation would silence a perfectly good published FAQ.
    broken = _audit("approved", "2026-09-30T00:00:00Z", {"mainEntity": []})
    good = _audit("approved", "2026-01-01T00:00:00Z", _faq_node("Kept?", "Yes."))
    assert faq.approved_faq([broken, good])["mainEntity"][0]["name"] == "Kept?"


def test_a_newer_REJECTED_audit_does_not_suppress_an_older_approved_one():
    # Rejecting a new suggestion is not the same as retracting what is already approved.
    rejected = _audit("rejected", "2026-09-30T00:00:00Z", _faq_node("No?", "No."))
    approved = _audit("approved", "2026-01-01T00:00:00Z", _faq_node("Yes?", "Yes."))
    assert faq.approved_faq([rejected, approved])["mainEntity"][0]["name"] == "Yes?"


@pytest.mark.parametrize("key", ["suggestedJsonLd", "fullAiResponse", "fullAiResponse.jsonLd"])
def test_the_faq_is_found_wherever_the_generator_put_it(key):
    """Three places, because the output is stored twice and the prompt asks for `faqSchema` at
    the TOP level of the result rather than inside `jsonLd`. Reading only one of them would work
    or silently not, depending on how the model nested its reply."""
    assert faq.approved_faq([_audit("approved", key=key)]) is not None


# --------------------------------------------------------------------------- #
# attach
# --------------------------------------------------------------------------- #

def test_attach_puts_it_where_the_page_reads_it():
    # src/pages/post/[slug].tsx reads post.jsonLd.faqSchema.mainEntity - this is that path.
    post = faq.attach({"slug": "a-post", "jsonLd": {}}, [_audit("approved")])
    assert post["jsonLd"]["faqSchema"]["@type"] == "FAQPage"


def test_attach_preserves_anything_else_in_jsonLd():
    post = faq.attach(
        {"slug": "a-post", "jsonLd": {"blogPosting": {"@type": "BlogPosting"}}},
        [_audit("approved")],
    )
    assert post["jsonLd"]["blogPosting"] == {"@type": "BlogPosting"}
    assert "faqSchema" in post["jsonLd"]


def test_attach_repairs_a_non_dict_jsonLd_rather_than_throwing():
    post = faq.attach({"slug": "a-post", "jsonLd": "not a dict"}, [_audit("approved")])
    assert post["jsonLd"]["faqSchema"]["@type"] == "FAQPage"


def test_attach_adds_nothing_when_nothing_is_approved():
    post = faq.attach({"slug": "a-post", "jsonLd": {}}, [_audit("pending_review")])
    assert post["jsonLd"] == {}


def test_attach_never_raises_and_always_returns_the_post():
    """The FAQ is an enhancement to a page that has to be served either way. A malformed record
    must not turn a working published article into a 503."""
    for records in (None, "garbage", [None], [{"recordType": "audit", "status": "approved"}]):
        post = faq.attach({"slug": "a-post"}, records)  # type: ignore[arg-type]
        assert post["slug"] == "a-post"


# --------------------------------------------------------------------------- #
# the wiring, asserted against the handler source
# --------------------------------------------------------------------------- #

HANDLER = (SEO_DIR / "handler.py").read_text(encoding="utf-8")


def test_the_single_post_route_attaches_and_guards_the_query():
    """attach() cannot raise, but list_slug_records talks to DynamoDB and can. An absent FAQ is
    invisible; a 503 on a published article is not."""
    assert "faq.attach(post, storage.list_slug_records(slug))" in HANDLER
    body = HANDLER[HANDLER.index("if '/blog-public/' in path:"):]
    # The public read source is chosen by blog_source (BLOG_SOURCE flag); the LIST
    # call is the boundary between the single-post branch and the list branch.
    body = body[:body.index("posts = blog_source.list_blog_posts()")]
    assert "try:" in body and "except Exception:" in body


def test_the_LIST_route_is_not_enriched():
    """faqSchema is read by the post page alone; the index renders cards from seven fields and
    never touches it. Enriching the list would add a DynamoDB query per post to a response that
    already carries 1279 of them, for output nothing consumes."""
    listing = HANDLER[HANDLER.index("posts = blog_source.list_blog_posts()"):]
    listing = listing[:listing.index("except RuntimeError:")]
    assert "faq." not in listing


def test_a_kill_switch_can_stop_publication_without_a_code_deploy(monkeypatch):
    """SEO_FAQ_PUBLISH=0 stops serving immediately.

    Default ON is deliberate and narrow: the "off by default" rule in this architecture is for
    AI calls, which cost money, and for expensive infrastructure. This module does neither - no
    model call, no new resource, and it serves only what a human already approved. What it costs
    is one DynamoDB query on an existing on-demand table, on an index eleven other call sites
    already use. Generation stays off structurally, not by flag: ai.invoke_seo is reachable from
    one authenticated admin route and nothing schedules it.
    """
    assert faq.PUBLISH_ENABLED is True
    monkeypatch.setattr(faq, 'PUBLISH_ENABLED', False)
    post = faq.attach({"slug": "a-post", "jsonLd": {}}, [_audit("approved")])
    assert post["jsonLd"] == {}, 'the kill switch did not stop publication'
