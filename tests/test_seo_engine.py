"""The derived-SEO engine, freshness sweep and cost/AI config.

THE ONE INVARIANT THESE EXIST TO PROVE: SEO processing NEVER modifies source content. The
source object handed to the engine must be byte-identical afterwards, and the engine must write
only into its own `recordType='seo'` partition. Everything else here - idempotency, AI-off,
fail-safe - is a corollary of "this is a derived, read-only layer".

Loaded the way the deployed zip lays the modules out (siblings on sys.path), matching
tests/test_seo_blog_public_cache.py. The scheduled sweep reads through the AWS-native
`blog_source` seam.
"""
from __future__ import annotations

import copy
import importlib.util
import json
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


storage = _load("storage")
seo_config = _load("seo_config")
seo_engine = _load("seo_engine")
seo_refresh = _load("seo_refresh")


# --------------------------------------------------------------------------- #
# an in-memory stand-in for the DynamoDB resource Table storage.py uses
# --------------------------------------------------------------------------- #

class FakeTable:
    """Supports exactly the resource-Table calls seo_engine + storage.get_typed use:
    put_item(Item=...) and get_item(Key={'id': ...}). Records every write so a test can prove
    what was and was not written."""

    def __init__(self):
        self.items = {}
        self.writes = []  # every id written, in order

    def put_item(self, Item):  # noqa: N803 - boto3 kwarg name
        self.items[Item["id"]] = copy.deepcopy(Item)
        self.writes.append(Item["id"])
        return {}

    def get_item(self, Key):  # noqa: N803 - boto3 kwarg name
        item = self.items.get(Key["id"])
        return {"Item": copy.deepcopy(item)} if item is not None else {}


@pytest.fixture
def fake_table(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(storage, "table", lambda: table)
    return table


def _source_post(**overrides):
    """A public blog post in the native public-blog shape. `jsonLd` is {} on the public
    surface, matching production."""
    post = {
        "id": "abc123",
        "slug": "when-a-word-is-load-bearing",
        "title": "When a Word Is Load-Bearing",
        "excerpt": "A short, honest summary of the piece that a card and a meta tag can share.",
        "url": "https://wecare.digital/post/when-a-word-is-load-bearing/",
        "seoTitle": "",
        "metaDescription": "",
        "focusKeyword": "integrity",
        "keywords": ["integrity", "trust"],
        "jsonLd": {},
        "publishedDate": "2026-03-01T00:00:00Z",
        "modifiedDate": "2026-03-02T00:00:00Z",
        "coverImage": "https://wecare.digital/get/o/blog/cover.jpg",
        "category": "Conversations",
        "tags": ["integrity", "trust"],
        "hashtags": ["#integrity"],
        "authorName": "Anew by WECARE.DIGITAL",
        "robots": "index, follow, max-image-preview:large",
    }
    post.update(overrides)
    return post


# --------------------------------------------------------------------------- #
# THE headline invariant: source is never mutated
# --------------------------------------------------------------------------- #

class TestSourceIsReadOnly:
    def test_derive_does_not_mutate_the_source(self):
        source = _source_post()
        snapshot = copy.deepcopy(source)
        seo_engine.derive(seo_engine.ENTITY_BLOG, source)
        assert source == snapshot, "derive() mutated the source object"

    def test_refresh_does_not_mutate_the_source(self, fake_table):
        source = _source_post()
        snapshot = copy.deepcopy(source)
        seo_engine.refresh(seo_engine.ENTITY_BLOG, source)
        assert source == snapshot, "refresh() mutated the source object"

    def test_refresh_writes_only_the_seo_partition(self, fake_table):
        seo_engine.refresh(seo_engine.ENTITY_BLOG, _source_post())
        # Exactly one write, and it is a derived seo record - never a blogPost/source row.
        assert fake_table.writes == ["seo_blog_when-a-word-is-load-bearing"]
        written = fake_table.items["seo_blog_when-a-word-is-load-bearing"]
        assert written["recordType"] == seo_engine.SEO_RECORD_TYPE
        assert written["recordType"] != storage.BLOG_RECORD_TYPE

    def test_the_freshness_sweep_never_writes_a_source_record(self, fake_table, monkeypatch):
        posts = [_source_post(slug="a", id="1"), _source_post(slug="b", id="2")]
        snapshot = copy.deepcopy(posts)
        monkeypatch.setattr(seo_refresh.blog_source, "list_blog_posts", lambda: posts)
        seo_refresh.run({"seoFreshness": True})
        assert posts == snapshot, "the sweep mutated the source corpus"
        # Every id written is a derived seo record.
        assert all(wid.startswith("seo_blog_") for wid in fake_table.writes)


# --------------------------------------------------------------------------- #
# sourceHash change detection / idempotency
# --------------------------------------------------------------------------- #

class TestSourceHashIdempotency:
    def test_a_second_refresh_of_unchanged_content_writes_nothing(self, fake_table):
        source = _source_post()
        first = seo_engine.refresh(seo_engine.ENTITY_BLOG, source)
        assert first["skipped"] is False
        writes_after_first = list(fake_table.writes)

        second = seo_engine.refresh(seo_engine.ENTITY_BLOG, source)
        third = seo_engine.refresh(seo_engine.ENTITY_BLOG, source)
        assert second["skipped"] is True
        assert third["skipped"] is True
        assert fake_table.writes == writes_after_first, "an unchanged refresh wrote to the table"

    def test_a_changed_title_re_derives(self, fake_table):
        source = _source_post()
        seo_engine.refresh(seo_engine.ENTITY_BLOG, source)
        changed = _source_post(title="A New Title Entirely")
        result = seo_engine.refresh(seo_engine.ENTITY_BLOG, changed)
        assert result["skipped"] is False
        assert result["created"] is False  # same slug, so it overwrites rather than creates

    def test_an_unrelated_field_change_does_not_re_derive(self, fake_table):
        """A change to a field that does not affect SEO output must not invalidate the record -
        otherwise the skip logic stops saving anything."""
        source = _source_post()
        seo_engine.refresh(seo_engine.ENTITY_BLOG, source)
        # `hashtags` is not part of the SEO material hashed by source_hash.
        noise = _source_post(hashtags=["#totally", "#different"])
        result = seo_engine.refresh(seo_engine.ENTITY_BLOG, noise)
        assert result["skipped"] is True

    def test_force_re_derives_even_when_unchanged(self, fake_table):
        source = _source_post()
        seo_engine.refresh(seo_engine.ENTITY_BLOG, source)
        result = seo_engine.refresh(seo_engine.ENTITY_BLOG, source, force=True)
        assert result["skipped"] is False

    def test_source_hash_is_stable_across_key_order(self):
        a = _source_post()
        b = {k: a[k] for k in reversed(list(a.keys()))}
        assert seo_engine.source_hash(a) == seo_engine.source_hash(b)


# --------------------------------------------------------------------------- #
# deterministic derivation
# --------------------------------------------------------------------------- #

class TestDeterministicDerivation:
    def test_seo_title_uses_brand_template_when_source_has_none(self):
        d = seo_engine.derive(seo_engine.ENTITY_BLOG, _source_post())
        assert d["seoTitle"] == "When a Word Is Load-Bearing | WECARE.DIGITAL"

    def test_a_source_seo_title_is_used_verbatim(self):
        d = seo_engine.derive(
            seo_engine.ENTITY_BLOG, _source_post(seoTitle="Author's Own Title"))
        assert d["seoTitle"] == "Author's Own Title"

    def test_meta_description_prefers_the_source_value(self):
        d = seo_engine.derive(
            seo_engine.ENTITY_BLOG, _source_post(metaDescription="A deliberate description."))
        assert d["metaDescription"] == "A deliberate description."

    def test_meta_description_falls_back_to_excerpt(self):
        d = seo_engine.derive(seo_engine.ENTITY_BLOG, _source_post())
        assert d["metaDescription"].startswith("A short, honest summary")

    def test_blog_canonical_matches_the_live_route(self):
        d = seo_engine.derive(seo_engine.ENTITY_BLOG, _source_post(url=""))
        assert d["canonicalUrl"] == (
            "https://wecare.digital/post/when-a-word-is-load-bearing/")

    def test_json_ld_omits_unsupported_properties(self):
        """No author node when there is no author, no dates when there are none. The structured
        data must match the page, not invent facts."""
        bare = _source_post(authorName="", publishedDate="", modifiedDate="", coverImage="")
        d = seo_engine.derive(seo_engine.ENTITY_BLOG, bare)
        article = next(s for s in d["structuredData"] if s["@type"] == "BlogPosting")
        assert "author" not in article
        assert "datePublished" not in article
        assert "image" not in article
        # BreadcrumbList is always safe and present.
        assert any(s["@type"] == "BreadcrumbList" for s in d["structuredData"])

    def test_json_ld_includes_supported_properties(self):
        d = seo_engine.derive(seo_engine.ENTITY_BLOG, _source_post())
        article = next(s for s in d["structuredData"] if s["@type"] == "BlogPosting")
        assert article["datePublished"] == "2026-03-01T00:00:00Z"
        assert article["dateModified"] == "2026-03-02T00:00:00Z"
        assert article["author"]["name"] == "Anew by WECARE.DIGITAL"

    def test_deterministic_generator_is_marked(self):
        d = seo_engine.derive(seo_engine.ENTITY_BLOG, _source_post())
        assert d["generator"] == "deterministic"
        assert d["faqSuggestions"] == []  # never fabricated deterministically

    def test_unknown_entity_type_is_refused(self):
        with pytest.raises(ValueError):
            seo_engine.derive("widget", _source_post())


# --------------------------------------------------------------------------- #
# cost / AI configuration - the brief's hard defaults
# --------------------------------------------------------------------------- #

class TestCostAndAiConfig:
    def test_defaults_are_free_and_ai_off(self, monkeypatch):
        for var in ("COST_MODE", "AI_ENABLED", "ENABLE_BEDROCK_ASSIST", "FAQ_AI_GENERATION"):
            monkeypatch.delenv(var, raising=False)
        assert seo_config.cost_mode() == seo_config.COST_MODE_FREE
        assert seo_config.ai_enabled() is False
        assert seo_config.faq_ai_generation_enabled() is False

    def test_free_mode_pins_ai_off_even_if_flags_are_on(self, monkeypatch):
        monkeypatch.setenv("COST_MODE", "FREE")
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("ENABLE_BEDROCK_ASSIST", "true")
        assert seo_config.ai_enabled() is False

    def test_ai_needs_both_flags_and_a_paid_mode(self, monkeypatch):
        monkeypatch.setenv("COST_MODE", "LOW_COST")
        monkeypatch.setenv("AI_ENABLED", "true")
        monkeypatch.setenv("ENABLE_BEDROCK_ASSIST", "false")
        assert seo_config.ai_enabled() is False  # bedrock flag off
        monkeypatch.setenv("ENABLE_BEDROCK_ASSIST", "true")
        assert seo_config.ai_enabled() is True

    def test_unknown_cost_mode_falls_back_to_free(self, monkeypatch):
        monkeypatch.setenv("COST_MODE", "PLATINUM")
        assert seo_config.cost_mode() == seo_config.COST_MODE_FREE

    def test_snapshot_is_value_free(self, monkeypatch):
        monkeypatch.setenv("COST_MODE", "FREE")
        snap = seo_config.snapshot()
        assert set(snap) >= {"costMode", "aiEnabled", "faqAiGenerationEnabled"}
        # A snapshot must be safe to log: booleans and a mode string, nothing secret-shaped.
        for value in snap.values():
            assert isinstance(value, (bool, str))


# --------------------------------------------------------------------------- #
# fail-safe: the derived layer failing must not depend on / break anything upstream
# --------------------------------------------------------------------------- #

class TestFailSafe:
    def test_ai_being_disabled_still_produces_a_full_record(self, fake_table, monkeypatch):
        """With AI off (the default), refresh still writes a complete deterministic record. The
        public site never depends on AI to have SEO."""
        monkeypatch.setenv("COST_MODE", "FREE")
        result = seo_engine.refresh(seo_engine.ENTITY_BLOG, _source_post())
        assert result["skipped"] is False
        rec = fake_table.items["seo_blog_when-a-word-is-load-bearing"]
        assert rec["seoTitle"] and rec["canonicalUrl"] and rec["structuredData"]
        assert rec["generator"] == "deterministic"

    def test_one_bad_post_does_not_stall_the_sweep(self, fake_table, monkeypatch):
        posts = [
            _source_post(slug="good-1", id="1"),
            _source_post(slug="", id="2"),          # no slug -> counted as an error, skipped
            _source_post(slug="good-2", id="3"),
        ]
        monkeypatch.setattr(seo_refresh.blog_source, "list_blog_posts", lambda: posts)
        summary = seo_refresh.run({"seoFreshness": True})
        assert summary["refreshed"] == 2
        assert summary["errors"] == 1

    def test_a_freshness_event_is_recognised_only_by_shape(self):
        assert seo_refresh.is_freshness_event({"seoFreshness": True}) is True
        # An API Gateway request carries a requestContext and delivers its body as a string,
        # so it can never trip this branch.
        assert seo_refresh.is_freshness_event(
            {"seoFreshness": True, "requestContext": {"http": {}}}) is False
        assert seo_refresh.is_freshness_event({"body": "{}"}) is False

    def test_sweep_bounds_the_changed_set(self, fake_table, monkeypatch):
        posts = [_source_post(slug=f"post-{i}", id=str(i)) for i in range(5)]
        monkeypatch.setattr(seo_refresh.blog_source, "list_blog_posts", lambda: posts)
        summary = seo_refresh.run({"seoFreshness": True, "maxRefresh": 2})
        assert summary["refreshed"] == 2
        # The remaining three are reported as skipped rather than silently dropped.
        assert summary["skipped"] == 3
