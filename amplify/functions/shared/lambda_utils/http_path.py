"""API Gateway stage-prefix normalization. One implementation, no copies.

Why this module exists at all
----------------------------
On this HTTP API the custom domain mapping puts the stage in the path: a request
to the API Gateway stage for `/plivo/answer` arrives with
`rawPath = "/prod/plivo/answer"`. That single difference has now caused two
separate production incidents, because it breaks two things at once:

  * ROUTING - `"/prod/whatsapp" != "/whatsapp"`, so the public webhook branch is
    skipped and execution falls through to the admin auth gate. Measured: 532
    consecutive 401s returned to Meta in 12 hours, with `wecare-inbound-whatsapp`
    receiving zero invocations because nothing forwarded to it. Every inbound
    WhatsApp message and call webhook was rejected.
  * SIGNATURES - Plivo signs the URL it actually requested. Reconstructing
    `.../prod/plivo/hangup` yields a different digest, so every genuine callback
    fails verification, and a fail-closed verifier then drops all of them.

The logic was fixed in `plivo-answer` first, then re-derived in `whatsapp-calling`
when the same bug appeared there, and a third hand-rolled copy sat in
`core/url-shortener`. Three copies of one rule is how it came back a second time,
so it lives here now and the other sites import it.

Why it moved out of `plivo_signature`
-------------------------------------
The shared helper previously lived in `lambda_utils/plivo_signature.py`, which is
a reasonable home for URL reconstruction used by Plivo signature checks but a
misleading one for a rule that the WhatsApp ingress and the short-link service
also depend on. Anyone auditing WhatsApp routing would not think to look in a
Plivo module. `plivo_signature.normalize_path` is kept as a re-export so existing
imports and tests keep working.

The bare-stage case
-------------------
`core/url-shortener` handled one case the shared helper did not: a path that is
exactly `/{stage}` with no trailing segment. For the short-link service that is
the difference between the root and a lookup for a code named after the stage. It
is folded in here, so the shared version is now the most complete one rather than
the least.
"""

from __future__ import annotations

from typing import Any, Dict


def normalize_path(event: Dict[str, Any]) -> str:
    """The path as the CALLER wrote it, with any API Gateway stage prefix removed.

    Stripping is driven by `requestContext.stage`, never a hardcoded "prod", so
    adding a second stage cannot reintroduce the incident. `$default` is left
    alone because that stage does not appear in the path.

    Returns "/" when the result would be empty, so callers can compare against
    "/" without a None check.
    """
    rc = event.get("requestContext") or {}
    path = (
        event.get("rawPath")
        or (rc.get("http") or {}).get("path")
        or event.get("path")
        or ""
    )
    stage = str(rc.get("stage") or "")

    if stage and stage != "$default":
        prefix = f"/{stage}"
        if path.startswith(prefix + "/"):
            path = path[len(prefix):]
        elif path == prefix:
            # Exactly "/prod" - the caller asked for the root. Without this the
            # short-link service treats "prod" as a short code.
            path = "/"

    return path or "/"


def strip_stage(path: str, stage: str) -> str:
    """String-only form, for callers that already have the path and stage."""
    return normalize_path({"rawPath": path, "requestContext": {"stage": stage}})
