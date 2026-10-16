"""Collection-level repetition: the failure mode where no two articles are duplicates.

WHY THE PER-ARTICLE DEDUPE GATE IS NOT ENOUGH.

`blog_quality_v2.CorpusIndex` answers "is this article too close to an existing one". Run 500
articles through it and every one can pass while the collection is obviously machine-made,
because the thing that gives it away is not overlap between any two articles. It is that 340 of
them open the same way, 420 use the same four connectives, and every single one has a mean
sentence length of 17 words. Each article is individually defensible. The wave is not.

That is the specific risk of bulk generation, and it is invisible to a gate that only ever looks
at one record at a time. Section 13 of the standard names the symptom - stock construction,
uniform cadence, repeated opener - but checks it within an article, where three stock phrases is
the threshold. Across a collection the threshold that matters is a PROPORTION.

So this module reports two different things:

  pairs     near-duplicate pairs inside the batch, which the per-article gate cannot see
            because it compares against the published corpus, not against siblings still in
            flight
  patterns  openers, closers, title shapes, phrase concentration and cadence spread, measured
            across the whole collection

## It is advisory, deliberately, and that is not weakness

Nothing here blocks a publish. A proportion is not a defect in any individual article - the
fiftieth article to open with "Something was counting on" is not worse than the first, and
picking one to refuse would be arbitrary. What a reviewer needs is the list and the numbers, so
they can decide which ones to send back. `pipeline.repetitionStatus` records IMPLICATED so a
batch listing can show it, and the release path does not read it.

The exception is the pair check: a near-duplicate PAIR is a real defect and it routes through
the existing dedupe machinery rather than being reported here twice. This module records it and
sets the status; `blog_qa.run` catches it as a finding through `CorpusIndex` once the sibling is
published.

## The pair sweep is not O(n squared) in sketch comparisons

2,500 articles is 3.1 million pairs, and each comparison unions two 128-element sketches. That
does not finish inside a Lambda.

Two sketches that share NO hash values have an estimated Jaccard of exactly zero -
`sketch_jaccard` takes the k smallest of the union and counts values present in both, so an
empty intersection gives 0/k. That makes an inverted index on hash values an EXACT prefilter,
not a heuristic: build `hash -> articles`, and only pairs appearing together under some hash can
possibly score above zero. On real prose that reduces the candidate set by orders of magnitude,
and the pairs it discards are provably below any positive threshold.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import blog_sources
import storage

logger = logging.getLogger(__name__)

RECORD_TYPE = "blogRepetitionRun"

#: A pair this close inside one batch is the same article twice. Matches
#: `CorpusIndex.BODY_SIMILARITY` on purpose: a sibling still in flight and a sibling already
#: published should not be judged by different numbers.
PAIR_BODY = 0.35
PAIR_BODY_NEAR_DUPLICATE = 0.60
PAIR_TITLE = 0.80
PAIR_DISTINCTION = 0.55

#: Proportions, because that is what makes a collection read as generated. A shape used by more
#: than a fifth of a wave is a house tic; one used by more than a third is a template.
SHAPE_NOTICEABLE = 0.20
SHAPE_DOMINANT = 0.33

#: How many words of the opening and closing sentence define a "shape". Four is enough to catch
#: "Something was counting on" and short enough that two genuinely different sentences do not
#: collide.
SHAPE_WORDS = 4

#: Cadence uniformity. Human prose across 50 articles spreads its mean sentence length; a
#: generator clusters it. Reported as the standard deviation of per-article means, in words -
#: below this and every article is breathing at the same rate.
CADENCE_SPREAD_MIN = 1.8
#: Below this many articles the statistics say nothing, so they are not reported as findings.
MIN_COLLECTION = 6

#: Bounded so one enormous batch cannot produce a report nobody can read or a response nobody
#: can render. A reviewer works from the worst offenders.
MAX_PAIRS = 200
MAX_SHAPES = 25


def run_id() -> str:
    return f"blogrep_{uuid.uuid4().hex}"


def body_key(batch_id: str, record_id: str) -> str:
    return f"{blog_sources.REPETITION_PREFIX}{batch_id}/{record_id}.json"


# ── Shapes ──────────────────────────────────────────────────────────────────────

def _sentences(text: str, q) -> List[str]:
    stripped = q.strip_markdown(text)
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", stripped) if part.strip()]


def opener_shape(text: str, q) -> str:
    sentences = _sentences(text, q)
    if not sentences:
        return ""
    return " ".join(re.findall(r"[a-z0-9']+", sentences[0].lower())[:SHAPE_WORDS])


def closer_shape(text: str, q) -> str:
    sentences = _sentences(text, q)
    if not sentences:
        return ""
    return " ".join(re.findall(r"[a-z0-9']+", sentences[-1].lower())[:SHAPE_WORDS])


def title_shape(title: str) -> str:
    """A title with its content words removed, leaving the frame.

    "What a broken promise teaches about trust" and "What a missed deadline teaches about
    reliability" are the same article template wearing two subjects. Reducing to the function
    words plus position is what makes them collide, and it is why this is not just a title
    similarity check - those two share almost no content words at all.
    """
    words = re.findall(r"[a-z0-9']+", str(title or "").lower())
    frame = [word if word in _FUNCTION_WORDS else "_" for word in words]
    return " ".join(frame)


_FUNCTION_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this", "these",
    "those", "of", "in", "on", "at", "to", "for", "with", "without", "from", "by", "about",
    "as", "is", "are", "was", "were", "be", "been", "being", "not", "no", "what", "why",
    "how", "when", "where", "who", "which", "whose", "does", "do", "did", "can", "cannot",
    "will", "would", "should", "could", "it", "its", "you", "your", "we", "our", "they",
    "their", "he", "she", "his", "her", "there", "here", "more", "most", "less", "least",
    "between", "against", "after", "before", "over", "under", "still", "only", "just",
}


def cadence(text: str, q) -> float:
    sentences = _sentences(text, q)
    if not sentences:
        return 0.0
    lengths = [len(sentence.split()) for sentence in sentences]
    return round(sum(lengths) / len(lengths), 2)


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return round((sum((value - mean) ** 2 for value in values) / (len(values) - 1)) ** 0.5, 2)


def _shape_findings(label: str, shapes: Dict[str, List[str]], total: int,
                    description: str) -> List[Dict[str, Any]]:
    """A shape used by a noticeable proportion of the collection, with the articles."""
    out: List[Dict[str, Any]] = []
    for shape, members in sorted(shapes.items(), key=lambda pair: -len(pair[1])):
        if not shape or len(members) < 2:
            continue
        share = len(members) / total
        if share < SHAPE_NOTICEABLE:
            continue
        out.append({
            "kind": label,
            "shape": shape,
            "count": len(members),
            "share": round(share, 3),
            "severity": "DOMINANT" if share >= SHAPE_DOMINANT else "NOTICEABLE",
            "description": description,
            #: Bounded: a reviewer needs to see which articles, not all 400 of them.
            "sources": sorted(members)[:20],
        })
        if len(out) >= MAX_SHAPES:
            break
    return out


# ── Pairs ───────────────────────────────────────────────────────────────────────

def candidate_pairs(sketches: Sequence[Sequence[int]]) -> List[Tuple[int, int]]:
    """Index pairs that share at least one sketch value.

    EXACT, not a heuristic. `sketch_jaccard` scores a pair with no shared values at exactly
    zero, so a pair absent from this list is provably below every positive threshold. See the
    module docstring for why that matters at 2,500 articles.
    """
    buckets: Dict[int, List[int]] = defaultdict(list)
    for index, values in enumerate(sketches):
        for value in values:
            buckets[value].append(index)
    pairs: set = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        #: A hash shared by a large fraction of the collection contributes nothing but work -
        #: it pairs everything with everything. In practice that only happens for degenerate
        #: input (identical boilerplate), which the pair scores will report anyway.
        if len(members) > 400:
            continue
        for position, left in enumerate(members):
            for right in members[position + 1:]:
                pairs.add((left, right) if left < right else (right, left))
    return sorted(pairs)


def _pair_findings(articles: Sequence[Dict[str, Any]], q) -> List[Dict[str, Any]]:
    sketches = [article["sketch"] for article in articles]
    out: List[Dict[str, Any]] = []
    for left, right in candidate_pairs(sketches):
        body = q.sketch_jaccard(sketches[left], sketches[right])
        if body < PAIR_BODY:
            continue
        out.append({
            "a": articles[left]["sourceId"],
            "b": articles[right]["sourceId"],
            "aTitle": articles[left]["title"],
            "bTitle": articles[right]["title"],
            "bodySimilarity": round(body, 3),
            "severity": "NEAR_DUPLICATE" if body >= PAIR_BODY_NEAR_DUPLICATE else "OVERLAP",
        })
    out.sort(key=lambda item: -item["bodySimilarity"])
    return out[:MAX_PAIRS]


def _text_pair_findings(articles: Sequence[Dict[str, Any]], field: str, threshold: float,
                        kind: str, q) -> List[Dict[str, Any]]:
    """Title and distinction pairs. O(n squared) on purpose and affordable.

    These are word-set comparisons over a title or two sentences, not over a body, so the inner
    operation is cheap enough that 3 million of them is still seconds rather than minutes - and
    there is no sketch to build an inverted index from.
    """
    out: List[Dict[str, Any]] = []
    tokens = [set(re.findall(r"[a-z0-9']+", str(article.get(field) or "").lower()))
              for article in articles]
    for left in range(len(articles)):
        if not tokens[left]:
            continue
        for right in range(left + 1, len(articles)):
            if not tokens[right]:
                continue
            union = tokens[left] | tokens[right]
            if not union:
                continue
            score = len(tokens[left] & tokens[right]) / len(union)
            if score < threshold:
                continue
            out.append({
                "kind": kind,
                "a": articles[left]["sourceId"],
                "b": articles[right]["sourceId"],
                "aTitle": articles[left]["title"],
                "bTitle": articles[right]["title"],
                "similarity": round(score, 3),
            })
    out.sort(key=lambda item: -item["similarity"])
    return out[:MAX_PAIRS]


# ── The sweep ───────────────────────────────────────────────────────────────────

def _articles(rows: Iterable[Dict[str, Any]], q) -> List[Dict[str, Any]]:
    """The batch's sources that actually have an article body, prepared for comparison."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        draft = row.get("draftRecord") or {}
        body = str(draft.get("contentMarkdown") or "")
        if not body.strip():
            continue
        out.append({
            "sourceId": str(row.get("id") or ""),
            "title": str(draft.get("title") or ""),
            "slug": str(draft.get("slug") or ""),
            "distinction": str(draft.get("centralDistinction") or ""),
            "body": body,
            "sketch": q.sketch(body),
            "opener": opener_shape(body, q),
            "closer": closer_shape(body, q),
            "titleShape": title_shape(draft.get("title") or ""),
            "cadence": cadence(body, q),
        })
    return out


def analyse(articles: Sequence[Dict[str, Any]], q) -> Dict[str, Any]:
    """The whole report for a prepared collection. Pure, so it is testable without a table."""
    total = len(articles)
    if total == 0:
        return {"articles": 0, "pairs": [], "titlePairs": [], "distinctionPairs": [],
                "patterns": [], "cadenceSpread": 0.0, "implicated": [],
                "note": "no articles in this batch have a body yet"}

    pairs = _pair_findings(articles, q)
    title_pairs = _text_pair_findings(articles, "title", PAIR_TITLE, "TITLE", q)
    distinction_pairs = _text_pair_findings(
        articles, "distinction", PAIR_DISTINCTION, "DISTINCTION", q)

    patterns: List[Dict[str, Any]] = []
    cadences = [article["cadence"] for article in articles if article["cadence"]]
    spread = _stdev(cadences)
    if total >= MIN_COLLECTION:
        openers: Dict[str, List[str]] = defaultdict(list)
        closers: Dict[str, List[str]] = defaultdict(list)
        title_shapes: Dict[str, List[str]] = defaultdict(list)
        for article in articles:
            if article["opener"]:
                openers[article["opener"]].append(article["sourceId"])
            if article["closer"]:
                closers[article["closer"]].append(article["sourceId"])
            if article["titleShape"]:
                title_shapes[article["titleShape"]].append(article["sourceId"])

        patterns += _shape_findings(
            "OPENER", openers, total,
            "articles in this batch begin with the same four words")
        patterns += _shape_findings(
            "CLOSER", closers, total,
            "articles in this batch end with the same four words")
        patterns += _shape_findings(
            "TITLE_FRAME", title_shapes, total,
            "titles share a frame once their content words are removed")
        patterns += _phrase_findings(articles, q)

        #: `len(cadences) > 1`, NOT `if spread`. A spread of exactly 0.0 is falsy in Python and
        #: it is also the WORST case this check exists to catch - every article in the wave
        #: breathing at an identical rate. The first version skipped precisely that one.
        if len(cadences) > 1 and spread < CADENCE_SPREAD_MIN:
            patterns.append({
                "kind": "UNIFORM_CADENCE",
                "shape": f"mean sentence length {round(sum(cadences) / len(cadences), 1)} words",
                "count": total,
                "share": 1.0,
                "severity": "DOMINANT",
                "description": (f"every article breathes at the same rate: the spread of "
                                f"per-article mean sentence length is {spread} words, below "
                                f"{CADENCE_SPREAD_MIN}"),
                "sources": [],
            })

    implicated = sorted({item["a"] for item in pairs} | {item["b"] for item in pairs}
                        | {item["a"] for item in title_pairs}
                        | {item["b"] for item in title_pairs}
                        | {item["a"] for item in distinction_pairs}
                        | {item["b"] for item in distinction_pairs}
                        | {source for pattern in patterns
                           if pattern["severity"] == "DOMINANT"
                           for source in pattern["sources"]})
    return {
        "articles": total,
        "pairs": pairs,
        "titlePairs": title_pairs,
        "distinctionPairs": distinction_pairs,
        "patterns": patterns,
        "cadenceSpread": spread,
        "implicated": implicated,
        "note": ("below the %d-article minimum for pattern statistics, so only pairs were "
                 "checked" % MIN_COLLECTION) if total < MIN_COLLECTION else "",
    }


def _phrase_findings(articles: Sequence[Dict[str, Any]], q) -> List[Dict[str, Any]]:
    """Stock constructions counted ACROSS the collection rather than within an article.

    Section 13 allows two per article and fails at three, which is the right rule for one
    article and says nothing about a wave. One phrase appearing once in each of 300 articles
    passes the per-article rule 300 times and is the clearest possible signal that one generator
    wrote all of them.
    """
    total = len(articles)
    counts: Counter = Counter()
    members: Dict[str, List[str]] = defaultdict(list)
    for article in articles:
        lowered = q.strip_markdown(article["body"]).lower()
        for phrase in q.AI_RHYTHM_PHRASES:
            if phrase in lowered:
                counts[phrase] += 1
                members[phrase].append(article["sourceId"])
    out: List[Dict[str, Any]] = []
    for phrase, count in counts.most_common(MAX_SHAPES):
        share = count / total
        if count < 2 or share < SHAPE_NOTICEABLE:
            continue
        out.append({
            "kind": "STOCK_PHRASE",
            "shape": phrase,
            "count": count,
            "share": round(share, 3),
            "severity": "DOMINANT" if share >= SHAPE_DOMINANT else "NOTICEABLE",
            "description": ("a stock construction shared across the batch; section 13 allows "
                            "two per article, which says nothing about a wave using one each"),
            "sources": sorted(members[phrase])[:20],
        })
    return out


def run(batch_id: str, actor: str) -> Dict[str, Any]:
    """Sweep a batch, record the report, and mark the sources it implicates."""
    import blog_batches
    import blog_quality_v2 as q

    batch = blog_batches.get(batch_id)
    if not batch:
        raise LookupError("Unknown batchId")

    rows = blog_batches.batch_articles(batch_id)
    detailed = [blog_sources.get_source(str(row["id"])) or {} for row in rows]
    articles = _articles(detailed, q)
    report = analyse(articles, q)

    record_id = run_id()
    now = storage.now_iso()
    document = {
        "repetitionRunId": record_id,
        "batchId": batch_id,
        "batchName": str(batch.get("name") or ""),
        "ranAt": now,
        "ranBy": actor,
        "thresholds": {
            "pairBody": PAIR_BODY, "pairBodyNearDuplicate": PAIR_BODY_NEAR_DUPLICATE,
            "pairTitle": PAIR_TITLE, "pairDistinction": PAIR_DISTINCTION,
            "shapeNoticeable": SHAPE_NOTICEABLE, "shapeDominant": SHAPE_DOMINANT,
            "cadenceSpreadMin": CADENCE_SPREAD_MIN, "minCollection": MIN_COLLECTION,
        },
        **report,
    }
    key = body_key(batch_id, record_id)
    blog_sources.s3_client().put_object(
        Bucket=blog_sources.BUCKET, Key=key,
        Body=json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8")

    stored = {
        "id": record_id,
        "recordType": RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": batch_id,
        "batchId": batch_id,
        "bodyKey": key,
        "articles": report["articles"],
        "pairCount": len(report["pairs"]),
        "nearDuplicateCount": sum(1 for item in report["pairs"]
                                  if item["severity"] == "NEAR_DUPLICATE"),
        "titlePairCount": len(report["titlePairs"]),
        "distinctionPairCount": len(report["distinctionPairs"]),
        "patternCount": len(report["patterns"]),
        "dominantPatternCount": sum(1 for item in report["patterns"]
                                    if item["severity"] == "DOMINANT"),
        "implicatedCount": len(report["implicated"]),
        "cadenceSpread": report["cadenceSpread"],
        "ranBy": actor,
    }
    storage.put_record(stored)

    #: Recorded per source so a batch listing can show it WITHOUT reading the report. Every
    #: article with a body is marked, including the clear ones - "checked and clear" and "never
    #: checked" are different facts and an empty string must keep meaning the second.
    implicated = set(report["implicated"])
    for article in articles:
        blog_sources.update_pipeline(
            article["sourceId"],
            repetitionStatus="IMPLICATED" if article["sourceId"] in implicated else "CLEAR")

    logger.info(json.dumps({
        "event": "blog_repetition_run", "batchId": batch_id, "actor": actor,
        "articles": report["articles"], "pairs": len(report["pairs"]),
        "patterns": len(report["patterns"]), "implicated": len(report["implicated"]),
        "cadenceSpread": report["cadenceSpread"],
    }))
    return {**_view(stored), "report": document}


def get(record_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_typed(record_id, RECORD_TYPE)


def history(batch_id: str) -> List[Dict[str, Any]]:
    rows = [row for row in storage.list_slug_records(str(batch_id))
            if row.get("recordType") == RECORD_TYPE]
    rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    return [storage._json_safe(row) for row in rows]


def latest(batch_id: str) -> Optional[Dict[str, Any]]:
    rows = history(batch_id)
    return rows[0] if rows else None


def read_report(record: Dict[str, Any]) -> Dict[str, Any]:
    key = str(record.get("bodyKey") or "")
    if not key:
        return {}
    try:
        raw = blog_sources.s3_client().get_object(
            Bucket=blog_sources.BUCKET, Key=key)["Body"].read()
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "blog_repetition_report_read_failed",
            "repetitionRunId": record.get("id", ""), "error": type(exc).__name__}))
        return {}


def _view(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "repetitionRunId": item.get("id", ""),
        "batchId": item.get("batchId", ""),
        "articles": int(item.get("articles") or 0),
        "pairCount": int(item.get("pairCount") or 0),
        "nearDuplicateCount": int(item.get("nearDuplicateCount") or 0),
        "titlePairCount": int(item.get("titlePairCount") or 0),
        "distinctionPairCount": int(item.get("distinctionPairCount") or 0),
        "patternCount": int(item.get("patternCount") or 0),
        "dominantPatternCount": int(item.get("dominantPatternCount") or 0),
        "implicatedCount": int(item.get("implicatedCount") or 0),
        "cadenceSpread": float(item.get("cadenceSpread") or 0),
        "ranBy": item.get("ranBy", ""),
        "ranAt": item.get("createdAt", ""),
    }


def view(item: Dict[str, Any]) -> Dict[str, Any]:
    return _view(item)


def detail(record_id: str) -> Dict[str, Any]:
    record = get(record_id)
    if not record:
        raise LookupError("Unknown repetitionRunId")
    return {**_view(record), "report": read_report(record)}


def batch_state(batch_id: str) -> Dict[str, Any]:
    """Repetition as a batch rollup, derived from the source rows.

    Never from the run record's own counts: an article edited after the sweep still carries
    `repetitionStatus` from it, and the honest report is how many sources are currently marked,
    next to when the sweep happened.
    """
    import blog_batches
    sources = blog_batches.batch_articles(batch_id)
    statuses: Dict[str, int] = {}
    for row in sources:
        status = str((row.get("pipeline") or {}).get("repetitionStatus") or "")
        statuses[status or "UNCHECKED"] = statuses.get(status or "UNCHECKED", 0) + 1
    recent = latest(batch_id)
    return {
        "sources": len(sources),
        "byStatus": dict(sorted(statuses.items())),
        "implicated": statuses.get("IMPLICATED", 0),
        "clear": statuses.get("CLEAR", 0),
        "unchecked": statuses.get("UNCHECKED", 0),
        "latestRun": _view(recent) if recent else {},
        "runs": len(history(batch_id)),
    }
