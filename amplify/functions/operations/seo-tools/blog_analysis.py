"""Source analysis as a first-class, versioned record - evidence, not an opinion.

WHY THIS IS NOT A FIELD ON THE SOURCE ROW.

Section 2 of the quality standard is the one clause the rest of the pipeline rests on: an
article may not be built from a title, an excerpt or metadata. Somebody has to have read the
source. Before this module that claim was a single boolean, `sourceReviewedFully`, and a
boolean is not auditable - it records that a click happened, not what was read or when, and a
re-extraction silently left it standing over text nobody had seen.

So the analysis is its own record with its own id and its own version. Three properties
follow, and each of them is the reason for the shape:

1. **Versioned, never overwritten.** Re-analysing a source produces v2 and leaves v1 exactly
   as the reviewer found it. A reviewer's sign-off names the version they read, so a
   re-extraction invalidates the sign-off instead of quietly inheriting it.
2. **Evidence rather than judgement.** Everything this module computes is derived
   mechanically from the extracted text and is reproducible: which passages are first person,
   which sentences carry a checkable number, which quotations have no attribution nearby.
   None of it is a claim about quality. The editorial fields stay empty until a human fills
   them, the same contract `blog_sources._draft_record` keeps.
3. **It cannot move an article forward.** `analyse()` writes no status, no gate and no
   `sourceReviewedFully`. Only `record_review()` does, it is reachable only from an
   authenticated Admin route, and it refuses unless the reviewer names the analysis version
   they actually read.

## Where the body lives

The evidence can run to tens of kB on a long document - passage text, sentence text, a list
of quotations - so it goes to S3 and the DynamoDB record keeps counts plus the key. Same
reason the extract does: a 400 kB item cap is not much once real prose is involved.

The key lives under the source's canonical private work directory:
`secure/blog-production/03-work/<category>/<sourceId>/source-analysis/v<n>.json`.
Versioned keys preserve the exact artifact a reviewer signed against, while keeping every
artifact derived from one PDF/book together. Analysis bodies are never written to the public
`o/blog-production/` tree.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

import blog_sources
import storage

logger = logging.getLogger(__name__)

RECORD_TYPE = "blogSourceAnalysis"

#: Bounded so one enormous document cannot produce an evidence file nobody can read and a
#: response nobody can render. A reviewer needs representative passages, not all 400 of them.
MAX_PASSAGES = 40
MAX_PASSAGE_CHARS = 400
MAX_CLAIMS = 40
MAX_QUOTATIONS = 30

#: A quotation in the extracted text. Straight and curly, because a PDF extractor emits both
#: and a pattern that only knows about `"` misses most real documents.
_QUOTE = re.compile(r'[“"]([^”"]{25,400})[”"]')

#: "said X", "according to X", "X writes" - the shapes that make a quotation attributed. Only
#: looked for NEAR the quotation, because an attribution three pages away attributes nothing.
_ATTRIBUTION = re.compile(
    r"\b(?:said|says|wrote|writes|according to|argues|argued|notes|noted|observes|"
    r"observed|in the words of|as \w+ put it|quoted in|cited in)\b", re.IGNORECASE)
_ATTRIBUTION_WINDOW = 160

#: A sentence carrying a number a reader would take as fact. Bare years are excluded on
#: purpose: "in 1943" is a date, and flagging every date buries the percentages and dosages
#: that actually need a source.
_CHECKABLE_NUMBER = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:%|percent|per cent|mg|ml|g\b|kg|hours?|minutes?|days?|weeks?|"
    r"months?|years? old|times|x\b|billion|million|thousand|crore|lakh)", re.IGNORECASE)

#: A named private individual is a privacy obligation under section 19. Two capitalised words
#: in a row is a crude proxy and it is deliberately crude: it over-reports, a human filters,
#: and the alternative - a name list - under-reports in exactly the cases that matter.
_PROPER_NOUN_PAIR = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")

#: Words that make a capitalised pair a place, an institution or a title rather than a person.
_NOT_A_PERSON = {
    "The", "This", "That", "These", "Those", "There", "Then", "When", "While", "What",
    "Where", "Which", "Who", "Why", "How", "And", "But", "For", "Not", "All", "Any",
    "New", "United", "South", "North", "East", "West", "Chapter", "Part", "Section",
    "Figure", "Table", "Page", "Copyright", "Press", "University", "Institute", "Journal",
    "Review", "Times", "Post", "News", "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday", "January", "February", "March", "April", "May",
    "June", "July", "August", "September", "October", "November", "December",
}


def analysis_id(source_id: str, version: int) -> str:
    """Deterministic, so the same source and version always name the same record.

    Derived from the source id rather than a uuid, which means a replayed request resolves to
    the row that already exists instead of minting a second analysis of the same version -
    the same resolve-before-generate discipline the source id itself uses.
    """
    stem = str(source_id or "")
    if stem.startswith("blogsrc_"):
        stem = stem[len("blogsrc_"):]
    if not stem:
        raise ValueError("a source id is required")
    if int(version) < 1:
        raise ValueError("version starts at 1")
    return f"blogana_{stem}_v{int(version)}"


def body_key(source_id: str, version: int) -> str:
    return blog_sources.work_key_for_id(
        source_id, f"source-analysis/v{int(version)}.json")


# ── The evidence, computed from the text ────────────────────────────────────────

def _sentences(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _paragraphs(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def first_person_passages(text: str, q) -> List[Dict[str, Any]]:
    """Paragraphs written in the source author's first person.

    Section 18: a first-person story in the source must not survive into Anew's voice as
    Anew's own biography. Finding the passages is the mechanical half; deciding whether to
    remove, generalise or attribute each one is the human half.
    """
    pattern = re.compile(q.FIRST_PERSON_WRAPPER)
    out: List[Dict[str, Any]] = []
    for index, paragraph in enumerate(_paragraphs(text)):
        hits = pattern.findall(paragraph)
        if not hits:
            continue
        out.append({
            "paragraph": index,
            "markers": len(hits),
            "text": paragraph[:MAX_PASSAGE_CHARS],
        })
        if len(out) >= MAX_PASSAGES:
            break
    return out


def checkable_claims(text: str, q) -> List[Dict[str, Any]]:
    """Sentences a reader would take as a verifiable fact.

    Two independent triggers, reported together because they route to the same desk: a
    quantity a reader would act on, and a subject from `FACT_DOMAIN_TRIGGERS` whose review
    flag section 20 then requires to be an explicit YES rather than N/A.
    """
    out: List[Dict[str, Any]] = []
    for index, sentence in enumerate(_sentences(text)):
        lowered = sentence.lower()
        domains = sorted({
            domain for domain, triggers in q.FACT_DOMAIN_TRIGGERS.items()
            if any(trigger in lowered for trigger in triggers)
        })
        numbers = _CHECKABLE_NUMBER.findall(sentence)
        if not domains and not numbers:
            continue
        out.append({
            "sentence": index,
            "reviewFlags": domains,
            "quantities": len(numbers),
            "text": sentence[:MAX_PASSAGE_CHARS],
        })
        if len(out) >= MAX_CLAIMS:
            break
    return out


def quotations(text: str) -> List[Dict[str, Any]]:
    """Quoted passages, and whether an attribution sits near them.

    Section 19 requires a quotation to keep its attribution through reconstruction. An
    unattributed quotation in the SOURCE is not automatically a defect - it may be attributed
    in a caption the extractor dropped - so this reports it rather than judging it.
    """
    out: List[Dict[str, Any]] = []
    for match in _QUOTE.finditer(text):
        #: THE QUOTED SPAN ITSELF IS EXCLUDED FROM THE WINDOW, and this was wrong first time
        #: round in a way that made the check useless rather than merely imprecise. A window
        #: spanning the quotation matches any attribution verb INSIDE it, and quoted prose is
        #: full of them - "floats free of whoever said it" contains `said`, so an
        #: unattributed quotation reported itself as attributed. Look before and after, never
        #: within.
        before = text[max(0, match.start() - _ATTRIBUTION_WINDOW):match.start()]
        after = text[match.end():match.end() + _ATTRIBUTION_WINDOW]
        out.append({
            "text": match.group(1).strip()[:MAX_PASSAGE_CHARS],
            "attributionNearby": bool(_ATTRIBUTION.search(before)
                                      or _ATTRIBUTION.search(after)),
        })
        if len(out) >= MAX_QUOTATIONS:
            break
    return out


def named_individuals(text: str) -> List[str]:
    """Capitalised name-shaped pairs, over-reported on purpose.

    A privacy obligation that is missed is a disclosure; a privacy obligation that is
    over-reported is a reviewer glancing at a list. The asymmetry decides the precision.
    """
    found: Dict[str, int] = {}
    for first, second in _PROPER_NOUN_PAIR.findall(text):
        if first in _NOT_A_PERSON or second in _NOT_A_PERSON:
            continue
        name = f"{first} {second}"
        found[name] = found.get(name, 0) + 1
    return [name for name, _ in sorted(found.items(), key=lambda pair: (-pair[1], pair[0]))][:30]


def obsolete_markers(text: str) -> List[Dict[str, Any]]:
    """Datedness a reconstruction has to deal with, with the phrase that shows it.

    Section 3's "obsolete wrapper" is not an abstraction: it is a workshop date, a price, a
    "call this number", a reference to a product that no longer exists. Each is reported with
    its own phrase so a reviewer can see what they are being asked about.
    """
    patterns = (
        ("dated_event", r"\b(?:19|20)\d{2}\b(?=[^.]{0,60}\b(?:workshop|seminar|conference|"
                        r"course|edition|programme|program|batch|session)\b)"),
        ("call_to_action", r"\b(?:call|dial|phone|whatsapp|write to|email us|visit us at|"
                           r"register (?:now|today)|book (?:now|your)|limited seats)\b"),
        ("price", r"(?:₹|rs\.?|inr|\$|usd)\s?\d"),
        ("deprecated_platform", r"\b(?:orkut|blackberry|flash player|internet explorer|"
                                r"vine|google\+|periscope)\b"),
        ("first_edition_pointer", r"\b(?:in this (?:book|chapter)|as (?:we|i) said (?:earlier|"
                                  r"above)|see (?:chapter|page) \d+|overleaf|on the next page)\b"),
    )
    out: List[Dict[str, Any]] = []
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 60)
            out.append({"kind": kind,
                        "text": text[start:match.end() + 60].replace("\n", " ").strip()})
            break  # one representative example per kind is enough to raise the question
    return out


def evidence(text: str, q) -> Dict[str, Any]:
    """Everything mechanically derivable, in one dict.

    Note what is NOT here: any judgement of whether the source is worth an article. That is
    section 2's question and it belongs to a person. The counts below help them answer it.
    """
    paragraphs = _paragraphs(text)
    sentences = _sentences(text)
    lengths = [len(sentence.split()) for sentence in sentences] or [0]
    quoted = quotations(text)
    return {
        "chars": len(text),
        "words": len(text.split()),
        "paragraphs": len(paragraphs),
        "sentences": len(sentences),
        "longestParagraphWords": max((len(p.split()) for p in paragraphs), default=0),
        "meanSentenceWords": round(sum(lengths) / len(lengths), 1),
        "firstPersonPassages": first_person_passages(text, q),
        "checkableClaims": checkable_claims(text, q),
        "quotations": quoted,
        "unattributedQuotations": sum(1 for item in quoted
                                      if not item["attributionNearby"]),
        "namedIndividuals": named_individuals(text),
        "obsoleteMarkers": obsolete_markers(text),
    }


def _summary(found: Dict[str, Any]) -> Dict[str, Any]:
    """The counts that go on the DynamoDB row. Bounded, unlike the evidence itself."""
    flags = sorted({flag for claim in found["checkableClaims"]
                    for flag in claim["reviewFlags"]})
    return {
        "words": found["words"],
        "paragraphs": found["paragraphs"],
        "sentences": found["sentences"],
        "meanSentenceWords": found["meanSentenceWords"],
        "firstPersonPassages": len(found["firstPersonPassages"]),
        "checkableClaims": len(found["checkableClaims"]),
        "reviewFlagsTriggered": flags,
        "quotations": len(found["quotations"]),
        "unattributedQuotations": found["unattributedQuotations"],
        "namedIndividuals": len(found["namedIndividuals"]),
        "obsoleteMarkers": [item["kind"] for item in found["obsoleteMarkers"]],
    }


# ── Records ─────────────────────────────────────────────────────────────────────

def get(record_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_typed(record_id, RECORD_TYPE)


def history(source_id: str) -> List[Dict[str, Any]]:
    """Every analysis of a source, newest version first.

    Through the slug index rather than a scan: every analysis of a source carries that
    source's id as its `slug`, which is what makes the version history one query.
    """
    rows = [row for row in storage.list_slug_records(str(source_id))
            if row.get("recordType") == RECORD_TYPE]
    rows.sort(key=lambda row: int(row.get("version") or 0), reverse=True)
    return [storage._json_safe(row) for row in rows]


def current(source_id: str) -> Optional[Dict[str, Any]]:
    """The newest version, as a stored RECORD rather than a view.

    Records, not views, because every internal caller needs `extractSha256` and `bodyKey`,
    which a view deliberately does not carry. A route that wants the view maps through
    `view()`, which is what `_route_get` does.
    """
    rows = history(source_id)
    return rows[0] if rows else None


def next_version(source_id: str) -> int:
    rows = history(source_id)
    return (int(rows[0].get("version") or 0) + 1) if rows else 1


def read_body(record: Dict[str, Any]) -> Dict[str, Any]:
    """The EVIDENCE from S3, unwrapped from the envelope it is stored in.

    The stored object is `{analysisId, sourceId, version, generatedAt, generatedBy, evidence}`
    so the file is self-describing on its own - an artifact that only makes sense next to its
    DynamoDB row is a poor archive. This returns the inner `evidence`, because every caller
    wants the findings and already has the surrounding metadata from the record.

    Returning the envelope instead is a mistake the unit tests did not catch and the first live
    run did: they asserted the S3 object's shape and the route's truthiness separately, and
    nothing joined the two. `test_the_detail_route_returns_the_evidence_unwrapped` now does.

    An unreadable body is reported, not raised: the summary on the row is what a listing
    renders, so losing the detail is a degradation rather than a failure.
    """
    key = str(record.get("bodyKey") or "")
    if not key:
        return {}
    try:
        raw = blog_sources.s3_client().get_object(
            Bucket=blog_sources.BUCKET, Key=key)["Body"].read()
        document = json.loads(raw.decode("utf-8"))
        return document.get("evidence") if isinstance(document, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "blog_analysis_body_read_failed",
            "analysisId": record.get("id", ""), "error": type(exc).__name__}))
        return {}


def analyse(source_id: str, actor: str) -> Dict[str, Any]:
    """Produce the next analysis version for a source.

    Refuses a source with no extract, because an analysis of nothing is the exact artifact
    this module exists to prevent: something that looks like evidence of reading and is not.
    """
    import blog_quality_v2 as q

    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("Unknown sourceId")
    if record.get("status") != blog_sources.EXTRACTED:
        raise ValueError(
            f"a source must be EXTRACTED before it can be analysed; this one is "
            f"{record.get('status')}")
    text = blog_sources.read_extract(record)
    if not text.strip():
        raise ValueError("this source has no extracted text to analyse")

    version = next_version(source_id)
    found = evidence(text, q)
    summary = _summary(found)
    key = body_key(source_id, version)
    blog_sources.s3_client().put_object(
        Bucket=blog_sources.BUCKET, Key=key,
        Body=json.dumps({
            "analysisId": analysis_id(source_id, version),
            "sourceId": source_id,
            "version": version,
            "generatedAt": storage.now_iso(),
            "generatedBy": actor,
            "evidence": found,
        }, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8")

    now = storage.now_iso()
    stored = {
        "id": analysis_id(source_id, version),
        "recordType": RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        #: The source id, so `list_slug_records` gives the version history in one query.
        "slug": source_id,
        "sourceId": source_id,
        "batchId": record.get("batchId") or blog_sources.NO_BATCH,
        "category": str(record.get("category") or ""),
        "version": version,
        "bodyKey": key,
        #: The hash of the text this analysis was computed FROM. A sign-off is only valid
        #: while this matches the source's current `contentSha256`; a re-extraction that
        #: changes the text therefore invalidates the reading rather than inheriting it.
        "extractSha256": str(record.get("contentSha256") or ""),
        "summary": summary,
        "generatedBy": actor,
        #: Deliberately absent until a human fills them through `record_review`. An analysis
        #: is evidence; these four are the editorial reading of it.
        "reviewedBy": "",
        "reviewedAt": "",
        "sourceReviewedFully": "",
        "reviewNotes": "",
    }
    storage.put_record(stored)
    logger.info(json.dumps({
        "event": "blog_source_analysed", "sourceId": source_id, "actor": actor,
        "version": version, **{k: v for k, v in summary.items()
                               if isinstance(v, (int, float))},
    }))
    #: The source row points at the CURRENT analysis so a listing need not query per row.
    #:
    #: NOTE WHAT IS NOT WRITTEN. No status, no gate, and `sourceReviewedFully` is left exactly
    #: as it was. Producing a new analysis must not look like somebody read it - and if the
    #: text moved, `stale()` will now refuse a sign-off that names the older version.
    blog_sources.update_pipeline(
        source_id, analysisId=stored["id"], analysisVersion=version)
    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression="SET analysisId = :a, analysisAt = :t, updatedAt = :u",
        ExpressionAttributeValues={":a": stored["id"], ":t": now, ":u": now},
    )
    return {**_view(stored), "evidence": found}


def _view(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "analysisId": item.get("id", ""),
        "sourceId": item.get("sourceId", ""),
        "batchId": item.get("batchId", ""),
        "version": int(item.get("version") or 0),
        "extractSha256": item.get("extractSha256", ""),
        "summary": item.get("summary", {}) or {},
        "generatedBy": item.get("generatedBy", ""),
        "createdAt": item.get("createdAt", ""),
        "reviewedBy": item.get("reviewedBy", ""),
        "reviewedAt": item.get("reviewedAt", ""),
        "sourceReviewedFully": item.get("sourceReviewedFully", ""),
        "reviewNotes": item.get("reviewNotes", ""),
    }


def view(item: Dict[str, Any]) -> Dict[str, Any]:
    return _view(item)


def detail(record_id: str) -> Dict[str, Any]:
    record = get(record_id)
    if not record:
        raise LookupError("Unknown analysisId")
    #: The body is PROXIED, not linked. See the module docstring: the prefix is public, so
    #: returning a URL here would publish the evidence file to anyone it was shared with.
    return {**_view(record), "evidence": read_body(record)}


# ── The human half ──────────────────────────────────────────────────────────────

def stale(analysis: Dict[str, Any], source: Dict[str, Any]) -> bool:
    """True when the text moved under the analysis.

    Compared on `contentSha256` rather than on a timestamp, because a re-extraction that
    produces identical bytes is not a change and should not invalidate a reading somebody
    actually did.
    """
    recorded = str(analysis.get("extractSha256") or "")
    live = str(source.get("contentSha256") or "")
    return bool(recorded and live and recorded != live)


def record_review(body: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """A human records that they read the source, against a NAMED analysis version.

    THIS IS THE ONLY PLACE `sourceReviewedFully` IS EVER WRITTEN, and the version has to be
    named explicitly rather than defaulted to "the current one". Defaulting would let a
    reviewer sign for a re-analysis produced while they were reading, which is precisely the
    substitution this record exists to make impossible.

    `blog_quality_v2.check_class_and_source` routes an article to SOURCE_REVIEW until this is
    YES, so this call is what releases it - and nothing a model can write reaches here. The
    field is not in `blog_draft.WRITABLE_FIELDS`, so a prompt-injected source asking for
    `sourceReviewedFully: YES` cannot produce one.
    """
    analysis_ref = str(body.get("analysisId") or "").strip()
    if not analysis_ref:
        raise ValueError("analysisId is required, and must name the version you read")
    analysis = get(analysis_ref)
    if not analysis:
        raise LookupError("Unknown analysisId")

    answer = str(body.get("sourceReviewedFully") or "").strip().upper()
    if answer not in {"YES", "NO"}:
        raise ValueError("sourceReviewedFully must be YES or NO")

    source = blog_sources.get_source(str(analysis.get("sourceId") or ""))
    if not source:
        raise LookupError("the analysed source no longer exists")
    if stale(analysis, source):
        raise ValueError(
            "the source text changed after this analysis was produced; re-analyse and "
            "read the new version before signing for it")

    distinction = str(body.get("centralDistinctionCandidate") or "").strip()
    wrapper = str(body.get("wrapperToRemove") or "").strip()
    #: PROVENANCE THE EXTRACTOR COULD NOT FIND, supplied by the person holding the document.
    #:
    #: Section 23 requires ARCHIVE_DERIVED to preserve `originalSourceDate`, and a scanned
    #: archive PDF frequently has no machine-readable date at all - it is on a copyright page the
    #: extractor flattened, or on a cover image. Until this existed there was no writer for it:
    #: not `blog_draft.WRITABLE_FIELDS`, correctly, because a model guessing a publication date
    #: is inventing provenance. So every archive article with an undated PDF was permanently
    #: held back with no route forward.
    #:
    #: It belongs here rather than anywhere else because this is the moment somebody has the
    #: document open. Only ever FILLS A GAP - an extracted date is never overwritten, since the
    #: document itself is better evidence than a reviewer's recollection of it.
    source_date = str(body.get("originalSourceDate") or "").strip()[:60]
    source_title = str(body.get("originalSourceTitle") or "").strip()[:300]
    if answer == "YES" and len(distinction) < 40:
        #: Section 4 wants a distinction of substance, and a reviewer who cannot name one has
        #: not finished reading. Refused rather than warned, because a YES with no
        #: distinction is the shape of a tick-box.
        raise ValueError(
            "a YES must name the central distinction the source makes available "
            "(at least 40 characters)")

    now = storage.now_iso()
    storage.table().update_item(
        Key={"id": analysis_ref},
        UpdateExpression=("SET reviewedBy = :by, reviewedAt = :at, "
                          "sourceReviewedFully = :yes, reviewNotes = :notes, "
                          "centralDistinctionCandidate = :cd, wrapperToRemove = :wr, "
                          "updatedAt = :u"),
        ExpressionAttributeValues={
            ":by": actor, ":at": now, ":yes": answer,
            ":notes": str(body.get("reviewNotes") or "")[:4000],
            ":cd": distinction[:2000], ":wr": wrapper[:2000], ":u": now,
        },
    )

    source_id = str(analysis["sourceId"])
    #: The batch listing reads this rather than querying every analysis, and it is written in
    #: the same request as the draft below so the two cannot disagree.
    blog_sources.update_pipeline(
        source_id, sourceReviewedFully=answer, analysisId=analysis_ref,
        analysisVersion=int(analysis.get("version") or 0))
    draft = dict(source.get("draftRecord") or {})
    draft["sourceReviewedFully"] = answer
    draft["sourceAnalysisId"] = analysis_ref
    draft["sourceAnalysisVersion"] = int(analysis.get("version") or 0)
    if distinction and not str(draft.get("centralDistinction") or "").strip():
        #: Only when the draft has none. A reviewer's candidate is a starting point for the
        #: writing, not a replacement for what the writer settled on.
        draft["centralDistinction"] = distinction
    if wrapper:
        draft["wrapperToRemove"] = wrapper
    if source_date and not str(draft.get("originalSourceDate") or "").strip():
        draft["originalSourceDate"] = source_date
    if source_title and not str(draft.get("originalSourceTitle") or "").strip():
        draft["originalSourceTitle"] = source_title

    import blog_gate
    assessment = blog_gate.assess_draft(source, draft)
    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression=("SET draftRecord = :dr, articleStatus = :as, gateBlocking = :gb, "
                          "gateReview = :gr, sourceReviewedBy = :by, updatedAt = :u"),
        ExpressionAttributeValues={
            ":dr": storage._clean(draft), ":as": assessment["status"],
            ":gb": assessment["blocking"], ":gr": assessment["review"],
            ":by": actor, ":u": now,
        },
    )
    try:
        import blog_article_work
        blog_article_work.sync_parent_review(
            source_id, answer, analysis_ref, int(analysis.get("version") or 0), actor)
    except Exception:  # noqa: BLE001 - parent review remains authoritative
        logger.exception("article-work parent review propagation failed")

    logger.info(json.dumps({
        "event": "blog_source_review_recorded", "sourceId": source_id,
        "analysisId": analysis_ref, "actor": actor, "answer": answer,
        "articleStatus": assessment["status"],
    }))
    return {
        "analysisId": analysis_ref,
        "sourceId": source_id,
        "version": int(analysis.get("version") or 0),
        "sourceReviewedFully": answer,
        "articleStatus": assessment["status"],
        "blocking": assessment["blocking"],
        "review": assessment["review"],
        "humanGatesOutstanding": assessment["humanGatesOutstanding"],
        "readyToPublish": assessment["readyToPublish"],
        "note": ("Recording the source reading releases section 2 only. The section 29 "
                 "gates and the section 30 read are separate, and neither is set here."),
    }


def batch_review_state(batch_id: str) -> Dict[str, Any]:
    """How much of a batch has actually been read, derived from the analysis records.

    Counted from the records rather than from a field on the batch, for the same reason every
    other batch total is: a counter and the rows it counts disagree exactly when it matters.
    """
    import blog_batches
    sources = blog_batches.batch_sources(batch_id)
    analyses = blog_batches.batch_records(batch_id, record_type=RECORD_TYPE)

    #: Read off the SOURCE rows, not the analysis rows. Both are on this index, but the
    #: sources carry the current answer in their `pipeline` map, so the counts come from one
    #: pass and do not depend on reducing a version history per source. The analysis rows are
    #: still counted, because how many times a wave had to be re-analysed is worth seeing.
    analysed = sum(1 for row in sources if (row.get("pipeline") or {}).get("analysisId"))
    reviewed = sum(1 for row in sources
                   if str((row.get("pipeline") or {}).get("sourceReviewedFully") or
                          "").upper() == "YES")
    return {
        "sources": len(sources),
        "analysed": analysed,
        "reviewed": reviewed,
        "awaitingAnalysis": max(0, len(sources) - analysed),
        "awaitingReview": max(0, analysed - reviewed),
        "analysisVersions": len(analyses),
    }


def pending_analysis(batch_id: str = "", limit: int = 0) -> List[str]:
    """Extracted sources with no analysis yet, oldest first."""
    if batch_id:
        import blog_batches
        sources = blog_batches.batch_sources(batch_id)
    else:
        sources = storage.scan_by_record_type(blog_sources.RECORD_TYPE)
    out = [str(row["id"]) for row in sources
           if row.get("status") == blog_sources.EXTRACTED
           and not (row.get("pipeline") or {}).get("analysisId")]
    return out[:limit] if limit else out


def analysis_fields() -> Sequence[str]:
    """The evidence keys, so a test can assert the shape has not quietly shrunk."""
    return ("chars", "words", "paragraphs", "sentences", "longestParagraphWords",
            "meanSentenceWords", "firstPersonPassages", "checkableClaims", "quotations",
            "unattributedQuotations", "namedIndividuals", "obsoleteMarkers")
