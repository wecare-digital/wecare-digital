# App Router Migration Evaluation (Pages Router under static export + Capacitor)

- **Scope:** Strategic, evaluate-only. This is a feasibility and decision document, not an instruction to migrate. No code or configuration is changed by this document. It belongs to Phase 5 ("Strategic, evaluate only") of `architecture/workspace-audit-2026-11-02.md` section 6.
- **Date:** 2026-11-02
- **Subject:** Whether to migrate the frontend from the Next.js Pages Router to the App Router, given the hard constraint that the production build is a static export (`output: 'export'`) packaged into native shells by Capacitor.
- **Primary source files cited:** `next.config.js`, `capacitor.config.ts`, `capacitor.public.config.ts`, `src/pages/_app.tsx`, `src/pages/_document.tsx`, `src/pages/**` (57 page files), plus the usage counts verified from the repo root (reproduced below).

## 1. The hard constraint: static export, consumed by two Capacitor shells

`next.config.js` sets:

```js
output: process.env.NODE_ENV === 'production' ? 'export' : undefined,
trailingSlash: true,
images: { unoptimized: true },
turbopack: { root: projectRoot },
```

The production build is therefore a fully static export into `out/`. There is no Node server at runtime. This is not a preference that can be toggled for convenience, because both native shells depend on it:

- `capacitor.config.ts` (internal "Stack CRM" app, `appId: 'digital.wecare.stackcrm'`) sets `webDir: 'out'`.
- `capacitor.public.config.ts` (public WECARE.DIGITAL app, whose `appId` comes from env `WECARE_PUBLIC_APP_ID`) also sets `webDir: 'out'`.

Both shells package the contents of `out/` as the web assets of a native app. Any migration target must still emit a complete static `out/` directory, or Capacitor packaging breaks for both apps. This single fact governs the entire evaluation: whatever the App Router could do in general, here it must run under `output: 'export'`.

Note on headers: `next.config.js` defines an async `headers()` function (`X-Frame-Options: DENY`, CSP-adjacent headers, `Permissions-Policy`, etc.). Under static export `headers()` does not execute at runtime, because there is no server to apply it. The comments in `src/pages/_document.tsx` confirm the security headers (XFO/CSP and related) ship at the hosting edge via `amplify.yml` / `customHttp.yml`, not through Next. This matters for the migration discussion because it means the headers behaviour is already decoupled from the Next router and would not change with an App Router move.

## 2. What this app actually uses (verified counts)

Counts were produced from the repo root and are reproducible:

| Signal | Count | Where |
| --- | --- | --- |
| Page files under `src/pages` | 57 | `src/pages/**` |
| `getServerSideProps` | 0 | none |
| `pages/api` route files | 0 | none |
| Files with `getStaticProps` | 9 | blog + shop: `src/pages/blog/*`, `src/pages/post/[slug].tsx`, `src/pages/shop/*` |
| Files with `getStaticPaths` | 8 | same blog + shop set |
| Files importing `next/router` | 36 | across `src` |
| Files importing `next/link` | 36 | across `src` |
| Files importing `next/image` | 0 | `images.unoptimized: true` |
| Class components repo-wide | 1 | `ErrorBoundary` (audit section 5h) |
| `UNSAFE_*` / `componentWill*` lifecycles | 0 | audit section 5h |

Read plainly: this is a statically exported, client-rendered SPA shell plus a thin build-time-static blog/shop. It uses **zero** runtime server features. The only build-time data fetching is the blog and shop `getStaticProps` / `getStaticPaths` pair, which run at build time and produce static HTML.

## 3. The `_app.tsx` client-shell architecture and the `ssr: false` bug fix

`src/pages/_app.tsx` is a deliberately client-heavy shell, and its structure is load-bearing:

- `AuthShell` is loaded with `dynamic(() => import('../components/AuthShell'), { ssr: false })`. Per the extensive in-file comments, **`ssr: false` is a required bug fix, not an optimisation.** Restoring `ssr: true` blanked every `/workspace/*` page: a Turbopack pages-router build emits no `react-loadable-manifest.json`, so `__NEXT_DATA__` carries no `dynamicIds`, and Next hydrates before the dynamic chunk is in flight, producing a hydration mismatch that leaves the build-time HTML visible and the real UI appended off-screen. The requirement to keep `ssr: false` is documented in the `_app.tsx` in-file comments (which reference a `PublicBundleWeight.test.ts` guard), but it is not currently backed by an automated test in the repo: no such test file or `src/test/` directory exists, and the repo's JS tests live under `tests/*.test.mjs`. Treat the `ssr: false` constraint as a documented-but-untested invariant.
- Global CSS is imported here (`amplify-base.css`, `Pages.css`, `Layout.css`, ..., `form-controls.css`) in a strict cascade order. In the Pages Router a global CSS import is unconditional and joins every route.
- Amplify is configured via a side-effect import of `lib/amplifyConfig.ts` (not imported in `_app.tsx` directly; it is pulled in by `AuthShell` and the API client).
- Capacitor native-shell detection is done by reading `window.androidBridge` / `webkit.messageHandlers.bridge` / `Capacitor.isNativePlatform` **without importing `@capacitor/core`**, to keep the native bridge and its plugins out of the web bundle.

This is a client-rendered SPA shell that happens to be exported statically. The interesting UI resolves on the client after hydration.

## 4. `_document.tsx` and the head/script machinery

`src/pages/_document.tsx` is a custom `Document` carrying:

- an inline deploy-skew guard script that must be the first script in `<head>`,
- GTM bootstrap with Consent Mode v2 ordering,
- a Meta Pixel bootstrap.

The App Router has **no** `_document.tsx` or `_app.tsx`. Their equivalents are `app/layout.tsx` (plus optional `template.tsx` and the Metadata API). The inline head scripts, the "first script in `<head>`" deploy-skew guard, and the strict GTM / Consent Mode ordering would all have to be re-expressed with `next/script` strategies and careful ordering in the root layout. That is a real, non-trivial migration cost with a correctness bar (consent ordering and skew-guard-first are behavioural requirements, not cosmetics).

## 5. App Router features: what works under `output: 'export'` vs what does not

### Supported under static export

- React Server Components that render at **build time** only.
- Static generation of routes.
- `generateStaticParams` (the App Router replacement for `getStaticPaths`).
- Route groups, nested layouts, `template.tsx`.
- The Metadata API (`generateMetadata`, `metadata` export).

### Not supported under static export

- Server Actions.
- Route Handlers used as runtime endpoints.
- Dynamic / SSR rendering per request.
- Incremental Static Regeneration (ISR) and on-demand revalidation.
- Middleware.
- `next/image` runtime optimization.

Every item in the "not supported" column is **already unused or already incompatible** in this codebase: 0 `getServerSideProps`, 0 `pages/api`, 0 `next/image`, `images.unoptimized: true`, and no middleware. So the App Router's headline benefits (RSC data fetching against a running server, streaming SSR, Server Actions) are precisely the features that `output: 'export'` removes, and that this app does not use anyway.

## 6. What this app would actually gain

Under the static-export + Capacitor constraint, the net functional gain from App Router is close to zero:

- The RSC / streaming SSR / Server Actions value proposition is unavailable under static export.
- The one data-fetching pattern in use (blog + shop `getStaticProps` / `getStaticPaths`) already produces static HTML; re-expressing it as build-time Server Components + `generateStaticParams` is a lateral move, not a capability gain.
- Nested layouts and the Metadata API are genuinely nicer ergonomics, but they are a refactor-quality improvement, not a new capability for an app that is a client SPA shell plus a static blog/shop.

## 7. Migration cost and risk

The cost side is substantial and concrete:

1. **Rewrite `_app.tsx` + `_document.tsx` into `app/layout.tsx`** (plus `template`/metadata). This includes re-homing the strict global-CSS cascade and the Amplify side-effect configuration.
2. **Re-home 57 page files** and the dynamic routes into the `app/` directory structure and its file conventions.
3. **Re-express 9 `getStaticProps` / 8 `getStaticPaths`** (blog + shop) as build-time Server Components plus `generateStaticParams`.
4. **Re-verify the `ssr: false` AuthShell hydration behaviour under App Router + Turbopack static export.** The current workaround exists because of a specific Turbopack pages-router manifest gap; there is no guarantee the App Router static export behaves the same way, and `/workspace/*` rendering blank is the known failure mode. This has to be re-measured in the exported HTML, not assumed.
5. **Re-wire GTM / Meta Pixel / the deploy-skew head script** with `next/script`, preserving Consent Mode v2 ordering and the skew-guard-first requirement.
6. **Re-validate Capacitor `out/` packaging** for both shells (`digital.wecare.stackcrm` and the env-driven public app id) against the regenerated export.

The risk is amplified by the codebase's current state (audit): thin test coverage (4 JS test files / 26 assertions per audit section 5e) and large files such as `src/api/client.ts` at ~7,800 lines. A migration touching `_app` / `_document`, routing, and hydration behaviour across 57 pages, backed by thin tests, is a high-blast-radius change with weak automated safety nets. The hydration workaround in particular is the kind of defect that ships silently (HTTP 200, no console error) and is only caught by measuring the exported HTML.

## 8. Is there a clean incremental path?

Next.js does allow `app/` and `pages/` to coexist, so in principle routes could be moved a few at a time. In practice the incremental path is costly here, and the reasons are specific:

- `_app.tsx` and `_document.tsx` are **shared** across all Pages routes. The global CSS cascade and the head/script machinery live there. A mixed `app/` + `pages/` tree means maintaining both the Pages `_app`/`_document` and the App Router `layout`/head wiring in parallel, with two places for global CSS and two places for GTM/consent to drift.
- The `ssr: false` AuthShell hydration workaround is specific to the Pages Router + Turbopack combination. Splitting the tree means validating hydration behaviour in two routing models at once.
- The blog/shop static-generation routes are the obvious first candidates to move (they are already build-time static), but they are also the lowest-value to move, since they already work.

So an incremental split is technically available but does not de-risk the expensive parts (shared shell, global CSS, hydration, head scripts); it mostly spreads them over more time while running two systems. That tradeoff is stated honestly: incremental is possible, but it is not cheap here.

## 9. Recommendation

**Defer. Do not migrate to the App Router now.**

Rationale, grounded in the evidence above:

- Under the hard `output: 'export'` + Capacitor constraint (`capacitor.config.ts` and `capacitor.public.config.ts` both `webDir: 'out'`), the App Router features that justify a migration (RSC data fetching, streaming SSR, Server Actions, ISR, middleware, image optimization) are all unavailable, and this app already uses none of them (0 `getServerSideProps`, 0 `pages/api`, 0 `next/image`).
- The only data-fetching in use (blog/shop `getStaticProps` / `getStaticPaths`) already produces static HTML; moving it to Server Components + `generateStaticParams` is lateral.
- The migration cost is high and the risk is concentrated in exactly the fragile areas: the `ssr: false` AuthShell hydration behaviour (a documented, silent-failure bug fix tied to Turbopack pages-router manifests), the strict GTM / Consent Mode / deploy-skew head-script ordering in `_document.tsx`, the global-CSS cascade in `_app.tsx`, and Capacitor `out/` packaging for two shells, all against thin test coverage and very large files.

This is a decision with a rationale, not a prohibition. Revisit the question only if **both** of the following become true: the product needs genuine runtime server rendering (SSR/RSC/Server Actions/ISR), **and** the Capacitor static-packaging model is dropped or changed so that a non-static output becomes acceptable. Until then, the App Router is high-cost and low-benefit for this specific application, and staying on the Pages Router is the sound engineering choice.
