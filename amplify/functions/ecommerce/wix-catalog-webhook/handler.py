"""`wecare-wix-catalog-webhook` - turn a verified Wix product event into a catalogue rebuild.

Design reference: `.agents/tasks/wix-catalog-auto-sync-b2.md` step 3 ("Auto-trigger the rebuild")
and `docs/wix-catalogue-auto-sync.md`, which carries the owner registration steps.

WHAT IT DOES, AND THE LIST IS SHORT ON PURPOSE
----------------------------------------------
1. Verify the RS256 JWT in the request body against the Wix app's PUBLIC key.
2. On failure: **401, empty body**. Nothing else happens - no dispatch, no token read, no log of
   the body.
3. On success: `POST /repos/<owner>/<repo>/dispatches` with
   `{"event_type": "wix-catalogue-changed"}`, which starts
   `.github/workflows/catalogue-sync.yml`. That job re-reads Wix, commits
   `src/content/wix-catalog.json` if the catalogue actually moved, and the push to `stack`
   triggers the Amplify production build.

THE RECEIVER DOES NOT READ THE CATALOGUE AND DOES NOT DECIDE ANYTHING
---------------------------------------------------------------------
It does not call Wix, does not touch DynamoDB, does not import the catalogue, and deliberately
does not inspect WHICH product changed. A verified Wix event means "re-read the catalogue", and
re-reading is the right answer whatever the event said - so a change in Wix's envelope shape can
cost a log field and can never cost a missed sync. The authority on what the catalogue now
contains is `scripts/fetch-wix-catalog.js` running in the workflow, in one place, with the same
guards (0 products -> write nothing) that the scheduled run gets.

WHY A GITHUB DISPATCH RATHER THAN AN AMPLIFY `StartJob`
-------------------------------------------------------
`StartJob` would rebuild the CURRENT commit, which still carries the stale snapshot - so the site
would redeploy unchanged. The snapshot has to be refreshed and committed first, and the thing
that can do that is the GitHub workflow. The cost is recorded: this function needs a GitHub token
(`wecare/github-pat`, field `token`), where an `amplify:StartJob` call would have needed no
credential at all.

THE SCHEDULE IS THE BACKSTOP, NOT THE OTHER WAY AROUND
------------------------------------------------------
`catalogue-sync.yml` runs on a six-hourly cron independently of this function. So auto-sync works
with this receiver unregistered, unreachable, or failing closed on a missing key - all it costs is
latency. That ordering is deliberate: the reliable mechanism needs no provider registration and no
secret, and this one only makes it faster.

A BURST COLLAPSES AT GITHUB, NOT HERE
-------------------------------------
Ten edits in a minute produce ten dispatches. There is no dedup table here on purpose: the
workflow's `concurrency: catalogue-sync` with `cancel-in-progress: false` keeps one run going and
at most one queued, superseding the older queued one - which is exactly the collapse a dedup store
would have to reimplement, with state to keep and rot.

AUTHORIZATION
-------------
The route is `AuthorizationType=NONE`, as all 361 routes on this API are, and it must be: Wix
presents its own JWT, not a Cognito token, and an API Gateway authorizer cannot verify a signature
over the raw body. `scripts/audit_route_auth.py` classifies this handler as authenticated on the
`verify_signature` STRONG_MARKER, which is the real check and not a declaration about it. WAF was
removed by owner decision on 2026-09-28, so handler verification plus stage/route throttling is
the entire filter in front of this route.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping

from lambda_utils.ecommerce import wix_webhook
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

#: Secret NAMES, never values.
GITHUB_SECRET_ID = os.environ.get("GITHUB_TOKEN_SECRET_ID", "wecare/github-pat")
GITHUB_TOKEN_FIELD = "token"

#: The repository the workflow lives in, and the event type it listens for. Both overridable by
#: environment variable so a fork or a rename does not need a code change, and both defaulted so
#: the function works with no configuration at all.
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "wecare-digital/wecare-digital")
DISPATCH_EVENT_TYPE = os.environ.get("CATALOGUE_DISPATCH_EVENT", "wix-catalogue-changed")

DISPATCH_TIMEOUT_SECONDS = 10


def _read_secret(secret_id: str) -> Mapping[str, Any]:
    """Read a JSON secret by id, at request time. No cache, and NEVER raises.

    A module-scope read is frozen into a warm sandbox, so a rotation would not take effect until
    every sandbox recycled - the defect fixed in `payments/razorpay-webhook` on 2026-09-19.
    Nothing here logs the result, not even its shape or its truthiness: CodeQL tracks taint across
    function boundaries and a ternary on a secret is still a finding.

    `{}` ON ANY FAILURE, AND THAT IS NOT DEFENSIVE PADDING - it is the difference between 401 and
    500, found by probing the live endpoint rather than by reading this file. `wecare/wix/
    catalog-webhook` does not exist yet, so a JWT-SHAPED body got past the cheap checks, reached
    the key read, and boto3's `ResourceNotFoundException` escaped the verifier's
    `WixWebhookUnauthorized` handler entirely:

        POST 'not-a-jwt'                           -> 401   (refused before the read)
        POST 'eyJhbGciOiJSUzI1NiJ9.eyJ...fQ.c2ln'  -> 500   <- the defect
        POST ''                                    -> 401

    A verifier that cannot read its key must REFUSE, not crash. Returning `{}` lands in
    `verify_signature`'s "no usable public key is configured" branch, which is a 401. The same
    applies to a transient Secrets Manager failure: refusing is correct and the six-hourly
    `catalogue-sync.yml` cron is what covers the missed event.
    """
    try:
        import boto3
        client = boto3.client("secretsmanager",
                              region_name=os.environ.get("AWS_REGION", "us-east-1"))
        return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    except Exception as error:  # noqa: BLE001 - a read failure is a refusal, never a 500
        # The secret NAME and the exception TYPE. Never the value, and never a message that
        # could carry one.
        logger.warning(json.dumps({
            "event": "secret_read_failed",
            "secretId": secret_id,
            "errorType": type(error).__name__,
        }))
        return {}


def _inbound_shape(request: Mapping[str, Any]) -> Dict[str, Any]:
    """TEMPORARY. Non-secret SHAPE facts about a request that was just REFUSED.

    Why it exists, and why it is temporary: as of 2026-10-05 the access log for
    `POST /wix-catalog-webhook` shows that every invocation this function has ever had came from
    `curl/8.7.1` - Wix has never delivered here. So the only `wix_webhook_rejected` lines on
    record are our own probes, and when a real delivery finally arrives this line is what says
    what arrived without anyone having to guess. Remove it once one real delivery has been
    observed; `wix_webhook_verified` is the permanent log line.

    WHAT IT MAY REPORT, and the boundary is deliberate: the declared content type, the API
    Gateway base64 flag, the body's TYPE, its LENGTH, its first and last 12 characters, and how
    many dots it contains. Twelve characters of a JWT header is `{"alg":` in base64 and twelve of
    the tail cannot reconstruct a 2048-bit signature. The body is never logged whole, the key is
    never read on this path at all, and nothing a secret could taint enters the expression - which
    is the standard `py/clear-text-logging-sensitive-data` applies.

    It is emitted ONLY from the rejection branch, so verification still precedes every other
    statement in `handler` and a refused caller buys one log line rather than any work.
    """
    body = request.get("body")
    headers = request.get("headers") or {}
    content_type = ""
    if isinstance(headers, Mapping):
        for name, value in headers.items():
            if isinstance(name, str) and name.lower() == "content-type":
                content_type = str(value)[:64]
                break
    shape: Dict[str, Any] = {
        "contentType": content_type,
        "isBase64Encoded": bool(request.get("isBase64Encoded")),
        "bodyType": type(body).__name__,
    }
    if isinstance(body, (str, bytes)):
        text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
        shape["bodyLength"] = len(text)
        shape["head12"] = text[:12]
        shape["tail12"] = text[-12:]
        shape["dots"] = text.count(".")
    return shape


#: The three claim names this diagnostic may report, and nothing else may be added to it.
#: `iss` is the issuer string, `aud` is the receiving appId and `kid` is a PUBLIC key id. None is
#: a credential and none is personal or business data. Every other claim is excluded on purpose:
#: `data` carries the product entity, which is business data this function has no reason to log.
_REPORTABLE_CLAIMS = ("iss", "aud")
_REPORTABLE_HEADER = ("kid", "alg")


def _claim_fields(request: Mapping[str, Any]) -> Dict[str, Any]:
    """TEMPORARY. `iss`, `aud`, `kid` and `alg` off an UNVERIFIED body. NEVER raises.

    Why it exists: on 2026-10-05 Wix began delivering genuinely signed tokens here - they pass
    signature verification against the configured public key and are then refused one step later
    with "the token issuer is not Wix", because `iss` is not the literal `wix.com` that
    `wix_webhook.ISSUER` expects. Wix documents neither the issuer string nor the `aud` value for
    these deliveries, so the delivered token is the only authority on both. `wix_webhook_shape`
    reports twelve characters of each end, which is enough to recognise a JWT and not enough to
    read a claim.

    THE ALLOWLIST IS THE BOUNDARY, and it is positive rather than negative: the returned dict is
    built from `_REPORTABLE_CLAIMS` and `_REPORTABLE_HEADER` only, so a future Wix envelope cannot
    widen what is logged by adding a field. The signature segment is never decoded, the token is
    never logged whole, and `data` - the product entity - is never read on this path.

    IT DECIDES NOTHING. The caller logs the result and ignores it; `verify_signature` is the only
    thing that grants a dispatch, and it is called first and unchanged. Remove this once the
    issuer and audience have been observed once; `wix_webhook_verified` is the permanent line.
    """
    fields: Dict[str, Any] = {}
    try:
        jwt = wix_webhook.token_from_body(
            request.get("body"),
            is_base64_encoded=bool(request.get("isBase64Encoded")))
    except Exception:  # noqa: BLE001 - a diagnostic that raises turns a 401 into a 500
        return fields
    if not wix_webhook.is_jwt_shaped(jwt):
        return fields
    header_segment, payload_segment, _ = jwt.split(".")
    for segment, allowed in ((header_segment, _REPORTABLE_HEADER),
                             (payload_segment, _REPORTABLE_CLAIMS)):
        try:
            decoded = json.loads(
                base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if not isinstance(decoded, dict):
            continue
        for name in allowed:
            value = decoded.get(name)
            if isinstance(value, str):
                fields[name] = value[:128]
            elif value is not None:
                # A list-valued `aud` is reported as its TYPE rather than joined, matching the
                # verifier's refusal to treat "one of these apps" as an audience.
                fields[name] = type(value).__name__
    return fields


def _unauthorized() -> Dict[str, Any]:
    """401 with an EMPTY body.

    No detail, because the caller is either Wix - which does not need it - or someone probing,
    who must not have it.
    """
    return {"statusCode": 401, "headers": {}, "body": ""}


def _json_response(status: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload)}


def _dispatch(reader=None, opener=None) -> bool:
    """Ask GitHub to run `catalogue-sync.yml`. True when GitHub accepted it.

    `reader` and `opener` are injected so the tests can drive this without a network or an AWS
    call. The token is read BY REFERENCE and used only as a request header - it is never put on a
    command line, never logged, and never reduced to a logged boolean.

    BOTH DEFAULT TO `None` AND RESOLVE INSIDE, which is not a style choice. Writing
    `reader=_read_secret` binds the function object at DEFINITION time, so patching the module
    attribute has no effect - and the first run of this file's tests proved the consequence
    rather than predicted it: the test that was meant to simulate a missing GitHub token instead
    reached live Secrets Manager, read the real credential and reported success. A default
    argument that captures a credential-reading function is a test that silently talks to
    production.
    """
    reader = reader or _read_secret
    secret = reader(GITHUB_SECRET_ID) or {}
    token = secret.get(GITHUB_TOKEN_FIELD)
    if not isinstance(token, str) or not token:
        # Reported WITHOUT reference to the value. "not configured" is a fact about the secret
        # entry, which is a name, not about the credential.
        logger.error(json.dumps({
            "event": "catalogue_dispatch_unconfigured",
            "secretId": GITHUB_SECRET_ID,
            "field": GITHUB_TOKEN_FIELD,
        }))
        return False

    request = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/dispatches",
        data=json.dumps({"event_type": DISPATCH_EVENT_TYPE}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "wecare-wix-catalog-webhook",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=DISPATCH_TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 0) or 0)
    except urllib.error.HTTPError as error:
        # The STATUS only. A GitHub error body can echo request content, and this request's one
        # header is a credential.
        logger.error(json.dumps({
            "event": "catalogue_dispatch_rejected",
            "status": int(error.code),
            "repository": GITHUB_REPOSITORY,
        }))
        return False
    except Exception as error:  # noqa: BLE001 - a transport failure is not a crash
        logger.error(json.dumps({
            "event": "catalogue_dispatch_failed",
            "errorType": type(error).__name__,
        }))
        return False

    # 204 is the documented success for repository_dispatch; anything else 2xx is accepted and
    # recorded rather than treated as a failure.
    accepted = 200 <= status < 300
    logger.info(json.dumps({
        "event": "catalogue_dispatch_sent" if accepted else "catalogue_dispatch_unexpected",
        "status": status,
        "repository": GITHUB_REPOSITORY,
        "eventType": DISPATCH_EVENT_TYPE,
    }))
    return accepted


def handler(event, context):  # noqa: ARG001 - Lambda signature
    """Verify, then dispatch. Verification is FIRST and nothing precedes it.

    No OPTIONS branch and no CORS headers: this is a server-to-server endpoint that no browser
    calls, so advertising an allowed origin would be describing a caller that does not exist.
    """
    event = event or {}

    try:
        verified = wix_webhook.verify_signature(
            event.get("body"),
            headers=event.get("headers") or {},
            now=int(time.time()),
            reader=_read_secret,
            is_base64_encoded=bool(event.get("isBase64Encoded")),
        )
    except wix_webhook.WixWebhookUnauthorized as error:
        # `str(error)` is safe here and only here: every message this exception carries is
        # assembled in wix_webhook.py from known-safe literal parts - never a claim value, never
        # the key, never a token segment.
        logger.warning(json.dumps({
            "event": "wix_webhook_rejected",
            "reason": str(error),
        }))
        # TEMPORARY, and only on the refusal path. See `_inbound_shape`: Wix has never actually
        # delivered to this endpoint, so a refusal is the moment the shape of what arrived is
        # worth recording. Remove once one real delivery has been observed.
        logger.warning(json.dumps({
            "event": "wix_webhook_shape",
            **_inbound_shape(event),
        }))
        # TEMPORARY, same justification as the shape line and a narrower allowlist. See
        # `_claim_fields`: Wix documents neither the issuer string nor the `aud` value for these
        # deliveries, and a refused delivery is the only place either can be read from.
        logger.warning(json.dumps({
            "event": "wix_webhook_claims",
            **_claim_fields(event),
        }))
        return _unauthorized()

    # `eventType`, `slug` and `entityId` are Wix catalogue identifiers for PUBLIC products. None
    # is a credential and none is personal data, so they are logged in full - this is the
    # correlation a reader needs to tie a Wix edit to a workflow run to an Amplify build.
    #
    # `audience` is the token's `aud` claim, i.e. the appId Wix addressed this delivery to. It is
    # here because `app_id` in `wecare/wix/catalog-webhook` is not configured, so step 7 of
    # `verify_signature` is dormant, and a real delivery is the only authority on which of the
    # candidate appIds to store. Same class of value as `instanceId`: a public installation
    # identifier, not a credential.
    logger.info(json.dumps({
        "event": "wix_webhook_verified",
        "eventType": verified.event_type,
        "slug": verified.slug,
        "entityId": verified.entity_id,
        "instanceId": verified.instance_id,
        "audience": verified.audience,
    }))

    # TEMPORARY, and emitted on the SUCCESS path too so one grep answers the question whichever
    # way the delivery went. It runs AFTER verification, so it is not work done for an
    # unauthenticated caller, and `info` rather than `warning` keeps a working endpoint off the
    # refusal channel. Remove with `_claim_fields`.
    logger.info(json.dumps({
        "event": "wix_webhook_claims",
        **_claim_fields(event),
    }))

    accepted = _dispatch()

    # 200 EITHER WAY, and that is deliberate. A non-2xx answer makes Wix retry, and a retry cannot
    # fix a missing GitHub token or a GitHub outage - it would just repeat. The six-hourly
    # `catalogue-sync.yml` cron is the backstop that actually covers this case, so the honest
    # answer is "received, and here is whether the rebuild was started".
    return _json_response(200, {
        "received": True,
        "rebuildRequested": accepted,
        "eventType": verified.event_type,
    })
