#!/usr/bin/env python3
"""WECARE.DIGITAL Conversations Content Quality Standard v2, as executable checks.

WHAT THIS IS, AND THE ONE THING IT DELIBERATELY REFUSES TO DO.

The standard has 34 sections. Some are mechanically decidable - a slug either collides
or it does not, a meta description either fits its band or it does not, a body either
carries an image node or it does not. Those are implemented here, and they fail the
build.

Several are not decidable by a program, and pretending otherwise would be the single
most damaging thing this file could do. Section 29 asks for a PASS/FAIL on ORIGINAL
EXPRESSION ("independently Anew rather than cosmetically rewritten"), on VOICE, and on
SUBSTANCE; section 30 asks a reader whether the article "was written because there was
something worth saying". A regex cannot answer any of those, and a pipeline that
auto-stamps them would convert the standard into a rubber stamp while reporting
100% compliance.

So the rule this module enforces is:

    mechanical checks can only ever move a record DOWN, never up to READY_TO_PUBLISH.

`decide_status` will return EDITORIAL_QA for a record that passes every machine check
but carries no human verdict. READY_TO_PUBLISH requires a human to have recorded the
human-only gates in `record['gate']`. Section 32's "only READY_TO_PUBLISH may enter the
publishing queue" is therefore preserved rather than defeated: the machine clears
the mechanical debt so the human time goes where only human judgement works.

Two categories are supported, because two exist on the live site: Conversations and
Gastronomy. Gastronomy additionally carries the recipe structure its own gate already
enforces, and those checks are reproduced here rather than imported so this module has
no boto3 dependency and runs anywhere.

Usage:
    python scripts/blog_quality_v2.py validate --manifest content/conversations/batches/CONV-001-CONV-025.json
    python scripts/blog_quality_v2.py report   --manifest <file> [--json]
    python scripts/blog_quality_v2.py wave     --manifest <file>   # section 34 rollup
    python scripts/blog_quality_v2.py corpus   --manifest <file> --against <glob...>
"""
from __future__ import annotations

import argparse
import glob as globlib
import hashlib
import json
import re
import sys
#: Imported under an alias because this module defines its own `field()` - the
#: alias-aware record reader - and the two silently collided, turning every
#: `default_factory` into a TypeError at class-definition time.
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# ── Fixed vocabulary from the standard ──────────────────────────────────────────

AUTHOR = "Anew by WECARE.DIGITAL"
PUBLISHER = "WECARE.DIGITAL"
SITE = "https://wecare.digital"

#: Section 25. Exactly two, and an enum rather than free text on purpose: the existing
#: admin form uses a `<datalist>`, which means a typo silently creates a third category
#: and the /blog/ default is whichever sorts first alphabetically. "Conversatons" would
#: have taken over the blog index.
CATEGORIES: Tuple[str, ...] = ("Conversations", "Gastronomy")
DEFAULT_CATEGORY = "Conversations"

#: Section 1.
ARTICLE_CLASSES: Tuple[str, ...] = ("ORIGINAL_109", "ARCHIVE_DERIVED")

#: Sections 10 and 11. Bands are "typical", not mandatory, so a miss is a REVIEW rather
#: than a BLOCK - except for a body so thin it cannot have landed a distinction at all.
ARTICLE_TYPES: Dict[str, Tuple[int, int]] = {
    "DISTINCTION": (250, 400),
    "REFLECTION": (500, 800),
    "ARTICLE": (800, 1500),
    "DEEP_ARTICLE": (1200, 6000),
}
ABSOLUTE_MIN_WORDS = 120

#: Section 32. Exactly one of these per record.
STATUSES: Tuple[str, ...] = (
    "SOURCE_REVIEW",
    "DEDUPE_REWORK",
    "PERSONAL_REFERENCE_REWORK",
    "ATTRIBUTION_REVIEW",
    "FACT_CHECK_REQUIRED",
    "EDITORIAL_REWRITE",
    "EDITORIAL_QA",
    "READY_TO_PUBLISH",
    "PUBLISHED",
    "VERIFIED",
)
PUBLISHABLE_STATUS = "READY_TO_PUBLISH"

#: Section 29, split by who can actually decide it.
MACHINE_GATES: Tuple[str, ...] = (
    "NON_DUPLICATION",
    "TIGHTNESS",
    "METADATA",
    "AUTHOR_IDENTITY",
    "PUBLIC_SOURCE_EXPOSURE",
)
HUMAN_GATES: Tuple[str, ...] = (
    "DISTINCTION",
    "SOURCE_FIDELITY",
    "CLARITY",
    "VALUE",
    "ORIGINAL_EXPRESSION",
    "SUBSTANCE",
    "VOICE",
    "FACTUAL_INTEGRITY",
    "PRIVACY",
    #: Section 30, asked as one question.
    "HUMAN_QUALITY_TEST",
)

#: Section 13. None is forbidden outright; the standard's complaint is repetition and
#: formula, so these are counted rather than banned.
AI_RHYTHM_PHRASES: Tuple[str, ...] = (
    "the real question is",
    "the point is not",
    "what if",
    "here is the truth",
    "here's the truth",
    "this changes everything",
    "there is another possibility",
    "sometimes the most",
    "at its core",
    "in today's fast-paced world",
    "in todays fast-paced world",
    "ultimately,",
    "it's important to note",
    "it is important to note",
    "in conclusion",
    "let's dive in",
    "lets dive in",
    "in the realm of",
    "navigate the complexities",
    "unlock the",
    "delve into",
    "a testament to",
)

#: Section 14.
SELF_HELP_PHRASES: Tuple[str, ...] = (
    "believe in yourself",
    "embrace the journey",
    "become your best self",
    "best version of yourself",
    "step into your power",
    "choose positivity",
    "everything happens for a reason",
    "live your truth",
    "manifest your",
    "you've got this",
    "you got this",
    "trust the process",
    "level up your life",
    "unleash your potential",
)

#: Section 8.
CLICKBAIT_MARKERS: Tuple[str, ...] = (
    "everything you know is wrong",
    "will change your life",
    "this one trick",
    "you won't believe",
    "you wont believe",
    "shocking truth",
    "nobody tells you",
    "what they don't want you to know",
    "secret to",
    "hack your",
    "must-read",
    "mind-blowing",
)

#: Section 6. Titles that differ only by this scaffolding are the same article.
TITLE_SCAFFOLD: Tuple[str, ...] = (
    "understanding", "understand", "why", "matters", "the", "power", "of", "a", "an",
    "explained", "explaining", "guide", "to", "introduction", "intro", "what", "is",
    "on", "about", "and", "in", "for", "how", "basics", "essentials", "overview",
    "thoughts", "reflections", "notes", "exploring", "rethinking", "truth",
)

#: Section 18. A first-person-plural life story is the specific failure the standard
#: names: "I went through" must NOT become "We went through".
FALSE_BIOGRAPHY_PATTERNS: Tuple[str, ...] = (
    r"\bwe (?:went through|grew up|were raised|lost our|survived|struggled with|battled)\b",
    r"\bwhen we were (?:young|children|kids|little|growing up)\b",
    r"\bour (?:childhood|upbringing|mother|father|parents|divorce|diagnosis)\b",
    r"\bwe remember (?:the day|when we)\b",
    r"\bin our (?:twenties|thirties|forties|fifties)\b",
)

#: Section 18, the other direction: an un-removed first-person wrapper from the source.
FIRST_PERSON_WRAPPER = r"\b(?:I|my|me|myself)\b"

#: Section 18. An ARCHIVE_DERIVED article is a reconstruction, not a book report or a
#: narrated summary of the source. These are deliberately narrow: ordinary uses such as
#: "the source of the action" or "the next chapter of life" must not trip this gate.
SOURCE_WRAPPER_PATTERNS: Tuple[str, ...] = (
    r"\btopline\s+summar(?:y|ies)\b",
    r"\b(?:seminar|workshop|course|training)\s+materials(?:\s+collected\s+under)?\b",
    r"\b(?:the|this|our|original)\s+source\s+materials\b",
    r"\b(?:the|this|our|original)\s+source(?:'s|\s+(?:says|said|describes|described|"
    r"argues|argued|explains|explained|frames|framed|presents|presented|defines|defined|"
    r"suggests|suggested|calls|called|offers|offered|notes|noted|observes|observed|treats|"
    r"treated|introduces|introduced|distinguishes|distinguished|uses|used|examines|examined|"
    r"materials|model))\b",
    r"\b(?:the|this)\s+(?:book|essay|article|chapter|paper|report|pdf|summary)\s+"
    r"(?:says|said|describes|described|argues|argued|explains|explained|frames|framed|"
    r"presents|presented|defines|defined|suggests|suggested|calls|called|offers|offered|"
    r"notes|noted|observes|observed|treats|treated|introduces|introduced|distinguishes|"
    r"distinguished|uses|used|examines|examined)\b",
    r"\b(?:source|book|essay|article|chapter|paper|report|pdf|summary)'s\s+"
    r"(?:treatment|framing|account|discussion|description|argument|explanation|presentation|"
    r"definition|distinction)\b",
    r"\b(?:the|this)\s+(?:topline\s+summar(?:y|ies)\s+)?treatment\s+of\b",
    r"\bthis\s+(?:article|post|piece)\s+(?:says|describes|argues|explains|frames|"
    r"presents|defines|suggests|calls|offers|notes|observes|treats|introduces|distinguishes|"
    r"uses|examines)\b",
    r"\bthe\s+[a-z0-9 &,\'’:-]{0,55}\bchapter\s+"
    r"(?:opens|uses|places|brings|values|presents|describes|covers|contains|includes|notes|"
    r"shows|represents|does\s+not\s+prescribe)\b",
)

#: Broken remnants left after a source name or attribution was stripped. These are grammar
#: defects in any article class, not merely a style preference for archive reconstructions.
SOURCE_REMNANT_PATTERNS: Tuple[str, ...] = (
    r"(?:^|[.!?]\s+)(?:notes|says|describes|explains|presents|recommends|introduces|uses|"
    r"encourages)\s+that\b",
    r"(?:^|[.!?]\s+)[\'’]s\s+[a-z]",
    r"\bthe\s+introduces\b",
    r"\bthroughout\s+the\s+as\b",
    r"\bhow\s+says\b",
    r"\brecommended\s+note\b",
    r"\bthe\s+(?:regularly|repeatedly)\s+(?:uses|encourages|features|includes|recommends|"
    r"notes|presents)\b",
    r"\bthe\s+also\b",
    r"\bfrom\s+there,\s+the\s+offers\b",
)

#: Section 20. Presence of any of these means the matching review flag must be an
#: explicit YES, not N/A. The point is not to ban the subject, it is to stop a record
#: declaring a review "not applicable" while making the claim anyway.


# Public-copy corruption classes discovered by the October 2026 independent corpus audit.
# These are live-copy integrity failures, not style preferences, so they are intentionally
# NOT included in LEGACY_SOFTENED_CODES.
EDITORIAL_ORPHAN_VERBS: Tuple[str, ...] = (
    "recommends", "suggests", "offers", "uses", "presents", "describes", "explains",
    "notes", "advises", "considers", "keeps", "gives", "allows", "rests", "pairs",
    "serves", "prepares", "makes", "solves", "aims", "leaves", "combines",
    "introduces", "encourages", "includes", "treats", "frames", "cautions", "adapts",
    "explicitly", "frequently", "regularly",
)

EDITORIAL_KNOWN_FUSED_WORDS = frozenset({
    "appearspecifically", "carefullygives", "schedulenotes", "heatexplicitly",
    "measurementgives", "rollinggives", "roleschooses", "tastinguses",
    "graduallyspecifically", "mealpairs", "stereotypepresents", "contextpresents",
    "fatgives", "defaultpresents", "easilya", "togetherdivides", "lightasks", "formkanji",
})

EDITORIAL_CAMEL_ALLOWLIST = frozenset({
    "YouTube", "iPhone", "iPad", "iCloud", "JavaScript", "ChatGPT", "LinkedIn",
    "WordPress", "PowerPoint", "OpenAI", "PayPal", "GitHub", "WhatsApp", "OneLogin",
    "OnePassword",
})

EDITORIAL_SOURCE_REFERENCE_RE = re.compile(
    r"\b(?:from\s+the\s+recipe\s+on\s+book\s+p\.|book\s+p\.\s*\d+|"
    r"source\s+ref(?:erence)?\s*:|source\s+file\s*:|blogsrc_|blogbatch_|"
    r"archive[_ -]?derived|original[_ -]?109)\b",
    re.IGNORECASE,
)

EDITORIAL_BROKEN_POSSESSIVE_RE = re.compile(
    r"\b(?:the|a|an|using|from|follow|across)\s+[’']s\b",
    re.IGNORECASE,
)

EDITORIAL_MALFORMED_RE = re.compile(
    r"\b(?:uses briefly using|fusion Here:|Across the,|according to how says|"
    r"throughout the as|from there, the offers|recommended note)\b",
    re.IGNORECASE,
)

EDITORIAL_PREPARATION_WRAPPER_RE = re.compile(
    r"\bThe preparation\s+(?:describes|suggests|notes|uses|offers|presents|explains|"
    r"recommends|gives|allows|keeps|pairs|serves|makes|calls|includes|frames|treats)\b",
    re.IGNORECASE,
)

# The migration artifact this catches is detached EDITORIAL narration: a disembodied
# source "recommending / suggesting / noting / describing" as if the recipe were an author.
# It must fire ONLY on those advisory verbs — not on physical description of the dish, where
# "The recipe" is an ordinary subject: "The recipe is intentionally spare.", "The recipe
# makes four servings.", "The recipe uses fresh herbs.", "The recipe requires two rises."
# are all correct prose and every one appears in the already-published corpora. Verbs like
# makes/uses/has/requires/starts/works are therefore excluded; the advisory set mirrors
# EDITORIAL_PREPARATION_WRAPPER_RE. The possessive ("The recipe's heat…") stays a match
# because it is narration regardless of the verb.
EDITORIAL_DETACHED_RECIPE_RE = re.compile(
    r"(?:^|[.!?]\s+)The recipe(?:"
    r"(?:'s|’s)\b"
    r"|\s+(?:describes|suggests|notes|offers|presents|explains|recommends|advises|"
    r"frames|treats|considers|cautions|encourages|introduces)\b)",
    re.IGNORECASE | re.MULTILINE,
)


def _terminally_punctuated_public_copy(value: str) -> bool:
    return bool(re.search(r"[.!?…][\"'”’\)\]]*$", value.strip()))


def _metadata_looks_truncated(value: str) -> bool:
    value = value.strip()
    if not value:
        return True
    if re.search(r",\s*(?:\.|\.\.\.)\s*$|\.{4,}\s*$", value):
        return True
    trimmed = re.sub(r"[.!?…\"'”’\)\]]+$", "", value).rstrip()
    if re.search(r"(?:^|\s)[a-z]$", trimmed):
        return True
    return len(value) >= 120 and not _terminally_punctuated_public_copy(value)


def check_editorial_corruption(record: Dict[str, Any]) -> List[Finding]:
    """Hard blockers for public-copy corruption found by the October 2026 audit."""
    out: List[Finding] = []
    body = body_of(record)
    category = str(record.get("category") or "").strip()

    structural_patterns = (
        ("FUSED_INGREDIENTS_HEADING", r"(?m)^Ingredients(?=\*|\-|\d)",
         "Ingredients is fused to the first ingredient instead of being a Markdown heading"),
        ("FUSED_METHOD_HEADING", r"(?m)^Method(?=\d+[.)]|[A-Z][a-z])",
         "Method is fused to the first numbered step or sentence"),
        ("PLAIN_SECTION_HEADING", r"(?m)^(?:Ingredients|Method)\s*$",
         "Ingredients/Method must be Markdown headings, not collapsed plain-text labels"),
    )
    for code, pattern, message in structural_patterns:
        if re.search(pattern, body):
            out.append(_block("26", code, message))

    for token in re.findall(r"\b[A-Za-z]{2,}[a-z][A-Z][a-z]{2,}[A-Za-z]*\b", body):
        if token not in EDITORIAL_CAMEL_ALLOWLIST:
            out.append(_block(
                "26", "FUSED_WORD_BOUNDARY",
                f"possible lost word/heading boundary in {token!r}; restore the intended spacing "
                "or explicitly allow the proper name"))
            break

    lowered_body = body.lower()
    for token in EDITORIAL_KNOWN_FUSED_WORDS:
        if re.search(r"\b" + re.escape(token) + r"\b", lowered_body):
            out.append(_block(
                "26", "FUSED_LOWERCASE_WORDS",
                f"known migration join {token!r} survives in the body"))
            break

    public_surfaces = [("body", strip_markdown(body))]
    for field_name in ("excerpt", "metaDescription"):
        value = text_field(record, field_name)
        if value:
            public_surfaces.append((field_name, value))

    for surface_name, surface_text in public_surfaces:
        if EDITORIAL_BROKEN_POSSESSIVE_RE.search(surface_text):
            out.append(_block(
                "18", "BROKEN_SOURCE_POSSESSIVE",
                f"broken source-name removal survives in {surface_name}"))
            break
        if EDITORIAL_SOURCE_REFERENCE_RE.search(surface_text):
            out.append(_block(
                "18", "SOURCE_REFERENCE_LEAK",
                f"internal source/reference metadata leaked into public {surface_name}"))
            break
        if EDITORIAL_MALFORMED_RE.search(surface_text):
            out.append(_block(
                "18", "MALFORMED_SOURCE_REMNANT",
                f"known source-removal grammar damage survives in public {surface_name}"))
            break
        if re.search(r"\ba suitable version uses\b", surface_text, re.IGNORECASE):
            out.append(_block(
                "18", "DETACHED_SOURCE_NARRATION",
                f"source-facing 'a suitable version uses' wrapper survives in {surface_name}"))
            break

    orphan = "|".join(re.escape(v) for v in EDITORIAL_ORPHAN_VERBS)
    prose = strip_markdown(body)
    if re.search(rf"(?:^|[.!?]\s+)(?:also\s+)?(?:{orphan})\b", prose):
        out.append(_block(
            "18", "ORPHAN_PROSE_START",
            "a sentence begins with a lower-case source/narrator verb and is missing its subject"))
    if re.search(
            rf"\b(?:Because|Although|While|If|When|Since|Where|As|Despite the name)"
            rf",?\s+(?:also\s+)?(?:{orphan})\b",
            prose):
        out.append(_block(
            "18", "MISSING_SUBJECT_AFTER_CLAUSE",
            "a subordinate clause is followed by a source/narrator verb with no grammatical subject"))

    if category == "Gastronomy":
        if EDITORIAL_DETACHED_RECIPE_RE.search(prose):
            out.append(_block(
                "18", "DETACHED_RECIPE_NARRATION",
                "Gastronomy prose is narrated as 'The recipe...' instead of stating the culinary point directly"))
        if EDITORIAL_PREPARATION_WRAPPER_RE.search(prose):
            out.append(_block(
                "18", "DETACHED_PREPARATION_NARRATION",
                "Gastronomy prose is narrated as 'The preparation...' instead of stating the point directly"))
        for line in body.splitlines():
            match = re.search(r"\bHere\b", line)
            if match and line[:match.start()].strip():
                out.append(_block(
                    "18", "MID_SENTENCE_CAPITAL_HERE",
                    "capitalized 'Here' appears mid-sentence in Gastronomy copy, a known migration-removal artifact"))
                break

    # §24 asks for a public summary, not specifically the `excerpt` field. The native
    # store keeps `excerpt` and `metaDescription` as independent public fields and derives
    # each from the other when one is absent (storage.create → excerpt or body;
    # seo_engine._meta_description → metaDescription or excerpt), so a record that carries a
    # metaDescription already HAS a public summary even with no separate excerpt. The 108+
    # already-published legacy manifests store only metaDescription; requiring excerpt too
    # would hard-block healthy live copy, which is the exact failure a corruption gate must
    # not create. EXCERPT_MISSING therefore fires only when there is NO public summary at
    # all; META_MISSING (also §24) still independently requires the metaDescription.
    excerpt = text_field(record, "excerpt")
    meta_description = text_field(record, "metaDescription")
    if not excerpt and not meta_description:
        out.append(_block("24", "EXCERPT_MISSING", "public excerpt is required"))
    for field_name, value in (("excerpt", excerpt),
                              ("metaDescription", meta_description)):
        if value and _metadata_looks_truncated(value):
            out.append(_block(
                "24", "PUBLIC_METADATA_TRUNCATED",
                f"{field_name} appears cut off or ends in malformed truncation punctuation"))

    return out

FACT_DOMAIN_TRIGGERS: Dict[str, Tuple[str, ...]] = {
    "healthReviewComplete": (
        "cortisol", "dopamine", "serotonin", "amygdala", "neuroplasticity", "diagnosis",
        "symptom", "disorder", "depression", "anxiety disorder", "therapy", "medication",
        "dosage", "clinical", "patient", "cure", "immune system", "blood sugar",
        "cholesterol", "nutrient", "vitamin", "calorie", "detox", "gluten",
    ),
    "legalReviewComplete": (
        "illegal", "lawsuit", "liability", "contract law", "statute", "regulation",
        "court ruled", "your rights", "legally required", "compliance requirement",
        "gdpr", "copyright", "defamation",
    ),
    "financialReviewComplete": (
        "invest", "investment", "returns", "portfolio", "interest rate", "inflation",
        "tax deduction", "mutual fund", "equity", "roi", "guaranteed return",
    ),
    "historicalReviewComplete": (
        "century", "ancient", "in 18", "in 19", "world war", "dynasty", "bce", "b.c.",
        "medieval", "renaissance", "colonial",
    ),
    "currentFactCheckComplete": (
        "government", "election", "policy", "minister", "parliament", "president",
        "supreme court", "sanction", "tariff", "the current",
    ),
}

#: Section 26. Typography belongs to the frontend; none of this may survive migration.
LEGACY_MARKUP = (
    r"<font\b", r"<span\b", r"<div\b", r"<table\b", r"style\s*=", r"font-size",
    r"font-family", r"&nbsp;", r"color\s*:\s*#", r"<br\s*/?>", r"<center\b",
)

#: Section 27, and the same set the existing migration gate already refuses.
FORBIDDEN_MEDIA_NODES = {"IMAGE", "GALLERY", "GIF", "VIDEO", "AUDIO", "EMBED", "FILE"}
FORBIDDEN_IMAGE_KEYS = ("heroImage", "coverImage", "media", "featuredImage", "thumbnail")

SEVERITIES = ("BLOCK", "REVIEW", "NOTE")

#: Where `blog_corpus_index.py` writes the sketch index of the published corpus.
PUBLISHED_INDEX = Path("content/conversations/corpus-index.json")


# ── Findings ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Finding:
    """One rule outcome. `section` is the standard's own numbering, so a failure is
    traceable back to the clause that produced it rather than to this file."""

    section: str
    code: str
    severity: str
    message: str
    #: The status a REVIEW finding routes the record to (section 32).
    routes_to: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.severity}] §{self.section} {self.code}: {self.message}"


def _block(section: str, code: str, message: str) -> Finding:
    return Finding(section, code, "BLOCK", message, "EDITORIAL_REWRITE")


def _review(section: str, code: str, message: str, routes_to: str) -> Finding:
    return Finding(section, code, "REVIEW", message, routes_to)


def _note(section: str, code: str, message: str) -> Finding:
    return Finding(section, code, "NOTE", message, None)


# ── Text utilities ──────────────────────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def strip_markdown(body: str) -> str:
    """Prose only: headings, emphasis, list bullets and link syntax removed."""
    text = str(body or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    return text


def word_count(body: str) -> int:
    return len([token for token in re.split(r"\s+", strip_markdown(body)) if token])


def blocks(body: str) -> List[Tuple[str, str]]:
    """Markdown body as (kind, text) blocks. Kinds: heading, list, quote, paragraph.

    Blank-line separated, which is what makes "substantive top-level paragraph" a
    meaningful count rather than a line count - the existing Gastronomy gate learned
    that the hard way when single-newline bodies passed a paragraph check and then
    published as one wall of text.
    """
    out: List[Tuple[str, str]] = []
    for chunk in re.split(r"\n\s*\n", str(body or "").replace("\r\n", "\n")):
        chunk = chunk.strip()
        if not chunk:
            continue
        first = chunk.splitlines()[0].strip()
        if first.startswith("#"):
            kind = "heading"
        elif re.match(r"^[-*+]\s+", first) or re.match(r"^\d+\.\s+", first):
            kind = "list"
        elif first.startswith(">"):
            kind = "quote"
        else:
            kind = "paragraph"
        out.append((kind, chunk))
    return out


def headings(body: str) -> List[str]:
    return [
        re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip()
        for line in str(body or "").splitlines()
        if re.match(r"^\s{0,3}#{1,6}\s+", line)
    ]


def substantive_paragraphs(body: str, minimum_chars: int = 60) -> List[str]:
    return [
        text for kind, text in blocks(body)
        if kind == "paragraph" and len(strip_markdown(text).strip()) >= minimum_chars
    ]


def has_list(body: str) -> bool:
    """Any bullet or numbered item, anywhere.

    Deliberately line-based rather than block-based. `blocks()` splits on blank lines, so
    a list written straight after its lead-in paragraph with no blank line between them -
    which is how every committed Gastronomy body is written - lands inside a 'paragraph'
    block and a block-based check reports no list at all. That false negative fired on
    all 25 records of a batch that its own gate passes.
    """
    return any(
        re.match(r"^\s{0,3}(?:[-*+]\s+|\d{1,2}[.)]\s+)", line)
        for line in str(body or "").splitlines()
    )


def sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _normalize_title(title: str) -> str:
    """Section 6: a title reduced to its content words. "The Power of Integrity" and
    "Understanding Integrity" both reduce to "integrity", which is the standard's own
    example of two titles that must not become two articles."""
    tokens = re.findall(r"[a-z0-9]+", str(title or "").lower())
    kept = [t for t in tokens if t not in TITLE_SCAFFOLD]
    return " ".join(kept or tokens)


def _shingles(text: str, size: int = 8) -> Set[str]:
    tokens = re.findall(r"[a-z0-9']+", strip_markdown(text).lower())
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


def _jaccard(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    if not intersection:
        return 0.0
    return intersection / len(left | right)


# ── Bottom-k sketches, for comparing against the whole published corpus ─────────
#
# These live HERE rather than in `blog_corpus_index` to break a circular import: the indexer
# needs this module's `strip_markdown` and `_normalize_title`, so this module cannot import
# the indexer. Keeping one implementation matters more than where it sits - two sketchers
# would produce two incompatible indexes.
#
# WHY SKETCHES AT ALL. Section 28 requires comparison against the whole corpus, which is
# 1,165 published posts. Exact 8-word shingle sets for that are ~4.5 MB of committed JSON
# and grow with every publish. A bottom-k sketch reduces each post to `SKETCH_K` hashes -
# a uniform random sample of its shingles, because a good hash makes "smallest" independent
# of content - which estimates Jaccard over a set of any size from a fixed budget.

SKETCH_K = 128
SHINGLE_SIZE = 8
#: 32-bit, a size decision. A JSON array of 128 64-bit ints renders as ~2.5 kB of decimal
#: digits and made the first real index 3.7 MB; packed 32-bit hex is ~1.0 kB per post and
#: 1.4 MB total. At ~600,000 distinct shingles across the corpus the birthday bound predicts
#: ~42 collisions, which cannot move a 128-sample estimate across the 0.35/0.60 thresholds.
SKETCH_HASH_BITS = 32
_SKETCH_MASK = (1 << SKETCH_HASH_BITS) - 1
_SKETCH_HEX = SKETCH_HASH_BITS // 4


def shingle_hashes(text: str, size: int = SHINGLE_SIZE) -> Set[int]:
    tokens = re.findall(r"[a-z0-9']+", strip_markdown(text).lower())
    if len(tokens) < size:
        return {_hash_shingle(" ".join(tokens))} if tokens else set()
    return {_hash_shingle(" ".join(tokens[i:i + size]))
            for i in range(len(tokens) - size + 1)}


def _hash_shingle(value: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big") & _SKETCH_MASK


def sketch(text: str, k: int = SKETCH_K) -> List[int]:
    """The k smallest shingle hashes, ascending so a rebuild is byte-stable."""
    return sorted(shingle_hashes(text))[:k]


def encode_sketch(values: Sequence[int]) -> str:
    return "".join(f"{value:0{_SKETCH_HEX}x}" for value in values)


def decode_sketch(encoded: Any) -> List[int]:
    """Packed hex, or a legacy integer array so an older index still loads."""
    if isinstance(encoded, list):
        return [int(value) for value in encoded]
    text = str(encoded or "")
    return [int(text[i:i + _SKETCH_HEX], 16) for i in range(0, len(text), _SKETCH_HEX)]


def sketch_jaccard(left: Sequence[int], right: Sequence[int], k: int = SKETCH_K) -> float:
    """Unbiased Jaccard from two bottom-k sketches.

    NOT `|A n B| / |A u B|` over the sketches, which is the obvious formula and is biased
    downward: each sketch holds only its OWN k smallest values, so a shingle present in both
    documents can survive in one sketch and be cut from the other purely because that
    document is longer. The bias grows with the size difference - precisely the case that
    matters here, a 300-word distinction against a 1,400-word deep article.

    Taking the k smallest of the UNION fixes it: every value in that window is below both
    sketches' thresholds, so membership is known for both documents and the sample is fair.
    Measured against exact Jaccard on a size-skewed pair: 2.6% error, versus a visible
    underestimate from the naive form.
    """
    if not left or not right:
        return 0.0
    left_set, right_set = set(left), set(right)
    window = sorted(left_set | right_set)[:k]
    if not window:
        return 0.0
    return sum(1 for value in window
               if value in left_set and value in right_set) / len(window)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:120]


def walk_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_nodes(nested)


#: Retained content manifests use both camelCase and snake_case fields. Accept
#: both naming conventions without rewriting published content to suit the validator.
FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "seoTitle": ("seoTitle", "seo_title"),
    "metaDescription": ("metaDescription", "meta_description"),
    "imageStatus": ("imageStatus", "image_status", "articleImage"),
    "author": ("author", "authorName"),
    "tags": ("tags", "tagLabels"),
    "sourceFile": ("sourceFile", "source_ref", "sourceRef"),
    "originalPublishedDate": ("originalPublishedDate", "sourcePublishedDate"),
    "originalSourceDate": ("originalSourceDate", "sourceDate", "source_date"),
    "originalSourceTitle": ("originalSourceTitle", "sourceTitle", "source_title"),
    "sourceHash": ("sourceHash", "source_hash", "sourceSha256"),
    "articleType": ("articleType", "article_type"),
    "articleClass": ("articleClass", "article_class"),
    "centralDistinction": ("centralDistinction", "central_distinction"),
    "distinctPurpose": ("distinctPurpose", "distinct_purpose"),
    "establishedSlug": ("establishedSlug", "established_slug"),
    "sourceSlug": ("sourceSlug", "source_slug"),
    "publicPublishedDate": ("publicPublishedDate", "public_published_date"),
    "sourceType": ("sourceType", "source_type"),
    "sourceReviewedFully": ("sourceReviewedFully", "source_reviewed_fully"),
}


def field(record: Dict[str, Any], name: str, default: Any = None) -> Any:
    """Read a field under any spelling the corpus actually uses."""
    for candidate in FIELD_ALIASES.get(name, (name,)):
        if candidate in record and record[candidate] not in (None, ""):
            return record[candidate]
    return default


def text_field(record: Dict[str, Any], name: str) -> str:
    return str(field(record, name, "") or "").strip()


def _is_yes(value: Any) -> bool:
    return str(value or "").strip().upper() in {"YES", "TRUE", "1", "PASS"}


def _is_no(value: Any) -> bool:
    return str(value or "").strip().upper() in {"NO", "FALSE", "0"}


def _flag_answer(value: Any) -> str:
    return str(value or "").strip().upper()


# ── The record ──────────────────────────────────────────────────────────────────

def body_of(record: Dict[str, Any]) -> str:
    """The editorial body, under any of the three field names in use.

    `contentMarkdown` is the Conversations migration name, `body_markdown` the
    Gastronomy one, `content` the DynamoDB admin one. Accepting all three is what lets
    one gate cover the existing corpora instead of only new records.
    """
    for key in ("bodyMarkdown", "body_markdown", "contentMarkdown", "content", "body"):
        value = record.get(key)
        if value:
            return str(value)
    return ""


def is_legacy_record(record: Dict[str, Any]) -> bool:
    """True for a record written before the v2 standard existed.

    The 109 Conversations originals and the 340 Gastronomy recipes carry no
    `articleClass`, no `status` and none of the section 4/5 fields, because those fields
    were introduced by this standard. They are already published. Detecting them lets the
    gate report the v2 fields as OUTSTANDING (which routes them to SOURCE_REVIEW and
    keeps them out of the publish queue) rather than as CONTENT DEFECTS, which would make
    the gate print 333 failures on healthy live articles and get itself switched off.
    """
    return not any(field(record, name) for name in
                   ("articleClass", "centralDistinction", "distinctPurpose")) \
        and not record.get("status")


def canonical_of(record: Dict[str, Any]) -> str:
    return str(record.get("canonical") or "").strip()


def expected_canonical(slug: str) -> str:
    return f"{SITE}/post/{slug}/"


# ── Section-by-section checks ───────────────────────────────────────────────────

def check_class_and_source(record: Dict[str, Any]) -> List[Finding]:
    """Sections 1, 2 and 3."""
    out: List[Finding] = []
    article_class = text_field(record, "articleClass").upper()
    if article_class not in ARTICLE_CLASSES:
        #: REVIEW, not BLOCK. An unclassified record cannot be checked against sections 22
        #: and 23 at all, since both branch on the class - so it must not publish. Routing
        #: it to SOURCE_REVIEW achieves that. Blocking adds nothing beyond making the gate
        #: report a hard failure on every already-published legacy record.
        out.append(_review("1", "CLASS_MISSING",
                           f"articleClass must be one of {list(ARTICLE_CLASSES)}, got "
                           f"{article_class or '<empty>'}",
                           "SOURCE_REVIEW"))

    if not _is_yes(field(record, "sourceReviewedFully")):
        out.append(_review("2", "SOURCE_NOT_READ",
                           "sourceReviewedFully must be YES; an article may not be built from "
                           "title, excerpt or metadata alone",
                           "SOURCE_REVIEW"))

    for key, label in (
        ("sourceFile", "Source file"),
        ("originalSourceTitle", "Original source title"),
        ("sourceType", "Source type"),
        ("sourceHash", "Source hash/reference"),
    ):
        if not text_field(record, key):
            out.append(_review("2", "SOURCE_PROVENANCE",
                               f"{label} ({key}) is required so provenance survives publication",
                               "SOURCE_REVIEW"))
    return out


def check_distinction_and_purpose(record: Dict[str, Any]) -> List[Finding]:
    """Sections 4 and 5."""
    out: List[Finding] = []
    distinction = text_field(record, "centralDistinction")
    purpose = text_field(record, "distinctPurpose")

    if len(distinction) < 40:
        out.append(_review("4", "NO_CENTRAL_DISTINCTION",
                           "centralDistinction must state, in 1-2 sentences, what the reader can "
                           "newly notice or distinguish; it is not a summary",
                           "EDITORIAL_REWRITE"))
    elif len(sentences(distinction)) > 3:
        out.append(_note("4", "DISTINCTION_LONG",
                         "centralDistinction runs past 2 sentences; it is drifting into summary"))

    if len(purpose) < 40:
        out.append(_review("5", "NO_DISTINCT_PURPOSE",
                           "distinctPurpose must answer why this article deserves its own URL",
                           "DEDUPE_REWORK"))

    #: Section 5 makes these four explicit, and a FAIL on any is DEDUPE_REWORK by name.
    if not _is_yes(record.get("materiallyDifferentInquiry")):
        out.append(_review("5", "NOT_MATERIALLY_DIFFERENT",
                           "materiallyDifferentInquiry is not YES", "DEDUPE_REWORK"))
    if not _is_no(record.get("titleOnlyDifference")):
        out.append(_review("5", "TITLE_ONLY_DIFFERENCE",
                           "titleOnlyDifference must be NO", "DEDUPE_REWORK"))
    if not _is_yes(record.get("uniqueReaderPromise")):
        out.append(_review("5", "NO_UNIQUE_PROMISE",
                           "uniqueReaderPromise is not YES", "DEDUPE_REWORK"))
    if not _is_yes(record.get("uniqueIntellectualMovement")):
        out.append(_review("5", "NO_UNIQUE_MOVEMENT",
                           "uniqueIntellectualMovement is not YES", "DEDUPE_REWORK"))
    return out


def check_type_and_length(record: Dict[str, Any]) -> List[Finding]:
    """Sections 10 and 11."""
    out: List[Finding] = []
    body = body_of(record)
    words = word_count(body)
    article_type = text_field(record, "articleType").upper().replace(" ", "_")

    if not body.strip():
        #: A draft from `blog_ingest` carries the faithful source extract and no article
        #: yet. Same outcome - it cannot publish - but the message has to say which of the
        #: two situations it is, because an editor working through 250 records reads the
        #: message, and "the article has no body" on every row looks like a broken export
        #: rather than a queue of work not yet started.
        if str(record.get("sourceExtract") or "").strip():
            out.append(_block("31", "NOT_YET_WRITTEN",
                              "the source extract is present but the article has not been "
                              "written; reconstruct it in Anew voice into contentMarkdown"))
        else:
            out.append(_block("11", "EMPTY_BODY", "the article has no body"))
        return out

    if article_type not in ARTICLE_TYPES:
        out.append(_review("10", "TYPE_MISSING",
                           f"articleType must be one of {list(ARTICLE_TYPES)}, got "
                           f"{article_type or '<empty>'}; the type is chosen deliberately, "
                           "not defaulted",
                           "EDITORIAL_QA"))
    else:
        low, high = ARTICLE_TYPES[article_type]
        #: A miss is a REVIEW, never a BLOCK: section 11 opens "There is no mandatory
        #: word count" and says a strong 350-word article beats a padded 1,200-word one.
        #: Turning a band into a hard gate is exactly how padding gets rewarded.
        if words < low:
            out.append(_review("11", "BELOW_BAND",
                               f"{words} words is below the {article_type} band of {low}-{high}; "
                               "either the distinction has not landed or the type is wrong",
                               "EDITORIAL_QA"))
        elif words > high:
            out.append(_review("11", "ABOVE_BAND",
                               f"{words} words exceeds the {article_type} band of {low}-{high}; "
                               "check for explanatory padding before re-typing it",
                               "EDITORIAL_QA"))

    #: The word floor is a prose notion and it does not govern Gastronomy, which has its
    #: own established contract of 450 characters enforced in `check_gastronomy_structure`.
    #: Applying both flagged 8 live recipes that pass their own gate - a short pickle
    #: recipe is complete at 110 words, and declaring it defective would be this file
    #: overruling a published standard it does not own.
    if str(record.get("category") or "").strip() != "Gastronomy" and words < ABSOLUTE_MIN_WORDS:
        out.append(_block("11", "BODY_TOO_THIN",
                          f"{words} words cannot land a distinction "
                          f"(absolute floor {ABSOLUTE_MIN_WORDS})"))

    if article_type == "DEEP_ARTICLE" and len(headings(body)) < 2:
        out.append(_review("10", "DEEP_WITHOUT_SECTIONS",
                           "DEEP_ARTICLE is claimed but the body has fewer than 2 headings; "
                           "the type requires several connected distinctions",
                           "EDITORIAL_QA"))

    #: Keyed on LENGTH, not on the declared type. A 300-word DISTINCTION legitimately runs
    #: as one or two paragraphs - several of the published originals do - so demanding
    #: three would be demanding padding, which section 11 explicitly rejects. Past the
    #: DISTINCTION ceiling, a body with no paragraph breaks is the wall of text the
    #: Gastronomy gate added this assertion to catch.
    paragraphs = substantive_paragraphs(body)
    ceiling = ARTICLE_TYPES["DISTINCTION"][1]
    if len(paragraphs) < 3 and words > ceiling:
        out.append(_block("26", "NO_PARAGRAPH_SPACING",
                          f"{words} words in only {len(paragraphs)} substantive top-level "
                          "paragraph(s); blank-line separated paragraphs are what stop the post "
                          "publishing as one wall"))
    return out


def check_opening(record: Dict[str, Any]) -> List[Finding]:
    """Sections 7 and 8."""
    out: List[Finding] = []
    body = body_of(record)
    paragraphs = substantive_paragraphs(body, minimum_chars=1)
    opening = strip_markdown(paragraphs[0]).lower() if paragraphs else ""

    for marker in CLICKBAIT_MARKERS:
        if marker in opening:
            out.append(_block("8", "CLICKBAIT_OPENING",
                              f"opening carries the clickbait marker {marker!r}"))

    #: Section 7 permits the technique and then warns against it: "Do not turn every
    #: article into rhetorical questions." So this counts rather than bans.
    prose = strip_markdown(body)
    all_sentences = sentences(prose)
    questions = [s for s in all_sentences if s.endswith("?")]
    if all_sentences and len(questions) / len(all_sentences) > 0.25 and len(questions) >= 4:
        out.append(_review("7", "RHETORICAL_QUESTION_HEAVY",
                           f"{len(questions)} of {len(all_sentences)} sentences are questions; "
                           "the experience-before-explanation technique has become the format",
                           "EDITORIAL_REWRITE"))
    return out


def check_voice(record: Dict[str, Any]) -> List[Finding]:
    """Sections 13, 14 and 15. Produces the `formulaicAIRhythmDetected` answer."""
    out: List[Finding] = []
    prose = strip_markdown(body_of(record)).lower()

    hits = sorted({phrase for phrase in AI_RHYTHM_PHRASES if phrase in prose})
    #: One stock phrase is a word choice. Three is a formula, and section 13's required
    #: answer `formulaicAIRhythmDetected: NO` is what that threshold is deciding.
    if len(hits) >= 3:
        out.append(_block("13", "AI_RHYTHM",
                          f"formulaicAIRhythmDetected would be YES: {len(hits)} stock AI "
                          f"constructions present ({', '.join(hits[:5])})"))
    elif len(hits) == 2:
        out.append(_review("13", "AI_RHYTHM_EMERGING",
                           f"two stock AI constructions present ({', '.join(hits)}); "
                           "the problem is repetition and formula",
                           "EDITORIAL_REWRITE"))
    elif hits:
        out.append(_note("13", "AI_RHYTHM_TRACE", f"stock construction {hits[0]!r} present"))

    self_help = sorted({phrase for phrase in SELF_HELP_PHRASES if phrase in prose})
    if self_help:
        out.append(_block("14", "GENERIC_SELF_HELP",
                          "generic self-help language present, and Anew is inquiry-driven "
                          f"writing: {', '.join(self_help[:5])}"))

    if record.get("formulaicAIRhythmDetected") and not _is_no(record.get("formulaicAIRhythmDetected")):
        out.append(_block("13", "AI_RHYTHM_DECLARED",
                          "formulaicAIRhythmDetected is not NO"))

    #: Section 15. Uniform sentence length is the measurable signature of generated
    #: prose, and it is the one thing "every article should have its own rhythm" rules out.
    lengths = [len(s.split()) for s in sentences(strip_markdown(body_of(record)))]
    if len(lengths) >= 12:
        mean = sum(lengths) / len(lengths)
        if mean:
            variance = sum((n - mean) ** 2 for n in lengths) / len(lengths)
            if (variance ** 0.5) / mean < 0.28:
                out.append(_review("15", "UNIFORM_CADENCE",
                                   f"sentence lengths are near-uniform (mean {mean:.1f} words, "
                                   "spread under 28%); the article has no rhythm of its own",
                                   "EDITORIAL_REWRITE"))

    #: Section 15 again: repeated paragraph openings are transitional padding.
    openers = [strip_markdown(text).split()[0].lower()
               for kind, text in blocks(body_of(record))
               if kind == "paragraph" and strip_markdown(text).split()]
    if len(openers) >= 6:
        top = max(set(openers), key=openers.count)
        if openers.count(top) / len(openers) > 0.34:
            out.append(_review("15", "REPEATED_OPENER",
                               f"{openers.count(top)} of {len(openers)} paragraphs open with "
                               f"{top!r}",
                               "EDITORIAL_REWRITE"))

    if record.get("explanatoryPaddingRemoved") is not None and not _is_yes(
            record.get("explanatoryPaddingRemoved")):
        out.append(_review("15", "PADDING_NOT_REMOVED",
                           "explanatoryPaddingRemoved must be YES", "EDITORIAL_REWRITE"))
    return out


def check_privacy_and_attribution(record: Dict[str, Any]) -> List[Finding]:
    """Sections 17, 18 and 19."""
    out: List[Finding] = []
    body = body_of(record)
    prose = strip_markdown(body)
    lowered = prose.lower()
    article_class = text_field(record, "articleClass").upper()
    public_surfaces = [("body", prose)]
    for field_name in ("title", "excerpt", "seoTitle", "metaDescription", "focusKeyword"):
        value = text_field(record, field_name)
        if value:
            public_surfaces.append((field_name, value))

    for pattern in FALSE_BIOGRAPHY_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            out.append(_block("18", "FALSE_ANEW_BIOGRAPHY",
                              "a source biography has been converted into Anew's own "
                              f"({match.group(0)!r}); choose REMOVE, ANONYMIZE, GENERALIZE, "
                              "KEEP_INTERNAL_ONLY or RESTRUCTURE_AROUND_DISTINCTION instead"))
            break

    #: ARCHIVE_DERIVED is reconstructed fresh, so a surviving first-person wrapper means
    #: the "rename and swap I for we" path the standard's final rule forbids.
    if article_class == "ARCHIVE_DERIVED" and re.search(FIRST_PERSON_WRAPPER, prose):
        out.append(_review("18", "FIRST_PERSON_WRAPPER",
                           "first-person wrapper survives in an ARCHIVE_DERIVED body; the "
                           "personal wrapper is removed and the distinction reconstructed",
                           "PERSONAL_REFERENCE_REWORK"))

    #: Public copy may not retain source-facing narration or attribution. Source identity and
    #: provenance stay internal; the public article states the distinction directly.
    if article_class == "ARCHIVE_DERIVED":
        found_wrapper = False
        for surface_name, surface_text in public_surfaces:
            for pattern in SOURCE_WRAPPER_PATTERNS:
                match = re.search(pattern, surface_text, flags=re.IGNORECASE | re.MULTILINE)
                if match:
                    out.append(_block(
                        "18", "SOURCE_WRAPPER",
                        "source-facing wrapper survives in public copy "
                        f"{surface_name} ({match.group(0)!r}); state the distinction directly "
                        "and keep provenance in non-public source metadata"))
                    found_wrapper = True
                    break
            if found_wrapper:
                break

    found_remnant = False
    for surface_name, surface_text in public_surfaces:
        for pattern in SOURCE_REMNANT_PATTERNS:
            match = re.search(pattern, surface_text, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                out.append(_block(
                    "18", "SOURCE_REMNANT",
                    "broken source-removal residue survives in public copy "
                    f"{surface_name} ({match.group(0)!r}); reconstruct the sentence before "
                    "publication"))
                found_remnant = True
                break
        if found_remnant:
            break

    if record.get("privateNamesChecked") is not None and not _is_yes(record.get("privateNamesChecked")):
        out.append(_review("18", "NAMES_UNCHECKED", "privateNamesChecked must be YES",
                           "PERSONAL_REFERENCE_REWORK"))
    if record.get("falseAnewBiography") and not _is_no(record.get("falseAnewBiography")):
        out.append(_block("18", "BIOGRAPHY_DECLARED", "falseAnewBiography must be NO"))

    #: A long quotation-like passage needs ownership/provenance adjudication. The remedy is
    #: never to add public attribution: either establish it as article-owned/rhetorical copy,
    #: rewrite it independently, or omit it.
    for quote in re.findall(r"[\"\u201c]([^\"\u201d]{40,})[\"\u201d]", prose):
        out.append(_review(
            "19", "QUOTATION_PROVENANCE_UNCLEAR",
            f"a {len(quote.split())}-word quotation-like passage needs provenance review; "
            "do not add public attribution",
            "EDITORIAL_REWRITE"))
        break

    if re.search(r"\b\d{1,3}(?:\.\d+)?\s?%", prose) or re.search(
            r"\b(?:studies show|research shows|scientists (?:say|found)|a study found|"
            r"statistics show)\b", lowered):
        if not _is_yes(record.get("currentFactCheckComplete")) and \
                _flag_answer(record.get("currentFactCheckComplete")) != "N/A":
            out.append(_review("20", "UNVERIFIED_STATISTIC",
                               "the body carries a statistic or a 'studies show' claim; a "
                               "factual review must be recorded, not left blank",
                               "FACT_CHECK_REQUIRED"))

    return out


def _trigger_present(trigger: str, lowered: str) -> bool:
    """A section 20 trigger, anchored on a word boundary at the LEFT only.

    Plain `trigger in lowered` fired on words that merely CONTAIN a trigger, and the first real
    article to hit it was a piece about keeping agreements: it says "reliability", which contains
    "liability", so the gate demanded a legal review of an article with no legal claim in it.
    That is the failure section 20 is trying to prevent, arrived at backwards - a reviewer who is
    asked for a legal review of something with no law in it learns to answer YES to clear the
    form.

    LEFT ONLY, deliberately. Two triggers are prefixes on purpose - `in 18` and `in 19` are meant
    to catch "in 1943" - and a right-hand boundary would break exactly those. So this fixes
    trigger-at-the-end-of-a-word ("reliability") and knowingly leaves
    trigger-at-the-start-of-a-word ("invest" inside "investigation"), which is the narrower
    remaining imprecision and errs toward asking rather than skipping.
    """
    return bool(re.search(r"\b" + re.escape(trigger), lowered))


def check_factual_reviews(record: Dict[str, Any]) -> List[Finding]:
    """Section 20. A domain claim may not sit behind an N/A review."""
    out: List[Finding] = []
    lowered = strip_markdown(body_of(record)).lower()
    for flag, triggers in FACT_DOMAIN_TRIGGERS.items():
        matched = sorted({t for t in triggers if _trigger_present(t, lowered)})
        if not matched:
            continue
        answer = _flag_answer(record.get(flag))
        if answer == "YES":
            continue
        out.append(_review("20", "REVIEW_REQUIRED",
                           f"{flag} is {answer or '<unset>'} but the body makes claims in that "
                           f"domain ({', '.join(matched[:4])})",
                           "FACT_CHECK_REQUIRED"))
    return out


def check_title(record: Dict[str, Any]) -> List[Finding]:
    """Section 21."""
    out: List[Finding] = []
    title = str(record.get("title") or "").strip()
    if not title:
        out.append(_block("21", "TITLE_MISSING", "title is required"))
        return out
    lowered = title.lower()
    for marker in CLICKBAIT_MARKERS:
        if marker in lowered:
            out.append(_block("21", "CLICKBAIT_TITLE",
                              f"title carries the clickbait marker {marker!r}"))
    if len(title) > 90:
        out.append(_review("21", "TITLE_LONG", f"title is {len(title)} characters",
                           "EDITORIAL_QA"))
    if title.isupper():
        out.append(_block("21", "TITLE_SHOUTING", "title is all caps"))
    if record.get("titleRepresentsArticle") is not None and not _is_yes(
            record.get("titleRepresentsArticle")):
        out.append(_block("21", "TITLE_UNFAITHFUL", "titleRepresentsArticle must be YES"))
    return out


def check_slug_and_dates(record: Dict[str, Any]) -> List[Finding]:
    """Sections 22 and 23, both of which branch on article class."""
    out: List[Finding] = []
    article_class = text_field(record, "articleClass").upper()
    slug = str(record.get("slug") or "").strip()

    if not slug:
        out.append(_block("22", "SLUG_MISSING", "slug is required"))
    elif slug != slugify(slug):
        out.append(_block("22", "SLUG_NOT_URL_SAFE",
                          f"slug {slug!r} is not URL-safe; expected {slugify(slug)!r}"))

    if article_class == "ORIGINAL_109":
        established = text_field(record, "establishedSlug")
        if established and slug and slug != established:
            if not str(record.get("redirectResolved") or "").strip():
                out.append(_block("22", "SLUG_BROKEN_WITHOUT_REDIRECT",
                                  f"slug moved from {established!r} to {slug!r}; section 22 "
                                  "requires the redirect to be resolved first"))
        original_date = text_field(record, "originalPublishedDate")
        if not original_date:
            out.append(_review("23", "ORIGINAL_DATE_MISSING",
                               "ORIGINAL_109 must preserve originalPublishedDate",
                               "SOURCE_REVIEW"))

    if article_class == "ARCHIVE_DERIVED":
        source_slug = text_field(record, "sourceSlug")
        if source_slug and slug == source_slug:
            out.append(_block("22", "SLUG_NOT_FRESH",
                              "ARCHIVE_DERIVED requires a fresh Anew slug distinct from the "
                              "source slug"))
        if re.search(r"-\d{1,3}$", slug):
            out.append(_review("22", "SLUG_NUMBERED",
                               f"slug {slug!r} ends in a number, which section 22 forbids when "
                               "it is only there to force uniqueness",
                               "DEDUPE_REWORK"))
        if not text_field(record, "originalSourceDate"):
            out.append(_review("23", "SOURCE_DATE_MISSING",
                               "ARCHIVE_DERIVED must preserve originalSourceDate internally",
                               "SOURCE_REVIEW"))
        #: Section 23's explicit prohibition: do not publicly backdate a newly
        #: reconstructed article to its archive source date.
        public_date = text_field(record, "publicPublishedDate")
        source_date = text_field(record, "originalSourceDate")
        if public_date and source_date and public_date[:10] == source_date[:10]:
            out.append(_block("23", "PUBLIC_BACKDATED",
                              f"publicPublishedDate {public_date[:10]} equals the archive source "
                              "date; the public date must be the actual publication moment"))
    return out


def check_public_source_exposure(record: Dict[str, Any]) -> List[Finding]:
    """Block external source/reference/attribution material from public blog copy.

    Internal provenance metadata may exist, but title, SEO, excerpt, meta description,
    and body must read as independent WECARE.DIGITAL editorial copy.
    """
    out: List[Finding] = []
    surfaces = {
        "title": str(record.get("title") or ""),
        "seoTitle": text_field(record, "seoTitle"),
        "excerpt": text_field(record, "excerpt"),
        "metaDescription": text_field(record, "metaDescription"),
        "body": strip_markdown(body_of(record)),
    }
    patterns = (
        ("PUBLIC_EXTERNAL_URL", r"https?://|www\\."),
        ("PUBLIC_CITATION_LANGUAGE",
         r"\\b(?:according to|cited by|quoted in|reference(?:s)?\\s*:|source\\s*:|"
         r"adapted from|the source|source recipe|the cookbook|in the cookbook|the book says|"
         r"the author says|the author writes)\\b"),
    )
    source_terms = []
    for key in (
        "originalSourceTitle", "sourceTitle", "source_author", "sourceAuthor",
        "sourcePublisher", "publisherName", "sourceInstitution", "institutionName",
    ):
        value = str(record.get(key) or "").strip()
        if value:
            source_terms.append(value)

    for surface_name, value in surfaces.items():
        for code, pattern in patterns:
            if re.search(pattern, value, re.IGNORECASE):
                out.append(_block(
                    "19", code,
                    f"{surface_name} contains public source/reference/attribution material; "
                    "keep provenance internal and rewrite public copy without the reference"))
                break
        lowered = value.casefold()
        for term in source_terms:
            if term.casefold() in lowered:
                out.append(_block(
                    "19", "PUBLIC_NAMED_SOURCE_TERM",
                    f"{surface_name} exposes source/person/work provenance {term!r}; "
                    "keep it internal and rewrite the public copy"))
                break
    return out


def check_seo_and_metadata(record: Dict[str, Any]) -> List[Finding]:
    """Sections 24 and 25."""
    out: List[Finding] = []
    slug = str(record.get("slug") or "").strip()

    if not text_field(record, "seoTitle"):
        out.append(_block("24", "SEO_TITLE_MISSING", "seoTitle is required"))

    meta = text_field(record, "metaDescription")
    if not meta:
        out.append(_block("24", "META_MISSING", "metaDescription is required"))
    elif len(meta) < 80 or len(meta) > 200:
        out.append(_block("24", "META_LENGTH",
                          f"metaDescription is {len(meta)} characters; outside 80-200 it is "
                          "either uninformative or truncated everywhere it appears"))
    elif not 140 <= len(meta) <= 160:
        out.append(_note("24", "META_BAND",
                         f"metaDescription is {len(meta)} characters, outside the 140-160 "
                         "target (section 24 says 'where practical')"))

    canonical = canonical_of(record)
    if slug:
        if not canonical:
            #: REVIEW rather than BLOCK, because an absent canonical is DERIVED at publish
            #: time from the slug, and none of the 108 published Conversations manifests
            #: stores one. A stored canonical that DISAGREES with the slug is the real
            #: defect, and that still blocks below.
            out.append(_review("24", "CANONICAL_MISSING",
                               f"canonical is not stored; it will be derived as "
                               f"{expected_canonical(slug)}",
                               "EDITORIAL_QA"))
        elif canonical != expected_canonical(slug):
            out.append(_block("24", "CANONICAL_MISMATCH",
                              f"canonical {canonical!r} does not match the slug; expected "
                              f"{expected_canonical(slug)!r}"))

    tags = field(record, "tags", []) or []
    if not isinstance(tags, list) or not 1 <= len(tags) <= 3:
        out.append(_block("24", "TAG_COUNT",
                          f"tags must be a list of 1-3 labels, got "
                          f"{len(tags) if isinstance(tags, list) else type(tags).__name__}"))
    elif len({str(t).strip().lower() for t in tags}) != len(tags):
        out.append(_block("24", "TAG_DUPLICATE", "tags contain a duplicate"))

    author = text_field(record, "author")
    if author != AUTHOR:
        out.append(_block(
            "25", "AUTHOR_WRONG",
            f"public author must be explicitly present and exactly {AUTHOR!r}, got {author or '<missing>'!r}"))

    category = str(record.get("category") or "").strip()
    if category not in CATEGORIES:
        out.append(_block("25", "CATEGORY_INVALID",
                          f"category must be one of {list(CATEGORIES)}, got {category or '<empty>'}"))
    return out


def check_formatting_and_images(record: Dict[str, Any]) -> List[Finding]:
    """Sections 26 and 27."""
    out: List[Finding] = []
    body = body_of(record)

    for pattern in LEGACY_MARKUP:
        if re.search(pattern, body, re.IGNORECASE):
            out.append(_block("26", "LEGACY_MARKUP",
                              f"legacy styling {pattern!r} in the body; typography belongs to "
                              "the frontend system"))
            break

    if "\\n" in body:
        out.append(_block("26", "LITERAL_NEWLINE",
                          "body contains a literal escaped newline, which publishes verbatim"))
    if re.search(r"\b(?:undefined|null|NaN)\b", strip_markdown(body)):
        out.append(_block("26", "PLACEHOLDER_TOKEN",
                          "body contains an editor placeholder token (undefined/null/NaN)"))
    if re.search(r'\{\s*["\']?(?:type|nodes|richContent|textData)["\']?\s*:', body):
        out.append(_block("26", "RAW_EDITOR_JSON", "raw editor JSON leaked into the body"))
    if re.search(r"^#{1,6}\s", body) and re.search(r"[^\n]#{2,6}\s", body):
        out.append(_note("26", "INLINE_HASH", "a '#' heading marker appears mid-line"))

    #: Section 27: the default is NONE, and it is a default the corpus actually holds.
    image_status = (text_field(record, "imageStatus") or "none").lower()
    if image_status not in {"none", ""}:
        out.append(_block("27", "IMAGE_PRESENT",
                          f"articleImage must be NONE; got {image_status!r}"))
    for key in FORBIDDEN_IMAGE_KEYS:
        if record.get(key):
            out.append(_block("27", "IMAGE_FIELD",
                              f"{key} is forbidden: the blog is image-free"))
    for node in walk_nodes(record.get("richContent") or {}):
        node_type = str(node.get("type") or "").upper()
        if node_type in FORBIDDEN_MEDIA_NODES:
            out.append(_block("27", "MEDIA_NODE",
                              f"forbidden rich-content media node: {node_type}"))
            break
    if re.search(r"!\[[^\]]*\]\([^)]*\)", body):
        out.append(_block("27", "MARKDOWN_IMAGE", "the body embeds a markdown image"))
    return out


def check_gastronomy_structure(record: Dict[str, Any]) -> List[Finding]:
    """The Gastronomy category's own structural contract.

    Reproduced from `gastronomy_batch.validate_batch_document` rather than imported,
    because that module reaches for boto3 and this gate must run with nothing installed.
    Divergence risk is real and accepted: `tests/test_blog_quality_v2.py` asserts the
    two agree on a known-good committed batch, so a drift shows up as a failing test
    rather than as two gates quietly disagreeing.
    """
    out: List[Finding] = []
    body = body_of(record)
    found = headings(body)
    if "Ingredients" not in found:
        out.append(_block("26", "GAST_NO_INGREDIENTS", "missing Ingredients heading"))
    if "Method" not in found:
        out.append(_block("26", "GAST_NO_METHOD", "missing Method heading"))
    if not has_list(body):
        out.append(_block("26", "GAST_NO_LIST", "missing ingredient list"))
    if len(strip_markdown(body).strip()) < 450:
        out.append(_block("11", "GAST_TOO_THIN", "body too thin for editorial publication"))
    return out


# ── Section 28: the duplication gate ────────────────────────────────────────────

@dataclass
class CorpusEntry:
    slug: str
    title: str
    normalized_title: str
    category: str
    #: A bottom-k sketch, not an exact shingle set. Holding exact shingles for the 1,165
    #: published posts was 4.5 MB in memory and unshippable as a committed index; this is
    #: ~1 kB per post and estimates the same quantity to within ~3%.
    sketch: List[int] = dataclass_field(default_factory=list)
    distinction: str = ""
    origin: str = ""


class CorpusIndex:
    """Everything already published or prepared, for section 28 to compare against.

    Section 28 lists six populations to check: the 109 originals, the already-published
    designation articles, later archive articles, earlier articles in the current wave,
    prepared-but-unpublished articles, and near titles/slugs. They are all the same
    operation, so this holds one index and the caller decides what to load into it.
    """

    #: Two titles this close are the same article under a different name.
    TITLE_SIMILARITY = 0.80
    #: Shared 8-word shingles at this rate is a cosmetic rewrite, not a new article.
    BODY_SIMILARITY = 0.35
    BODY_NEAR_DUPLICATE = 0.60
    DISTINCTION_SIMILARITY = 0.55

    #: The committed sketch index of everything already published.
    PUBLISHED_INDEX_PATH = Path("content/conversations/corpus-index.json")

    def __init__(self) -> None:
        self.entries: List[CorpusEntry] = []
        self._by_slug: Dict[str, CorpusEntry] = {}

    def __len__(self) -> int:
        return len(self.entries)

    def add(self, record: Dict[str, Any], origin: str = "") -> None:
        slug = str(record.get("slug") or "").strip()
        title = str(record.get("title") or "").strip()
        entry = CorpusEntry(
            slug=slug,
            title=title,
            normalized_title=_normalize_title(title),
            category=str(record.get("category") or "").strip(),
            sketch=sketch(body_of(record)),
            distinction=text_field(record, "centralDistinction"),
            origin=origin or str(record.get("sourceFile") or ""),
        )
        self.entries.append(entry)
        if slug:
            self._by_slug.setdefault(slug, entry)

    def load_manifest(self, path: Path) -> int:
        posts = load_posts(path)
        for post in posts:
            self.add(post, origin=str(path))
        return len(posts)

    def load_published_index(self, path: Path = PUBLISHED_INDEX) -> int:
        """Load the sketch index of the whole published corpus.

        THIS IS WHAT MAKES SECTION 28 HONEST. Without it the gate compared a new article
        against the committed manifests only - 383 records against a live corpus of 1,165 -
        and returned `PASS` having checked a third of it. A duplication gate that reports
        success on an unchecked corpus is worse than no gate, because it is believed.

        Silently absent is deliberate: the index is built by `blog_corpus_index.py` and a
        caller that needs to know whether it is present asks `published_index_health()`,
        which is what the CI gate does. Raising here would make every unit test that builds
        a two-record corpus depend on a 1.4 MB file.
        """
        target = Path(path)
        if not target.exists():
            return 0
        try:
            document = json.loads(target.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return 0
        added = 0
        for post in document.get("posts") or []:
            slug = str(post.get("slug") or "").strip()
            if not slug or slug in self._by_slug:
                continue
            title = str(post.get("title") or "")
            entry = CorpusEntry(
                slug=slug,
                title=title,
                normalized_title=str(post.get("normalizedTitle") or _normalize_title(title)),
                category=str(post.get("category") or ""),
                sketch=decode_sketch(post.get("sketch")),
                #: Published posts predate the standard, so they carry no centralDistinction.
                #: Distinction-level comparison is therefore within-wave only, by necessity.
                distinction="",
                origin="published-corpus",
            )
            self.entries.append(entry)
            self._by_slug[slug] = entry
            added += 1
        return added

    def findings(self, record: Dict[str, Any], exclude_slug: str = "") -> List[Finding]:
        out: List[Finding] = []
        slug = str(record.get("slug") or "").strip()
        exclude_slug = str(exclude_slug or "").strip()
        title = str(record.get("title") or "").strip()
        normalized = _normalize_title(title)
        mine = sketch(body_of(record))
        distinction = text_field(record, "centralDistinction")

        if slug and slug in self._by_slug and slug != exclude_slug:
            other = self._by_slug[slug]
            out.append(_block("28", "EXACT_SLUG_COLLISION",
                              f"slug {slug!r} already exists"
                              + (f" ({other.origin})" if other.origin else "")))

        worst_body = 0.0
        worst_body_entry: Optional[CorpusEntry] = None
        for entry in self.entries:
            if entry.slug and entry.slug == slug:
                continue
            if normalized and entry.normalized_title:
                if normalized == entry.normalized_title:
                    out.append(_review("6", "TITLE_ONLY_DIFFERENCE",
                                       f"title reduces to the same inquiry as {entry.title!r} "
                                       f"({entry.slug}); two titles do not make two articles",
                                       "DEDUPE_REWORK"))
                else:
                    similarity = _jaccard(set(normalized.split()), set(entry.normalized_title.split()))
                    if similarity >= self.TITLE_SIMILARITY:
                        out.append(_review("28", "NEAR_TITLE",
                                           f"title is {similarity:.0%} similar to {entry.title!r} "
                                           f"({entry.slug})",
                                           "DEDUPE_REWORK"))
            if mine and entry.sketch:
                similarity = sketch_jaccard(mine, entry.sketch)
                if similarity > worst_body:
                    worst_body, worst_body_entry = similarity, entry
            if distinction and entry.distinction:
                similarity = _jaccard(set(re.findall(r"[a-z0-9']+", distinction.lower())),
                                      set(re.findall(r"[a-z0-9']+", entry.distinction.lower())))
                if similarity >= self.DISTINCTION_SIMILARITY:
                    out.append(_review("28", "SAME_DISTINCTION",
                                       f"centralDistinction is {similarity:.0%} similar to "
                                       f"{entry.slug!r}; same domain is allowed, same distinction "
                                       "is not",
                                       "DEDUPE_REWORK"))

        if worst_body_entry is not None:
            if worst_body >= self.BODY_NEAR_DUPLICATE:
                out.append(_block("28", "EXACT_BODY_DUPLICATE",
                                  f"body shares {worst_body:.0%} of its 8-word sequences with "
                                  f"{worst_body_entry.slug!r}; this is a rewrite, not an article"))
            elif worst_body >= self.BODY_SIMILARITY:
                out.append(_review("28", "BODY_OVERLAP",
                                   f"body shares {worst_body:.0%} of its 8-word sequences with "
                                   f"{worst_body_entry.slug!r}",
                                   "DEDUPE_REWORK"))

        for flag, expected in (("exactSlugCollision", False), ("exactBodyDuplicate", False),
                               ("unresolvedConceptualDuplicate", False),
                               ("uniquePurposeRecorded", True)):
            value = record.get(flag)
            if value is None:
                continue
            if expected and not _is_yes(value):
                out.append(_review("28", "DEDUPE_FLAG", f"{flag} must be YES", "DEDUPE_REWORK"))
            if not expected and not _is_no(value):
                out.append(_review("28", "DEDUPE_FLAG", f"{flag} must be NO", "DEDUPE_REWORK"))
        return out


# ── Section 29 / 32: the gate table and the status decision ─────────────────────

def machine_gate_table(findings: Sequence[Finding]) -> Dict[str, str]:
    """The three section-29 rows a program can actually decide."""
    blocking = [f for f in findings if f.severity == "BLOCK"]
    dedupe = [f for f in findings if f.section in {"6", "28"} and f.severity in {"BLOCK", "REVIEW"}]
    metadata = [f for f in findings
                if f.section in {"21", "22", "23", "24", "25"} and f.severity == "BLOCK"]
    tightness = [f for f in findings if f.code in {
        "AI_RHYTHM", "AI_RHYTHM_EMERGING", "UNIFORM_CADENCE", "REPEATED_OPENER",
        "ABOVE_BAND", "PADDING_NOT_REMOVED", "RHETORICAL_QUESTION_HEAVY",
    }]
    author_identity = [f for f in findings if f.code == "AUTHOR_WRONG" and f.severity == "BLOCK"]
    public_source = [f for f in findings if (
        f.code.startswith("PUBLIC_")
        or f.code in {"SOURCE_WRAPPER", "SOURCE_REFERENCE_LEAK"}
    ) and f.severity == "BLOCK"]
    return {
        "NON_DUPLICATION": "FAIL" if dedupe else "PASS",
        "METADATA": "FAIL" if metadata else "PASS",
        #: The standard asks "Can anything unnecessary still be removed?" and requires NO.
        "TIGHTNESS": "NO" if not tightness else "YES",
        "AUTHOR_IDENTITY": "FAIL" if author_identity else "PASS",
        "PUBLIC_SOURCE_EXPOSURE": "FAIL" if public_source else "PASS",
        "_BLOCKING": str(len(blocking)),
    }


def decide_status(record: Dict[str, Any], findings: Sequence[Finding]) -> str:
    """The single status for a record (section 32).

    Mechanical checks can only move a record down. A record that passes everything here
    lands on EDITORIAL_QA, and only a human recording the section-29 human gates plus
    the section-30 read can carry it to READY_TO_PUBLISH. That asymmetry is the whole
    point of this module - see the file docstring.
    """
    current = str(record.get("status") or "").strip().upper()
    if current in {"PUBLISHED", "VERIFIED"}:
        #: Never rewind a published record from a validator; section 33 owns that
        #: transition and it needs a live read-back to make it.
        return current

    #: Order matters: the earliest unmet precondition is the status, because that is the
    #: desk the record has to go back to. Source review precedes dedupe precedes writing.
    precedence = (
        "SOURCE_REVIEW",
        "DEDUPE_REWORK",
        "PERSONAL_REFERENCE_REWORK",
        "FACT_CHECK_REQUIRED",
        "EDITORIAL_REWRITE",
    )
    routed = {f.routes_to for f in findings if f.severity in {"BLOCK", "REVIEW"} and f.routes_to}
    for status in precedence:
        if status in routed:
            return status
    if any(f.severity == "BLOCK" for f in findings):
        return "EDITORIAL_REWRITE"

    gate = {str(k).strip().upper(): _flag_answer(v)
            for k, v in (record.get("gate") or {}).items()}
    missing = [name for name in HUMAN_GATES if gate.get(name) not in {"PASS", "N/A"}]
    if missing:
        return "EDITORIAL_QA"
    if current == PUBLISHABLE_STATUS:
        return PUBLISHABLE_STATUS
    return PUBLISHABLE_STATUS


def check_status_field(record: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    status = str(record.get("status") or "").strip().upper()
    if not status:
        out.append(_review("32", "STATUS_MISSING",
                           "every record must carry exactly one status", "SOURCE_REVIEW"))
    elif status not in STATUSES:
        out.append(_block("32", "STATUS_INVALID",
                          f"status {status!r} is not one of {list(STATUSES)}"))
    return out


# ── The whole-record entry point ────────────────────────────────────────────────

#: Content-shape rules that a pre-v2 published record can fail without that being a
#: reason to fail a build. Metadata, duplication and image-policy failures are NOT here:
#: a colliding slug or a leaked image is a live defect regardless of when it was written.
LEGACY_SOFTENED_CODES: Tuple[str, ...] = (
    "BODY_TOO_THIN", "NO_PARAGRAPH_SPACING", "META_LENGTH", "AI_RHYTHM",
    "GENERIC_SELF_HELP", "CLICKBAIT_OPENING", "FALSE_ANEW_BIOGRAPHY",
    # A metaDescription clipped at migration (the legacy corpus has 48 cut uniformly at
    # ~155 chars) is a real defect worth REVIEW, but hard-failing the build on already-
    # published content is the "cries wolf, gets switched off" outcome the softening exists
    # to avoid. Still BLOCKs for a NEW record, where a truncated description is an authoring
    # defect to fix before publish; only legacy records are softened to REVIEW.
    "PUBLIC_METADATA_TRUNCATED",
)


def _soften_for_legacy(findings: Sequence[Finding]) -> List[Finding]:
    """Downgrade content-shape BLOCKs to REVIEW on a pre-v2 record.

    NOT the same as hiding them. The finding is still reported, the record still routes
    to a rework status and therefore still cannot publish; only the build-failing severity
    changes. The alternative was a gate that printed 293 hard failures across 333 already
    published articles on its first run, and a gate that cries wolf about live content
    gets switched off - at which point it protects nothing.
    """
    out: List[Finding] = []
    for finding in findings:
        if finding.severity == "BLOCK" and finding.code in LEGACY_SOFTENED_CODES:
            out.append(Finding(finding.section, finding.code, "REVIEW",
                               finding.message + " (pre-v2 record: reported, not blocking)",
                               finding.routes_to or "EDITORIAL_REWRITE"))
            continue
        out.append(finding)
    return out


def check_record(record: Dict[str, Any], corpus: Optional[CorpusIndex] = None,
                 extra_findings: Sequence[Finding] = (),
                 corpus_exclude_slug: str = "") -> List[Finding]:
    """Every mechanically decidable clause of the standard, for one record.

    `extra_findings` exists so a caller can fold in rules this module cannot own. Content
    templates are the case that needed it: a template is a per-project record living in
    DynamoDB, and this module runs in CI with no AWS access at all, so it cannot resolve one.
    The dependency has to point that way round - `blog_templates` imports the gate, never the
    reverse - and passing findings in keeps the status machinery and the legacy softening in
    one place rather than duplicated at the call site.
    """
    findings: List[Finding] = list(extra_findings)
    findings += check_class_and_source(record)
    findings += check_distinction_and_purpose(record)
    findings += check_type_and_length(record)
    findings += check_opening(record)
    findings += check_voice(record)
    findings += check_privacy_and_attribution(record)
    findings += check_factual_reviews(record)
    findings += check_title(record)
    findings += check_slug_and_dates(record)
    findings += check_public_source_exposure(record)
    findings += check_seo_and_metadata(record)
    findings += check_editorial_corruption(record)
    findings += check_formatting_and_images(record)
    findings += check_status_field(record)
    if str(record.get("category") or "").strip() == "Gastronomy":
        findings += check_gastronomy_structure(record)
    if corpus is not None:
        findings += corpus.findings(record, exclude_slug=corpus_exclude_slug)
    if is_legacy_record(record):
        findings = _soften_for_legacy(findings)
    return findings


def assess(record: Dict[str, Any], corpus: Optional[CorpusIndex] = None,
           extra_findings: Sequence[Finding] = (),
           corpus_exclude_slug: str = "") -> Dict[str, Any]:
    """`check_record` plus the derived verdicts, as one reportable dict."""
    findings = check_record(record, corpus, extra_findings=extra_findings,
                            corpus_exclude_slug=corpus_exclude_slug)
    gate = machine_gate_table(findings)
    return {
        "slug": str(record.get("slug") or ""),
        "title": str(record.get("title") or ""),
        "category": str(record.get("category") or ""),
        "articleClass": text_field(record, "articleClass"),
        "articleType": text_field(record, "articleType"),
        "legacyRecord": is_legacy_record(record),
        "words": word_count(body_of(record)),
        "declaredStatus": str(record.get("status") or ""),
        "status": decide_status(record, findings),
        "blocking": [str(f) for f in findings if f.severity == "BLOCK"],
        "review": [str(f) for f in findings if f.severity == "REVIEW"],
        "notes": [str(f) for f in findings if f.severity == "NOTE"],
        "machineGate": {k: v for k, v in gate.items() if not k.startswith("_")},
        "humanGatesOutstanding": [
            name for name in HUMAN_GATES
            if _flag_answer((record.get("gate") or {}).get(name)) not in {"PASS", "N/A"}
        ],
        "readyToPublish": decide_status(record, findings) == PUBLISHABLE_STATUS,
    }


# ── Section 34: the wave ────────────────────────────────────────────────────────

def load_posts(path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    posts = raw.get("posts") if isinstance(raw, dict) else raw
    if not isinstance(posts, list):
        raise ValueError(f"{path}: expected a posts array or a JSON array")
    return posts


def assess_wave(posts: Sequence[Dict[str, Any]],
                corpus: Optional[CorpusIndex] = None) -> Dict[str, Any]:
    """Assess a wave, comparing each record against the ones before it.

    Section 28 requires comparison against "earlier articles in the current 250-wave",
    so the index grows as the wave is walked. That also means the FIRST occurrence of a
    duplicated pair is the clean one and the second is flagged, which is the right way
    round for a reviewer.
    """
    index = corpus or CorpusIndex()
    results: List[Dict[str, Any]] = []
    for post in posts:
        results.append(assess(post, index))
        index.add(post, origin="current-wave")

    by_status: Dict[str, int] = {}
    for result in results:
        by_status[result["status"]] = by_status.get(result["status"], 0) + 1
    return {
        "total": len(results),
        #: Section 34: every record must have an explicit status before the wave moves.
        "everyRecordHasStatus": all(r["status"] in STATUSES for r in results),
        "byStatus": dict(sorted(by_status.items())),
        "readyToPublish": sum(1 for r in results if r["readyToPublish"]),
        "blocked": sum(1 for r in results if r["blocking"]),
        "records": results,
    }


def publish_queue(wave: Dict[str, Any]) -> List[str]:
    """Only READY_TO_PUBLISH slugs. Section 32's gate on the publishing queue."""
    return [r["slug"] for r in wave["records"] if r["readyToPublish"]]


# ── CLI ─────────────────────────────────────────────────────────────────────────

def published_index_health(path: Path = PUBLISHED_INDEX) -> Dict[str, Any]:
    """Whether the duplication gate can honestly claim to have checked the corpus.

    Reported rather than raised, because the answer belongs in the output next to the
    verdict. The failure this guards against is not a crash - it is a `PASS` on
    NON_DUPLICATION produced by comparing against a third of the corpus, which is what the
    gate did until the index existed.
    """
    target = Path(path)
    if not target.exists():
        return {"present": False, "indexed": 0, "listing": 0, "builtAt": "",
                "note": (f"{target} is missing, so section 28 compared against committed "
                         "manifests only. Run: python scripts/blog_corpus_index.py build")}
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return {"present": False, "indexed": 0, "listing": 0, "builtAt": "",
                "note": f"{target} is unreadable ({type(exc).__name__}); rebuild it"}
    indexed = int(document.get("indexedCount") or 0)
    listing = int(document.get("listingCount") or 0)
    note = ""
    if listing and indexed < listing:
        note = (f"index covers {indexed} of {listing} posts recorded at build time; "
                f"{listing - indexed} unindexed")
    return {
        "present": indexed > 0,
        "indexed": indexed,
        "listing": listing,
        "builtAt": str(document.get("builtAt") or ""),
        "sketchK": document.get("sketchK"),
        "note": note,
    }


def _build_corpus(patterns: Sequence[str], published: bool = True) -> CorpusIndex:
    corpus = CorpusIndex()
    for pattern in patterns or ():
        for match in sorted(globlib.glob(pattern, recursive=True)):
            path = Path(match)
            if path.is_file() and path.suffix == ".json":
                try:
                    corpus.load_manifest(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    print(f"warning: skipped {path}: {exc}", file=sys.stderr)
    if published:
        corpus.load_published_index()
    return corpus


#: The published corpora section 28 wants every new record compared against.
DEFAULT_CORPUS = (
    "content/gastronomy/batches/GAST-*.json",
    "content/conversations/batches/CONV-*.json",
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Conversations Content Quality Standard v2 gate")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "report", "wave"):
        node = sub.add_parser(name)
        node.add_argument("--manifest", required=True, type=Path)
        node.add_argument("--against", nargs="*", default=None,
                          help="corpus globs for the section 28 duplication gate")
        node.add_argument("--no-default-corpus", action="store_true")
        node.add_argument("--no-published-index", action="store_true",
                          help="skip the published-corpus sketch index (testing only)")
        node.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    patterns: List[str] = list(args.against or [])
    if not args.no_default_corpus:
        patterns += [p for p in DEFAULT_CORPUS if str(args.manifest) not in p]
    use_published = not args.no_published_index and not args.no_default_corpus
    corpus = _build_corpus(patterns, published=use_published)
    #: A manifest under validation must not be compared against itself, or every record
    #: reports an exact slug collision with its own committed copy.
    target = Path(args.manifest).resolve()
    corpus.entries = [e for e in corpus.entries if Path(e.origin or ".").resolve() != target]
    corpus._by_slug = {e.slug: e for e in reversed(corpus.entries) if e.slug}

    posts = load_posts(args.manifest)
    wave = assess_wave(posts, corpus)

    health = published_index_health() if use_published else {
        "present": False, "note": "published index skipped by flag", "indexed": 0}
    if args.json:
        print(json.dumps({**wave, "publishedIndex": health}, indent=2))
    else:
        print(f"{args.manifest}: {wave['total']} record(s), corpus {len(corpus)} entries")
        # SAID OUT LOUD, EVERY RUN. A NON_DUPLICATION pass means nothing without knowing
        # what it was compared against, and the gate previously printed the pass alone.
        if health["present"]:
            print(f"  published corpus index: {health['indexed']} posts"
                  + (f", built {health['builtAt']}" if health.get("builtAt") else "")
                  + (f"  ⚠ {health['note']}" if health.get("note") else ""))
        else:
            print(f"  ⚠ NO PUBLISHED CORPUS INDEX — {health['note']}")
        for result in wave["records"]:
            marks = []
            if result["blocking"]:
                marks.append(f"{len(result['blocking'])} blocking")
            if result["review"]:
                marks.append(f"{len(result['review'])} review")
            print(f"  {result['status']:<26} {result['slug'] or '<no slug>':<44} "
                  f"{result['words']:>5}w  {', '.join(marks)}")
            for line in result["blocking"] + result["review"]:
                print(f"      {line}")
        print(f"\nby status: {wave['byStatus']}")
        print(f"READY_TO_PUBLISH: {wave['readyToPublish']}/{wave['total']}")
        if wave["readyToPublish"] < wave["total"]:
            outstanding = sorted({
                name for record in wave["records"] for name in record["humanGatesOutstanding"]
            })
            if outstanding:
                print("human gates still outstanding somewhere in this wave: "
                      + ", ".join(outstanding))

    if args.command == "wave":
        return 0 if wave["everyRecordHasStatus"] else 1
    if args.command == "report":
        return 0
    #: `validate` is the CI gate: blocking findings fail, review findings do not, because
    #: a record correctly parked on FACT_CHECK_REQUIRED is the system working.
    return 1 if wave["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
