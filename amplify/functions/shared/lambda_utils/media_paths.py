"""The S3 key contract for `wecare-digital-get`. One bucket, two roots.

Measured, not assumed
---------------------
Read live on 2026-09-28, account 775261844268, `us-east-1`.

There is exactly **one** media bucket, and it has exactly **two** top-level prefixes::

    s3://wecare-digital-get/o/        249 objects   public
    s3://wecare-digital-get/secure/     2 objects   gated

Nothing else exists at the root, and exactly **one** CloudFront distribution now reads
the bucket::

    ``wecare.digital/get/<X>``   ``E2GP22R4BIFGQ3``  origin path ``""``  ->  key ``<X>``

Why ``o/`` is load-bearing
--------------------------
It was originally the thing that made an object *dual-homed*. A second host,
``app.wecare.digital``, served this same bucket through origin path ``/o`` on
distribution ``ERCXSFDL0VM8X`` (which also carried ``customerservice.wecare.digital`` and
``selfcare.wecare.digital`` - all three names went with it), so
``app.wecare.digital/<X>`` resolved to key
``o/<X>`` and an object was reachable on both hosts only if its key carried ``o/``.

**That host was retired on 2026-09-28** — distribution deleted, DNS record removed, and
the bucket that once shared its name deleted before that. Re-measured the same day:
``get_distribution_config`` returns ``NoSuchDistribution`` and the hostname does not
resolve. So there is no second home any more.

``o/`` remains mandatory regardless, for reasons that never depended on that host:

* Every key this module composes, and every ``storageKey`` already persisted in
  ``stack-wecare-digital-DocumentTable``, is written against it.
* The BIMI ``l=`` record and every apex ``/get/o/...`` URL already issued name it.
* ``o/public/wa-tpl/`` holds **61 objects** whose URLs are embedded in WhatsApp
  templates Meta has already **approved**, and Meta refetches media from the approved
  URL at send time. An approved template body cannot be edited in place.

Dropping the prefix is therefore a data migration, not a rename. Keep composing keys
through `public` and `secure` rather than hand-building them.

One historical trap worth keeping, because it explains why this went unnoticed for two
days: a key written to the bucket **root** still returned **HTTP 200** on the apex host,
so addressing one level above the data errored nowhere, logged nothing and alarmed
nothing. Verified by probe at the time — a key at the root and the same key under
``o/`` both served 200, while a key under ``secure/`` served 302.

The defect this module closes
-----------------------------
Every handler prefix was written against the old bucket, where the key had no ``o/``
segment because the whole bucket was the public root. The merge mapped
``app.wecare.digital/<X>`` to ``wecare-digital-get/o/<X>`` and the prefixes were never
updated, so the fleet read and wrote one level above its own data. Two consequences
were live:

* **Reads of migrated assets returned NoSuchKey.** ``stream/media/m/wecare-digital.png``
  and ``stream/media/fonts/DejaVuSansMono.ttf`` are absent at the root and present
  under ``o/`` — so the invoice logo and the PDF font both resolved to nothing.
* **`system-cleanup` deleted nothing.** Eleven TTL prefixes all targeted ``stack/``
  at the root, which is empty, so expiry silently no-opped.

``secure/`` is the security boundary, ``o/`` is not
--------------------------------------------------
Worth stating plainly, because the naming invites the opposite reading: ``o/`` does
not make an object public. *Everything* outside ``secure/`` is public, including the
bucket root. ``o/`` is a location, not a permission. Only ``secure/`` is gated, by the
``wecare-get-miss-redirect``
Lambda@Edge on origin-response, and its sub-prefixes are ``secure/u/`` (the upload as
received) and ``secure/d/`` (the deliverable rendition).

So a key must never be moved between the two roots to "make it work" — that is a
disclosure in one direction and a broken link in the other.

Legacy keys
-----------
Keys already persisted in DynamoDB predate this fix and lack the ``o/`` segment —
``stack-wecare-digital-DocumentTable`` holds rows whose ``storageKey`` is
``stack/whatsapp-media/incoming/<file>`` while the object is at
``o/stack/whatsapp-media/incoming/<file>``. Rewriting stored rows is a data migration;
normalising on read is not. `canonical` does the latter, so legacy and current rows
both resolve, and it is idempotent so a corrected row stays corrected.
"""

from __future__ import annotations

from typing import Optional

#: Public root. Where real objects live; see the module docstring for why it is still
#: mandatory now that the second host it once served is retired.
PUBLIC_ROOT = "o/"

#: Gated root. Denied at the edge; reachable only via a presigned URL.
SECURE_ROOT = "secure/"

#: The single media bucket. Everything below lives here.
BUCKET = "wecare-digital-get"

#: The apex media host, including its path segment. Deliberately NOT the bucket name:
#: the old bucket was named ``app.wecare.digital`` and so doubled as a hostname, which
#: is why several handlers used to interpolate the bucket into a URL. ``wecare-digital-get``
#: is not a domain, so that pattern now produces a URL resolving to nothing.
CDN_DOMAIN = "wecare.digital/get"


def public(*parts: str) -> str:
    """Join ``parts`` into a key under the public root.

        public("stack/whatsapp-media", "incoming/")  -> "o/stack/whatsapp-media/incoming/"

    A trailing slash on the last part is preserved, so the result is usable directly
    as a ``Prefix=`` argument as well as a key stem.
    """
    return PUBLIC_ROOT + _join(parts)


def secure(*parts: str) -> str:
    """Join ``parts`` into a key under the gated root."""
    return SECURE_ROOT + _join(parts)


def _join(parts: tuple[str, ...]) -> str:
    trailing = parts[-1].endswith("/") if parts else False
    cleaned = [p.strip("/") for p in parts if p and p.strip("/")]
    joined = "/".join(cleaned)
    return joined + "/" if trailing and joined else joined


def canonical(key: Optional[str]) -> str:
    """Return ``key`` rooted in the tree it belongs to, without moving it between roots.

    A key already under ``o/`` or ``secure/`` is returned unchanged — so this is safe to
    apply twice, and safe to apply to a gated key without exposing it. Anything else is
    treated as a legacy key written before the bucket merge and rooted under ``o/``.

    A full URL is returned unchanged: `DocumentTable` stores either a key or an absolute
    ``fileUrl``, and prefixing the latter would corrupt it.
    """
    if not key:
        return ""
    k = key.lstrip("/")
    if k.startswith(("http://", "https://")):
        return key
    if k.startswith(PUBLIC_ROOT) or k.startswith(SECURE_ROOT):
        return k
    return PUBLIC_ROOT + k


def public_url(key: Optional[str], cdn_domain: Optional[str] = None) -> str:
    """The apex URL for a public key.

    Built from `canonical`, so a legacy un-prefixed key yields a URL that actually
    resolves. Returns ``""`` for a gated key rather than a URL that will 302: a caller
    handing a ``secure/`` key to a public-URL builder has made a mistake, and an empty
    string surfaces it at the call site instead of shipping a dead link to a recipient.
    """
    k = canonical(key)
    if not k or k.startswith(SECURE_ROOT):
        return ""
    if k.startswith(("http://", "https://")):
        return k
    return f"https://{(cdn_domain or CDN_DOMAIN).strip('/')}/{k}"


def is_gated(key: Optional[str]) -> bool:
    """True when the key lives under the gated root."""
    return bool(key) and canonical(key).startswith(SECURE_ROOT)
