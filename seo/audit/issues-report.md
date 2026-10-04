# SEO Issues Report — WECARE.DIGITAL
## Generated: 2026-04-25

### CRITICAL Issues

1. **Homepage has NO JSON-LD schema on live site**
   - Organization, WebSite, WebPage schemas exist in code but NOT injected into Wix page
   - Fix: Manual → Wix Dashboard → Home → SEO Panel → Add structured data markup
   - Priority: P0

2. **37 static pages have NO custom SEO titles/descriptions**
   - Wix auto-generates generic titles like "BNB Club | WECARE.DIGITAL"
   - No custom meta descriptions on most pages
   - Fix: Manual → Wix Dashboard → each page → SEO Panel
   - Priority: P0

3. **14 system pages may be indexed**
   - Cart, checkout, login, signup, 404, members area
   - Fix: Manual → Wix Dashboard → each system page → SEO Panel → set noindex
   - Priority: P1

4. **Product pages have no custom JSON-LD**
   - Wix auto-generates basic Product schema but missing: brand, seller, inLanguage
   - Fix: Manual → Wix Dashboard → each product → SEO Panel → Add structured data
   - Priority: P1

### HIGH Issues

5. **No hreflang tags** — Site is en-IN only, no multilingual. Not an issue unless expanding.

6. **Blog posts missing cover images** — Many posts have no featured image, hurting OG/Twitter cards and image search.

7. **Blog content is thin** — Many posts are under 300 words. Google may classify as thin content.

8. **No image sitemap** — Only URL sitemaps exist. Product/blog images not in sitemap.

9. **Search results page should be noindex** — `/search` page may be indexed.

10. **Brand store pages have no ItemList schema** — Store pages list products but no ItemList structured data.

### MEDIUM Issues

11. **Duplicate Organization schema risk** — `schema_engine.py` was adding Organization to every page (fixed to homepage only).

12. **No `article:published_time` on some blog posts** — Fixed in latest http-functions.js update.

13. **Product schema missing real prices** — `schema_engine.py` had `price: "0"` as default (needs real price from Wix Stores).

14. **No internal links in blog post body** — AI suggests internal links but they're not auto-inserted into post content.

15. **FAQ page has static FAQs** — 13 Q&A pairs are hardcoded, not dynamically updated.

### LOW Issues

16. **Legal pages could be noindex** — `[retired public path 32bc4583]` and `/privacy` don't need search ranking.

17. **No video schema** — No video content on site.

18. **No Event schema** — Expo Week page has no Event structured data.

19. **No Booking schema** — Appointment page has no Booking/Service structured data via Wix.

20. ~~**Stack app (retired legacy frontend host) has no robots.txt** — Admin tool should have `Disallow: /`.~~
    **OBSOLETE 2026-09-26.** The host was retired on 2026-09-25 with its Route 53 CNAME and is
    NXDOMAIN, so there is nothing left to serve a `robots.txt` from. Kept rather than deleted so
    the item is not silently re-raised against the apex, which is a public site and must stay
    crawlable. The admin surface now lives on paths under `wecare.digital`; if those need to be
    excluded, that belongs in the apex `robots.txt`, not a per-host one.
