"""The one place an article is assessed, and the one place its gate is resolved.

WHY THIS MODULE EXISTS AT ALL.

Five different code paths write an `articleStatus`: extraction, an AI proposal, accepting an
edit, recording the source reading, and a QA run. Before this they each called
`blog_quality_v2.assess` directly. That works right up until a rule needs to come from
somewhere the gate cannot see - a per-project content template, or a human's gate sign-off -
at which point the rule applies on whichever call sites somebody remembered to change, and the
ones they missed keep reporting a status computed from fewer rules. The difference is invisible
in the record.

So: every writer of an `articleStatus` goes through `assess_draft`, and
`test_every_assessment_site_routes_through_blog_gate` greps the modules to keep it that way.

## THE GATE IS DERIVED, NEVER STORED

`blog_quality_v2.decide_status` will not return READY_TO_PUBLISH until `record["gate"]` answers
all eleven section 29 human gates. The obvious implementation writes that object onto the draft
when a human signs off - and then the article can be edited afterwards while the gate stays
behind, certifying text nobody approved. The fix would be a revocation step on every write
path, which is the same class of problem as the one above: a cleanup somebody has to remember.

Instead the gate is computed on every assessment from the current sign-off, and only when the
sign-off's recorded body hash still matches the article. Editing one word of the body changes
the hash, so the gate simply is not there any more. There is nothing to revoke and nothing to
forget.

## Why the corpus is off by default

Section 28 duplication needs the 1,165-post sketch index, which is 1.4 MB of JSON. Extraction
assesses five drafts per worker invocation and none of them has an article body yet, so loading
it there costs real time to compare nothing. It is loaded for a QA run, where the comparison is
meaningful and the result is recorded - and `blog_qa` refuses a sign-off against a run that did
not load it, so the release path can never skip it.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Cached after the first load. It is a packaged, immutable artifact rather than a secret or a
#: rotated value, so caching it for the life of the execution environment is correct - the
#: lazy-load discipline the fleet follows exists for values that change under a warm sandbox,
#: and this one changes only when a deploy replaces the file.
_corpus = None
_corpus_state: Dict[str, Any] = {}


def body_sha256(record: Dict[str, Any]) -> str:
    """A stable hash of the article body, and of nothing else.

    Computed from `blog_quality_v2.body_of`, which is the same text every rule is applied to, so
    the hash moves exactly when the assessed content moves. Deliberately NOT a hash of the whole
    draft: changing a tag or an SEO title must not silently invalidate a reviewer's reading of
    the prose, and those fields have their own findings.

    Whitespace is collapsed first. A reflow that changes no words is not an edit, and treating
    it as one would revoke sign-offs for nothing.
    """
    import blog_quality_v2 as q
    text = " ".join(q.body_of(record).split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def corpus_index():
    """The published-corpus sketch index, loaded once.

    Returns a `CorpusIndex` that may be EMPTY, and `corpus_state()` is how a caller finds out.
    Empty is not an error here - the CLI and the unit tests legitimately run without the file -
    but it is a fact that has to travel with any NON_DUPLICATION verdict, because a PASS
    produced by comparing against nothing is worse than no check at all.
    """
    global _corpus, _corpus_state
    if _corpus is not None:
        return _corpus
    import blog_quality_v2 as q
    index = q.CorpusIndex()
    loaded = 0
    try:
        loaded = index.load_published_index()
    except Exception as exc:  # noqa: BLE001 - a corrupt index must not break the route
        logger.warning(json.dumps({
            "event": "blog_corpus_index_load_failed", "error": type(exc).__name__}))
    health = {}
    try:
        health = q.published_index_health()
    except Exception:  # noqa: BLE001
        health = {}
    _corpus_state = {
        "loaded": loaded,
        "present": bool(loaded),
        "path": str(q.PUBLISHED_INDEX),
        "packaged": Path(q.PUBLISHED_INDEX).exists(),
        "builtAt": str(health.get("builtAt") or ""),
        "note": str(health.get("note") or ""),
    }
    logger.info(json.dumps({"event": "blog_corpus_index_loaded", **_corpus_state}))
    _corpus = index
    return _corpus


def corpus_state() -> Dict[str, Any]:
    """What the corpus comparison actually covered. Load it first if nobody has."""
    corpus_index()
    return dict(_corpus_state)


def reset_corpus_cache() -> None:
    """For tests, which need to load a different index in the same process."""
    global _corpus, _corpus_state
    _corpus, _corpus_state = None, {}


def resolved_signature(source_record: Dict[str, Any],
                       draft: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the current sign-off asserts, IF it still covers this body.

    Returns `{}` when there is no sign-off or when the body has moved since - which is what
    makes an edit after sign-off revoke it without any revocation code existing.

    Two groups come back, and they are shaped the way `blog_quality_v2` reads them: the eleven
    section 29 judgements nest under `gate`, while the sections 5, 28 and 20 declarations sit at
    the top level of the record because that is where `check_distinction_and_purpose` and
    `check_factual_reviews` look for them.
    """
    import blog_qa
    signoff = blog_qa.current_signoff(str(source_record.get("id") or ""))
    if not signoff:
        return {}
    if str(signoff.get("bodySha256") or "") != body_sha256(draft):
        return {}
    fields: Dict[str, Any] = dict(signoff.get("declarations") or {})
    gates = dict(signoff.get("gates") or {})
    if gates:
        fields["gate"] = gates
    return fields


def resolved_gate(source_record: Dict[str, Any], draft: Dict[str, Any]) -> Dict[str, Any]:
    """Just the eleven section 29 answers, for a caller that only wants those."""
    return dict(resolved_signature(source_record, draft).get("gate") or {})


def assess_draft(source_record: Dict[str, Any], draft: Dict[str, Any],
                 with_corpus: bool = False) -> Dict[str, Any]:
    """`blog_quality_v2.assess` with this article's template and gate folded in.

    The draft is copied before the gate is injected. Mutating the caller's dict would persist a
    gate onto `draftRecord` on the next write, which is exactly the stored-gate failure the
    module docstring exists to rule out.
    """
    import blog_quality_v2 as q
    import blog_templates

    template = blog_templates.for_source(source_record) or {}
    candidate = dict(draft)
    signature = resolved_signature(source_record, draft)
    candidate.update(signature)

    findings = blog_templates.check_article(candidate, template, q) if template else []
    corpus = corpus_index() if with_corpus else None

    #: A published revision must compare against every OTHER published article, not against
    #: its own live slug. Exclusion is deliberately earned from the persisted publish linkage:
    #: a merely colliding candidate slug does not qualify. blog_publish.revise repeats the
    #: post-id/slug check before the write, so this only removes the false self-collision.
    pipeline = source_record.get("pipeline") or {}
    candidate_slug = str(candidate.get("slug") or "").strip()
    post_url = str(pipeline.get("postUrl") or "").split("?", 1)[0].rstrip("/")
    is_linked_revision = (
        bool(str(pipeline.get("postId") or "").strip())
        and str(pipeline.get("publishStatus") or "").strip().upper() == "PUBLISHED"
        and bool(candidate_slug)
        and post_url.endswith(f"/post/{candidate_slug}")
    )
    corpus_exclude_slug = candidate_slug if is_linked_revision else ""
    result = q.assess(candidate, corpus, extra_findings=findings,
                      corpus_exclude_slug=corpus_exclude_slug)
    result["template"] = blog_templates.compliance(candidate, template)
    result["bodySha256"] = body_sha256(draft)
    result["gateResolved"] = bool(signature)
    result["corpus"] = corpus_state() if with_corpus else {"loaded": 0, "present": False,
                                                           "note": "corpus not checked"}
    return result


def persist_assessment(source_id: str, draft: Dict[str, Any],
                       assessment: Dict[str, Any]) -> None:
    """Write the assessed status back onto the source row.

    `draftRecord` is stored WITHOUT a `gate` key, always. The gate is derived on read, and a
    copy on the record would be a second source of truth that outlives the sign-off it came
    from.
    """
    import blog_qa
    import storage
    #: The gate AND the declarations are stripped. Both belong to the signature, which covers
    #: one exact body; a copy on the record would outlive the body it was given for.
    signed = {"gate"} | {name for name, _ in blog_qa.DECLARATIONS} | set(
        __import__("blog_quality_v2").FACT_DOMAIN_TRIGGERS)
    stored = {name: value for name, value in draft.items() if name not in signed}
    storage.table().update_item(
        Key={"id": str(source_id)},
        UpdateExpression=("SET draftRecord = :dr, articleStatus = :as, gateBlocking = :gb, "
                          "gateReview = :gr, updatedAt = :u"),
        ExpressionAttributeValues={
            ":dr": storage._clean(stored),
            ":as": assessment["status"],
            ":gb": assessment["blocking"],
            ":gr": assessment["review"],
            ":u": storage.now_iso(),
        },
    )
