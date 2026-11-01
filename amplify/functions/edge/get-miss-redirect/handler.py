"""Lambda@Edge origin-response: send non-matching /get links to the main domain.

Why this exists as Lambda@Edge and not a CloudFront Function
------------------------------------------------------------
``wecare.digital/get/<key>`` is an Amplify 200-rewrite onto CloudFront
distribution ``E2GP22R4BIFGQ3``, whose origin is the private S3 bucket
``wecare-digital-get`` behind OAC. Because the bucket policy grants only
``s3:GetObject`` and never ``s3:ListBucket``, S3 answers **403 AccessDenied**
for a key that does not exist - it deliberately will not confirm absence.

Two cheaper mechanisms were tried first and both are structurally incapable:

1. **CloudFront custom error responses** can map 403 to a page, but the allowed
   ``ResponseCode`` values are 200/4xx/5xx only. They cannot emit a 3xx, so they
   cannot redirect.
2. **A CloudFront Function on viewer-response** cannot run at all here:
   "CloudFront doesn't invoke edge functions for viewer response events when the
   origin returns HTTP status code 400 or higher."
   https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/edge-function-restrictions-all.html
   Verified empirically - routing the 403 through a custom error response with
   ``ResponseCode 200`` still did not invoke it, because the restriction keys off
   the *origin's* status, not the status CloudFront finally returns.

Lambda@Edge **origin-response** is the one trigger that fires for origin
responses of 400 and above, so it is the only place a true 302 can be produced.

It runs on cache misses only. CloudFront then caches the 302 we return, so the
steady-state cost of a bad link is a cache hit, not an invocation.

Constraints this file must respect
----------------------------------
* No environment variables - Lambda@Edge forbids them. The redirect target is
  therefore a module constant.
* Must be published as a numbered version; ``$LATEST`` cannot be associated.
* Deployed only to ``us-east-1``.
"""

from __future__ import annotations

from urllib.parse import unquote

# Lambda@Edge cannot read environment variables, so this is a constant.
MAIN_SITE = "https://wecare.digital/"

# Anything at or above this is treated as "no such file".
ERROR_THRESHOLD = 400

# Prefixes that must never be served over this public, unauthenticated path.
#
# ``o/`` is the legacy open tier. ``secure/d/public/`` is the application public-delivery
# tier and is intentionally exempted below. All other ``secure/`` keys remain gated:
# it requires a Cognito session (WhatsApp OTP) and a server-verified payment per
# download, and it is delivered only as a short-lived presigned S3 URL issued by
# the gated Lambda. It must therefore never be reachable through CloudFront, and
# this deny is permanent defence in depth rather than a placeholder - even if a
# routing rule is later misconfigured to point at it, the object does not leak.
#
# Matched after normalising away a leading slash, on a segment boundary, so
# ``secure/x`` is denied but a legitimately public ``secure-notes.pdf`` is not.
#
# Matched on the PERCENT-DECODED key, because S3 decodes the request path once before
# looking the key up. Comparing the raw URI let ``/secur%65/...`` or ``/secure%2Fu/...``
# miss the deny while S3 still resolved and served the gated object.
PUBLIC_DELIVERABLE_PREFIX = "secure/d/public/"
DENIED_PREFIXES = ("secure/",)

# Catalog masters, manifest, QA and deploy evidence live under the public-delivery tier, but
# the only public route for approved catalog artwork is /api/catalog-media/<file> (a Lambda
# with its own S3 read), so CloudFront never needs to serve this subtree. Denied before the
# exemption. product-image-gen's draft previews are the one part still delivered here.
CATALOG_DEPLOY_PREFIX = "secure/d/public/catalog-deploy/"
CATALOG_GENERATED_MEDIA_PREFIX = CATALOG_DEPLOY_PREFIX + "catalog-media/generated/"

# Customer data inside the public-delivery tier, denied like the rest of ``secure/``.
# Must equal ``lambda_utils.media_paths.PRIVATE_DELIVERABLE_PREFIXES`` (this package cannot
# import it); ``scripts/verify_media_prefixes.py`` fails if the two drift. Code reaches these
# objects through the S3 API or presigned URLs only.
PRIVATE_DELIVERABLE_PREFIXES = tuple(PUBLIC_DELIVERABLE_PREFIX + p for p in (
    # Private, paid Vault files: the public/ parent does NOT make this safe to serve.
    "valut/",
    "Invoice/customer_invoice/",
    "receipts/",
    "whatsapp/incoming/",
    "whatsapp/outgoing/",
    "whatsapp/voice/",
    "whatsapp/transcriptions/",
    "whatsapp/downloads/",
    "whatsapp/calling-ai/",
    "whatsapp/resumable/",
))

# Response headers that describe the refused object. Dropped on a deny so the 302 reveals
# nothing about it - not even an ETag, which for a small file is a content fingerprint.
# x-amz-cf-* belong to CloudFront and are never exposed to the function, so they are skipped.
_OBJECT_HEADERS = frozenset({
    "etag", "last-modified", "accept-ranges", "content-range", "content-disposition",
    "content-encoding", "content-language", "expires",
})


def _redirect(response: dict) -> dict:
    """Turn the origin's error response into a 302, mutating it in place.

    **Do not build a fresh response dict here.** ``Via`` and ``Transfer-Encoding``
    are read-only in origin-response events, and returning a new object *deletes*
    them - which counts as changing a read-only header. CloudFront then rejects
    the result with ``x-cache: LambdaValidationError`` and serves the viewer a
    502, while the Lambda logs stay completely clean because the function itself
    succeeded. That combination is very hard to read backwards, hence this note.

    So: keep the origin's header dict and add to it.

    The origin's error body (S3's ``AccessDenied`` XML) is left attached, along
    with its matching ``Content-Length`` and ``Content-Type``. Clients follow the
    ``Location`` and discard the body, and leaving the three consistent avoids a
    length mismatch.

    ``Cache-Control: no-store`` targets the browser, not CloudFront: a visitor
    should not hold this redirect if the file is later uploaded under the same key.
    """
    headers = response.setdefault("headers", {})
    headers["location"] = [{"key": "Location", "value": MAIN_SITE}]
    headers["cache-control"] = [
        {"key": "Cache-Control", "value": "no-cache, no-store, must-revalidate"}
    ]
    response["status"] = "302"
    response["statusDescription"] = "Found"
    return response


def _refuse(response: dict) -> dict:
    """Redirect a denied path AND drop the object the origin returned with it.

    Lambda@Edge sends the origin's body to the viewer unless the function replaces it, so a
    status-and-headers-only redirect still carried the gated object to any client that reads
    a 302's body instead of following it. The body is emptied here and the object's
    descriptive headers removed. ``Via`` and ``Transfer-Encoding`` stay untouched (read-only),
    and ``Content-Length`` is rewritten only when the origin sent one, so a chunked origin
    response never gains a conflicting length.
    """
    _redirect(response)
    headers = response["headers"]
    for name in list(headers):
        lower = name.lower()
        if lower in _OBJECT_HEADERS or (
                lower.startswith("x-amz-") and not lower.startswith("x-amz-cf-")):
            del headers[name]
    if "content-length" in headers:
        headers["content-length"] = [{"key": "Content-Length", "value": "0"}]
    headers["content-type"] = [{"key": "Content-Type", "value": "text/plain; charset=utf-8"}]
    response["body"] = ""
    return response


def _is_denied(uri: str) -> bool:
    """Whether this URI addresses a prefix that must not be served publicly.

    Decoded exactly once, like S3: a double-encoded ``%2565`` stays a literal ``%65`` in
    the key, which names no object and falls through to the error redirect.
    """
    normalised = unquote(uri or "").lstrip("/")
    # No real key here has a "." or ".." segment, and refusing them means a prefix
    # exemption below can never be stretched over a dot-segment path.
    if any(segment in (".", "..") for segment in normalised.split("/")):
        return True
    if (normalised.startswith(CATALOG_DEPLOY_PREFIX)
            and not normalised.startswith(CATALOG_GENERATED_MEDIA_PREFIX)):
        return True
    if normalised.startswith(PRIVATE_DELIVERABLE_PREFIXES):
        return True
    if normalised.startswith(PUBLIC_DELIVERABLE_PREFIX):
        return False
    return any(normalised.startswith(prefix) for prefix in DENIED_PREFIXES)


def handler(event: dict, context: object) -> dict:
    """Redirect denied prefixes and errors; pass real files through untouched."""
    record = event["Records"][0]["cf"]
    response = record["response"]

    # Checked before the status, and regardless of it: a gated object that exists
    # returns 200 from S3, so keying only off errors would serve it.
    if _is_denied(record.get("request", {}).get("uri", "")):
        return _refuse(response)

    try:
        status = int(response["status"])
    except (KeyError, TypeError, ValueError):
        # An unreadable status is not something to guess about - serve it as-is
        # rather than redirecting a response that may have been a real file.
        return response

    if status >= ERROR_THRESHOLD:
        return _redirect(response)

    return response
