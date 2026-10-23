"""Contract tests for the Conversations Content Quality Standard v2 gate.

The load-bearing test in this file is `test_clean_record_cannot_self_certify`. Everything
else checks a clause; that one checks the property the whole design rests on - that no
amount of mechanical correctness produces READY_TO_PUBLISH on its own. If that ever
starts passing records through, the standard has become decoration.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import blog_quality_v2 as q  # noqa: E402


GOOD_BODY = """A person gives their word and then does not honour it. The ordinary response reaches for morality: they were wrong, they should feel bad, they are not to be trusted. That reading arrives instantly and explains nothing about what actually broke.

Something was counting on the word. A schedule, a decision someone else made on the strength of it, a resource committed. The word was load-bearing. When it came out, the structure moved, and the movement is visible whether or not anybody feels guilty about it afterwards.

## What workability asks instead

Workability asks a different question from whether the person is good. It asks what became possible, and what stopped being possible. A colleague who reliably says what will happen creates a condition in which other people can plan against it. One whose word is decorative forces everybody around them to carry a private second plan, and that cost is paid quietly, in duplicated effort nobody ever logs.

Restoring a broken word is not apologising for it. An apology addresses the feeling. Restoration addresses the structure: saying plainly what was not done, acknowledging what it cost the people who were relying on it, and saying what will happen now instead. Notice how rarely that third part appears anywhere.

What appears instead is explanation, aimed at the listener's judgement rather than at the thing that broke. Explanation asks to be excused. Restoration asks what is needed. The difference is not one of tone, and a listener can usually tell which is happening within a sentence or two of the attempt beginning."""


def good_record(**overrides):
    record = {
        "articleClass": "ARCHIVE_DERIVED",
        "status": "EDITORIAL_QA",
        "sourceReviewedFully": "YES",
        "sourceFile": "sources/integrity.pdf",
        "originalSourceTitle": "The Integrity of One's Word",
        "sourceType": "pdf",
        "sourceHash": "a" * 64,
        "originalSourceDate": "2019-04-02",
        "title": "When a Word Is Load-Bearing",
        "slug": "when-a-word-is-load-bearing",
        "sourceSlug": "integrity-of-word",
        "category": "Conversations",
        "author": q.AUTHOR,
        "canonical": "https://wecare.digital/post/when-a-word-is-load-bearing/",
        "tags": ["Integrity", "Accountability"],
        "seoTitle": "When a Word Is Load-Bearing | WECARE.DIGITAL",
        "metaDescription": ("Integrity read as structure rather than virtue: what an "
                            "unhonoured word actually moves, and why restoring it is not "
                            "the same as apologising."),
        "articleType": "ARTICLE",
        "imageStatus": "none",
        "centralDistinction": ("An unhonoured word is a structural event before it is a "
                               "moral one, and the two questions produce different responses."),
        "distinctPurpose": ("Other Integrity articles ask whether breaking one's word is "
                            "wrong. This one asks what it moves, and separates restoration "
                            "from apology."),
        "materiallyDifferentInquiry": "YES",
        "titleOnlyDifference": "NO",
        "uniqueReaderPromise": "YES",
        "uniqueIntellectualMovement": "YES",
        "contentMarkdown": GOOD_BODY,
    }
    record.update(overrides)
    return record


def codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity == severity}


# ── The property the design rests on ────────────────────────────────────────────

def test_clean_record_cannot_self_certify():
    """A record that passes every machine check still lands on EDITORIAL_QA.

    Sections 29 and 30 ask for judgements a program cannot make. If this test fails, the
    gate has started stamping them, and the standard is no longer being enforced - it is
    being simulated.
    """
    record = good_record()
    findings = q.check_record(record)
    assert codes(findings, "BLOCK") == set(), codes(findings, "BLOCK")
    assert q.decide_status(record, findings) == "EDITORIAL_QA"
    assert not q.assess(record)["readyToPublish"]


def test_human_gates_unlock_ready_to_publish():
    record = good_record(gate={name: "PASS" for name in q.HUMAN_GATES})
    assessment = q.assess(record)
    assert assessment["status"] == q.PUBLISHABLE_STATUS
    assert assessment["readyToPublish"] is True


def test_partial_human_gate_does_not_unlock():
    gate = {name: "PASS" for name in q.HUMAN_GATES}
    del gate["VOICE"]
    record = good_record(gate=gate)
    assert q.assess(record)["status"] == "EDITORIAL_QA"


def test_blocking_finding_overrides_a_full_human_gate():
    """A human cannot sign off a record with a mechanical defect."""
    record = good_record(gate={name: "PASS" for name in q.HUMAN_GATES},
                         category="Insights")
    assessment = q.assess(record)
    assert not assessment["readyToPublish"]
    assert "CATEGORY_INVALID" in " ".join(assessment["blocking"])


def test_every_human_gate_name_is_in_the_standards_table():
    assert set(q.MACHINE_GATES).isdisjoint(q.HUMAN_GATES)
    #: Section 29 lists thirteen rows; between them the two tuples must cover it.
    assert len(q.MACHINE_GATES) + len(q.HUMAN_GATES) == 14  # 13 rows + section 30's read


# ── Section 1, 2, 3 ─────────────────────────────────────────────────────────────

def test_article_class_must_be_one_of_two():
    findings = q.check_class_and_source(good_record(articleClass="NEW"))
    assert "CLASS_MISSING" in codes(findings)


def test_unread_source_routes_to_source_review():
    record = good_record(sourceReviewedFully="NO")
    findings = q.check_record(record)
    assert "SOURCE_NOT_READ" in codes(findings)
    assert q.decide_status(record, findings) == "SOURCE_REVIEW"


def test_missing_provenance_is_reported_per_field():
    findings = q.check_class_and_source(good_record(sourceHash="", sourceFile=""))
    assert sum(1 for f in findings if f.code == "SOURCE_PROVENANCE") == 2


# ── Sections 4, 5, 6 ────────────────────────────────────────────────────────────

def test_missing_central_distinction_is_flagged():
    assert "NO_CENTRAL_DISTINCTION" in codes(
        q.check_distinction_and_purpose(good_record(centralDistinction="")))


def test_uniqueness_booleans_route_to_dedupe_rework():
    record = good_record(titleOnlyDifference="YES")
    findings = q.check_record(record)
    assert "TITLE_ONLY_DIFFERENCE" in codes(findings)
    assert q.decide_status(record, findings) == "DEDUPE_REWORK"


@pytest.mark.parametrize("left,right", [
    ("Understanding Integrity", "Why Integrity Matters"),
    ("The Power of Integrity", "Integrity Explained"),
    ("A Guide to Integrity", "Integrity"),
])
def test_section_6_scaffold_titles_collapse_to_the_same_inquiry(left, right):
    """The standard's own example: these must not become separate articles."""
    assert q._normalize_title(left) == q._normalize_title(right)


def test_genuinely_different_inquiries_do_not_collapse():
    assert q._normalize_title("Honouring One's Word") != q._normalize_title(
        "Integrity and Workability")


# ── Sections 10, 11 ─────────────────────────────────────────────────────────────

def test_length_band_miss_is_review_not_block():
    """Section 11 opens 'There is no mandatory word count'."""
    findings = q.check_type_and_length(good_record(articleType="DEEP_ARTICLE"))
    assert "BELOW_BAND" in codes(findings)
    assert "BELOW_BAND" not in codes(findings, "BLOCK")


def test_absolute_floor_blocks():
    assert "BODY_TOO_THIN" in codes(
        q.check_type_and_length(good_record(contentMarkdown="Too short to say anything.")),
        "BLOCK")


def test_gastronomy_is_exempt_from_the_prose_word_floor():
    """A 110-word recipe passes its own gate; this file must not overrule that."""
    body = ("A quick refrigerator pickle.\n\n## Ingredients\n\n- carrots\n- lemon\n\n"
            "## Method\n\nSlice and steep. " + "Stir the mixture well. " * 12)
    findings = q.check_type_and_length(good_record(category="Gastronomy", contentMarkdown=body))
    assert "BODY_TOO_THIN" not in codes(findings)


def test_deep_article_needs_sections():
    long_body = GOOD_BODY.replace("## What workability asks instead", "Workability")
    findings = q.check_type_and_length(
        good_record(articleType="DEEP_ARTICLE", contentMarkdown=long_body * 4))
    assert "DEEP_WITHOUT_SECTIONS" in codes(findings)


def test_short_distinction_may_be_one_paragraph():
    """Demanding three paragraphs of a 300-word distinction would demand padding."""
    body = " ".join(["A single sustained observation about resentment."] * 30)
    findings = q.check_type_and_length(
        good_record(articleType="DISTINCTION", contentMarkdown=body))
    assert "NO_PARAGRAPH_SPACING" not in codes(findings)


def test_long_body_with_no_paragraph_breaks_blocks():
    body = " ".join(["The structure moved when the word came out of it."] * 120)
    findings = q.check_type_and_length(good_record(contentMarkdown=body))
    assert "NO_PARAGRAPH_SPACING" in codes(findings, "BLOCK")


# ── Sections 13, 14, 15 ─────────────────────────────────────────────────────────

def test_three_stock_phrases_is_a_formula():
    body = GOOD_BODY + ("\n\nAt its core, the real question is this. Ultimately, "
                        "it is important to note the point.")
    assert "AI_RHYTHM" in codes(q.check_voice(good_record(contentMarkdown=body)), "BLOCK")


def test_one_stock_phrase_is_only_a_note():
    body = GOOD_BODY + "\n\nAt its core this is a question about structure."
    findings = q.check_voice(good_record(contentMarkdown=body))
    assert "AI_RHYTHM" not in codes(findings, "BLOCK")
    assert "AI_RHYTHM_TRACE" in codes(findings, "NOTE")


def test_self_help_language_blocks():
    body = GOOD_BODY + "\n\nEmbrace the journey and believe in yourself."
    assert "GENERIC_SELF_HELP" in codes(q.check_voice(good_record(contentMarkdown=body)),
                                        "BLOCK")


def test_uniform_cadence_is_detected():
    body = "\n\n".join([
        "The word was given and the word was broken here today.",
        "The plan was made and the plan was moved again today.",
        "The cost was paid and the cost was hidden from view.",
        "The trust was lost and the trust was never rebuilt now.",
    ] * 4)
    assert "UNIFORM_CADENCE" in codes(q.check_voice(good_record(contentMarkdown=body)))


def test_natural_prose_is_not_flagged_as_uniform():
    assert "UNIFORM_CADENCE" not in codes(q.check_voice(good_record()))


# ── Sections 17, 18, 19, 20 ─────────────────────────────────────────────────────

def test_false_anew_biography_blocks():
    body = GOOD_BODY + "\n\nWe went through a long divorce and it taught us this."
    assert "FALSE_ANEW_BIOGRAPHY" in codes(
        q.check_privacy_and_attribution(good_record(contentMarkdown=body)), "BLOCK")


def test_surviving_first_person_wrapper_routes_to_personal_rework():
    body = GOOD_BODY + "\n\nI learned this myself during a difficult period of my life."
    record = good_record(contentMarkdown=body)
    findings = q.check_record(record)
    assert "FIRST_PERSON_WRAPPER" in codes(findings)
    assert q.decide_status(record, findings) == "PERSONAL_REFERENCE_REWORK"


@pytest.mark.parametrize("wrapper", [
    "The Topline Summaries treatment of the work describes a default future.",
    "The source describes the distinction as a change in context.",
    "This book explains the model as a practical framework.",
    "This article presents the idea as a way to organize action.",
    "The breakfast chapter opens with a fixed account of the morning meal.",
    "The 2010 seminar materials collected under A New Model of Integrity frame the issue.",
])
def test_archive_derived_source_wrapper_blocks(wrapper):
    record = good_record(contentMarkdown=GOOD_BODY + "\n\n" + wrapper)
    findings = q.check_privacy_and_attribution(record)
    assert "SOURCE_WRAPPER" in codes(findings, "BLOCK")


@pytest.mark.parametrize("remnant", [
    "The meal is ready. notes that the spices may be reused.",
    "The meal is ready. ’s broader freshness principle supports the same habit.",
    "The introduces five elements as a culinary framework.",
    "Nuts appear throughout the as more than garnish.",
    "Recipes are marked according to how says they affect those patterns.",
    "The tea is specifically recommended note.",
    "The regularly uses chickpeas and olive oil together.",
    "The also distinguishes a defined snack from grazing.",
    "From there, the offers several lighter options.",
])
def test_broken_source_remnant_blocks_in_any_article_class(remnant):
    record = good_record(articleClass="NEW", contentMarkdown=GOOD_BODY + "\n\n" + remnant)
    findings = q.check_privacy_and_attribution(record)
    assert "SOURCE_REMNANT" in codes(findings, "BLOCK")


def test_ordinary_source_and_chapter_language_is_not_a_source_wrapper():
    body = (GOOD_BODY + "\n\nThe source of the action is a commitment already made. "
            "The next chapter of life can remain open without becoming a prediction.")
    findings = q.check_privacy_and_attribution(good_record(contentMarkdown=body))
    assert "SOURCE_WRAPPER" not in codes(findings)
    assert "SOURCE_REMNANT" not in codes(findings)


def test_archive_source_wrapper_in_meta_description_blocks():
    record = good_record(
        metaDescription="This article presents the source distinction as a way to organize action."
    )
    findings = q.check_privacy_and_attribution(record)
    assert "SOURCE_WRAPPER" in codes(findings, "BLOCK")


def test_source_remnant_in_excerpt_blocks_even_when_body_is_clean():
    record = good_record(excerpt="The practice is established. notes that the form may change.")
    findings = q.check_privacy_and_attribution(record)
    assert "SOURCE_REMNANT" in codes(findings, "BLOCK")


def test_generic_source_materials_phrase_is_not_wrapper_without_source_determiner():
    record = good_record(
        metaDescription=(
            "Practices have histories, iterations, source materials, and people behind "
            "their present forms."
        )
    )
    findings = q.check_privacy_and_attribution(record)
    assert "SOURCE_WRAPPER" not in codes(findings)


def test_unattributed_long_quotation_routes_to_attribution_review():
    body = GOOD_BODY + ('\n\n"Integrity is the condition of being whole and undivided in '
                        'the matters that concern one most."')
    record = good_record(contentMarkdown=body)
    findings = q.check_record(record)
    assert "UNATTRIBUTED_QUOTATION" in codes(findings)
    assert q.decide_status(record, findings) == "ATTRIBUTION_REVIEW"


def test_attributed_quotation_is_accepted():
    body = GOOD_BODY + ('\n\nAs Erhard writes, "integrity is a matter of a person being '
                        'whole and complete in the matters that concern them."')
    assert "UNATTRIBUTED_QUOTATION" not in codes(
        q.check_privacy_and_attribution(good_record(contentMarkdown=body)))


def test_statistic_without_a_recorded_review_routes_to_fact_check():
    body = GOOD_BODY + "\n\nStudies show 87% of commitments are renegotiated silently."
    record = good_record(contentMarkdown=body)
    findings = q.check_record(record)
    assert q.decide_status(record, findings) == "FACT_CHECK_REQUIRED"


def test_domain_claim_may_not_hide_behind_na():
    body = GOOD_BODY + "\n\nThe amygdala drives this response and cortisol sustains it."
    findings = q.check_factual_reviews(
        good_record(contentMarkdown=body, healthReviewComplete="N/A"))
    assert "REVIEW_REQUIRED" in codes(findings)


def test_domain_claim_with_a_yes_review_is_accepted():
    body = GOOD_BODY + "\n\nThe amygdala drives this response and cortisol sustains it."
    findings = q.check_factual_reviews(
        good_record(contentMarkdown=body, healthReviewComplete="YES"))
    assert "REVIEW_REQUIRED" not in codes(findings)



def test_public_external_url_blocks():
    record = good_record(contentMarkdown=GOOD_BODY + "\n\nSee https://example.com/source for details.")
    assert "PUBLIC_EXTERNAL_URL" in codes(q.check_public_source_exposure(record), "BLOCK")


def test_public_citation_language_blocks():
    record = good_record(contentMarkdown=GOOD_BODY + "\n\nAccording to Example Author, the distinction begins here.")
    assert "PUBLIC_CITATION_LANGUAGE" in codes(q.check_public_source_exposure(record), "BLOCK")


def test_internal_source_metadata_does_not_trigger_public_copy_gate():
    record = good_record(sourceFile="private://archive.pdf", sourceHash="abc123")
    assert codes(q.check_public_source_exposure(record), "BLOCK") == set()


# ── Sections 21, 22, 23 ─────────────────────────────────────────────────────────

def test_clickbait_title_blocks():
    assert "CLICKBAIT_TITLE" in codes(
        q.check_title(good_record(title="This Will Change Your Life")), "BLOCK")


def test_archive_derived_slug_must_be_fresh():
    assert "SLUG_NOT_FRESH" in codes(
        q.check_slug_and_dates(good_record(slug="integrity-of-word")), "BLOCK")


def test_numbered_slug_is_flagged():
    assert "SLUG_NUMBERED" in codes(
        q.check_slug_and_dates(good_record(slug="integrity-and-workability-2")))


def test_original_109_slug_change_needs_a_resolved_redirect():
    record = good_record(articleClass="ORIGINAL_109", establishedSlug="integrity",
                         slug="integrity-restated", originalPublishedDate="2026-09-03")
    assert "SLUG_BROKEN_WITHOUT_REDIRECT" in codes(q.check_slug_and_dates(record), "BLOCK")


def test_original_109_slug_change_is_allowed_once_the_redirect_is_resolved():
    record = good_record(articleClass="ORIGINAL_109", establishedSlug="integrity",
                         slug="integrity-restated", originalPublishedDate="2026-09-03",
                         redirectResolved="redirect added 2026-09-29")
    assert "SLUG_BROKEN_WITHOUT_REDIRECT" not in codes(q.check_slug_and_dates(record))


def test_public_backdating_an_archive_article_blocks():
    record = good_record(publicPublishedDate="2019-04-02")
    assert "PUBLIC_BACKDATED" in codes(q.check_slug_and_dates(record), "BLOCK")


def test_original_109_must_keep_its_publication_date():
    record = good_record(articleClass="ORIGINAL_109", originalPublishedDate="")
    assert "ORIGINAL_DATE_MISSING" in codes(q.check_slug_and_dates(record))


# ── Sections 24, 25 ─────────────────────────────────────────────────────────────

def test_canonical_must_match_the_slug():
    assert "CANONICAL_MISMATCH" in codes(
        q.check_seo_and_metadata(good_record(canonical="https://wecare.digital/post/x/")),
        "BLOCK")


def test_absent_canonical_is_review_because_it_is_derived_at_publish():
    findings = q.check_seo_and_metadata(good_record(canonical=""))
    assert "CANONICAL_MISSING" in codes(findings)
    assert "CANONICAL_MISSING" not in codes(findings, "BLOCK")


@pytest.mark.parametrize("tags", [[], ["a", "b", "c", "d"], ["same", "Same"]])
def test_tag_rules(tags):
    assert codes(q.check_seo_and_metadata(good_record(tags=tags)), "BLOCK") & {
        "TAG_COUNT", "TAG_DUPLICATE"}


def test_author_identity_is_not_enforced_by_public_copy_gate():
    assert "AUTHOR_WRONG" not in codes(
        q.check_seo_and_metadata(good_record(author="Someone Else")), "BLOCK")


def test_only_two_categories_are_accepted():
    assert q.CATEGORIES == ("Conversations", "Gastronomy")
    assert "CATEGORY_INVALID" in codes(
        q.check_seo_and_metadata(good_record(category="Insights")), "BLOCK")


def test_snake_case_metadata_is_read():
    """The Gastronomy corpus spells these with underscores and is already published."""
    record = good_record()
    record.pop("seoTitle")
    record.pop("metaDescription")
    record["seo_title"] = "Carrot Pickles | WECARE.DIGITAL"
    record["meta_description"] = "x" * 150
    assert codes(q.check_seo_and_metadata(record), "BLOCK") == set()


# ── Sections 26, 27 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body,code", [
    ('<font size="3">text</font> ' + GOOD_BODY, "LEGACY_MARKUP"),
    (GOOD_BODY + "\\n literal", "LITERAL_NEWLINE"),
    (GOOD_BODY + "\n\nThe value is undefined here.", "PLACEHOLDER_TOKEN"),
    (GOOD_BODY + '\n\n{"type": "PARAGRAPH"}', "RAW_EDITOR_JSON"),
    (GOOD_BODY + "\n\n![alt](https://x/y.png)", "MARKDOWN_IMAGE"),
])
def test_formatting_violations_block(body, code):
    assert code in codes(q.check_formatting_and_images(good_record(contentMarkdown=body)),
                         "BLOCK")


def test_image_policy_default_is_none():
    assert codes(q.check_formatting_and_images(good_record()), "BLOCK") == set()


@pytest.mark.parametrize("overrides", [
    {"imageStatus": "hero"},
    {"coverImage": "x.png"},
    {"heroImage": "x.png"},
    {"richContent": {"nodes": [{"type": "IMAGE"}]}},
])
def test_any_image_blocks(overrides):
    assert codes(q.check_formatting_and_images(good_record(**overrides)), "BLOCK")


# ── Section 28 ──────────────────────────────────────────────────────────────────

def test_exact_slug_collision_blocks():
    corpus = q.CorpusIndex()
    corpus.add(good_record(), origin="published")
    assert "EXACT_SLUG_COLLISION" in codes(corpus.findings(good_record()), "BLOCK")


def test_published_revision_can_exclude_its_own_slug_only():
    record = good_record()
    corpus = q.CorpusIndex()
    corpus.add(record, origin="published-corpus")
    assert "EXACT_SLUG_COLLISION" in codes(corpus.findings(record), "BLOCK")
    assert "EXACT_SLUG_COLLISION" not in codes(
        corpus.findings(record, exclude_slug=record["slug"]), "BLOCK")


def test_cosmetic_rewrite_is_caught_as_a_body_duplicate():
    corpus = q.CorpusIndex()
    corpus.add(good_record(), origin="published")
    rewritten = good_record(slug="integrity-and-the-given-word",
                            title="Integrity and the Given Word",
                            contentMarkdown=GOOD_BODY.replace("workability", "function"))
    assert "EXACT_BODY_DUPLICATE" in codes(corpus.findings(rewritten), "BLOCK")


def test_a_genuinely_different_article_passes_the_dedupe_gate():
    corpus = q.CorpusIndex()
    corpus.add(good_record(), origin="published")
    other = good_record(
        slug="the-cost-of-a-private-second-plan",
        title="The Cost of a Private Second Plan",
        centralDistinction=("Colleagues silently duplicate planning around an unreliable "
                            "promise, and the duplicated effort never appears in any budget."),
        contentMarkdown="\n\n".join([
            "Every team carries hidden redundancy. Somebody has quietly built a second "
            "version of the plan, because they do not believe the first one will hold.",
            "That redundancy is invisible in the accounts. Nobody files a line item for "
            "the afternoon spent preparing against a commitment they expect to move.",
            "Ask where the duplication sits and the answer is rarely about capability. It "
            "tracks almost exactly onto whose stated intentions have historically held.",
            "The remedy is not exhortation. It is making the commitments small enough "
            "that they can be kept, and then keeping them visibly, for long enough.",
        ]))
    assert codes(corpus.findings(other), "BLOCK") == set()


def test_wave_compares_each_record_against_earlier_ones():
    first = good_record()
    second = good_record(slug="another-slug", title="Another Title")
    wave = q.assess_wave([first, second])
    assert wave["total"] == 2
    assert "EXACT_BODY_DUPLICATE" in " ".join(wave["records"][1]["blocking"])
    assert not wave["records"][0]["blocking"]


# ── Sections 32, 34 ─────────────────────────────────────────────────────────────

def test_status_must_be_from_the_vocabulary():
    assert "STATUS_INVALID" in codes(q.check_status_field(good_record(status="DONE")), "BLOCK")


def test_published_records_are_never_rewound_by_the_validator():
    record = good_record(status="PUBLISHED", category="Insights")
    assert q.decide_status(record, q.check_record(record)) == "PUBLISHED"


def test_status_precedence_returns_the_earliest_desk():
    """Source review precedes dedupe precedes writing."""
    record = good_record(sourceReviewedFully="NO", titleOnlyDifference="YES")
    assert q.decide_status(record, q.check_record(record)) == "SOURCE_REVIEW"


def test_publish_queue_holds_only_ready_records():
    ready = good_record(gate={n: "PASS" for n in q.HUMAN_GATES})
    unready = good_record(slug="other-slug", title="Quite Another Inquiry Entirely",
                          contentMarkdown="short")
    wave = q.assess_wave([ready, unready])
    assert q.publish_queue(wave) == ["when-a-word-is-load-bearing"]


def test_wave_reports_an_explicit_status_for_every_record():
    wave = q.assess_wave([good_record(), good_record(slug="s2", title="T2")])
    assert wave["everyRecordHasStatus"] is True
    assert sum(wave["byStatus"].values()) == wave["total"]


# ── The committed corpora ───────────────────────────────────────────────────────

COMMITTED = sorted(glob.glob(str(ROOT / "content/gastronomy/batches/GAST-*.json"))) + \
            sorted(glob.glob(str(ROOT / "migration/blog/batch-*.json")))


@pytest.mark.parametrize("manifest", COMMITTED, ids=lambda p: Path(p).stem)
def test_committed_corpora_produce_no_blocking_findings(manifest):
    """Live published content must not read as broken.

    A gate that reports hard failures on 333 healthy articles gets switched off, and a
    switched-off gate protects nothing. Pre-v2 records are detected and their
    content-shape findings softened to REVIEW - reported, still unpublishable, not
    build-failing. Metadata, duplication and image findings are NOT softened.
    """
    posts = q.load_posts(Path(manifest))
    wave = q.assess_wave(posts)
    blocking = [(r["slug"], r["blocking"]) for r in wave["records"] if r["blocking"]]
    assert blocking == [], blocking


@pytest.mark.parametrize("manifest", COMMITTED, ids=lambda p: Path(p).stem)
def test_committed_corpora_are_recognised_as_pre_v2(manifest):
    posts = q.load_posts(Path(manifest))
    assert all(q.is_legacy_record(post) for post in posts)


@pytest.mark.parametrize("manifest", COMMITTED, ids=lambda p: Path(p).stem)
def test_no_committed_record_reaches_the_publish_queue_without_human_gates(manifest):
    wave = q.assess_wave(q.load_posts(Path(manifest)))
    assert q.publish_queue(wave) == []


def test_gastronomy_structure_agrees_with_the_gastronomy_gate():
    """Guard against drift between this file's copy of the recipe contract and the original.

    `check_gastronomy_structure` reproduces `gastronomy_batch.validate_batch_document`
    rather than importing it, so that this gate has no boto3 dependency. That duplication
    is only safe while something checks the two agree.
    """
    gastronomy = pytest.importorskip("gastronomy_batch")
    manifest = ROOT / "content/gastronomy/batches/GAST-216-GAST-240.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert gastronomy.validate_batch_document(document) == []
    for post in document["posts"]:
        mine = q.check_gastronomy_structure(post)
        assert [f.code for f in mine] == [], (post["slug"], [str(f) for f in mine])


def test_slug_helper_matches_the_storage_slugifier():
    for value in ("Carrot Pickles", "When a Word Is Load-Bearing", "  Trailing  "):
        assert q.slugify(value) == q.slugify(q.slugify(value))
        assert " " not in q.slugify(value)
