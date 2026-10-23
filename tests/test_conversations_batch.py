"""Contract tests for the Conversations batch runner and the native blog contract it checks.

Three of these carry most of the weight:

  `test_a_record_without_human_gates_is_never_queued` - automation must not be able to
  self-certify. If that test starts passing records through, the standard is decoration.

  `test_the_runner_has_no_publish_path` - publication belongs to Blog Studio, behind its
  own sign-off and release gates. A second writer here would route around them, and the
  easiest way to grow one back is quietly, so this asserts it against the source.

  `test_audit_catches_the_wrong_body_under_the_right_slug` - metadata can match perfectly
  while the body belongs to another article, which is the failure a reader notices first.

Everything runs on plain data or a recording fake, so no test touches Lambda.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "conversations_batch.py"
sys.path.insert(0, str(ROOT / "scripts"))

import blog_ledger  # noqa: E402
import blog_quality_v2 as quality  # noqa: E402


def load_module():
    spec = importlib.util.spec_from_file_location("conversations_batch", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: A body that uses the Markdown the native post page renders: paragraphs and `## `.
GOOD_BODY = """A person gives their word and then does not honour it. The ordinary response reaches for morality: they were wrong, they should feel bad, they are not to be trusted. That reading arrives instantly and explains nothing about what actually broke.

Something was counting on the word. A schedule, a decision someone else made on the strength of it, a resource committed. The word was load-bearing. When it came out, the structure moved, and the movement is visible whether or not anybody feels guilty about it afterwards.

## What workability asks instead

Workability asks a different question from whether the person is good. It asks what became possible, and what stopped being possible. A colleague who reliably says what will happen creates a condition in which other people can plan against it. One whose word is decorative forces everybody around them to carry a private second plan, and that cost is paid quietly, in duplicated effort nobody ever logs.

Restoring a broken word is not apologising for it. An apology addresses the feeling. Restoration addresses the structure: saying plainly what was not done, acknowledging what it cost the people who were relying on it, and saying what will happen now instead. Notice how rarely that third part appears anywhere.

What appears instead is explanation, aimed at the listener's judgement rather than at the thing that broke. Explanation asks to be excused. Restoration asks what is needed. The difference is not one of tone, and a listener can usually tell which is happening within a sentence or two of the attempt beginning."""


# ── fixtures that the duplication gate accepts ──────────────────────────────────
#
# EVERY RECORD NEEDS ITS OWN BODY, TITLE AND CENTRAL DISTINCTION. Section 28 compares each
# record against the ones before it in the wave at three thresholds - 0.60 on body
# shingles, 0.80 on title tokens, 0.55 on distinction tokens - so a fixture that reuses one
# body is correctly rejected as a cosmetic rewrite. That is the gate working, and the right
# response is a better fixture rather than a suppressed check.
#
# Uniqueness is guaranteed rather than hoped for: the record number is a token in its own
# right (`shingle_hashes` splits on `[a-z0-9']+`), and it recurs every few words, so almost
# no 8-word window is shared between two records. The prose is stilted because it is
# generated; it only has to be structurally sound, not good.

#: Pool sizes are coprime and each exceeds the largest fixture wave, so two records in one
#: wave collide in at most one pool. Smaller pools produced a pair whose distinctions
#: scored 56% against a 55% threshold - the gate was right and the fixture was too narrow.
NOUNS = ("promise", "schedule", "estimate", "handover", "rehearsal", "agreement",
         "commitment", "deadline", "assurance", "undertaking", "arrangement", "pledge",
         "booking", "referral", "waiver", "invoice", "renewal", "escalation", "rollout",
         "migration", "briefing", "retainer", "shipment", "inspection", "settlement",
         "warranty", "tenancy", "subscription", "licence", "clearance", "appraisal",
         "secondment", "embargo", "moratorium", "indemnity", "covenant", "guarantee",
         "concession", "franchise", "endorsement", "certification", "accreditation",
         "attestation", "affidavit", "undertaking-note", "memorandum", "protocol")
QUALITIES = ("structural", "quiet", "load-bearing", "unnoticed", "deferred", "explicit",
             "informal", "conditional", "shared", "provisional", "standing", "implicit",
             "reciprocal", "unilateral", "verbal", "documented", "witnessed", "tacit",
             "binding", "revocable", "perpetual", "seasonal", "contingent", "layered",
             "nested", "delegated", "inherited", "assumed", "negotiated", "imposed",
             "voluntary", "reluctant", "enthusiastic", "grudging", "formalised",
             "undocumented", "rehearsed", "improvised", "habitual", "novel", "fragile",
             "durable", "elastic", "rigid", "porous", "opaque", "transparent",
             "auditable", "traceable", "reversible", "terminal", "recurring")
EFFECTS = ("planning", "trust", "sequencing", "capacity", "attention", "budget",
           "handoff", "cadence", "review", "staffing", "forecast", "queue", "backlog",
           "roadmap", "throughput", "latency", "morale", "goodwill", "credit", "runway",
           "slack", "buffer", "contingency", "overtime", "rework", "escalation-cost",
           "churn", "attrition", "onboarding", "handover-time", "coverage", "rota",
           "availability", "utilisation", "billing", "collections", "renewals",
           "retention", "reputation", "referrals", "pipeline", "conversion",
           "compliance", "audit-trail", "reporting", "reconciliation", "settlement-time",
           "float", "exposure", "concentration", "diversification", "resilience",
           "redundancy")


ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen")
TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
        "ninety")


def spell(n: int) -> str:
    """The record number as a WORD, not a digit.

    Section 22 forbids a slug ending in a number when the number is only there to force
    uniqueness, and it is right to: `-1` tells a reader nothing. Spelling it also keeps the
    token unique for the duplication sketch, so the fixture satisfies both rules at once.
    """
    if n < 20:
        return ONES[n]
    tail = ONES[n % 10] if n % 10 else ""
    return TENS[n // 10] + (f"-{tail}" if tail else "")


def _pick(pool, n: int, offset: int = 0) -> str:
    return pool[(n + offset) % len(pool)]


def distinct_slug(n: int) -> str:
    return f"when-a-{_pick(NOUNS, n)}-turns-{_pick(QUALITIES, n, 3)}-{spell(n)}"


def distinct_title(n: int) -> str:
    return (f"When a {_pick(NOUNS, n).title()} Turns "
            f"{_pick(QUALITIES, n, 3).title()}, Reading {spell(n).title()}")


def distinct_distinction(n: int) -> str:
    """Deliberately scaffolding-light.

    Section 28 compares distinctions on token overlap at 0.55, and a template made mostly
    of connective words scores high however much the nouns are varied. Four fixed tokens
    against nine varying ones keeps any two of these comfortably apart.
    """
    return (f"Reading {spell(n)}: {_pick(QUALITIES, n)} {_pick(NOUNS, n)} versus "
            f"{_pick(QUALITIES, n, 5)} {_pick(NOUNS, n, 4)}; {_pick(EFFECTS, n)} hides "
            f"{_pick(EFFECTS, n, 7)}, {_pick(EFFECTS, n, 11)} reveals "
            f"{_pick(EFFECTS, n, 3)}.")


#: Three sentence shapes of deliberately different lengths. A generator that emits one
#: shape produces near-uniform cadence, which section 15 flags - correctly, since an
#: article with no rhythm of its own reads as machine-made.
def distinct_body(n: int) -> str:
    """Five paragraphs whose vocabulary and cadence belong to record `n`."""
    word = spell(n)
    paragraphs = []
    for para in range(5):
        sentences = []
        for index in range(6):
            seed = n + para * 3 + index
            shape = (para + index) % 3
            if shape == 0:
                sentences.append(
                    f"Reading {word} treats the {_pick(NOUNS, seed)} as "
                    f"{_pick(QUALITIES, seed)}.")
            elif shape == 1:
                sentences.append(
                    f"A {_pick(QUALITIES, seed, 2)} {_pick(NOUNS, seed, 1)} in reading "
                    f"{word} carries {_pick(EFFECTS, seed, 2)}, and the "
                    f"{_pick(NOUNS, seed, 5)} moves {_pick(EFFECTS, seed, 9)} with it.")
            else:
                sentences.append(
                    f"Where reading {word} finds a {_pick(QUALITIES, seed, 6)} "
                    f"{_pick(NOUNS, seed, 7)}, the {_pick(EFFECTS, seed, 4)} it was "
                    f"holding turns out to have been {_pick(QUALITIES, seed, 8)} all "
                    f"along, which is why {_pick(EFFECTS, seed, 13)} in reading {word} "
                    f"cannot be read off the {_pick(NOUNS, seed, 9)} alone and has to be "
                    f"traced through the {_pick(EFFECTS, seed, 15)} that depended on it.")
        paragraphs.append(" ".join(sentences))
    return "\n\n".join(paragraphs)


def record(n: int = 1, *, gated: bool = True, **overrides):
    slug = distinct_slug(n)
    row = {
        "sourceId": "",
        "articleClass": "ARCHIVE_DERIVED",
        "status": "EDITORIAL_QA",
        "sourceReviewedFully": "YES",
        "sourceFile": f"sources/integrity-{n}.pdf",
        "originalSourceTitle": f"The Integrity of One's Word {n}",
        "sourceType": "pdf",
        "sourceHash": f"{n:064d}",
        "originalSourceDate": "2019-04-02",
        "title": distinct_title(n),
        "slug": slug,
        "sourceSlug": f"integrity-of-word-{n}",
        "category": "Conversations",
        "author": quality.AUTHOR,
        "canonical": f"https://wecare.digital/post/{slug}/",
        "tags": ["Integrity", "Accountability"],
        "seoTitle": f"{distinct_title(n)} | WECARE.DIGITAL",
        "metaDescription": ("Integrity read as structure rather than virtue: what an "
                            "unhonoured word actually moves, and why restoring it is not "
                            "the same as apologising."),
        "articleType": "REFLECTION",
        "imageStatus": "none",
        "centralDistinction": distinct_distinction(n),
        "distinctPurpose": ("Other Integrity articles ask whether breaking one's word is "
                            "wrong. This one asks what it moves, and separates restoration "
                            "from apology."),
        "materiallyDifferentInquiry": "YES",
        "titleOnlyDifference": "NO",
        "uniqueReaderPromise": "YES",
        "uniqueIntellectualMovement": "YES",
        "contentMarkdown": distinct_body(n),
    }
    if gated:
        row["gate"] = {name: "PASS" for name in quality.HUMAN_GATES}
    row.update(overrides)
    return row


def document(count: int = 1, *, gated: bool = True):
    return {"posts": [record(n, gated=gated) for n in range(1, count + 1)]}


def ledger_for(path: Path, records) -> "blog_ledger.Ledger":
    """A ledger holding one row per record, with the record's sourceId filled in."""
    ledger = blog_ledger.Ledger(path)
    for item in records:
        #: A PDF's identity is its bytes, not its filename, so the fixture supplies bytes.
        row, _ = ledger.register("pdf", item["sourceFile"],
                                payload=item["sourceFile"].encode("utf-8"))
        item["sourceId"] = row.sourceId
        ledger.attach_article(row.sourceId, item["slug"], item["title"], "Conversations")
    ledger.save()
    return ledger


@pytest.fixture
def mod(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "build_corpus", lambda path: quality.CorpusIndex())
    return module


def public_post(item, *, published="2026-09-29T10:00:00Z", **overrides):
    """A live post as the native `/seo-tools/blog-public/<slug>` view returns it.

    `content` is the stored Markdown, verbatim, which is what `storage.create_blog_post`
    keeps and the post page renders. No trailing slash on `url`: that is what the store
    writes for a new post.
    """
    post = {
        "id": f"blog_{item['slug'].replace('-', '')[:12]}",
        "title": item["title"],
        "slug": item["slug"],
        "excerpt": item["metaDescription"],
        "url": f"https://wecare.digital/post/{item['slug']}",
        "seoTitle": item["seoTitle"],
        "metaDescription": item["metaDescription"],
        "publishedDate": published,
        "modifiedDate": published,
        "coverImage": "",
        "status": "published",
        "category": "Conversations",
        "tags": list(item["tags"]),
        "hashtags": [],
        "authorName": quality.AUTHOR,
        "content": item["contentMarkdown"],
        "contentText": item["contentMarkdown"],
    }
    post.update(overrides)
    return post


def serve(monkeypatch, mod, live_records, *, extra_listing=()):
    """Point the audit's two reads at plain data: the listing and the single-post view."""
    by_slug = {item["slug"]: public_post(item) for item in live_records}
    listing = [{"slug": slug, "title": post["title"]} for slug, post in by_slug.items()]
    listing.extend(extra_listing)
    monkeypatch.setattr(mod, "list_public_posts", lambda: list(listing))

    def fetch(slug):
        if slug not in by_slug:
            raise RuntimeError(f"public-blog HTTP 404 for /seo-tools/blog-public/{slug}")
        return by_slug[slug]

    monkeypatch.setattr(mod, "fetch_public_post", fetch)
    return by_slug


class FakeLambda:
    """Records each invoke and answers from a `(path, event) -> (status, body)` function."""

    def __init__(self, answer):
        self.answer = answer
        self.events = []

    def invoke(self, **kwargs):
        event = json.loads(kwargs["Payload"])
        self.events.append((kwargs["FunctionName"], kwargs["InvocationType"], event))
        status, body = self.answer(event["rawPath"], event)
        envelope = {"statusCode": status, "body": json.dumps(body)}
        return {"StatusCode": 200, "Payload": io.BytesIO(json.dumps(envelope).encode())}


# ── the entry gate ──────────────────────────────────────────────────────────────

def test_a_fully_gated_record_validates_and_enters_the_queue(mod, tmp_path):
    doc = document(1)
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert report["errors"] == []
    assert report["readyToPublish"] == [doc["posts"][0]["slug"]]


def test_a_record_without_human_gates_is_never_queued(mod, tmp_path):
    """The load-bearing property: automation must not be able to self-certify.

    `blog_quality_v2` holds an ungated record at EDITORIAL_QA. This asserts the runner
    honours that rather than queueing everything a manifest happens to contain.
    """
    doc = document(1, gated=False)
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert report["errors"] == []
    assert report["readyToPublish"] == []
    assert report["byStatus"] == {"EDITORIAL_QA": 1}


def test_one_gate_answer_missing_is_enough_to_hold_the_record(mod, tmp_path):
    doc = document(1)
    del doc["posts"][0]["gate"]["VOICE"]
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert report["readyToPublish"] == []


@pytest.mark.parametrize("count", [1, 3, 37])
def test_manifest_size_is_arbitrary(mod, tmp_path, count):
    """No editorial batch size. Gastronomy's contiguous 25 is its own rule, not this one."""
    doc = document(count)
    ledger_path = tmp_path / f"ledger-{count}.json"
    ledger_for(ledger_path, doc["posts"])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert report["errors"] == []
    assert report["total"] == count
    assert len(report["readyToPublish"]) == count


def test_duplicate_slug_inside_one_manifest_is_rejected(mod, tmp_path):
    doc = document(2)
    doc["posts"][1]["slug"] = doc["posts"][0]["slug"]
    ledger_path = tmp_path / "ledger.json"
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert any("appears 2 times" in error for error in report["errors"])


def test_a_record_with_no_ledger_row_cannot_be_queued(mod, tmp_path):
    """Publishing it would lose the source-to-article link permanently."""
    doc = document(2)
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"][:1])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert any("no ledger row" in error for error in report["errors"])
    assert doc["posts"][1]["slug"] in " ".join(report["errors"])


def test_record_contract_rejects_what_the_native_store_cannot_keep(mod):
    bad = record(1, slug="Not A Slug", tags=[], seoTitle="", coverImage="x.jpg")
    errors = " ".join(mod.payload_errors(bad))
    assert "slug must be lowercase" in errors
    assert "tags must be a list of 1-3" in errors
    assert "seoTitle is required" in errors
    assert "coverImage is forbidden" in errors


def test_a_slug_the_store_would_truncate_is_rejected(mod):
    """`storage._slugify` cuts at 120, so a longer slug goes live under a different URL."""
    long_slug = "-".join(["integrity"] * 14)
    assert len(long_slug) > mod.native.SLUG_MAX_CHARS
    errors = " ".join(mod.payload_errors(record(1, slug=long_slug,
                                                canonical=f"https://wecare.digital/post/{long_slug}/")))
    assert f"cuts slugs at {mod.native.SLUG_MAX_CHARS}" in errors


def test_markdown_the_native_page_renders_is_accepted(mod):
    assert mod.payload_errors(record(1, contentMarkdown=GOOD_BODY)) == []
    rendered = mod.native.parse_blocks(GOOD_BODY + "\n- a list line\n**Bold** and *italic*.")
    assert [block.kind for block in rendered].count("heading") == 1
    assert rendered[-2].kind == "item"
    assert rendered[-1].text == "Bold and italic."


@pytest.mark.parametrize("line, finding", [
    ("#### Too deep", "heading deeper than ###"),
    ("##Squashed", "heading marker needs a space"),
    ("* starred item", "'* ' list marker"),
    ("> a quotation", "blockquote marker"),
    ("---", "horizontal rule"),
    ("| a | b |", "Markdown table"),
    ("```", "code fence"),
    ("See [the page](https://example.com).", "Markdown link"),
    ("![alt](https://example.com/a.png)", "Markdown image"),
    ("Use `code` here.", "backtick code markup"),
    ("<p>markup</p>", "raw HTML markup"),
    ("A&nbsp;gap", "unresolved HTML entity"),
    ("This is _underscored_.", "underscore emphasis"),
    ("An *unpaired marker.", "unpaired * emphasis marker"),
    ("Lost line break ## Heading", "heading marker inside a line"),
    (r"Escaped\nnewline", "literal escaped newline"),
    ("Hello {{name}}", "unsubstituted template variable"),
])
def test_body_contract_flags_markdown_the_renderer_shows_literally(mod, line, finding):
    body = distinct_body(1) + "\n\n" + line
    errors = mod.native.body_errors(body)
    assert any(finding in error for error in errors), errors
    assert any(error.endswith(f"(line {len(body.splitlines())})") for error in errors), errors


def test_validate_reports_a_body_the_native_blog_cannot_render(mod, tmp_path):
    doc = document(1)
    doc["posts"][0]["contentMarkdown"] += "\n\n#### A heading the page cannot show"
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert any("heading deeper than ###" in error for error in report["errors"])


def test_a_body_too_large_for_the_native_item_is_rejected(mod):
    body = distinct_body(1) + "\n\n" + ("x" * (mod.native.MAX_BODY_BYTES + 1))
    errors = mod.native.body_errors(body)
    assert any("the native blogPost item allows" in error for error in errors)


def test_validate_needs_no_aws_sdk(mod, monkeypatch, tmp_path):
    """The validate job holds no AWS role, so it must not need boto3 either."""
    monkeypatch.setitem(sys.modules, "boto3", None)
    doc = document(1)
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert report["errors"] == []


# ── the live read-back ──────────────────────────────────────────────────────────

def test_a_correctly_published_post_audits_clean(mod):
    item = record(1)
    assert mod.audit_post(public_post(item), item,
                          live_slug_counts={item["slug"]: 1},
                          live_title_counts={item["title"]: 1}) == []


def test_a_trailing_slash_is_not_a_url_difference(mod):
    """New posts are stored without the slash; migrated posts carry the page's own form."""
    item = record(1)
    slashed = public_post(item, url=f"https://wecare.digital/post/{item['slug']}/")
    assert mod.audit_post(slashed, item) == []
    assert mod.audit_post(public_post(item), item) == []


def test_audit_catches_metadata_and_url_drift(mod):
    item = record(1)
    public = public_post(item, title="Something Else",
                         seoTitle="Wrong | WECARE.DIGITAL",
                         metaDescription="Wrong.",
                         tags=["Integrity"],
                         category="Gastronomy",
                         coverImage="https://example.com/cover.jpg",
                         url="https://wecare.digital/blog/when-a-word-is-load-bearing-1")
    errors = " ".join(mod.audit_post(public, item))
    assert "title is" in errors
    assert "seoTitle is" in errors
    assert "metaDescription is" in errors
    assert "tags are" in errors
    assert "category is" in errors
    assert "public URL is" in errors
    assert "coverImage is set" in errors


def test_tag_case_is_not_a_tag_difference(mod):
    """The standard folds case for tag identity; a different tag still fails."""
    item = record(1)
    assert mod.audit_post(public_post(item, tags=["integrity", "ACCOUNTABILITY"]), item) == []
    errors = mod.audit_post(public_post(item, tags=["integrity", "Trust"]), item)
    assert any("tags are" in error for error in errors)


def test_audit_does_not_enforce_fixed_author_identity(mod):
    item = record(1)
    assert mod.audit_post(public_post(item, authorName="WECARE.DIGITAL"), item) == []


def test_conversations_validate_blocks_public_external_reference(mod, tmp_path):
    doc = document(1)
    doc["posts"][0]["contentMarkdown"] += "\n\nSee https://example.com/source for the original."
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert any("PUBLIC_EXTERNAL_URL" in error for error in report["errors"])


def test_conversations_validate_blocks_public_citation_language(mod, tmp_path):
    doc = document(1)
    doc["posts"][0]["contentMarkdown"] += "\n\nAccording to Example Author, the distinction begins here."
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    report = mod.validate_document(doc, manifest_path=None, ledger_path=ledger_path)
    assert any("PUBLIC_CITATION_LANGUAGE" in error for error in report["errors"])


def test_conversations_audit_blocks_live_reference_leak(mod):
    item = record(1)
    leaked = item["contentMarkdown"] + "\n\nSee https://example.com/source for details."
    errors = mod.audit_post(public_post(item, content=leaked, contentText=leaked), item)
    assert any("public-copy policy: PUBLIC_EXTERNAL_URL" in error for error in errors)


def test_audit_catches_formatting_corruption_in_the_published_body(mod):
    """The real body with each corruption signature appended.

    Built on the correct body on purpose: the length floor and the body match then pass,
    so every error reported is a formatting finding and the assertions below cannot be
    satisfied by unrelated noise.
    """
    item = record(1)
    corrupt = (item["contentMarkdown"]
               + "\n\n" + r"Tail.\n\n## Heading\t<p>html</p> &nbsp; " + '{"type": "PARAGRAPH"}'
               + " {{placeholder}} undefined"
               + "\n#### Deep heading\nAn *unpaired marker")
    errors = mod.audit_post(public_post(item, content=corrupt, contentText=corrupt), item)
    joined = " ".join(errors)
    for expected in ("literal escaped newline", "literal escaped tab",
                     "heading marker inside a line", "heading deeper than ###",
                     "unpaired * emphasis marker", "raw editor JSON", "raw HTML markup",
                     "unresolved HTML entity", "unresolved template placeholder",
                     "unsubstituted template variable"):
        assert expected in joined, expected
    assert all("published body: " in error for error in errors), errors
    assert not any("chars, expected at least" in error for error in errors)
    assert not any("wrong content is live" in error for error in errors)


def test_markdown_in_the_live_body_is_the_format_not_corruption(mod):
    """Headings and emphasis are what the native page renders; they must not fail."""
    item = record(1, contentMarkdown=GOOD_BODY + "\n\nA closing line with **weight** and "
                                              "*lean*, long enough to be ordinary prose.")
    assert mod.audit_post(public_post(item), item) == []


def test_audit_catches_the_wrong_body_under_the_right_slug(mod):
    """Metadata can match perfectly while the body belongs to another article."""
    item = record(1)
    other = distinct_body(2)
    errors = " ".join(mod.audit_post(public_post(item, content=other, contentText=other),
                                     item))
    assert "the wrong content is live under this slug" in errors


def test_audit_reports_a_live_body_that_lost_a_paragraph(mod):
    """Still recognisably this article, so it is drift rather than the wrong post."""
    item = record(1)
    shortened = "\n\n".join(item["contentMarkdown"].split("\n\n")[:-1])
    errors = " ".join(mod.audit_post(public_post(item, content=shortened,
                                                 contentText=shortened), item))
    assert "it has drifted from the approved text" in errors
    assert "the wrong content is live" not in errors


def test_an_empty_live_body_is_reported_once(mod):
    item = record(1)
    errors = mod.audit_post(public_post(item, content="", contentText=""), item)
    assert [error for error in errors if "body" in error] == [
        f"{item['slug']}: published body is empty"]


def test_audit_requires_a_fresh_publication_timestamp(mod):
    item = record(1)
    stale = mod.audit_post(public_post(item, published="2019-04-02T00:00:00Z"), item)
    assert any("not newer than the source" in error for error in stale)

    since = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    early = mod.audit_post(public_post(item, published="2026-09-29T10:00:00Z"), item,
                           published_since=since)
    assert any("predates this run" in error for error in early)

    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ahead = mod.audit_post(public_post(item, published=future), item)
    assert any("in the future" in error for error in ahead)


def test_audit_catches_a_duplicated_slug_or_title_on_the_live_site(mod):
    item = record(1)
    errors = " ".join(mod.audit_post(public_post(item), item,
                                     live_slug_counts={item["slug"]: 2},
                                     live_title_counts={item["title"]: 3}))
    assert "2 live posts share this slug" in errors
    assert "3 live posts share the title" in errors


def test_a_missing_post_is_an_audit_failure_not_a_crash(mod):
    assert mod.audit_post({}, record(1)) == [
        f"{distinct_slug(1)}: not found on the live site"]


def test_audit_marks_verified_in_the_ledger(mod, monkeypatch, tmp_path):
    doc = document(2)
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    serve(monkeypatch, mod, doc["posts"])

    report = mod.audit_document(doc, ledger_path=ledger_path)
    assert report["errors"] == []
    assert sorted(report["verified"]) == sorted(p["slug"] for p in doc["posts"])
    for row in blog_ledger.Ledger.load(ledger_path).rows:
        assert row.status == "VERIFIED"
        assert row.verifiedAt
        assert row.publishedAt == "2026-09-29T10:00:00Z"


def test_audit_reports_an_unpublished_record_rather_than_failing_it(mod, monkeypatch,
                                                                   tmp_path):
    doc = document(1)
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    serve(monkeypatch, mod, [])
    report = mod.audit_document(doc, ledger_path=ledger_path)
    assert report["errors"] == []
    assert report["notPublished"] == [doc["posts"][0]["slug"]]
    assert all(row.status != "VERIFIED"
               for row in blog_ledger.Ledger.load(ledger_path).rows)


def test_audit_counts_duplicates_from_the_whole_live_listing(mod, monkeypatch, tmp_path):
    doc = document(1)
    item = doc["posts"][0]
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    serve(monkeypatch, mod, doc["posts"],
          extra_listing=[{"slug": "an-older-post", "title": item["title"]}])
    report = mod.audit_document(doc, ledger_path=ledger_path)
    assert any("2 live posts share the title" in error for error in report["errors"])
    assert report["verified"] == []


def test_a_failed_read_back_is_an_error_for_that_record(mod, monkeypatch, tmp_path):
    doc = document(1)
    ledger_path = tmp_path / "ledger.json"
    ledger_for(ledger_path, doc["posts"])
    serve(monkeypatch, mod, [], extra_listing=[{"slug": doc["posts"][0]["slug"],
                                                "title": doc["posts"][0]["title"]}])
    report = mod.audit_document(doc, ledger_path=ledger_path)
    assert [error.split(":")[0] for error in report["errors"]] == [doc["posts"][0]["slug"]]
    assert "read-back failed" in report["errors"][0]


# ── the read route ──────────────────────────────────────────────────────────────

def test_the_read_back_is_a_get_on_the_public_route(mod):
    item = record(1)
    fake = FakeLambda(lambda path, event: (200, {"ok": True, "post": public_post(item)}))
    post = mod.native.fetch_public_post(item["slug"], client=fake)
    assert post["slug"] == item["slug"]
    (function, invocation, event), = fake.events
    assert function == "wecare-seo-tools"
    assert invocation == "RequestResponse"
    assert event["requestContext"]["http"]["method"] == "GET"
    assert event["rawPath"] == f"/seo-tools/blog-public/{item['slug']}"


def test_the_listing_asks_only_for_the_fields_it_needs(mod):
    fake = FakeLambda(lambda path, event: (200, {"ok": True, "total": 1,
                                                 "posts": [{"slug": "a", "title": "A"}]}))
    assert mod.native.list_public_posts(client=fake) == [{"slug": "a", "title": "A"}]
    (_, _, event), = fake.events
    assert event["rawPath"] == "/seo-tools/blog-public"
    assert event["queryStringParameters"] == {"fields": "slug,title"}


def test_a_truncated_listing_is_refused(mod):
    """A short corpus hides duplicates and makes live posts look unpublished."""
    fake = FakeLambda(lambda path, event: (200, {"ok": True, "total": 3,
                                                 "posts": [{"slug": "a", "title": "A"}]}))
    with pytest.raises(RuntimeError, match="returned 1 of 3"):
        mod.native.list_public_posts(client=fake)


def test_a_missing_post_raises_from_the_read_route(mod):
    fake = FakeLambda(lambda path, event: (404, {"ok": False, "error": "Blog post not found"}))
    with pytest.raises(RuntimeError, match="HTTP 404"):
        mod.native.fetch_public_post("not-live", client=fake)


def test_the_read_helper_refuses_any_route_but_the_public_one(mod):
    fake = FakeLambda(lambda path, event: (200, {"ok": True}))
    with pytest.raises(ValueError, match="not on the public read route"):
        mod.native.invoke_public("/seo-tools/blog-publish/release", client=fake)
    assert fake.events == []


# ── no publish path, asserted against the source ────────────────────────────────

def test_the_runner_has_no_publish_path(mod):
    """Publication belongs to Blog Studio. Nothing here may write a post or hold a secret."""
    with pytest.raises(SystemExit) as refused:
        mod.main(["publish", "--manifest", "unused.json"])
    assert refused.value.code == 2
    assert not hasattr(mod, "publish_document")

    for path in (SCRIPT, ROOT / "scripts" / "blog_native_contract.py"):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("import urllib", "import requests", "http.client",
                          "get_secret_value", "secretsmanager", "Authorization",
                          "put_item", "update_item", "put_object", "create_blog_post(",
                          "/blog-publish"):
            assert forbidden not in source, f"{forbidden} in {path.name}"


def test_build_corpus_excludes_the_manifest_from_itself(tmp_path, monkeypatch):
    """Without this a committed record collides with its own committed copy."""
    module = load_module()
    manifest = tmp_path / "CONV-001.json"
    manifest.write_text(json.dumps(document(1)), encoding="utf-8")
    monkeypatch.setattr(quality, "DEFAULT_CORPUS", (str(manifest),))
    monkeypatch.setattr(quality.CorpusIndex, "load_published_index",
                        lambda self, *a, **k: None)
    corpus = module.build_corpus(manifest)
    assert len(corpus) == 0
