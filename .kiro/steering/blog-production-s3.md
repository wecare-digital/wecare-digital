---
inclusion: always
---

# Blog Production storage: one bucket, one prefix root, no exceptions

## THE MANDATORY RULE

**Use the existing S3 bucket `wecare-digital-get`.**

**DO NOT CREATE A NEW S3 BUCKET WITHOUT EXPLICIT USER APPROVAL.**

That applies to every part of the Blog Production system: source PDFs, fetched URL
payloads, extracted text, source analysis, working articles, QA records, publish
records, verification records and failure records. If isolation is needed, use
**prefixes, IAM scoping, object tags and metadata** — not another bucket.

`.kiro/hooks/block-s3-bucket-creation.json` denies the command shapes that would create
one. It refuses rather than asks, which is what makes it compatible with the workspace's
blanket-allow permissions.

## The name has a known typo, and it has already cost a round trip

The project specification asks for `wecare-di**f**ital-get`. That bucket **does not
exist** — `head-bucket` returns a clean 404, and no bucket with that spelling exists in
account `775261844268`. The real bucket is:

    wecare-digital-get          us-east-1        created 2026-09-25

Confirmed by the owner on 2026-09-29. If a future instruction spells it `difital` again,
that is the typo, not a second bucket. **Do not create it.** Ask.

## Prefix root

Everything lives under **`o/blog-production/`**.

`o/` is the **public** root — CloudFront `E2GP22R4BIFGQ3` serves it at
`https://wecare.digital/get/o/...` with no authentication. `secure/` is the gated root,
denied wholesale at the edge.

**`o/` is an explicit owner decision, taken twice**, most recently on 2026-09-29 covering
derived artefacts as well as sources. Recorded here with its consequence so nobody has to
re-derive it:

- An uploaded source PDF, its extracted text, and a working article draft are all
  **readable by anyone holding the URL**.
- The exposure is bounded, not absent. Keys are content hashes, so they cannot be
  guessed; bucket listing is not public (all four public-access-block settings are on,
  and the bucket policy grants `s3:GetObject` only to the CloudFront service principal).
- So the correct mental model is **unlisted-but-public**: safe from enumeration, not safe
  once a URL leaks. Treat the URL as the secret.
- These are third-party documents. The extracted markdown is more reproducible than the
  PDF it came from, which is why this was raised before being implemented.

Moving to `secure/` later is a prefix change plus an IAM change and nothing else, because
every key is composed through `media_paths`. It is not a rewrite.

## Compose keys through `media_paths`, never by hand

`amplify/functions/shared/lambda_utils/media_paths.py` owns the key contract and says so:
"Keep composing keys through `public` and `secure` rather than hand-building them."

```python
from lambda_utils import media_paths
key = media_paths.public("blog-production/sources/pdf", f"{sha256}.pdf")
url = media_paths.public_url(key)      # "" for a gated key, never a dead link
```

It also records why `o/` cannot be dropped: `o/public/wa-tpl/` holds **61 objects whose
URLs are embedded in WhatsApp templates Meta has already approved**, and Meta refetches
media from the approved URL at send time. An approved template body cannot be edited in
place.

**Never write to the bucket root.** A root-level key still returned HTTP 200 on the apex
host, so addressing one level above the data "errored nowhere, logged nothing and alarmed
nothing" for two days.

## The prefix layout

    o/blog-production/
      sources/pdf/<sha256>.pdf              uploaded source, key IS the content hash
      sources/url/<sourceId>.json           fetched payload plus response headers
      extracted/<sourceId>.md               reflowed markdown
      source-analysis/<sourceId>/v<n>.json  versioned; never overwritten, never linked
      article-working/<articleId>/<rev>.md
      qa/<sourceId>/<qaRunId>.json          immutable QA verdict, never overwritten
      repetition/<batchId>/<runId>.json     collection-level, so keyed on the BATCH
      publish-records/<articleId>.json
      verification/<articleId>/<runId>.json
      failures/<sourceId>.json

### Two corrections to the source-analysis line, both load-bearing

**It is a directory per source, not a flat file.** This line originally read
`source-analysis/<sourceId>.json`. An analysis is versioned, because a reviewer's sign-off
names the version they read and a re-extraction must invalidate that reading rather than
inherit it — so v2 cannot overwrite v1, or the artifact somebody signed against is gone. The
code was not bent to fit the documentation; the documentation was wrong.

**"Never public copy" means unlisted and unlinked, not gated.** The prefix is `o/`, which
CloudFront serves without authentication, so an analysis IS fetchable by anyone holding its
URL. The difference from a source PDF is intent: `blog_sources.source_url` deliberately
surfaces a link to the document, because a reviewer has to read it. Nothing returns a URL for
an analysis — `blog_analysis.detail` proxies the body through the authenticated route, and
`test_the_analysis_is_never_handed_out_as_a_url` asserts no key in the response is
URL-shaped. If the evidence must be genuinely private, the prefix moves under `secure/` and
no code changes.

### Why the key is the content hash

Three properties, all load-bearing:

1. **Resolve-before-generate.** Re-uploading the same PDF lands on the row that already
   exists instead of minting a second article. Publishing the same source twice is the one
   failure in this pipeline that cannot be undone after the fact.
2. **A rename is not a new source.** Re-exporting a batch from a drive with different
   filenames is the common case, and filename-keyed storage would convert all of it again.
3. **An overwrite writes identical bytes**, which is what makes bucket versioning being
   *Suspended* tolerable rather than dangerous.

The original filename is preserved **in the record**, never relied on for uniqueness.

## IAM

The inline policy `seo-blog-source-intake` on `wecare-digital-lambda-role` is scoped to
the prefix and to three actions:

    s3:PutObject, s3:GetObject, s3:HeadObject   on   o/blog-production/*

**No `DeleteObject`, deliberately.** Nothing in this pipeline deletes a source, because a
source is the provenance record for a published article. That role is shared by the whole
fleet, so a wildcard here would widen every other function too.

## Related

- `.kiro/steering/whatsapp-payments-india-reference.md` — the same content-hash,
  resolve-before-generate discipline applied to `reference_id`
- `amplify/functions/shared/lambda_utils/media_paths.py` — the key contract
- `docs/execution/` — the PHASE 0 audit that established the bucket and prefix decisions


## WhatsApp media: two folders, two roles (owner decision 2026-10-07)

WhatsApp media is split into an outgoing public folder and an incoming gated folder.
They are NOT interchangeable; the split is a privacy boundary, not organisation.

| Folder | Role | Access | Why |
|---|---|---|---|
| `o/public/wa-tpl/img/` | **Outgoing** template header images (e.g. `wecarepay-header.png`, the fixed payment-template logo) | **public** (CloudFront, unauthenticated) | Meta refetches a template's header from its URL at send time, so it MUST be publicly reachable. Reserved for outgoing template assets only — do not junk it with anything else. |
| `secure/stack/whatsapp-media/incoming/` | **Incoming** customer WhatsApp media (documents, images a customer sends) | **gated** (`secure/` root, denied at the edge) | Incoming customer content must never be publicly readable. |

The fixed payment-template header is `o/public/wa-tpl/img/wecarepay-header.png`
(verified serving HTTP 200, `image/png`, over `https://wecare.digital/get/...` 2026-10-07).
The invoice-engine and outbound-whatsapp send paths hardcode that URL as the header on
EVERY payment, with no per-call override.

**Known migration:** inbound WhatsApp uploads historically land at the PUBLIC
`o/stack/whatsapp-media/incoming/`. Phase O-2's Drop Docs path already copies an incoming
object into `secure/` before registering it as a customer document precisely because the
arrival prefix is public. The target end-state is that incoming customer media lands
directly under `secure/stack/whatsapp-media/incoming/` (gated), composed through
`media_paths.secure(...)`, so the public arrival prefix is no longer a customer-data
exposure. Compose all keys through `media_paths` (public()/secure()), never by hand.
No new bucket — prefixes + IAM scoping only.
