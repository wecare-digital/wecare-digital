"""WECARE.DIGITAL site language service.

Public website-facing text translation. The service discovers the language
catalogue from the provider at runtime; it does not keep a hardcoded one.

Routes (API Gateway HTTP API):
  GET  /site-language/languages   open - static catalogue, costs nothing per call
  POST /site-language/translate   requires an allowlisted Origin, see _origin_allowed

TWO ROUTES WERE REMOVED, not deprecated: GET /site-language/voices and
POST /site-language/tts. They drove Amazon Polly and had no consumer - the widget
dropped read-aloud once it was clear Polly has no voice for Tamil, Telugu,
Bengali, Marathi, Gujarati, Kannada, Malayalam or Punjabi, so the button was
hidden for nearly every language this serves. They stayed live and billable
afterwards. See the note above the client constructors.

Translation results are cached in DynamoDB - but only where the same strings
recur. The cache key is the text, so it does nothing against a caller sending
novel text, which is why the Origin check on /translate matters more than it does.

Translation provider
--------------------
Google Cloud Translation v2 is preferred when a key is available, because its
Indic output is materially better than Amazon Translate's. Amazon Translate is
the automatic fallback.

The Google key is read from Secrets Manager AT RUNTIME and never leaves this
process: it is not an env var, not a build input, and never reaches the browser.
That is the whole reason this route exists as a server. A browser widget cannot
hold a key - anything shipped to the page is readable in devtools - so the page
posts here and this function holds the credential.

This replaces the Cloud Run relay the widget used to call
(wecare-translation-relay). That relay checked the Origin header, which stops
another website embedding it but not a plain HTTP client, and it billed a Google
project directly with no request cap. Here the same work sits behind the
per-route API Gateway throttle in scripts/deploy_site_language.py and the
DynamoDB cache below, which is what actually holds the bill down.

Only handler.py is packaged (see package() in scripts/deploy_site_language.py),
so there is no `requests` in the bundle - HTTP goes through urllib from stdlib.
"""

import base64
import concurrent.futures
import hashlib
import html
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
CACHE_TABLE = os.environ.get("SITE_LANGUAGE_CACHE_TABLE", "stack-wecare-digital-SiteLanguageCache")
CACHE_TTL_SECONDS = int(os.environ.get("SITE_LANGUAGE_CACHE_TTL_SECONDS", str(90 * 24 * 3600)))
MAX_TEXTS = int(os.environ.get("SITE_LANGUAGE_MAX_TEXTS", "40"))
MAX_TEXT_BYTES = int(os.environ.get("SITE_LANGUAGE_MAX_TEXT_BYTES", "9000"))
MAX_TOTAL_BYTES = int(os.environ.get("SITE_LANGUAGE_MAX_TOTAL_BYTES", "30000"))

# "auto" uses Google when a key resolves and silently falls back to Amazon
# Translate when it does not, so this ships and serves traffic before the key is
# provisioned. "aws" and "google" pin one provider for debugging.
TRANSLATE_PROVIDER = os.environ.get("SITE_LANGUAGE_TRANSLATE_PROVIDER", "auto").strip().lower()

# wecare/google/cloud already exists in account 775261844268 and holds the
# unified Google API key (see scripts/store_provider_secret.py, which records the
# canonical id for every provider). Do NOT point this at a new secret: a parallel
# id means rotation updates one copy and consumers keep reading the other.
GOOGLE_SECRET_NAME = os.environ.get("SITE_LANGUAGE_GOOGLE_SECRET", "wecare/google/cloud")

# TWO FILES IN THIS REPO DISAGREE ABOUT WHAT THIS FIELD IS CALLED, so both names are tried.
#
#   scripts/store_provider_secret.py  declares wecare/google/cloud as holding `api_key`
#   scripts/check_secrets_live.py     probes wecare/google/cloud for `unified_google_api_key`
#
# One of them is wrong and it cannot be settled from the repository. The consequence depended
# on which, and BOTH possibilities were bad:
#
#   if the field is `api_key`                 check_secrets_live.py has been reading a field
#                                             that does not exist, so its INVALID verdict for
#                                             this secret was a false negative, not a refused key
#   if it is `unified_google_api_key`         this handler has been reading nothing, silently
#                                             serving Amazon Translate since the day it shipped
#
# Neither would ever surface, because TRANSLATE_PROVIDER defaults to "auto" and a missing key is
# indistinguishable from a working fallback. So the field is no longer a single guess: the
# candidates are tried in order and the one that resolved is logged by NAME. A field name is not
# a secret; the value is never logged, and nothing derived from the secret reaches a log call.
#
# The override remains a single name for pinning during debugging.
GOOGLE_SECRET_FIELDS: Tuple[str, ...] = tuple(
    part.strip() for part in os.environ.get(
        "SITE_LANGUAGE_GOOGLE_SECRET_FIELD", "api_key,unified_google_api_key"
    ).split(",") if part.strip()
)
GOOGLE_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"
# v2 accepts up to 128 q values per call. MAX_TEXTS is 40, so one HTTP request
# covers a whole batch - versus one AWS API call per string today.
GOOGLE_MAX_BATCH = max(1, int(os.environ.get("SITE_LANGUAGE_GOOGLE_MAX_BATCH", "64")))
GOOGLE_TIMEOUT_SECONDS = float(os.environ.get("SITE_LANGUAGE_GOOGLE_TIMEOUT", "8"))

translate_client = boto3.client("translate", region_name=REGION)
# POLLY AND THE TWO READ-ALOUD ROUTES ARE GONE.
#
# /site-language/tts and /site-language/voices had NO CONSUMER. SupportWidget dropped
# read-aloud when it became clear Amazon Polly has no voice for Tamil, Telugu, Bengali,
# Marathi, Gujarati, Kannada, Malayalam or Punjabi - its whole Indic range is Hindi and
# Indian English - so the button was hidden for nearly every language this serves. The
# routes stayed live afterwards: unauthenticated, uncached, and billed.
#
# That is a cost surface with no user. MAX_TTS_CHARS was 2,800 per request and the route
# shared the 15 rps throttle, so the ceiling was about $0.67 a second - roughly $2,400 an
# hour - for a feature nothing called. The handler now 404s both paths and the Polly client,
# the voice cache, the voice lookup and the synthesis path are deleted rather than left
# unreachable, so nothing can quietly route back to them.
#
# The IAM grant is separate and is NOT removed here: it lives in the Amplify backend
# definition, not in this file. Worth revoking, and it needs a deploy rather than an edit.
secrets_client = boto3.client("secretsmanager", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
cache_table = dynamodb.Table(CACHE_TABLE)

_language_cache: Dict[str, Any] = {"at": 0, "items": []}
CATALOG_TTL_SECONDS = 6 * 3600

# Resolved once per container and reused across warm invocations, same pattern as
# _get_gmaps_key() in messaging/whatsapp-templates. "loaded" is the negative
# cache: a missing or malformed secret must not re-hit Secrets Manager on every
# request, and must not turn into a 500 either - it just means "use AWS".
_google_key_cache: Dict[str, Any] = {"loaded": False, "key": ""}

ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "SITE_LANGUAGE_ALLOWED_ORIGINS",
        "https://wecare.digital,https://wecare.digital",
    ).split(",")
    if origin.strip()
}


def _origin(event: Dict[str, Any]) -> str:
    headers = event.get("headers") or {}
    candidate = headers.get("origin") or headers.get("Origin") or ""
    return candidate if candidate in ALLOWED_ORIGINS else "https://wecare.digital"


def _origin_allowed(event: Dict[str, Any]) -> bool:
    """
    Is the caller a browser on one of our own pages?

    THIS IS THE CHECK THAT WAS MISSING, AND _origin ABOVE IS NOT IT. _origin only decides
    which value to put in the Access-Control-Allow-Origin RESPONSE header. That header is an
    instruction to a browser, and a browser is the only thing that honours it: it stops
    another website's JavaScript from READING our reply, and it stops nothing else. curl
    sends no Origin, receives the translation, and is billed to us.

    So the endpoint was an open proxy onto a metered Google API. Sized against the limits
    actually configured - 15 rps in scripts/deploy_site_language.py, 30,000 bytes per request
    in MAX_TOTAL_BYTES - that is 450,000 characters a second, which at Google's $20 per
    million is about $9 a second, or $32,000 an hour. The DynamoDB cache below does not help
    against it: the cache key is the text, and an attacker sending random text never repeats a
    key. The throttle caps the RATE but not the bill.

    A REQUEST WITH NO Origin HEADER IS REFUSED, and that is safe for the real client because
    the site and the API are different hosts - wecare.digital calling api.wecare.digital is
    cross-origin, so every browser attaches Origin to the POST. A same-origin request could
    legitimately omit it; there is no same-origin caller here.

    WHAT THIS DOES NOT DO. It is not authentication and it is not a defence against a
    determined attacker, who can set any header they like. It removes the accidental and the
    casual - a script, a scraper, someone else's site hotlinking the endpoint - which is the
    traffic that actually produces a surprise invoice. Real protection is a budget alarm and
    per-IP WAF; both are account configuration, not code, and neither is in this repository.
    """
    headers = event.get("headers") or {}
    candidate = headers.get("origin") or headers.get("Origin") or ""
    return candidate in ALLOWED_ORIGINS


def _response(event: Dict[str, Any], status: int, body: Any) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": _origin(event),
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Vary": "Origin",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError, UnicodeDecodeError):
        return {}


def _path_method(event: Dict[str, Any]) -> tuple[str, str]:
    rc = event.get("requestContext") or {}
    http = rc.get("http") or {}
    method = (http.get("method") or event.get("httpMethod") or "GET").upper()
    path = http.get("path") or event.get("rawPath") or event.get("path") or "/"
    return path.rstrip("/") or "/", method


def _list_languages() -> List[Dict[str, str]]:
    now = time.time()
    if _language_cache["items"] and now - _language_cache["at"] < CATALOG_TTL_SECONDS:
        return _language_cache["items"]

    items: List[Dict[str, str]] = []
    token: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"DisplayLanguageCode": "en", "MaxResults": 500}
        if token:
            kwargs["NextToken"] = token
        result = translate_client.list_languages(**kwargs)
        items.extend(
            {"code": row["LanguageCode"], "name": row["LanguageName"]}
            for row in result.get("Languages", [])
            if row.get("LanguageCode") and row.get("LanguageName")
        )
        token = result.get("NextToken")
        if not token:
            break

    items.sort(key=lambda row: row["name"].casefold())
    _language_cache.update({"at": now, "items": items})
    return items


def _google_key() -> str:
    """The Google API key, or "" when unavailable. Never logged, never returned."""
    if _google_key_cache["loaded"]:
        return _google_key_cache["key"]

    key = ""
    # Held as a plain literal taken from the CONSTANT candidate tuple, never from the secret, so
    # nothing tainted is in scope when it is logged below. See the CodeQL note further down.
    resolved_from = ""
    failure = ""
    try:
        raw = secrets_client.get_secret_value(SecretId=GOOGLE_SECRET_NAME)
        data = json.loads(raw.get("SecretString") or "{}")
        if isinstance(data, dict):
            for candidate in GOOGLE_SECRET_FIELDS:
                value = str(data.get(candidate) or "").strip()
                if value:
                    key = value
                    resolved_from = candidate
                    break
        if not key:
            failure = "no_candidate_field"
    except Exception as exc:
        # Log the failure class only. str(exc) on a Secrets Manager error carries
        # the secret NAME, which is fine, but never the value.
        failure = type(exc).__name__

    # WHY THE MISS IS NOW LOGGED AT ALL. This used to fall through to Amazon Translate in
    # silence, which made two completely different faults look identical to a healthy fallback:
    # a secret this role cannot decrypt, and a secret whose field is named something else. The
    # second one is live in this repo - see the note on GOOGLE_SECRET_FIELDS. An "auto" provider
    # that hides why it chose the fallback is a provider nobody can debug.
    #
    # AccessDeniedException here most likely means kms:Decrypt, not GetSecretValue:
    # amplify/iam-policies.ts grants GetSecretValue on the wildcard wecare/*, and
    # scripts/audit_secrets_structure.py records wecare/google/cloud as CMK-encrypted, while no
    # kms:Decrypt grant appears anywhere in that file. That is the same shape as the false
    # CRITICAL plivo-drift.yml reported on 2026-09-28 when its role lacked kms:Decrypt.
    if failure == "no_candidate_field":
        logger.warning(
            "google key: secret read but none of the candidate fields held a value (%s); "
            "using amazon translate", ",".join(GOOGLE_SECRET_FIELDS))
    elif failure:
        logger.warning(
            "google key unavailable (%s), using amazon translate. AccessDeniedException here is "
            "most likely kms:Decrypt on the CMK, not GetSecretValue - see "
            "docs/CREDENTIAL-ROTATION-RUNBOOK.md", failure)
    elif resolved_from:
        logger.info("google key resolved from field %s", resolved_from)

    _google_key_cache.update({"loaded": True, "key": key})
    # Deliberately no logging here, and this getter has no side effects.
    #
    # It previously logged which provider had been resolved, as
    # "google" if key else "aws" - a string literal, so no key could ever reach
    # the output. CodeQL still failed the build on it
    # (py/clear-text-logging-sensitive-data): the secret appears INSIDE a logging
    # expression, and its taint analysis cannot see that the ternary discards the
    # value. CodeQL is structurally right regardless of this instance - this repo
    # lost four live credentials to exactly this class of mistake, see
    # .kiro/steering/secret-handling.md - so the rule wins over the reasoning.
    #
    # The resolved provider is logged in _translate_texts instead, where the
    # value comes from _google_enabled() returning a bool and nothing in scope
    # holds the key.
    return key


def _google_enabled() -> bool:
    if TRANSLATE_PROVIDER == "aws":
        return False
    return bool(_google_key())


def _google_translate_batch(texts: List[str], target: str, source: str) -> List[Dict[str, str]]:
    """Translate a batch in ONE HTTP call. Raises on any failure so the caller falls back."""
    key = _google_key()
    if not key:
        raise RuntimeError("google key unavailable")

    body: Dict[str, Any] = {"q": texts, "target": target, "format": "text"}
    if source and source != "auto":
        body["source"] = source

    request = urllib.request.Request(
        GOOGLE_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            # Header, not ?key= - Google's own API key best practices call out
            # that a key in the query string is exposed to URL scans and lands in
            # request logs. This way the key never enters a URL.
            "x-goog-api-key": key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=GOOGLE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Surface WHY. The overwhelmingly likely 403s here are SERVICE_DISABLED
        # (Cloud Translation not enabled on the project) and API_KEY_SERVICE_BLOCKED
        # (key restricted to other APIs, e.g. Maps only). Both are one console
        # click to fix and indistinguishable without this. The error body carries
        # a status and a message but never the key.
        detail = ""
        try:
            error = (json.loads(exc.read().decode("utf-8")) or {}).get("error") or {}
            detail = str(error.get("status") or "") or str(error.get("message") or "")
        except Exception:
            detail = ""
        raise RuntimeError(f"google http {exc.code}{': ' + detail if detail else ''}") from None

    rows = ((payload.get("data") or {}).get("translations") or [])
    if len(rows) != len(texts):
        raise RuntimeError(f"google returned {len(rows)} rows for {len(texts)} texts")

    results: List[Dict[str, str]] = []
    for index, row in enumerate(rows):
        translated = str(row.get("translatedText") or "")
        if not translated:
            raise RuntimeError("google returned an empty translation")
        # format="text" still escapes &, < and > in v2 output. The Velo widget
        # decodes entities client-side for the same reason; do it once here so
        # every consumer gets clean text.
        results.append(
            {
                "translatedText": html.unescape(translated),
                "sourceLanguage": str(row.get("detectedSourceLanguage") or source or "auto"),
            }
        )
    return results


def _translation_key(text: str, source: str, target: str, provider: str = "aws") -> str:
    # The "aws" payload is byte-identical to the pre-Google version on purpose:
    # the existing cache stays warm. Google gets its own namespace so enabling it
    # does not serve back Amazon output that a visitor already paid for, and so
    # pinning the provider for debugging gives a clean comparison.
    prefix = "v1" if provider == "aws" else f"v1\0{provider}"
    payload = f"{prefix}\0{source}\0{target}\0{text}".encode("utf-8")
    return "tr#" + hashlib.sha256(payload).hexdigest()


def _cached_translation(text: str, source: str, target: str, provider: str = "aws") -> Optional[Dict[str, str]]:
    try:
        item = cache_table.get_item(Key={"cacheKey": _translation_key(text, source, target, provider)}).get("Item")
        if not item or not item.get("translatedText"):
            return None
        return {
            "translatedText": item["translatedText"],
            "sourceLanguage": item.get("sourceLanguage", source),
        }
    except Exception as exc:
        logger.warning("translation cache read failed: %s", exc)
        return None


def _save_translation(
    text: str, source: str, target: str, translated: str, detected: str, provider: str = "aws"
) -> None:
    try:
        now = int(time.time())
        cache_table.put_item(
            Item={
                "cacheKey": _translation_key(text, source, target, provider),
                "kind": "translation",
                "provider": provider,
                "sourceLanguage": detected,
                "targetLanguage": target,
                "sourceHash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "translatedText": translated,
                "createdAt": now,
                "expiresAt": now + CACHE_TTL_SECONDS,
            }
        )
    except Exception as exc:
        logger.warning("translation cache write failed: %s", exc)


def _aws_translate_one(text: str, target: str, source: str) -> Dict[str, str]:
    result = translate_client.translate_text(
        Text=text,
        SourceLanguageCode=source,
        TargetLanguageCode=target,
    )
    return {
        "translatedText": result.get("TranslatedText", text),
        "sourceLanguage": result.get("SourceLanguageCode", source),
    }


def _aws_translate_batch(texts: List[str], target: str, source: str) -> List[Dict[str, str]]:
    """Amazon Translate has no batch text API, so fan out. Order is preserved by map()."""
    if not texts:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(texts))) as pool:
        return list(pool.map(lambda text: _aws_translate_one(text, target, source), texts))


def _translate_texts(texts: List[str], target: str, source: str) -> Tuple[List[Dict[str, str]], str]:
    """Translate in request order. Returns (rows, provider_actually_used).

    Cache first, then dedupe, then one provider call for whatever is left. Dedupe
    matters more than it looks: the widget walks every text node on the page, so a
    nav label or a repeated CTA arrives many times in one batch and used to be
    billed once per occurrence.
    """
    # DO NOT log which provider was resolved here, or anywhere the value derives
    # from _google_enabled(). CodeQL tracks taint interprocedurally:
    # provider <- _google_enabled() <- _google_key() <- the secret. It failed the
    # build twice on this - once as "google" if key else "aws" inside _google_key(),
    # then again here after the value was reduced to a bool, because the call chain
    # still reaches the secret. Neither version could actually emit a key; the point
    # is that the analysis cannot prove that, and this repo's history with leaked
    # credentials means the scanner gets the benefit of the doubt.
    #
    # Nothing is lost. Which provider ran is already observable two other ways:
    # the "provider" field on the translate response, and the
    # google_translate_failed warning below, which is the signal that actually
    # matters operationally.
    provider = "google" if _google_enabled() else "aws"
    rows: List[Optional[Dict[str, str]]] = [None] * len(texts)
    pending: Dict[str, List[int]] = {}

    for index, text in enumerate(texts):
        if not text or (source != "auto" and source == target):
            rows[index] = {"translatedText": text, "sourceLanguage": source, "cached": True}
            continue
        hit = _cached_translation(text, source, target, provider)
        if hit:
            hit["cached"] = True
            rows[index] = hit
            continue
        pending.setdefault(text, []).append(index)

    if pending:
        unique = list(pending.keys())
        fresh: List[Dict[str, str]] = []
        if provider == "google":
            try:
                for start in range(0, len(unique), GOOGLE_MAX_BATCH):
                    fresh.extend(_google_translate_batch(unique[start:start + GOOGLE_MAX_BATCH], target, source))
            except Exception as exc:
                # Any Google failure - bad key, API not enabled on the project,
                # key restricted to other APIs, quota, timeout - degrades to
                # Amazon rather than failing the visitor's page.
                #
                # Only OUR OWN RuntimeError text is logged verbatim, because
                # _google_translate_batch builds it from the HTTP status and
                # Google's error.status field and nothing else. Every other
                # exception contributes its type only.
                #
                # This is stricter than necessary: the key travels in the
                # x-goog-api-key header, and no urllib exception carries request
                # headers, so str(exc) could not echo it. But "I reasoned it cannot
                # leak" is what the previous version of this file said one line
                # before CodeQL failed the build on it, and a diagnostic is not
                # worth arguing with a secrets rule over. No detail is lost: the
                # useful 403 reason is already inside the RuntimeError.
                detail = str(exc) if isinstance(exc, RuntimeError) else ""
                logger.warning(
                    json.dumps({"event": "google_translate_failed",
                                "errorType": type(exc).__name__,
                                "detail": detail,
                                "fallback": "aws"})
                )
                provider = "aws"
                fresh = []
        if not fresh:
            provider = "aws"
            fresh = _aws_translate_batch(unique, target, source)

        for text, row in zip(unique, fresh):
            _save_translation(text, source, target, row["translatedText"], row["sourceLanguage"], provider)
            for index in pending[text]:
                rows[index] = {**row, "cached": False}

    # Nothing may stay None: every index is either short-circuited, a cache hit,
    # or filled from a provider call above.
    return [row or {"translatedText": texts[i], "sourceLanguage": source, "cached": False}
            for i, row in enumerate(rows)], provider


def _validate_texts(texts: Any) -> List[str]:
    if not isinstance(texts, list) or not texts:
        raise ValueError("texts must be a non-empty array")
    if len(texts) > MAX_TEXTS:
        raise ValueError(f"maximum {MAX_TEXTS} texts per request")

    clean: List[str] = []
    total = 0
    for value in texts:
        if not isinstance(value, str):
            raise ValueError("every text must be a string")
        text = value.strip()
        size = len(text.encode("utf-8"))
        if size > MAX_TEXT_BYTES:
            raise ValueError(f"one text exceeds {MAX_TEXT_BYTES} UTF-8 bytes")
        total += size
        clean.append(text)
    if total > MAX_TOTAL_BYTES:
        raise ValueError(f"request exceeds {MAX_TOTAL_BYTES} UTF-8 bytes")
    return clean


def _is_indian(voice: Dict[str, Any]) -> bool:
    codes = [voice.get("languageCode", "")] + list(voice.get("additionalLanguageCodes") or [])
    return any(str(code).lower().endswith("-in") for code in codes)


def _handle_translate(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _body(event)
    texts = _validate_texts(body.get("texts"))
    target = str(body.get("targetLanguage") or "").strip()
    source = str(body.get("sourceLanguage") or "auto").strip()
    if not target:
        raise ValueError("targetLanguage is required")

    supported = {row["code"] for row in _list_languages()}
    if target not in supported:
        raise ValueError("unsupported targetLanguage")
    if source != "auto" and source not in supported:
        raise ValueError("unsupported sourceLanguage")

    rows, provider = _translate_texts(texts, target, source)

    return _response(
        event,
        200,
        {
            "targetLanguage": target,
            # Reported so a failed Google call is visible in the browser's network
            # tab instead of silently costing quality. The client does not branch
            # on it - one endpoint, one response shape.
            "provider": provider,
            "translations": rows,
        },
    )


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    path, method = _path_method(event)
    if method == "OPTIONS":
        return _response(event, 200, {})
    # INTENTIONALLY PUBLIC - do not add require_auth here.
    #
    # SupportWidget renders from pages/_app.tsx on every page including public
    # ones, so anonymous visitors must be able to list languages and request a
    # translation. Requiring a Cognito token would blank the language control for
    # every signed-out visitor - which is everyone the feature exists for.
    #
    # It also cannot work mechanically: this function is packaged standalone
    # (see scripts/deploy_all_lambdas.py) and does not bundle lambda_utils, so
    # importing the shared middleware fails the pre-upload import validation.
    # That validation is what caught this before it shipped.
    #
    # THE EXPOSURE IS COST, NOT DATA, AND THE OLD NOTE HERE UNDERSTATED IT.
    # It said the mitigation was per-route throttling and that this was "not yet
    # applied". Throttling IS applied - scripts/deploy_site_language.py sets 15
    # rps / burst 30 per route - but a rate cap is not a spend cap. At 15 rps
    # with MAX_TOTAL_BYTES of 30,000 the ceiling is 450,000 characters a second,
    # about $9/sec or $32,000/hour at Google's $20 per million, and the cache
    # cannot help because an attacker's text never repeats a key.
    #
    # So the billed route now requires an allowlisted Origin. See
    # _origin_allowed for why that is safe for the real client and what it does
    # and does not defend against. /languages stays open: it returns a static
    # catalogue, costs nothing per call and is what the widget needs before a
    # visitor has asked for anything.
    try:
        if path.endswith("/site-language/languages") and method == "GET":
            return _response(event, 200, {"languages": _list_languages()})
        if path.endswith("/site-language/translate") and method == "POST":
            if not _origin_allowed(event):
                # 403 rather than 401: this is not a missing credential, it is a
                # caller that is not one of our pages, and there is no token that
                # would change the answer.
                logger.warning("translate refused: origin not allowed")
                return _response(event, 403, {"error": "Not allowed from this origin"})
            return _handle_translate(event)
        return _response(event, 404, {"error": "Not found"})
    except ValueError as exc:
        return _response(event, 400, {"error": str(exc)})
    except Exception as exc:
        logger.exception("site-language failure")
        return _response(event, 500, {"error": "Language service unavailable"})
