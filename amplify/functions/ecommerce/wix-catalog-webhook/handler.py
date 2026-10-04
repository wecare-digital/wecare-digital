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
    """Read a JSON secret by id, at request time. No cache, deliberately.

    A module-scope read is frozen into a warm sandbox, so a rotation would not take effect until
    every sandbox recycled - the defect fixed in `payments/razorpay-webhook` on 2026-09-19.
    Nothing here logs the result, not even its shape or its truthiness: CodeQL tracks taint across
    function boundaries and a ternary on a secret is still a finding.
    """
    import boto3
    client = boto3.client("secretsmanager",
                          region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])


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
        return _unauthorized()

    # `eventType`, `slug` and `entityId` are Wix catalogue identifiers for PUBLIC products. None
    # is a credential and none is personal data, so they are logged in full - this is the
    # correlation a reader needs to tie a Wix edit to a workflow run to an Amplify build.
    logger.info(json.dumps({
        "event": "wix_webhook_verified",
        "eventType": verified.event_type,
        "slug": verified.slug,
        "entityId": verified.entity_id,
        "instanceId": verified.instance_id,
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
