---
inclusion: always
---

# SEO, metadata, and structured data

Every page must be fully optimized for search engines so the site competes for
first-page rankings. SEO is a hard requirement: a page is not done until it has
correct metadata, structured data, and crawlable, indexable markup.

## Per-page metadata (required on every page)

- **Title:** unique, descriptive `<title>`, ~50–60 chars, primary keyword near
  the front, brand suffix (e.g. `… | WeCare Digital`). Never duplicate titles
  across pages.
- **Meta description:** unique, compelling, ~150–160 chars, includes the target
  keyword and a reason to click.
- **Canonical:** a self-referencing `<link rel="canonical">` on every page to
  prevent duplicate-content dilution.
- **Robots:** index/follow by default; only `noindex` thin/utility pages
  intentionally. Keep a valid `robots.txt` and an up-to-date `sitemap.xml`
  (the build already runs a sitemap generator — keep it correct).
- **Language/region:** set `<html lang>` and `hreflang` where multiple
  locales exist.

## Open Graph & social

- Provide Open Graph (`og:title`, `og:description`, `og:image`, `og:url`,
  `og:type`) and Twitter Card (`summary_large_image`) tags on every page.
- `og:image` must be a real, absolute URL, ≥ 1200×630, with a sensible
  fallback for pages without a bespoke image.

## Favicons & app icons

- Ship a complete icon set: `favicon.ico`, SVG favicon, `apple-touch-icon`
  (180×180), and a `site.webmanifest` with maskable PNG icons (192 & 512).
- Set `theme-color` so mobile browser chrome matches the brand.

## Structured data (Google rich results, JSON-LD)

- Emit valid **JSON-LD** `schema.org` structured data appropriate to the page:
  - `Organization` + `WebSite` (with `SearchAction`) sitewide.
  - `BreadcrumbList` on every page that sits below the home level — mirror the
    visible breadcrumb trail exactly.
  - `Product` + `Offer` (price, availability, currency) on product pages,
    `Article`/`BlogPosting` on blog posts, `FAQPage` where FAQs exist,
    `LocalBusiness` for location/contact pages.
- Keep structured data consistent with on-page content (no markup for content
  users can't see). Validate against Google's Rich Results Test before
  shipping.

## Breadcrumbs

- Render a visible breadcrumb trail on all non-home pages and back it with
  `BreadcrumbList` JSON-LD so Google can show breadcrumb rich results.
- Breadcrumb links must be real crawlable `<a href>` anchors.

## Content & technical ranking factors

- One `<h1>` per page; logical `<h2>`/`<h3>` hierarchy; keyword in headings
  naturally, no stuffing.
- Descriptive, keyword-relevant, lowercase, hyphenated URLs; avoid query-string
  URLs for indexable content.
- Every image needs meaningful `alt` text; use descriptive link anchor text,
  not "click here".
- Use semantic HTML landmarks (`header`, `nav`, `main`, `footer`, `article`).
- Internal-link related pages to spread authority and aid crawl depth.
- Core Web Vitals matter for ranking: keep LCP, CLS, and INP in the green
  (optimize images, avoid layout shift, defer non-critical JS).

## Verification before "done"

- Confirm `npm run build` succeeds and the sitemap / blog-index / llms
  generators run.
- Check that the page has a unique title, meta description, canonical, OG tags,
  and the correct JSON-LD.
- Validate structured data (Rich Results Test) and confirm no accidental
  `noindex` on pages that should rank.
