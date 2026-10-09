"""Publish AI-generated FAQPage schema to the public site — but only once a human approved it.

WHERE THIS SITS, AND WHY IT IS BACKEND RATHER THAN FRONTEND.
The public site is a static export. It builds by fetching every post from this Lambda's
`/blog-public/<slug>` route, so that route is the seam between the CMS and the published page.
Enriching the response here means the frontend changes NOTHING: `src/pages/post/[slug].tsx`
already renders `post.jsonLd.faqSchema` when it has `mainEntity` entries, and has done for some
time. The only reason no FAQ has ever appeared is that `wix.py::_blog_view` hardcodes
`'jsonLd': {}` — Wix is the post source and carries no schema of ours.

So the chain already existed end to end and was cut in exactly one place. This is that place.

    ai.py  -> generates faqSchema        (already existed)
    handler._run_audit -> stores it as an `audit` record, status pending_review
    Admin  -> approve / reject           (already existed)
    THIS   -> serves the APPROVED one on /blog-public/<slug>
    [slug].tsx -> renders it             (already existed)

APPROVAL IS THE WHOLE POINT OF THIS MODULE.
An audit is written with `status: 'pending_review'`. Serving that to the public would publish
unreviewed model output as structured data under the company's name — a machine's claims about
what the business says, asserted to Google and to every LLM that reads the page. The status
lifecycle is pending_review -> approved -> applying -> applied, and only `approved` and
`applied` mean a person said yes. `pending_review` and `rejected` are never published, and
`rejected` especially: a human looked at it and said no.

This is the same line the rest of the repository already holds. The Recipe work refuses to
invent prepTime or aggregateRating; a fabricated aggregateRating was removed from this site
once. Publishing an unreviewed FAQ would be the same defect with more words.

WHAT IT IS WORTH, STATED HONESTLY. Google deprecated FAQ rich results on 2026-05-07 — the note
in src/pages/grahak-os/index.tsx already records that date, and it is why FAQPage was removed
from that page. So this buys NO Google rich result. FAQPage is still valid schema.org and is
still read by LLMs and AI answer engines, which is the surface this is for. Nobody should read
a ranking promise into it.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger()

#: A kill switch, so publication can be stopped without deploying code.
#:
#: Default ON, and the reasoning is worth stating because "off by default" is the rule elsewhere
#: in this architecture. That rule exists for two things: AI calls, which cost money, and
#: expensive infrastructure. This module does NEITHER - it makes no model call, adds no resource,
#: and serves only content a human has already approved through the existing review workflow.
#: What it costs is one DynamoDB query on an existing on-demand table, on an index that eleven
#: other call sites already use.
#:
#: Generation is the part that is off by default, and it is off structurally rather than by flag:
#: ai.invoke_seo is reachable from exactly one authenticated admin route and nothing schedules
#: it. Verified with grep across amplify/, scripts/ and .github/workflows/.
#:
#: Set SEO_FAQ_PUBLISH=0 to stop serving FAQ immediately.
PUBLISH_ENABLED = os.environ.get('SEO_FAQ_PUBLISH', '1').strip().lower() not in ('0', 'false', 'no')

#: Statuses whose content a human has accepted. `applied` implies it passed `approved` first.
#:
#: NOT `pending_review`, which is where every audit starts, and NOT `rejected`, where a person
#: has actively said no. `applying` is excluded too - it is a transient lock taken mid-write, so
#: publishing from it would race a transaction that may still fail and roll back to `approved`.
PUBLISHABLE_STATUSES = ('approved', 'applied')

#: NON-EMPTY, and nothing stricter. A question with no answer is not an FAQ entry - Google's
#: guidance is that every Question needs exactly one acceptedAnswer - so an entry missing either
#: half is dropped rather than published malformed, because an invalid block is reported against
#: the page while a missing one is simply absent.
#:
#: This was briefly a two-character floor, which is the kind of arbitrary number that quietly
#: throws away real content: "6" is a complete answer to "how many tastes are there", and a
#: recipe corpus is full of numeric answers. Caught by a unit test using a one-character answer.
#: The only defensible threshold is "there is an answer at all".
_MIN_ANSWER_CHARS = 1


def _questions(raw: Any) -> List[Dict[str, Any]]:
    """The valid Question entries in a candidate FAQPage, in order. Invalid ones are dropped.

    Validated rather than trusted. This is model output that has been through a human review of
    the SUGGESTION, not necessarily of the JSON shape, and a malformed node would be emitted
    verbatim into the page. `[slug].tsx` only guards on `mainEntity.length`, so a list of
    unusable objects would still produce a script tag.
    """
    if not isinstance(raw, dict):
        return []
    entries = raw.get('mainEntity')
    if not isinstance(entries, list):
        return []
    out: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get('name') or '').strip()
        answer = entry.get('acceptedAnswer')
        text = ''
        if isinstance(answer, dict):
            text = str(answer.get('text') or '').strip()
        if not name or len(text) < _MIN_ANSWER_CHARS:
            continue
        out.append({
            '@type': 'Question',
            'name': name,
            'acceptedAnswer': {'@type': 'Answer', 'text': text},
        })
    return out


def normalise(raw: Any) -> Optional[Dict[str, Any]]:
    """A clean FAQPage node, or None when there is nothing publishable.

    REBUILT RATHER THAN PASSED THROUGH. The model's object may carry extra keys, a missing
    @context, or a nested shape that happens to render. Emitting only the properties named here
    means the published node cannot contain anything nobody decided to publish - the same reason
    recipe_schema builds its node instead of forwarding what it found.
    """
    questions = _questions(raw)
    if not questions:
        return None
    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': questions,
    }


def _candidate(record: Dict[str, Any]) -> Any:
    """Where an audit keeps its FAQ.

    Two places are checked because the generator's output is stored twice: `suggestedJsonLd` is
    `result.jsonLd` and `fullAiResponse` is the whole `result`, and the retained legacy audit contract stores
    `faqSchema` at the TOP level of the result rather than inside `jsonLd`. Reading only one
    of them would work or silently not, depending on how the model nested its reply.
    """
    suggested = record.get('suggestedJsonLd')
    if isinstance(suggested, dict) and suggested.get('faqSchema'):
        return suggested['faqSchema']
    full = record.get('fullAiResponse')
    if isinstance(full, dict):
        if full.get('faqSchema'):
            return full['faqSchema']
        nested = full.get('jsonLd')
        if isinstance(nested, dict) and nested.get('faqSchema'):
            return nested['faqSchema']
    return None


def approved_faq(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The newest human-approved FAQPage among a slug's records, or None.

    Newest wins: a later approved audit supersedes an earlier one, so re-running the generator
    and approving the result replaces what is published rather than adding to it. `createdAt` is
    an ISO-8601 string written by storage.now_iso(), so a string sort is a chronological sort.
    """
    audits = [
        record for record in records
        if isinstance(record, dict)
        and record.get('recordType') == 'audit'
        and record.get('status') in PUBLISHABLE_STATUSES
    ]
    audits.sort(key=lambda record: str(record.get('createdAt') or ''), reverse=True)
    for record in audits:
        node = normalise(_candidate(record))
        if node:
            return node
    return None


def attach(post: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Put an approved FAQPage into `post['jsonLd']['faqSchema']`. Mutates and returns `post`.

    NEVER RAISES, and never removes anything. The FAQ is an enhancement to a page that has to be
    served either way: a lookup failure or a malformed record must not turn a working post into
    a 503. The caller additionally guards the storage query, because that is the part that talks
    to DynamoDB.
    """
    try:
        if not PUBLISH_ENABLED:
            return post
        node = approved_faq(records)
        if not node:
            return post
        json_ld = post.get('jsonLd')
        if not isinstance(json_ld, dict):
            json_ld = {}
        json_ld['faqSchema'] = node
        post['jsonLd'] = json_ld
    except Exception:  # noqa: BLE001 - an enhancement must not break the page
        logger.exception('faq attach failed for slug %s', post.get('slug'))
    return post
