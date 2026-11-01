"""The S3 key contract for `wecare-digital-get`. One bucket, two roots.

Live layout
-----------
Read on 2026-10-25 (account 775261844268, `us-east-1`, 199 objects). Every constant below
names one of these prefixes, and nothing else holds a current object::

    secure/
      u/                         INPUT: the upload as received (edge-gated)
        dropdocs/
        service-requests/
      d/                         DELIVERABLES: generated output
        public/                  served without auth, except customer data (see below)
          Invoice/customer_invoice/   Invoice/fonts/
          receipts/
          whatsapp/  incoming/ outgoing/ voice/ transcriptions/ downloads/ calling-ai/
                     whatsapp-calling/ resumable/ template-headers/
                     wa-tpl/{img,docs,vid,aud,stk}/
          blog/{audits,categories,editorial,remediation}/
          catalog-deploy/  catalog/products/ (+ final manifest, contact sheet, QA reports)
                           catalog-media/ catalog-relocation/ catalog-always-available/
    o/                           STATIC/CDN assets
      stream/media/  m/ (branding; flags/)  ivr/  reports/  docs/
      error.html  healthcheck.txt

Compose keys from these constants rather than hand-building path strings.

What is public
--------------
CloudFront ``E2GP22R4BIFGQ3`` serves the bucket as ``https://wecare.digital/get/<key>``
(origin path ``""``, so the root segment is part of the URL), and the
``wecare-get-miss-redirect`` Lambda@Edge decides exposure by prefix:

* ``secure/d/public/**`` is served with **no authentication** - template media
  (``whatsapp/wa-tpl/``), template-header copies, the IVR greeting folder, catalog,
  blog and invoice fonts - EXCEPT the customer data in `PRIVATE_DELIVERABLE_PREFIXES`
  (invoices, receipts, WhatsApp incoming/outgoing/voice media, transcriptions,
  downloads, calling-ai, resumable uploads), which is redirected since 2026-10-25.
* Every other ``secure/**`` key - ``secure/u/**`` and any ``secure/d/`` key outside
  ``public/`` - is redirected at the edge and reachable only through a presigned URL.
* Everything else, including ``o/**`` and the bucket root, is public.

So ``o/`` is a location, not a permission, and the folder name alone does not say whether
a key is served. Ask `is_gated`, hand gated keys out only as presigned URLs, and never
move a key between subtrees to "make it work" - that is a disclosure one way and a broken
link the other.

Why ``o/`` stays
----------------
Brand assets, IVR audio, the BIMI ``l=`` record and every apex ``/get/o/...`` URL
already issued name it, as do keys persisted before the bucket merge. Dropping it is a
data migration, not a rename.

Legacy keys
-----------
Rows written before the merge store keys with no root (for example
``stack/whatsapp-media/incoming/<file>``), and older rows name the retired ``o/stack/``
and ``o/public/`` trees, which hold no current objects - only noncurrent versions, which
the bucket lifecycle expires 90 days after they became noncurrent. `canonical` roots a
bare key on read without moving it between roots and is idempotent; it cannot bring back
an object that is gone.
"""

from __future__ import annotations

from typing import Optional

#: Public root for static/CDN assets; see the module docstring for why it stays.
PUBLIC_ROOT = "o/"

#: Gated root. Denied at the edge and reachable only via a presigned URL, EXCEPT the
#: `PUBLIC_DELIVERABLE_ROOT` subtree below.
SECURE_ROOT = "secure/"

#: Public-delivery subtree inside the deliverable root. CloudFront serves this
#: subtree directly with no authentication; every other secure/ key remains gated.
PUBLIC_DELIVERABLE_ROOT = "secure/d/public/"
# Exact Vault-only staff upload prefix. The spelling is an intentional S3 contract.
# This path MUST be on the edge private-prefix list before any files are uploaded.
VAULT_UPLOAD_PREFIX = PUBLIC_DELIVERABLE_ROOT + "valut/"

# Canonical application-owned prefixes. New writes must use these names rather than
# recomposing path strings at call sites. Historical reads may still use canonical().
# There is deliberately no "secure deliverable" alias: the only deliverable subtree in the
# layout is public, and a name that reads as gated would invite a disclosure.
SECURE_UPLOAD_ROOT = "secure/u/"

# Dedicated customer Drop Docs storage. This is PRIVATE despite its public/ ancestor.
# The live S3 bucket policy denies CloudFront OAC access to the entire prefix.
DROP_DOCS_UPLOAD_PREFIX = PUBLIC_DELIVERABLE_ROOT + "drop-docs/"
# Old keys remain valid for historical reads; never write new documents here.
LEGACY_DROP_DOCS_UPLOAD_PREFIX = SECURE_UPLOAD_ROOT + "dropdocs/"
SERVICE_REQUEST_UPLOAD_PREFIX = SECURE_UPLOAD_ROOT + "service-requests/"

INVOICE_CUSTOMER_IMAGE_PREFIX = PUBLIC_DELIVERABLE_ROOT + "Invoice/customer_invoice/"
INVOICE_FONT_PREFIX = PUBLIC_DELIVERABLE_ROOT + "Invoice/fonts/"
RECEIPT_PREFIX = PUBLIC_DELIVERABLE_ROOT + "receipts/"

WHATSAPP_ROOT = PUBLIC_DELIVERABLE_ROOT + "whatsapp/"
WHATSAPP_INCOMING_PREFIX = WHATSAPP_ROOT + "incoming/"
LEGACY_WHATSAPP_INCOMING_PREFIX = PUBLIC_ROOT + "stack/whatsapp-media/incoming/"
WHATSAPP_OUTGOING_PREFIX = WHATSAPP_ROOT + "outgoing/"
WHATSAPP_VOICE_PREFIX = WHATSAPP_ROOT + "voice/"
WHATSAPP_TRANSCRIPTIONS_PREFIX = WHATSAPP_ROOT + "transcriptions/"
WHATSAPP_DOWNLOADS_PREFIX = WHATSAPP_ROOT + "downloads/"
WHATSAPP_CALLING_AI_PREFIX = WHATSAPP_ROOT + "calling-ai/"
WHATSAPP_CALLING_PREFIX = WHATSAPP_ROOT + "whatsapp-calling/"
WHATSAPP_RESUMABLE_PREFIX = WHATSAPP_ROOT + "resumable/"
WHATSAPP_TEMPLATE_HEADER_PREFIX = WHATSAPP_ROOT + "template-headers/"
WHATSAPP_TEMPLATE_ASSET_ROOT = WHATSAPP_ROOT + "wa-tpl/"
WHATSAPP_TEMPLATE_IMAGE_PREFIX = WHATSAPP_TEMPLATE_ASSET_ROOT + "img/"
WHATSAPP_TEMPLATE_DOCUMENT_PREFIX = WHATSAPP_TEMPLATE_ASSET_ROOT + "docs/"
WHATSAPP_TEMPLATE_VIDEO_PREFIX = WHATSAPP_TEMPLATE_ASSET_ROOT + "vid/"
WHATSAPP_TEMPLATE_AUDIO_PREFIX = WHATSAPP_TEMPLATE_ASSET_ROOT + "aud/"
WHATSAPP_TEMPLATE_STICKER_PREFIX = WHATSAPP_TEMPLATE_ASSET_ROOT + "stk/"

#: Customer data that sits under PUBLIC_DELIVERABLE_ROOT but must not be served by URL.
#: The edge function (`edge/get-miss-redirect`) redirects these exactly like the rest of
#: `secure/`; code reaches them through the S3 API or a presigned URL. Nothing hands a
#: public URL for them to Meta, Plivo, Sinch or a browser (checked 2026-10-25), so gating
#: them broke no consumer. `verify_media_prefixes.py` keeps the edge copy identical.
PRIVATE_DELIVERABLE_PREFIXES: tuple[str, ...] = (
    VAULT_UPLOAD_PREFIX,
    DROP_DOCS_UPLOAD_PREFIX,
    INVOICE_CUSTOMER_IMAGE_PREFIX,
    RECEIPT_PREFIX,
    WHATSAPP_INCOMING_PREFIX,
    WHATSAPP_OUTGOING_PREFIX,
    WHATSAPP_VOICE_PREFIX,
    WHATSAPP_TRANSCRIPTIONS_PREFIX,
    WHATSAPP_DOWNLOADS_PREFIX,
    WHATSAPP_CALLING_AI_PREFIX,
    WHATSAPP_RESUMABLE_PREFIX,
)

BLOG_ROOT = PUBLIC_DELIVERABLE_ROOT + "blog/"
BLOG_AUDITS_PREFIX = BLOG_ROOT + "audits/"
BLOG_CATEGORIES_PREFIX = BLOG_ROOT + "categories/"
BLOG_EDITORIAL_PREFIX = BLOG_ROOT + "editorial/"
BLOG_REMEDIATION_PREFIX = BLOG_ROOT + "remediation/"

CATALOG_DEPLOY_ROOT = PUBLIC_DELIVERABLE_ROOT + "catalog-deploy/"
CATALOG_PREFIX = CATALOG_DEPLOY_ROOT + "catalog/"
CATALOG_PRODUCTS_PREFIX = CATALOG_PREFIX + "products/"
CATALOG_MEDIA_PREFIX = CATALOG_DEPLOY_ROOT + "catalog-media/"
CATALOG_GENERATED_MEDIA_PREFIX = CATALOG_MEDIA_PREFIX + "generated/"
CATALOG_RELOCATION_PREFIX = CATALOG_DEPLOY_ROOT + "catalog-relocation/"
CATALOG_ALWAYS_AVAILABLE_PREFIX = CATALOG_DEPLOY_ROOT + "catalog-always-available/"

PUBLIC_STREAM_MEDIA_ROOT = PUBLIC_ROOT + "stream/media/"
PUBLIC_STREAM_MEDIA_M_PREFIX = PUBLIC_STREAM_MEDIA_ROOT + "m/"
PUBLIC_STREAM_MEDIA_IVR_PREFIX = PUBLIC_STREAM_MEDIA_ROOT + "ivr/"
PUBLIC_STREAM_MEDIA_REPORTS_PREFIX = PUBLIC_STREAM_MEDIA_ROOT + "reports/"
PUBLIC_STREAM_MEDIA_DOCS_PREFIX = PUBLIC_STREAM_MEDIA_ROOT + "docs/"
PUBLIC_STREAM_MEDIA_FLAGS_PREFIX = PUBLIC_STREAM_MEDIA_M_PREFIX + "flags/"

# Deployment marker retained from the media-prefix migration; runtime deployment is explicit.
#: The single media bucket. Everything below lives here.
BUCKET = "wecare-digital-get"

#: The apex media host, including its path segment. Deliberately NOT the bucket name:
#: the pre-merge bucket was named like a hostname, which is why several handlers used to
#: interpolate the bucket into a URL. ``wecare-digital-get`` is not a domain, so that
#: pattern produces a URL resolving to nothing.
CDN_DOMAIN = "wecare.digital/get"


def public(*parts: str) -> str:
    """Join ``parts`` into a key under the public root.

        public("stream/media", "ivr/")  -> "o/stream/media/ivr/"

    A trailing slash on the last part is preserved, so the result is usable directly
    as a ``Prefix=`` argument as well as a key stem.
    """
    return PUBLIC_ROOT + _join(parts)


def secure(*parts: str) -> str:
    """Join ``parts`` into a key under the secure root."""
    return SECURE_ROOT + _join(parts)


def deliverable_public(*parts: str) -> str:
    """Join ``parts`` under the public-delivery subtree."""
    return PUBLIC_DELIVERABLE_ROOT + _join(parts)


def _join(parts: tuple[str, ...]) -> str:
    trailing = parts[-1].endswith("/") if parts else False
    cleaned = [p.strip("/") for p in parts if p and p.strip("/")]
    joined = "/".join(cleaned)
    return joined + "/" if trailing and joined else joined


#: Stored-key prefixes that name a location no object lives at, mapped to where the objects
#: actually are. `secure/whatsapp/` was written into MessagesTable `s3Key` by the 2026-10 media
#: relocation, while the objects themselves went to `secure/d/public/whatsapp/`. Measured
#: 2026-10-25: 12 rows used it, `secure/whatsapp/` held no objects, and every one of the 12
#: objects was present at the mapped key. Nothing composes `secure/whatsapp/`, so this only
#: resolves old pointers; it moves no object and exposes nothing that was gated.
STORED_KEY_ALIASES: tuple[tuple[str, str], ...] = (
    ("secure/whatsapp/", WHATSAPP_ROOT),
)


def canonical(key: Optional[str]) -> str:
    """Return ``key`` rooted in the tree it belongs to, without moving it between roots.

    A key already under ``o/`` or ``secure/`` is returned unchanged — so this is safe to
    apply twice, and safe to apply to a gated key without exposing it — except a prefix in
    `STORED_KEY_ALIASES`, which is resolved to where its objects actually live. Anything
    else is treated as a legacy key written before the bucket merge and rooted under ``o/``.

    A full URL is returned unchanged: `DocumentTable` stores either a key or an absolute
    ``fileUrl``, and prefixing the latter would corrupt it.
    """
    if not key:
        return ""
    k = key.lstrip("/")
    if k.startswith(("http://", "https://")):
        return key
    for stored, actual in STORED_KEY_ALIASES:
        if k.startswith(stored):
            return actual + k[len(stored):]
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
    if not k or is_gated(k):
        return ""
    if k.startswith(("http://", "https://")):
        return k
    return f"https://{(cdn_domain or CDN_DOMAIN).strip('/')}/{k}"


def is_gated(key: Optional[str]) -> bool:
    """True when the edge refuses this key: all of `secure/` except the public-delivery
    subtree, and within that subtree the customer data in PRIVATE_DELIVERABLE_PREFIXES."""
    if not key:
        return False
    k = canonical(key)
    if k.startswith(PRIVATE_DELIVERABLE_PREFIXES):
        return True
    return k.startswith(SECURE_ROOT) and not k.startswith(PUBLIC_DELIVERABLE_ROOT)


def in_private_store(key: Optional[str]) -> bool:
    """True for a `secure/` key outside the public-delivery subtree: uploads as received
    (`secure/u/`) and secure-files deliverables. Conversation media under
    `secure/d/public/whatsapp/` is gated at the edge but is not in this store."""
    if not key:
        return False
    k = canonical(key)
    return k.startswith(SECURE_ROOT) and not k.startswith(PUBLIC_DELIVERABLE_ROOT)
