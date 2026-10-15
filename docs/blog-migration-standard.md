# WECARE.DIGITAL blog migration standard

The native blog is the content source of truth: posts live in `SeoToolsTable` and are
served by `wecare-seo-tools` at `/seo-tools/blog-public` and `/seo-tools/blog-public/{slug}`.

## Editorial reference

The approved **Integrity** article is the master reference for how existing posts
are upgraded. The rule is:

> Preserve the original distinction. Remove looseness. Strengthen rhythm.
> Sharpen wording. Add only the minimum structure needed to make the idea land.

Do not turn a short source post into a new essay. Do not introduce a new analogy,
framework, teaching, personal story, example, or conceptual claim unless the source
post itself supports it.

The approved Integrity flow begins:

> Once we learn to balance on a bicycle, we do not have to rediscover the whole
> skill every time we ride. We get on and use what we have learned.

and closes:

> We can choose it again. The choice matters because it has to become visible in
> what we do.

That standard means the upgrade is primarily editing, cadence, paragraph structure,
and selective emphasis.

**These two quotes are a dated snapshot, read from live on 2026-09-28, not a
frozen contract.** The live post is authoritative, so an editor revising it makes
these lines go stale rather than the post going wrong. They previously read:

> Once balance is distinguished, you do not need to rediscover it every time.
>
> We can always choose it again.

which is what `seo-tools-deploy.yml` asserted verbatim. When the post was edited,
that assertion failed and blocked the `wecare-seo-tools` deploy — a Lambda that
had shipped fine — so the deploy gate no longer pins prose. It now asserts only
what this document fixes as a *rule*: author, category, slug, no cover or inline
media, and that substantive prose came back at all. Re-read the live post
(`GET /seo-tools/blog-public/integrity-honoring-our-word`) before quoting these
lines as current.

## Fixed publication rules

- Author: **Anew by WECARE.DIGITAL**
- Default category: **Conversations**
- Tags: **1-3** precise distinctions actually present in the article
- Preserve an original source slug only as `sourceSlug` history
- Every new Anew article gets a fresh `slug` that reflects the revised article/SEO framing
- Preserve the original first-published date only as `sourcePublishedDate` history; never
  publish it as the new article's publication date
- Every post gets a unique, source-faithful SEO title and meta description
- Canonical frontend URL: `https://wecare.digital/post/[slug]/`
- No hero image
- No cover image
- No inline image
- No decorative migrated media
- Frontend typography: Inter; desktop body 20px / 1.4 line-height
- Publisher in structured data: WECARE.DIGITAL
- Visible editorial author: Anew by WECARE.DIGITAL

The source slug and source publication date are retained for auditability and optional
redirect planning only. They are not reused as the identity or date of the fresh post.

## Pipeline safety

Bulk intake: `POST /seo-tools/blog-sources` returns presigned PUTs to `wecare-digital-get`
under `secure/blog-production/01-sources/`, and `POST /seo-tools/blog-sources/confirm`
hands the uploaded files to an asynchronous worker. `scripts/blog_ingest.py` is the CLI.

Keep content generation separate from content publication: drafts are reviewed before they
are published, and a batch publisher never invents or broadens an article.
