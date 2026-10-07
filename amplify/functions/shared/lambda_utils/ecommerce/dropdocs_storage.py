"""Move a Drop Docs document out of the public tree BEFORE anything calls it a document.

The problem this exists to close
--------------------------------
A Drop Docs document can arrive two ways, and only one of them is already private:

* **Browser upload** -- the locker's presigned PUT targets ``secure/u/``, which the
  ``wecare-get-miss-redirect`` Lambda@Edge denies wholesale. Nothing to do.
* **WhatsApp** -- ``inbound-whatsapp-handler`` writes to
  ``media_paths.public('stack/whatsapp-media/incoming/')``, i.e.
  ``o/stack/whatsapp-media/incoming/``, and CloudFront ``E2GP22R4BIFGQ3`` serves the
  whole ``o/`` root **unauthenticated**. ``o/`` is a location, not a permission
  (``media_paths`` says so explicitly); only ``secure/`` is gated.

So an object that arrived over WhatsApp is readable by anyone holding its URL. This
module promotes it into ``secure/`` and returns the gated key. The enforcement itself is
NOT here -- it is at registration, in ``service_request_store.attach_document``, which
refuses to write a ``DOC#`` row for a key that is not ``media_paths.is_gated``. Putting
the gate at the write means a failed promotion leaves no customer-document row at all,
rather than a row pointing at a public object.

The key is the content hash
---------------------------
``secure/u/dropdocs/wecare-digital-<sha256><ext>``, composed only through
``media_paths.secure`` -- never a hand-built string, because a key one level off the data
still returns HTTP 200 on the apex host and so fails silently (see ``media_paths``).

Hashing the content, rather than naming the file, buys three things:

1. **Resolve-before-generate.** Re-sending the same document lands on the row that
   already exists instead of minting a second document against a paid request.
2. **A rename is not a new document.** Re-exporting from a phone with different
   filenames is the common case.
3. **An overwrite writes identical bytes**, which is what makes bucket versioning being
   Suspended tolerable here rather than dangerous.

The public original is NOT deleted, deliberately
------------------------------------------------
Neither ``wecare-secure-files-role`` nor ``wecare-digital-lambda-role`` holds
``s3:DeleteObject``, by design, and this module must never ask for it. The public copy
therefore survives until the existing ``s3_whatsapp_media_incoming`` TTL in
``operations/system-cleanup`` expires it. That is residual exposure, so it is reported
rather than hidden: the result carries ``publicSourceRetained`` and exactly one warning
is logged carrying the retained public key under the alert
``DROPDOCS_PUBLIC_SOURCE_RETAINED``. Do not add a delete to get a tidier story.

One deviation from the brief, and why
-------------------------------------
The brief said an already-gated source should be returned "unchanged", i.e. with no S3
call at all. It cannot be: ``attach_document`` keys its row on
``DOC#<request>#<sha256>``, so without a digest the row key is malformed and the
resolve-before-generate property above is lost. An already-gated source is therefore
still read and hashed -- but nothing is copied, nothing is written, and the storage key
returned is the source key itself, so no object moves between roots.

Logging carries keys and ids only; a key under ``o/`` appears in exactly one place (the
retention alert) and nowhere else. Exceptions are logged by ``type(exc).__name__``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional

from lambda_utils import media_paths

logger = logging.getLogger(__name__)

#: Where a promoted document lands, relative to the gated root. ``u/`` is the existing
#: "upload as received" child; a third top-level ``secure/`` child would fragment a
#: two-prefix contract that the role policy and a migration already encode.
DROPDOCS_SUBPREFIX = "u/dropdocs"

#: A deliberately conservative ceiling, mirroring ``secure-files._safe_extension``.
MAX_EXTENSION_CHARS = 8

#: Used only when S3 reports no type at all. Never guessed from the extension.
FALLBACK_CONTENT_TYPE = "application/octet-stream"

__all__ = [
    "DROPDOCS_SUBPREFIX",
    "DocumentNotPrivate",
    "DocumentPromotionFailed",
    "promote_to_secure",
    "safe_extension",
]


class DocumentPromotionFailed(RuntimeError):
    """S3 refused a read, a copy or the proving HEAD. No row may be written."""


class DocumentNotPrivate(RuntimeError):
    """A key that is not under the gated root reached a point that requires one.

    Raised rather than corrected. A key moved between roots to "make it work" is a
    disclosure in one direction and a dead link in the other.
    """


def safe_extension(key: str) -> str:
    """A short, conservative extension taken from ``key``, or ``""``.

    Mirrors ``secure-files._safe_extension`` exactly -- same whitelist, same ceiling,
    same drop-rather-than-sanitise rule -- because the result lands in an S3 key. Read
    from the basename so a dot in a directory segment cannot contribute.
    """
    basename = str(key or "").rsplit("/", 1)[-1]
    _, _, tail = basename.rpartition(".")
    if tail and tail != basename and 1 <= len(tail) <= MAX_EXTENSION_CHARS and tail.isalnum():
        return "." + tail.lower()
    return ""


def _read(s3: Any, *, bucket: str, key: str) -> Dict[str, Any]:
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        return {"body": response["Body"].read(),
                "contentType": str(response.get("ContentType") or "").strip()}
    except Exception as error:  # noqa: BLE001 - any S3 refusal means "write no row"
        raise DocumentPromotionFailed(
            f"could not read the source object: {type(error).__name__}") from error


def _already_private(source: str, *, digest: str, content_type: str,
                     size_bytes: int) -> Dict[str, Any]:
    logger.info(json.dumps({"event": "dropdocs_source_already_private",
                            "storageKey": source, "sha256": digest}))
    return {"storageKey": source, "sha256": digest, "contentType": content_type,
            "sizeBytes": size_bytes, "promoted": False, "publicSourceRetained": False}


def promote_to_secure(s3: Any, *, bucket: str, source_key: Optional[str]) -> Dict[str, Any]:
    """Return the gated key a Drop Docs document must be registered under.

    ``s3`` is injected, so every path below is exercisable offline against a fake that
    records the exact call set. The call set for a real promotion is exactly
    ``get_object``, ``copy_object``, ``head_object`` -- and never ``delete_object``.

    Raises ``DocumentPromotionFailed`` when S3 refuses anything, and
    ``DocumentNotPrivate`` when the destination this module composed is somehow not under
    the gated root. Both leave the caller with no row to write.
    """
    source = media_paths.canonical(source_key)
    if not source:
        raise DocumentPromotionFailed("no source key was given")
    if source.startswith(("http://", "https://")):
        # `canonical` passes a URL through untouched, so this is not an S3 key at all.
        raise DocumentPromotionFailed("a source must be an object key, not a URL")

    read = _read(s3, bucket=bucket, key=source)
    raw = read["body"]
    digest = hashlib.sha256(raw).hexdigest()
    content_type = read["contentType"] or FALLBACK_CONTENT_TYPE

    if media_paths.is_gated(source):
        return _already_private(source, digest=digest, content_type=content_type,
                                size_bytes=len(raw))

    destination = media_paths.secure(
        DROPDOCS_SUBPREFIX, f"wecare-digital-{digest}{safe_extension(source)}")
    if not media_paths.is_gated(destination):
        # Unreachable while `secure()` roots what it composes, and kept because the whole
        # feature rests on this one property holding.
        raise DocumentNotPrivate("the composed destination is not under the gated root")

    try:
        s3.copy_object(Bucket=bucket, Key=destination,
                       CopySource={"Bucket": bucket, "Key": source},
                       ContentType=content_type, MetadataDirective="REPLACE")
    except Exception as error:  # noqa: BLE001
        raise DocumentPromotionFailed(
            f"could not copy the document into the gated root: {type(error).__name__}"
        ) from error

    try:
        head = s3.head_object(Bucket=bucket, Key=destination)
    except Exception as error:  # noqa: BLE001
        # The copy claimed success and the destination is not there. Prove, never assume:
        # a row written here would point at nothing while the public original still serves.
        raise DocumentPromotionFailed(
            f"the promoted document is not readable at its destination: "
            f"{type(error).__name__}") from error

    size_bytes = int(head.get("ContentLength") or len(raw))
    stored_type = str(head.get("ContentType") or "").strip() or content_type

    logger.info(json.dumps({"event": "dropdocs_document_promoted", "storageKey": destination,
                            "sha256": digest, "sizeBytes": size_bytes}))
    # The ONE place a key under the public root is allowed to appear, because the
    # exposure outlives this call and a silent residual exposure is the worse outcome.
    logger.warning(json.dumps({"event": "dropdocs_public_source_retained",
                               "alert": "DROPDOCS_PUBLIC_SOURCE_RETAINED",
                               "publicSourceKey": source, "storageKey": destination,
                               "reason": "no role holds s3:DeleteObject; the original "
                                         "expires under s3_whatsapp_media_incoming"}))
    return {"storageKey": destination, "sha256": digest, "contentType": stored_type,
            "sizeBytes": size_bytes, "promoted": True, "publicSourceRetained": True}
