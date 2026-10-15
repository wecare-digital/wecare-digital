# Conversations — PDF and URL to blog pipeline

Bulk intake of PDFs and URLs, converted into Conversations (or Gastronomy) articles under
the **Conversations Content Quality Standard v2**, with a ledger recording which article
came from which source.

## The shape of it

```
sources (PDF / URL)
  │
  ├─ scripts/blog_ingest.py ingest    extract, reflow, hash, register in the ledger
  │     └─ extracts/<slug>-<id>.md    the readable source, for section 2
  │
  ├─ scripts/blog_ingest.py draft     draft records, every field a machine can fill
  │     └─ drafts/CONV-*.json         status SOURCE_REVIEW, body = source extract
  │
  ├─ EDITORIAL  (human)               read the source, reconstruct in Anew voice,
  │                                   fill centralDistinction / distinctPurpose,
  │                                   record the section 29 human gates
  │
  ├─ scripts/blog_quality_v2.py       the standard, as executable checks
  │     └─ batches/CONV-*.json        only READY_TO_PUBLISH enters the queue
  │
  ├─ batch gates                      scripts/conversations_batch.py (Conversations)
  │     │                             scripts/gastronomy_batch.py   (Gastronomy)
  │     └─ validate against the native blog contract (scripts/blog_native_contract.py)
  │
  └─ Blog Studio  (human)             release and publish, written by wecare-seo-tools
        └─ batch gates audit          read every published post back
```

## What is committed, and what is not

| Path | Committed | Why |
|---|---|---|
| `ledger.json` | **yes** | the source-to-article record; the whole point is that it is durable and diffable |
| `batches/CONV-*.json` | **yes** | the finished Anew articles, which are ours |
| `extracts/` | **no** | verbatim text of third-party PDFs. Committing a book's text is a licensing problem and a repo-size one |
| `drafts/` | **no** | each draft embeds the full `sourceExtract`, so the same reasoning applies |

`extracts/` and `drafts/` are gitignored. They are working files on the machine doing the
ingestion. The ledger keeps the source hash, so provenance survives without the text.

## Running it

```bash
# a directory of PDFs and a list of URLs, one run, thousands of sources
python scripts/blog_ingest.py ingest \
    --pdf-dir ~/sources/conversations \
    --url-file ~/sources/urls.txt \
    --category Conversations --article-class ARCHIVE_DERIVED --workers 8

# re-running is free: a source already in the ledger is skipped, not converted twice
python scripts/blog_ingest.py ingest --pdf-dir ~/sources/conversations

python scripts/blog_ingest.py status
python scripts/blog_ingest.py draft --out content/conversations/drafts/CONV-001-CONV-025.json --limit 25

# after editorial work
python scripts/blog_quality_v2.py validate --manifest content/conversations/batches/CONV-001-CONV-025.json
python scripts/blog_ledger.py verify
```

The admin page at `/workspace/seo/blog-studio` does the intake side: drop PDFs, add URLs,
pick one of the two categories, and export a **work order**. It computes each file's
SHA-256 in the browser, and `--work-order` re-checks that hash against the file on disk —
so selecting the wrong file is caught at ingestion rather than becoming permanent, wrong
provenance on a published article.

## The two categories

`Conversations` and `Gastronomy`. These are the two that exist on the live blog, and
`blog_quality_v2.CATEGORIES` is an enum rather than free text on purpose: the older admin
form used a `<datalist>`, where a typo silently creates a third category — and `/blog/`
serves whichever category sorts first alphabetically, so `Conversatons` would have taken
over the blog index.

Gastronomy records additionally carry the recipe structure its own gate enforces
(Ingredients heading, Method heading, an ingredient list, 450+ characters).

## What the pipeline will not do

It does not write the article, and it cannot mark one `READY_TO_PUBLISH`.

Section 29 of the standard asks for a PASS/FAIL on ORIGINAL EXPRESSION ("independently
Anew rather than cosmetically rewritten"), on VOICE, and on SUBSTANCE. Section 30 asks
whether an intelligent reader would feel the article was written because there was
something worth saying. No program can answer those, and one that stamped them would turn
the standard into a rubber stamp while reporting full compliance.

So mechanical checks only ever move a record **down**. A record that passes every
automated check lands on `EDITORIAL_QA`. Reaching `READY_TO_PUBLISH` requires a human to
have recorded the eleven human gates in the record's `gate` object. Section 32's rule that
only `READY_TO_PUBLISH` enters the publish queue is therefore preserved rather than defeated.

## Publication happens in Blog Studio, not here

Nothing in this directory's tooling publishes. Posts live in the AWS-native blog store
(`blogPost` records in SeoToolsTable), and the only writer is `wecare-seo-tools`: an operator
releases a signed-off article in Blog Studio and the publish step re-checks the sign-off and
the body hash before writing. Both `publish` workflow inputs are retired and fail explicitly.

The batch gates check records against the native blog contract in
`scripts/blog_native_contract.py`:

- **validate** — the v2 standard, ledger provenance, and whether the record would go live
  intact: a slug the store keeps unchanged (lowercase words and single hyphens, at most 120
  characters), a body under the store's item limit, and only Markdown the post page renders
  (`#`/`##`/`###` headings, paragraphs, `- ` lines, `**bold**`, `*italic*`). It needs no AWS
  access.
- **audit** — reads every published post back through the public read route
  (`/seo-tools/blog-public`) and checks title, slug, author, category, tags, SEO, URL, cover
  image, publication freshness, the body against the record, duplicates and formatting
  corruption, then checkpoints `VERIFIED` into `ledger.json`. A record that is not live yet
  is reported as not published rather than failed.

```bash
python scripts/conversations_batch.py validate --manifest content/conversations/batches/CONV-001.json
python scripts/conversations_batch.py audit    --manifest content/conversations/batches/CONV-001.json
```

Manifest size is arbitrary. There is no editorial batch count for Conversations; Gastronomy's
contiguous 25 is its own rule.

And because the public site is a static export (`output: 'export'` in `next.config.js`),
a published post is not visible until an Amplify build re-reads the native blog. See
`.kiro/steering/lambda-snapstart-deploy.md` for the same two-phase shape on Lambda.
