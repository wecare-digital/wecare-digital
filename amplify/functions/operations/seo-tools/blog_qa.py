"""QA runs and gate sign-offs: two records, one of them signed by a person.

THE SPLIT THIS MODULE ENFORCES.

Generation produces an article. QA produces a verdict on it. A sign-off is a person accepting
that verdict and taking responsibility for the eleven judgements no program can make. Before
this they were one motion - generate, assess, and the status came out the other end - which
means the only artifact was a status field, and a status field cannot answer "who decided this,
what did they see, and was it still true when it published".

So there are two records and they are both immutable:

  `blogQaRun`      what every rule said about one exact version of the article, with the body
                   hash it ran against, the template version, the corpus coverage, and the
                   analysis the writing rested on.
  `blogGateSignoff` a person's answers to the eleven section 29 human gates and the section 30
                   read, naming the QA run they relied on and the body hash they saw.

## Four refusals, and why each one is a refusal rather than a warning

1. **No sign-off without a QA run.** Signing for an article nobody ran the rules against is
   the whole failure mode.
2. **No sign-off when the run is stale.** The run records the body hash; if the article has
   moved since, the verdict describes different text.
3. **No sign-off when the run did not check the corpus.** Section 28 duplication needs the
   1,165-post index. A run that could not load it reports NON_DUPLICATION on an unchecked
   corpus, and a signature over that is a signature over nothing.
4. **No sign-off over a blocking finding.** A human may accept a REVIEW - that is what
   judgement is for - but a BLOCK is a mechanical fact, and overriding it by signature would
   make the mechanical half advisory.

## What a sign-off cannot do

It cannot publish. It makes READY_TO_PUBLISH reachable; releasing is a separate operator action
in `blog_publish`, which checks for a sign-off that is still valid at that moment. And it is
not stored on the article: `blog_gate.resolved_gate` derives it on every assessment and drops it
the instant the body hash moves, so an edit after signing revokes the signature with no
revocation code existing to be forgotten.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

import blog_gate
import blog_sources
import storage

logger = logging.getLogger(__name__)

RUN_RECORD_TYPE = "blogQaRun"
SIGNOFF_RECORD_TYPE = "blogGateSignoff"

#: The answers a human may give to a section 29 gate. `N/A` is a real answer - PRIVACY on an
#: article naming nobody is genuinely not applicable - and pretending otherwise trains people
#: to answer PASS to make the form go away.
GATE_ANSWERS = ("PASS", "FAIL", "N/A")

#: A gate answered FAIL blocks the sign-off rather than being recorded and ignored.
BLOCKING_ANSWER = "FAIL"

#: THE DECLARATIONS, AND WHY THEY HAD TO LAND HERE.
#:
#: Sections 5 and 28 require eight explicit yes/no answers, and section 20 requires a review
#: flag per factual domain the article touches. Until this module existed, NOTHING could write
#: any of them: they are correctly absent from `blog_draft.WRITABLE_FIELDS`, because a model
#: declaring its own output non-duplicative is worthless, and there was no human route either.
#:
#: The consequence was not a warning. `decide_status` routes an unanswered section 5 flag to
#: DEDUPE_REWORK, so READY_TO_PUBLISH was structurally UNREACHABLE and the entire publish path
#: was dead code that looked finished. The QA sign-off is where these belong - the same person
#: answering the eleven judgements is the person who has just read the duplication report.
#:
#: Each carries the answer the standard demands. Declaring `titleOnlyDifference: YES` is a
#: statement that this is the same article under a new name, so it is refused rather than
#: recorded: an operator saying that has told us not to publish it.
DECLARATIONS: Tuple[Tuple[str, str], ...] = (
    ("materiallyDifferentInquiry", "YES"),
    ("titleOnlyDifference", "NO"),
    ("uniqueReaderPromise", "YES"),
    ("uniqueIntellectualMovement", "YES"),
    ("exactSlugCollision", "NO"),
    ("exactBodyDuplicate", "NO"),
    ("unresolvedConceptualDuplicate", "NO"),
    ("uniquePurposeRecorded", "YES"),
)
DECLARATION_ANSWERS = ("YES", "NO")

QA_PASS = "PASS"
QA_REVIEW = "REVIEW"
QA_BLOCKED = "BLOCKED"


def run_id() -> str:
    return f"blogqa_{uuid.uuid4().hex}"


def signoff_id() -> str:
    return f"blogsign_{uuid.uuid4().hex}"


def run_body_key(source_id: str, qa_run_id: str) -> str:
    return blog_sources.work_key_for_id(
        source_id, f"qa/{source_id}/{qa_run_id}.json")


# ── QA runs ─────────────────────────────────────────────────────────────────────

def _verdict(assessment: Dict[str, Any]) -> str:
    if assessment["blocking"]:
        return QA_BLOCKED
    if assessment["review"]:
        return QA_REVIEW
    return QA_PASS


def run(source_id: str, actor: str) -> Dict[str, Any]:
    """Assess one exact version of an article and record the verdict immutably.

    WITH the corpus, always. That is the difference between this and the continuous assessment
    on every write: the section 28 comparison is expensive and meaningless before there is a
    body, so it runs here, where the answer is recorded and a signature can rest on it.
    """
    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("Unknown sourceId")
    draft = dict(record.get("draftRecord") or {})
    body = draft.get("contentMarkdown") or ""
    if not str(body).strip():
        raise ValueError(
            "this article has no body yet, so there is nothing to QA; write or propose a "
            "draft first")

    assessment = blog_gate.assess_draft(record, draft, with_corpus=True)
    corpus = assessment["corpus"]
    qa_run = run_id()
    now = storage.now_iso()
    pipeline = record.get("pipeline") or {}

    document = {
        "qaRunId": qa_run,
        "sourceId": source_id,
        "ranAt": now,
        "ranBy": actor,
        "bodySha256": assessment["bodySha256"],
        "status": assessment["status"],
        "verdict": _verdict(assessment),
        "words": assessment["words"],
        "machineGate": assessment["machineGate"],
        "blocking": assessment["blocking"],
        "review": assessment["review"],
        "notes": assessment["notes"],
        "humanGatesOutstanding": assessment["humanGatesOutstanding"],
        #: What a sign-off will be asked to declare, computed from THIS body. Reported with the
        #: run so the review form asks for a health review only when the article discusses
        #: health - section 20's rule is about claims actually made, not about a fixed checklist.
        "declarationsRequired": [name for name, _ in DECLARATIONS],
        "reviewFlagsRequired": triggered_review_flags(draft, __import__("blog_quality_v2")),
        "template": assessment["template"],
        #: What the duplication comparison actually covered, recorded WITH the verdict rather
        #: than inferred later. A NON_DUPLICATION PASS is only worth what this says.
        "corpus": corpus,
        #: The analysis the writing rested on, so the chain source -> reading -> article -> QA
        #: -> signature is complete in the records rather than reconstructed.
        "analysisId": str(pipeline.get("analysisId") or ""),
        "analysisVersion": int(pipeline.get("analysisVersion") or 0),
        "templateId": str(pipeline.get("templateId") or ""),
        "templateVersion": int(pipeline.get("templateVersion") or 0),
    }
    key = run_body_key(source_id, qa_run)
    blog_sources.s3_client().put_object(
        Bucket=blog_sources.BUCKET, Key=key,
        Body=json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8")

    stored = {
        "id": qa_run,
        "recordType": RUN_RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        #: The source id, so `list_slug_records` returns a source's whole QA history.
        "slug": source_id,
        "sourceId": source_id,
        "batchId": record.get("batchId") or blog_sources.NO_BATCH,
        "category": str(record.get("category") or ""),
        "bodyKey": key,
        "bodySha256": assessment["bodySha256"],
        "status": assessment["status"],
        "verdict": document["verdict"],
        "words": assessment["words"],
        "blockingCount": len(assessment["blocking"]),
        "reviewCount": len(assessment["review"]),
        "corpusChecked": int(corpus.get("loaded") or 0),
        "templateId": document["templateId"],
        "templateVersion": document["templateVersion"],
        "analysisId": document["analysisId"],
        "analysisVersion": document["analysisVersion"],
        "ranBy": actor,
    }
    storage.put_record(stored)
    blog_sources.update_pipeline(source_id, qaRunId=qa_run, qaStatus=document["verdict"])
    try:
        import blog_article_work
        blog_article_work.set_intent_status(source_id, "HUMAN_REVIEW", actor)
        parent_id = str(record.get("parentSourceId") or "")
        if parent_id:
            blog_article_work.refresh_parent_status(parent_id, actor)
    except Exception:  # noqa: BLE001 - QA evidence must survive a ledger-sync failure
        logger.exception("article-work QA state sync failed")
    logger.info(json.dumps({
        "event": "blog_qa_run", "sourceId": source_id, "qaRunId": qa_run, "actor": actor,
        "verdict": document["verdict"], "blocking": len(assessment["blocking"]),
        "review": len(assessment["review"]), "corpusChecked": stored["corpusChecked"],
    }))
    return {**_run_view(stored), "report": document}


def get_run(qa_run_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_typed(qa_run_id, RUN_RECORD_TYPE)


def run_history(source_id: str) -> List[Dict[str, Any]]:
    rows = [row for row in storage.list_slug_records(str(source_id))
            if row.get("recordType") == RUN_RECORD_TYPE]
    rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    return [storage._json_safe(row) for row in rows]


def latest_run(source_id: str) -> Optional[Dict[str, Any]]:
    rows = run_history(source_id)
    return rows[0] if rows else None


def read_run_report(record: Dict[str, Any]) -> Dict[str, Any]:
    key = str(record.get("bodyKey") or "")
    if not key:
        return {}
    try:
        raw = blog_sources.s3_client().get_object(
            Bucket=blog_sources.BUCKET, Key=key)["Body"].read()
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "blog_qa_report_read_failed", "qaRunId": record.get("id", ""),
            "error": type(exc).__name__}))
        return {}


def _run_view(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "qaRunId": item.get("id", ""),
        "sourceId": item.get("sourceId", ""),
        "batchId": item.get("batchId", ""),
        "verdict": item.get("verdict", ""),
        "status": item.get("status", ""),
        "words": int(item.get("words") or 0),
        "blockingCount": int(item.get("blockingCount") or 0),
        "reviewCount": int(item.get("reviewCount") or 0),
        "corpusChecked": int(item.get("corpusChecked") or 0),
        "bodySha256": item.get("bodySha256", ""),
        "templateId": item.get("templateId", ""),
        "templateVersion": int(item.get("templateVersion") or 0),
        "analysisId": item.get("analysisId", ""),
        "analysisVersion": int(item.get("analysisVersion") or 0),
        "ranBy": item.get("ranBy", ""),
        "ranAt": item.get("createdAt", ""),
    }


def run_view(item: Dict[str, Any]) -> Dict[str, Any]:
    return _run_view(item)


def run_detail(qa_run_id: str) -> Dict[str, Any]:
    record = get_run(qa_run_id)
    if not record:
        raise LookupError("Unknown qaRunId")
    return {**_run_view(record), "report": read_run_report(record)}


# ── Sign-off ────────────────────────────────────────────────────────────────────

def _clean_gates(raw: Any, q) -> Dict[str, str]:
    """Every section 29 human gate, answered explicitly, and nothing else.

    An unknown key is refused rather than dropped. A caller sending `DISTINCTON: PASS` would
    otherwise get a sign-off that silently lacks DISTINCTION, and `decide_status` would hold the
    article on EDITORIAL_QA with no visible reason.
    """
    if not isinstance(raw, dict) or not raw:
        raise ValueError("gates must be an object answering every human gate")
    answers: Dict[str, str] = {}
    for name, value in raw.items():
        key = str(name).strip().upper()
        if key not in q.HUMAN_GATES:
            raise ValueError(f"{key!r} is not a section 29 human gate; expected any of "
                             f"{list(q.HUMAN_GATES)}")
        answer = str(value).strip().upper().replace("NA", "N/A") if value else ""
        if answer not in GATE_ANSWERS:
            raise ValueError(f"gate {key} must be one of {list(GATE_ANSWERS)}, got "
                             f"{str(value)!r}")
        answers[key] = answer
    missing = [name for name in q.HUMAN_GATES if name not in answers]
    if missing:
        raise ValueError(f"every human gate must be answered; missing {missing}")
    return answers


def triggered_review_flags(draft: Dict[str, Any], q) -> List[str]:
    """The section 20 factual domains this article's body actually touches.

    Asked of the body rather than of a fixed list, because section 20's rule is narrow: a
    domain claim may not sit behind an N/A. An article that mentions no medicine does not need a
    health review, and demanding one anyway trains people to answer YES to clear the form -
    which is the failure the clause exists to prevent.
    """
    lowered = q.strip_markdown(q.body_of(draft)).lower()
    #: `q._trigger_present` rather than a second matcher here. Two copies of "does this article
    #: touch that domain" would drift, and the one that decided what to ASK for must be the one
    #: that decides whether the answer was needed.
    return sorted(flag for flag, triggers in q.FACT_DOMAIN_TRIGGERS.items()
                  if any(q._trigger_present(trigger, lowered) for trigger in triggers))


def _clean_declarations(raw: Any, required_flags: Sequence[str], q) -> Dict[str, str]:
    """The sections 5, 28 and 20 answers, each to the value the standard demands.

    A declaration answered the WRONG way is refused rather than stored. `titleOnlyDifference:
    YES` says this is the same article renamed, and `exactBodyDuplicate: YES` says it is a
    rewrite - an operator who answers either has told us not to publish, so recording it and
    then reporting DEDUPE_REWORK would be a slower way of saying no.
    """
    given = raw if isinstance(raw, dict) else {}
    answers: Dict[str, str] = {}
    known = {name for name, _ in DECLARATIONS} | set(q.FACT_DOMAIN_TRIGGERS)
    unknown = sorted({str(name) for name in given} - known)
    if unknown:
        raise ValueError(f"unknown declarations: {unknown}; expected any of {sorted(known)}")

    for name, expected in DECLARATIONS:
        answer = str(given.get(name) or "").strip().upper()
        if answer not in DECLARATION_ANSWERS:
            raise ValueError(
                f"declaration {name} must be {' or '.join(DECLARATION_ANSWERS)} "
                f"(section 5/28), got {str(given.get(name))!r}")
        if answer != expected:
            raise ValueError(
                f"declaration {name} is {answer} and the standard requires {expected}; this "
                f"article cannot be signed off until that is resolved")
        answers[name] = answer

    for flag in required_flags:
        answer = str(given.get(flag) or "").strip().upper()
        if answer != "YES":
            raise ValueError(
                f"the body makes claims in that domain, so {flag} must be YES (section 20), "
                f"got {str(given.get(flag)) or '<unset>'!r}")
        answers[flag] = "YES"
    return answers


def sign_off(body: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """A person accepts a named QA run and answers the eleven judgements.

    The QA run has to be named, not looked up. Defaulting to "the latest" would let a run
    produced while the reviewer was reading be the thing they signed, which is the same
    substitution `blog_analysis.record_review` refuses for the source reading.
    """
    import blog_quality_v2 as q

    qa_ref = str(body.get("qaRunId") or "").strip()
    if not qa_ref:
        raise ValueError("qaRunId is required, naming the run you read")
    qa = get_run(qa_ref)
    if not qa:
        raise LookupError("Unknown qaRunId")

    source_id = str(qa.get("sourceId") or "")
    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("the article this run belongs to no longer exists")
    draft = dict(record.get("draftRecord") or {})

    live = blog_gate.body_sha256(draft)
    if str(qa.get("bodySha256") or "") != live:
        raise ValueError(
            "the article changed after this QA run, so the verdict describes different text; "
            "run QA again and read the new report before signing")
    if not int(qa.get("corpusChecked") or 0):
        raise ValueError(
            "this QA run could not load the published corpus index, so its NON_DUPLICATION "
            "result compared against nothing; rebuild the index and re-run QA")
    if int(qa.get("blockingCount") or 0):
        raise ValueError(
            f"this QA run reports {qa['blockingCount']} blocking finding(s); a mechanical "
            "BLOCK cannot be accepted by signature, it has to be fixed")

    gates = _clean_gates(body.get("gates"), q)
    declarations = _clean_declarations(
        body.get("declarations"), triggered_review_flags(draft, q), q)
    failed = sorted(name for name, answer in gates.items() if answer == BLOCKING_ANSWER)
    if failed:
        raise ValueError(
            f"these gates are answered FAIL, so the article is not ready: {failed}. Record the "
            "rework and sign once they pass.")

    statement = str(body.get("statement") or "").strip()
    if len(statement) < 40:
        #: Section 30 asks one question - would a careful reader feel this was worth their time
        #: - and a signature with no sentence behind it is a click. Refused for the same reason
        #: a source reading must name the distinction.
        raise ValueError(
            "a sign-off must carry a statement of at least 40 characters recording what you "
            "checked and what you are accepting")

    record_id = signoff_id()
    now = storage.now_iso()
    stored = {
        "id": record_id,
        "recordType": SIGNOFF_RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": source_id,
        "sourceId": source_id,
        "batchId": record.get("batchId") or blog_sources.NO_BATCH,
        "category": str(record.get("category") or ""),
        "qaRunId": qa_ref,
        #: The hash the signature covers. `blog_gate.resolved_gate` compares the live article
        #: against this on every assessment, which is what makes an edit revoke the signature.
        "bodySha256": live,
        "gates": gates,
        #: Sections 5, 28 and 20. Stored beside the gates rather than on the article for the
        #: same reason: they are part of one signature over one exact body.
        "declarations": declarations,
        "statement": statement[:4000],
        "signedBy": actor,
        "signedAt": now,
        "revokedAt": "",
        "revokedBy": "",
        "revokeReason": "",
    }
    storage.put_record(stored)
    blog_sources.update_pipeline(source_id, signoffId=record_id, signedOffBy=actor)
    try:
        import blog_article_work
        blog_article_work.set_intent_status(source_id, "SIGNED_OFF", actor)
        parent_id = str(record.get("parentSourceId") or "")
        if parent_id:
            blog_article_work.refresh_parent_status(parent_id, actor)
    except Exception:  # noqa: BLE001 - sign-off remains authoritative
        logger.exception("article-work sign-off state sync failed")

    assessment = blog_gate.assess_draft(record, draft, with_corpus=True)
    blog_gate.persist_assessment(source_id, draft, assessment)
    logger.info(json.dumps({
        "event": "blog_gate_signed_off", "sourceId": source_id, "signoffId": record_id,
        "qaRunId": qa_ref, "actor": actor, "articleStatus": assessment["status"],
        "readyToPublish": assessment["readyToPublish"],
    }))
    return {
        **_signoff_view(stored),
        "articleStatus": assessment["status"],
        "readyToPublish": assessment["readyToPublish"],
        "blocking": assessment["blocking"],
        "review": assessment["review"],
        "note": ("Signed off. This makes the article releasable; it does not publish it. "
                 "Editing the body invalidates this signature automatically."),
    }


def get_signoff(record_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_typed(record_id, SIGNOFF_RECORD_TYPE)


def signoff_history(source_id: str) -> List[Dict[str, Any]]:
    rows = [row for row in storage.list_slug_records(str(source_id))
            if row.get("recordType") == SIGNOFF_RECORD_TYPE]
    rows.sort(key=lambda row: str(row.get("signedAt") or ""), reverse=True)
    return [storage._json_safe(row) for row in rows]


def current_signoff(source_id: str) -> Optional[Dict[str, Any]]:
    """The newest sign-off that has not been revoked.

    Note what this does NOT check: whether it still matches the article. That comparison lives
    in `blog_gate.resolved_gate`, which is the single place the question "does this signature
    still apply" is answered - so it cannot be answered two ways.
    """
    for row in signoff_history(source_id):
        if not row.get("revokedAt"):
            return row
    return None


def revoke(record_id: str, reason: str, actor: str) -> Dict[str, Any]:
    """Withdraw a signature deliberately, without touching the article.

    Separate from the automatic invalidation on edit, and needed for the other case: the
    article is unchanged but the reviewer has changed their mind. A revoked sign-off is kept,
    because "this was signed and then withdrawn, by whom and why" is exactly the history a
    deletion would destroy.
    """
    record = get_signoff(record_id)
    if not record:
        raise LookupError("Unknown signoffId")
    if record.get("revokedAt"):
        return {**_signoff_view(record), "alreadyRevoked": True}
    if len(str(reason or "").strip()) < 10:
        raise ValueError("a revocation must carry a reason")
    now = storage.now_iso()
    storage.table().update_item(
        Key={"id": record_id},
        UpdateExpression=("SET revokedAt = :at, revokedBy = :by, revokeReason = :why, "
                          "updatedAt = :at"),
        ExpressionAttributeValues={":at": now, ":by": actor,
                                   ":why": str(reason).strip()[:1000]},
    )
    source_id = str(record.get("sourceId") or "")
    source = blog_sources.get_source(source_id)
    if source:
        draft = dict(source.get("draftRecord") or {})
        blog_sources.update_pipeline(source_id, signoffId="", signedOffBy="")
        assessment = blog_gate.assess_draft(source, draft)
        blog_gate.persist_assessment(source_id, draft, assessment)
    logger.info(json.dumps({
        "event": "blog_gate_signoff_revoked", "signoffId": record_id,
        "sourceId": source_id, "actor": actor}))
    return {**_signoff_view({**record, "revokedAt": now, "revokedBy": actor}),
            "alreadyRevoked": False}


def _signoff_view(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "signoffId": item.get("id", ""),
        "sourceId": item.get("sourceId", ""),
        "batchId": item.get("batchId", ""),
        "qaRunId": item.get("qaRunId", ""),
        "bodySha256": item.get("bodySha256", ""),
        "gates": item.get("gates", {}) or {},
        "declarations": item.get("declarations", {}) or {},
        "statement": item.get("statement", ""),
        "signedBy": item.get("signedBy", ""),
        "signedAt": item.get("signedAt", ""),
        "revokedAt": item.get("revokedAt", ""),
        "revokedBy": item.get("revokedBy", ""),
        "revokeReason": item.get("revokeReason", ""),
    }


def signoff_view(item: Dict[str, Any]) -> Dict[str, Any]:
    return _signoff_view(item)


# ── State a reviewer and a release path both need ───────────────────────────────

def releasable(source_id: str) -> Tuple[bool, str]:
    """Whether this article may be released, and the reason when it may not.

    Returned as a reason rather than a bare boolean because every caller has to show the
    operator WHY, and a boolean forces each of them to reconstruct it differently.
    """
    record = blog_sources.get_source(source_id)
    if not record:
        return False, "unknown sourceId"
    draft = dict(record.get("draftRecord") or {})
    if not str(draft.get("contentMarkdown") or "").strip():
        return False, "the article has no body"
    signoff = current_signoff(source_id)
    if not signoff:
        return False, "no gate sign-off has been recorded"
    if str(signoff.get("bodySha256") or "") != blog_gate.body_sha256(draft):
        return False, ("the article was edited after it was signed off, so the signature no "
                       "longer covers it")
    qa = get_run(str(signoff.get("qaRunId") or ""))
    if not qa:
        return False, "the QA run this sign-off names no longer exists"
    assessment = blog_gate.assess_draft(record, draft, with_corpus=True)
    if not assessment["readyToPublish"]:
        return False, (f"the gate holds this article on {assessment['status']}: "
                       + "; ".join((assessment["blocking"] + assessment["review"])[:3]))
    return True, "signed off and passing every mechanical rule"


def source_state(source_id: str) -> Dict[str, Any]:
    """Everything a QA reviewer needs about one article, in one read."""
    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("Unknown sourceId")
    draft = dict(record.get("draftRecord") or {})
    signoff = current_signoff(source_id)
    latest = latest_run(source_id)
    ok, reason = releasable(source_id)
    return {
        "sourceId": source_id,
        "bodySha256": blog_gate.body_sha256(draft),
        "latestRun": _run_view(latest) if latest else {},
        "runStale": bool(latest and str(latest.get("bodySha256") or "")
                         != blog_gate.body_sha256(draft)),
        "signoff": _signoff_view(signoff) if signoff else {},
        "signoffStale": bool(signoff and str(signoff.get("bodySha256") or "")
                             != blog_gate.body_sha256(draft)),
        "releasable": ok,
        "reason": reason,
        "runs": len(run_history(source_id)),
        "signoffs": len(signoff_history(source_id)),
    }


def batch_qa_state(batch_id: str) -> Dict[str, Any]:
    """How far a whole wave has got through QA, derived from the source rows."""
    import blog_batches
    sources = blog_batches.batch_articles(batch_id)
    runs = blog_batches.batch_records(batch_id, record_type=RUN_RECORD_TYPE)
    signoffs = blog_batches.batch_records(batch_id, record_type=SIGNOFF_RECORD_TYPE)
    by_verdict: Dict[str, int] = {}
    for row in sources:
        verdict = str((row.get("pipeline") or {}).get("qaStatus") or "")
        if verdict:
            by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
    signed = sum(1 for row in sources if (row.get("pipeline") or {}).get("signoffId"))
    return {
        "sources": len(sources),
        "qaRun": sum(1 for row in sources if (row.get("pipeline") or {}).get("qaRunId")),
        "byVerdict": dict(sorted(by_verdict.items())),
        "signedOff": signed,
        "awaitingSignoff": max(0, sum(
            1 for row in sources
            if str((row.get("pipeline") or {}).get("qaStatus") or "") in (QA_PASS, QA_REVIEW)
        ) - signed),
        "totalRuns": len(runs),
        "totalSignoffs": len(signoffs),
    }


def human_gates() -> Sequence[str]:
    import blog_quality_v2 as q
    return tuple(q.HUMAN_GATES)
