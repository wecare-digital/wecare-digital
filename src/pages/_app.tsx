import { buildPageTitle } from '../lib/page-title';
﻿/**
 * WECARE.DIGITAL
 * Simplified auth - just wrap protected pages with Authenticator
 */

import type { AppProps } from 'next/app';
import Head from 'next/head';
import Script from 'next/script';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import { useState, useEffect } from 'react';
/* NO aws-amplify IMPORT IN THIS FILE (2026-10-27). Amplify.configure and the MFA vocabulary live in
   lib/amplifyConfig.ts, imported for its side effect by AuthShell, the API client and every direct
   Auth caller - see that file. Importing aws-amplify here is what put it on every public page. */
/* THE AUTHENTICATED SHELL IS LAZY, AND @aws-amplify/ui-react IS NO LONGER IMPORTED HERE.
   `Authenticator`, `ThemeProvider`, `Theme` and `useAuthenticator` used to be imported at
   this line, which put the library's 450 kB client chunk in the shared bundle and therefore
   on every public page. AuthShell owns them now; the file's header records the measurement.
   `ssr: false` IS MANDATORY HERE, AND IT IS A BUG FIX RATHER THAN AN OPTIMISATION.
   This line carried the default `ssr: true` from the split until 2026-10-05, on the reasoning
   that a static export renders SSR at build time so leaving it on costs nothing and keeps a
   sign-in shell in the HTML of 113 workspace pages. The reasoning was sound and the result was
   that https://wecare.digital/workspace/engage/ RENDERED BLANK, as did every other
   /workspace/* page. Measured in Chromium against the export, not inferred:

     out/workspace/engage/index.html   #__next children: [div[data-amplify-theme], style]
     after hydration                   #__next children: [div, style, div, style]

   TWO COPIES. The first is the build-time render, and its `.ag-centre` is EMPTY - at export
   time the Authenticator's state machine has not resolved, so it renders nothing, and the HTML
   holds header + an empty 592px centre + footer. The second is the live client render, carrying
   the real sign-in card, appended BELOW it at y=900 - off the bottom of a 900px viewport. So
   the first screen was header, blank, footer, with the working page just out of sight.

   WHY IT CANNOT HYDRATE. This builds with Turbopack (next.config.js sets `turbopack.root`), and
   a Turbopack pages-router build emits no `react-loadable-manifest.json`, so `__NEXT_DATA__`
   carries no `dynamicIds` - verified: the string is absent from every exported page. Next awaits
   exactly those ids in `__NEXT_PRELOADREADY` before calling `hydrateRoot`, so with none to await
   it hydrates while this chunk is still in flight. The first client render therefore produces
   null where the server HTML holds the whole Amplify subtree, hydration fails, and React
   recovers by client-rendering the boundary while leaving the server nodes in place. In a
   production build that failure is silent: no console error, no uncaught exception, HTTP 200,
   159 KB of HTML. Under `ssr: false` both sides render null on the first pass, they agree, and
   there is one tree with the card centred in the viewport.

   WHAT IS GIVEN UP, STATED PLAINLY: the 113 exported workspace pages now ship an empty
   `#__next`. That costs nothing measurable. They are `noindex, nofollow` (see the <Head> on the
   authenticated branch below), none of them functions without JavaScript, and the shell they
   used to ship was the half-render described above rather than a usable sign-in screen.
   DO NOT RESTORE `ssr: true` to put that HTML back - it is what blanked the page, and
   src/test/PublicBundleWeight.test.ts now fails the change.
   The perf win is untouched: the public branch still never renders this module, so no public
   page downloads the 450 kB chunk. `ssr: false` splits it at least as aggressively.
   `aws-amplify` itself used to stay a static import here, on the reasoning that the configuration
   must be in place before any route runs and that /get calls the API client. Both are still
   true and neither needs _app: the API client and AuthShell import lib/amplifyConfig.ts
   themselves, so whichever route needs Amplify configures it first, and /get does so through
   the client it already imports. */
const AuthShell = dynamic( () => import( '../components/AuthShell' ), { ssr: false } );
/* FloatingAgent is authenticated-only (it calls fetchAuthSession) and renders inside AuthShell,
   which is already client-only, so `ssr: false` changes nothing it renders. Statically imported,
   it kept aws-amplify/auth in the shared bundle of every public page. */
const FloatingAgent = dynamic( () => import( '../components/FloatingAgent' ), { ssr: false } );
/* `@aws-amplify/ui-react/styles.css` WAS IMPORTED HERE AND IS NOT ANY MORE.
   A global CSS import in the pages router is unconditional - it joins the `data-n-g` bundle
   on every route - and the built file is 310 kB minified, which made it the largest single
   asset on the home page, larger than any JavaScript chunk. Chrome's rule-usage tracker says
   a public page applies SEVEN of its rules; the rest styles Authenticator, Accordion,
   AIConversation and the other components that only exist behind the sign-in.
   Those seven are now `../styles/amplify-base.css`, imported first so it keeps the cascade
   position the Amplify sheet held. The component stylesheet is copied to
   `public/vendor/amplify-ui.css` by `scripts/generate-vendor-css.js` and linked from the
   authenticated branch's <Head> below - see AMPLIFY_UI_STYLESHEET. */
import '../styles/amplify-base.css';
import '../styles/Pages.css';
import '../styles/Layout.css';
import '../styles/Dashboard.css';
import '../styles/inner-pages.css';
import '../styles/inner-ux.css';
import '../styles/flex-layout.css';
import '../styles/button.css';
/* Authenticated Workspace normalization sits after every legacy dashboard/page layer so the
   no-sidebar shell can override dashboard-era framing and broad button rules in one place.
   It is scoped under .workspace-shell and therefore cannot affect public routes. */
import '../styles/workspace.css';
import '../styles/workspace-shell.css';
/* LAST, and that is the whole mechanism. form-controls.css is the one shared skin for the
   native controls, and it has to arrive after every rule in the 85-rule-set inventory above -
   including Layout.css's own @import of tokens.css and workspace.css - or a per-page select rule
   that ties it on specificity would win on source order. Nothing goes below this line. */
import '../styles/form-controls.css';
// Was LanguageBar. Renamed because it no longer only chooses a language: it is the single
// floating widget holding BOTH the WhatsApp contact button and the translate control. The
// external wecare-wa-widget.js that used to inject the WhatsApp button is retired with it.
import SupportWidget from '../components/SupportWidget';
import ErrorBoundary from '../components/ErrorBoundary';
import Header from '../components/Header';
import Footer from '../components/Footer';
import PublicShare from '../components/PublicShare';
import PublicToastProvider from '../components/public/PublicToastProvider';
import WorkspaceShell from '../components/WorkspaceShell';
import PublicPolicyDetails from '../components/public/PublicPolicyDetails';
import { ToastProvider } from '../contexts/ToastContext';
import { ConfirmProvider } from '../contexts/ConfirmContext';
import { VERIFICATION } from '../config/analytics';
import { ORGANIZATION, WEBSITE, ld } from '../lib/schema';

/* The MFA-chooser vocabulary and Amplify.configure moved to lib/amplifyConfig.ts, unchanged. */

/**
 * The Capacitor native shells, detected the way @capacitor/core detects them (androidBridge on
 * Android, the webkit `bridge` message handler on iOS), WITHOUT importing @capacitor/core. That
 * import, and the seven plugins lib/capacitor.ts pulls in with it, used to load on every web page
 * view only for initCapacitor to return immediately; now they load only inside a native shell.
 */
type NativeBridgeWindow = Window & {
  androidBridge?: unknown;
  webkit?: { messageHandlers?: { bridge?: unknown } };
  Capacitor?: { isNativePlatform?: () => boolean };
};
const isNativeShell = (): boolean => {
  const w = window as NativeBridgeWindow;
  return Boolean( w.androidBridge || w.webkit?.messageHandlers?.bridge || w.Capacitor?.isNativePlatform?.() );
};

/**
 * BRAND ASSETS, all from s3://wecare-digital-get/o/stream/media/m/ — served as
 * https://wecare.digital/get/o/stream/media/m/ via CloudFront E2GP22R4BIFGQ3. That is the
 * canonical media location since the wecare-digital-get merge (docs/media-bucket-merge.md).
 *
 * THERE ARE THREE ASSETS HERE, NOT ONE, AND THE SPLIT IS THE POINT.
 *
 * One file was doing all three jobs — `wecaredigital.png` — and it was the wrong file for two
 * of them. Measured from the live object rather than assumed:
 *
 *   wecaredigital.png    1080x1080  PNG colour-type 6 (RGBA)  68.4% FULLY TRANSPARENT
 *                        corner AND centre both rgba(0,0,0,0); the mark itself is black
 *   wecare-digital.png   1080x1080  RGBA but 0% transparent, white ground
 *   wd-brand-16x9.png    1440x810   PNG colour-type 2 (RGB) — no alpha channel at all
 *
 * WHY THE TRANSPARENT ONE WAS THE BUG. og:image and apple-touch-icon are both composited by
 * someone else's renderer, and neither guarantees a white backdrop: Apple has flattened
 * apple-touch-icon alpha to BLACK since iOS 7, and the social card renderers flatten to black
 * or to their own surface colour. A black mark on a flattened-black ground is an invisible
 * logo — so the shared-link preview and the iOS home-screen icon were plausibly rendering as
 * black squares. Nothing in the page could reveal that, because the asset is correct in
 * isolation and only wrong once something else flattens it.
 *
 * THE SHARE IMAGE IS THE OPAQUE SQUARE, AND THE CARD TYPE IS "summary" TO MATCH IT.
 * This reverses an earlier decision in this file, so the reasoning is worth keeping whole. The
 * wide wd-brand-16x9 card is the better-looking preview - mark, wordmark and the "Building
 * digital railroads for Everyday Bharat" line at 1.78:1 - and it was chosen here for exactly
 * that. What it is not is small: 801,077 bytes against the 600 KB that Meta's WhatsApp
 * link-preview documentation allows, with the practical limit nearer 300 KB because WhatsApp
 * discards an oversized image silently. So the good-looking card was not being rendered at all
 * on the platform that matters most here, and the repair is an S3 upload rather than a code
 * change. The icon is already live at 86,123 bytes and inside every stated limit.
 *
 * The pairing is the part to not break. A 1:1 image in a `summary_large_image` slot is
 * centre-cropped, which is what once cut the top and bottom off this mark; the tags also
 * declared 512x512 against a 1080x1080 file, so the size hint was wrong about the wrong asset.
 * Square image, `summary` card, width and height that match the object. Change any one of those
 * three and the other two stop being correct - which is why SHARE_CARD_TYPE lives beside the URL
 * in src/config/share.ts rather than being written into each head.
 *
 * LOGO_URL is the OPAQUE square, and now serves three slots rather than two: apple-touch-icon,
 * the schema.org Organization logo, and the link preview via SOCIAL_CARD_URL below.
 *
 * LOGO_SVG_URL IS LOAD-BEARING OUTSIDE THIS REPO — DO NOT REPOINT IT. The DNS record
 * `default._bimi.wecare.digital` carries `l=https://wecare.digital/get/o/stream/media/m/
 * wecare-digital.svg` under a `p=reject` DMARC policy. A BIMI record aimed at a missing logo
 * degrades silently rather than erroring, so a rename here breaks inbox branding with no
 * failure anywhere to notice. Change the DNS record first, verify, then this.
 */
const MEDIA_BASE = 'https://wecare.digital/get/o/stream/media/m';
/** 1080x1080, opaque white ground. Icons, structured data, AND the link preview. */
const LOGO_URL = `${MEDIA_BASE}/wecare-digital.png`;
const LOGO_SVG_URL = `${MEDIA_BASE}/wecare-digital.svg`;
const FAVICON_URL = `${MEDIA_BASE}/wecare-digital.ico`;
/* THE LINK PREVIEW IS THE ICON NOW, NOT THE WIDE CARD - on owner instruction, and the numbers back
   it up. wd-brand-16x9.png is 801,077 bytes against the 600 KB ceiling Meta documents for a
   WhatsApp preview, so WhatsApp was dropping the image on every page of a site whose business is
   WhatsApp, and repairing it needed an upload to S3 that this repo cannot perform. The icon is
   already live, already opaque, 86,123 bytes, 1080px wide against a 300px minimum and 1:1 against
   a 4:1 ceiling. Previews start working with nothing uploaded.
   THE COST IS STATED RATHER THAN HIDDEN: a square cannot be a full-width hero, so the preview is
   the compact thumbnail form and loses the "Building digital railroads for Everyday Bharat" line
   the designed card carried. A 273 KB re-export of that card sits at
   docs/brand/wd-brand-16x9.png if the wide preview is ever wanted back - one line here, plus the
   upload.
   THE CARD TYPE MOVED WITH THE SHAPE. twitter:card is "summary" below, because
   summary_large_image centre-crops anything that is not roughly 1.91:1 and would cut the top and
   bottom off this mark - the defect the link-preview test in BrandAssets.test.ts exists to catch.
   DECLARED AFTER LOGO_URL, not before it. These used to sit above it, and aliasing a const to one
   that is declared later is a temporal-dead-zone error at module evaluation, not a lint warning.
   These two values must equal the real pixels of the object at the URL; the pair once read
   512x512 against a 1080x1080 file. src/config/share.ts holds the same values for the content
   pages and ShareMeta.test.tsx holds the two copies equal. */
const SOCIAL_CARD_URL = LOGO_URL;
const SOCIAL_CARD_W = '1080';
const SOCIAL_CARD_H = '1080';
// Read but deliberately NOT used to inject a tag. GA4 is fired by the GTM container
// (see _document.tsx); a direct gtag.js snippet here double-counts. Kept so the env
// var stays documented and so anything that needs the id for a dataLayer push has it.
export const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID || '';

/**
 * `@aws-amplify/ui-react`'s component stylesheet, served as a file rather than bundled.
 *
 * Written by `scripts/generate-vendor-css.js` on every build, which is why the path is a
 * literal here and not an import: Next refuses a global CSS import from anywhere but this
 * file, so there is no way to scope one to a branch. A <link> is the export-mode equivalent.
 *
 * The URL carries no content hash on purpose. `public/` is copied verbatim into `out/`, and
 * an Amplify deploy invalidates the distribution, so a version bump reaches visitors without
 * one. A hash would mean a generated filename and a generated module to hold it.
 */
const AMPLIFY_UI_STYLESHEET = '/vendor/amplify-ui.css';

/* `authTheme` MOVED TO src/components/AuthShell.tsx, together with AuthGate and the
   Authenticator tree, and the move is a performance fix rather than tidying.
   `@aws-amplify/ui-react` builds to a 450 kB client chunk. Imported at the top of this file
   it sat in the shared bundle, so every visitor to every PUBLIC page downloaded it - 41% of
   the home page's 1,098 kB of JavaScript, for a sign-in card no marketing page renders.
   Measured in the export before the split: `2crp25xr6p9wh.js`, 450.7 kB, carrying
   amplify-authenticator, amplify-field and amplify-radio.
   This file has always had exactly two branches, so the dependency was shared only in the
   sense that an import is unconditional. AuthShell is loaded through next/dynamic below, with
   SSR left ON so the authenticated routes still export the same HTML. The Theme type import
   went with it. */

// Structured data for the organization
/**
 * THE COMPANY, IN ONE SENTENCE, DECLARED ONCE.
 *
 * This string was written out five times - three meta tags plus the Organization and WebSite
 * schema nodes - and the two schema copies had drifted to something else entirely:
 * "Enterprise WhatsApp Business API platform for multi-channel customer engagement", on 129
 * pages. The hero was deliberately rewritten AWAY from that framing: no channel names, no
 * platform language, "Everyday AI, built for consumers / enterprises / climate tech /
 * frontier tech". So the machine-readable description of the company contradicted the human
 * one on every page, and described a company the copy had stopped being.
 *
 * One constant means the next rewrite cannot leave half the site behind. It is deliberately
 * the same sentence the meta description uses, because a crawler reading both should not be
 * told two different things.
 */
const COMPANY_DESCRIPTION =
  'WECARE.DIGITAL builds everyday AI for consumers, enterprises, climate tech and frontier '
  + 'tech, with transparent pricing and one place to track everything.';

/**
 * MOVED TO src/lib/schema.ts, and the move is the fix rather than tidying.
 *
 * This node used to be defined here and emitted only from this file's <Head> - which is
 * rendered behind `!isContentPublic`, so it was ABSENT from all 1,279 posts and ~54 blog index
 * pages, roughly 98% of the indexable site. `post/[slug].tsx` and `BlogIndexHead.tsx` each
 * inlined their own anonymous `publisher` because of that, giving one company three
 * representations, two of them blank nodes.
 *
 * lib/schema.ts now owns it and all three surfaces emit the same object, so `#organization` is
 * defined on every public URL and `publisher: { '@id': ... }` resolves everywhere. The node
 * also gained the full PostalAddress and telephone that this site's own legal pages already
 * publish, and an ImageObject logo with dimensions.
 */
const organizationSchema = ORGANIZATION;

// THE SITEWIDE SoftwareApplication IS DELETED, 2026-10-25. It was emitted on every public route
// except /grahak-os/ and described "WECARE.DIGITAL" as an "Enterprise multi-channel messaging CRM
// platform" - Grahak OS's positioning - on /terms, /privacy, the puja kit, the home page and every
// other route whose visible content is not that software. It also asserted a `softwareVersion`
// of "1.0.0" and the logo as its `screenshot`, neither of which is true. Structured data must
// describe the page it is on (.kiro/steering/00-common.md), and the one page this software IS
// about already declares its own, accurate SoftwareApplication (src/pages/grahak-os/index.tsx).
// Its earlier removals - an invented aggregateRating and a price-0 Offer - are in git history.

// Structured data for the website
/** MOVED TO src/lib/schema.ts - see the note on organizationSchema above. Its `publisher` is
 *  an @id reference now; it used to restate a second anonymous Organization in the same file
 *  that defined the real one. SearchAction is still deliberately absent. */
const websiteSchema = WEBSITE;

// FAQ Schema for AI and search engines
// faqSchema DELETED, not commented out.
//
// It was defined here and emitted nowhere - removed from the <Head> when Google stopped
// showing FAQ rich results on 2026-05-07, and because it was being emitted on /terms,
// /privacy, /contact and /vayulok, none of which contain an FAQ. Marking up content that is
// not on the page is a guidelines violation rather than merely useless markup.
//
// A dead constant one line away from a <script> tag is a loaded gun: re-adding a single
// emission line restores four invented WhatsApp questions to a privacy policy. Deleted so
// that re-introducing it requires writing the content again, deliberately.

// Service Schema
const serviceSchema = {
  "@context": "https://schema.org",
  "@type": "Service",
  "@id": "https://wecare.digital/#service",
  // `name` was missing. It is a required property on Service, and without it the
  // entity describes a serviceType with nothing to call it - a validator reports it and
  // Google has no label to attach.
  "name": "WECARE.DIGITAL customer engagement services",
  "serviceType": "WhatsApp Business API Platform",
  // Reference, not a restatement: the full Organization is declared once with this
  // @id, so repeating its properties here is what creates conflicting copies.
  "provider": { "@id": "https://wecare.digital/#organization" },
  "areaServed": {
    "@type": "Country",
    "name": "India"
  },
  "hasOfferCatalog": {
    "@type": "OfferCatalog",
    "name": "Messaging Services",
    "itemListElement": [
      {
        "@type": "Offer",
        "itemOffered": {
          "@type": "Service",
          "name": "WhatsApp Business API"
        }
      },
      {
        "@type": "Offer",
        "itemOffered": {
          "@type": "Service",
          "name": "Bulk SMS"
        }
      },
      {
        "@type": "Offer",
        "itemOffered": {
          "@type": "Service",
          "name": "Email Marketing"
        }
      },
      {
        "@type": "Offer",
        "itemOffered": {
          "@type": "Service",
          "name": "Voice Calls"
        }
      }
    ]
  }
};

/**
 * Per-route WebPage/Service graph for public pages.
 *
 * NO `breadcrumb` PROPERTY, and no BreadcrumbList. Public pages render no visible trail
 * (components/Breadcrumbs.tsx returns null since the October 2026 hero/content flow), so the
 * WebPage used to point at a `#breadcrumb` node that no page defined - 32 dangling references,
 * failed by tools/audit/schemacheck.js. Re-add both only together with a rendered trail.
 *
 * Why this exists: every public page was emitting the same five site-level entities
 * and nothing that identified the page itself, so Google had no per-URL description of
 * the site's hierarchy.
 *
 * Deliberately NOT a sitelinks search box - see the note on websiteSchema. Google
 * removed that feature in November 2024.
 *
 * /contact uses ContactPage, which is the correct schema.org type for it. The rest are
 * WebPage. Anything not listed falls back to a bare WebPage with no breadcrumb, which
 * is correct for the home page: a breadcrumb whose only entry is the page you are on
 * says nothing.
 */
/**
 * `serviceType` IS OPTIONAL AND ITS ABSENCE IS A STATEMENT.
 *
 * Every entry here already produces a WebPage, and a WebPage says "this URL exists" without
 * saying what it is ABOUT. Where the page describes something the business actually offers, the
 * entry names it and getPublicPageSchema emits a schema.org Service alongside, with the WebPage
 * pointing at it through mainEntity. That is the difference between a crawler knowing we have a
 * page called Dastavez and knowing Dastavez is business documentation offered in India by this
 * organisation.
 *
 * IT IS NOT SET ON THE REQUESTS PAGES, deliberately. /submit-request, /drop-docs, /vault,
 * /request-pickup and /request-amendment are ways to
 * interact with us, not
 * services we sell - "Leave Review" is not an offering, and typing it as a Service to get a
 * richer graph would be describing the site we wish we had. Nor on /terms, /privacy, /contact
 * or /orders, which are page kinds rather than products.
 *
 * There is no rich result for Service, so this buys entity understanding rather than a search
 * appearance. That is the honest expectation to set: Google's structured-data guidance treats
 * Service as a supported type for describing an offering, and nothing here should be read as
 * promising a carousel.
 */
const PUBLIC_PAGE_META: Record<string, {
  name: string; type: string; description: string; serviceType?: string;
}> = {
  '/grahak-os': { name: 'Grahak OS', type: 'WebPage', description: 'Customer engagement across WhatsApp, SMS, Email and Voice.', serviceType: 'Customer engagement platform' },
  '/vayulok': { name: 'VayuLok', type: 'WebPage', description: 'Bharat air and weather insights.', serviceType: 'Air quality and weather insights' },
  '/contact': { name: 'Contact', type: 'ContactPage', description: 'Submit, amend or track a request, drop documents, or leave a review.' },
  '/terms': { name: 'Terms', type: 'WebPage', description: 'Terms of service.' },
  '/privacy': { name: 'Privacy', type: 'WebPage', description: 'How WECARE.DIGITAL handles your data.' },
  '/orders': { name: 'Orders', type: 'WebPage', description: 'Check the status of an order, delivery, request or booking.' },
  // Sehat is an appointment-booking service. Keep structured data limited to that scope.
  '/sehat': { name: 'Sehat', type: 'WebPage', description: 'Appointments with qualified professionals.', serviceType: 'Appointment booking' },
  // Product pages. Elsewhere is a category-only menu family, so there is deliberately no
  // Elsewhere is a non-clickable family label; its three child pages are registered directly.
  // Descriptions are shorter than the pages' own meta descriptions on purpose: this feeds
  // WebPage.description in the schema graph, while ProductPage.tsx owns the search-result copy.
  '/elsewhere/visa': { name: 'Visa', type: 'WebPage', description: 'Visa document preparation, application readiness and tracking.', serviceType: 'Visa application assistance' },
  '/elsewhere/trip': { name: 'Trip', type: 'WebPage', description: 'Travel planning and coordination around the people taking the trip.', serviceType: 'Travel planning and coordination' },
  '/elsewhere/activities': { name: 'Activities', type: 'WebPage', description: 'Travel activities selected around place, timing and itinerary.', serviceType: 'Travel activity planning' },
  '/expo-week': { name: 'Expo Week', type: 'WebPage', description: 'A virtual travel fair and immersive digital expo.', serviceType: 'Virtual travel fair and digital expo' },
  '/dastavez/drafting': { name: 'Drafting', type: 'WebPage', description: 'Structured business document preparation from the facts you provide.', serviceType: 'Business document drafting' },
  '/dastavez/registration': { name: 'Registration', type: 'WebPage', description: 'Registration paperwork and filing steps organised end to end.', serviceType: 'Business registration support' },
  '/dastavez/legal-reference': { name: 'Legal Reference', type: 'WebPage', description: 'Laws, judgments, rules and public source material organised around a question.', serviceType: 'Legal reference research' },
  '/ritual-guru/ritva': { name: 'Ritva', type: 'WebPage', description: 'Personal astrology and Vastu guidance built around your questions, timing and space.', serviceType: 'Personal astrology and Vastu guidance' },
  '/ritual-guru/puja-guidance': { name: 'Puja Guidance', type: 'WebPage', description: 'Step-by-step practical guidance for a puja you are performing yourself.', serviceType: 'Self-led puja guidance' },
  '/ritual-guru/diy-puja-kit': { name: 'DIY Puja Kit', type: 'WebPage', description: 'Clearly labelled puja essentials with a preparation checklist.', serviceType: 'DIY puja kit supply' },
  // Renamed twice: '[retired public path]' -> '[retired public path]' -> '/anew'. The route moved with the
  // brand name each time; neither earlier address was ever published, so there is nothing
  // to redirect from.
  '/anew': { name: 'Anew', type: 'WebPage', description: 'Reflection-led conversations that create clarity and action.', serviceType: 'Reflective conversation and coaching' },
  // Hunar is now a non-clickable family label. Kaushal owns skills/learning; Prastuti owns
  // CV/profile/pitch presentation. Hunar is a non-clickable family label.
  '/hunar/kaushal': { name: 'Kaushal', type: 'WebPage', description: 'A focused skills and learning path built around what you want to do next.', serviceType: 'Skills learning and development support' },
  '/hunar/prastuti': { name: 'Prastuti', type: 'WebPage', description: 'CV, professional profile and pitch deck creation built from real experience.', serviceType: 'CV, professional profile and pitch deck creation' },
  '/niji-setu': { name: 'Niji Setu', type: 'WebPage', description: 'A QR code people scan to reach you on a masked call.', serviceType: 'Number masking and call connection' },
  // Request and tracking actions live inside /orders/; their retired public
  // landing pages remain absent. /vault/?file= remains an owner-checked handoff.
  // THE CATALOGUE INDEX IS RESTORED, 2026-10-10, on owner instruction: /shop/ is browsable again,
  // so this key is back in the map (which is both the public allowlist and the structured-data
  // source - without it the page renders the staff sign-in shell at HTTP 200). It is coupled to
  // the '/shop' entry in PUBLIC_EXACT in scripts/generate-sitemap.js and the STRUCTURAL entry in
  // scripts/generate-public-pages.js by src/test/PublicRouteRegistration.test.ts, so the three
  // move together. src/pages/shop/index.tsx is restored to emit out/shop/index.html.
  //
  // THE SEVEN PRODUCT PAGES stay in the isContentPublic chain as '/shop/[slug]', NOT here: this
  // map is keyed on router.pathname, so a dynamic route keyed here would compute every URL from
  // the literal '[slug]'. Only the index front door belongs in this map. '/shop/page/[page]' is
  // in that chain for the same reason.
  //
  // THE DESCRIPTION WAS REWORDED when the listing widened from the eight catalogue rows to
  // every product and service the site sells: most cards now link to /<slug>/ rather than to
  // /shop/<slug>/, so "Individual products live under /shop/<slug>/" had become inaccurate. The
  // same sentence is carried by the STRUCTURAL fallback in scripts/generate-public-pages.js and by
  // the generated config/public-pages.json, and src/test/PublicAiSurface.test.ts compares the
  // catalogue to this literal - so rewording it means re-running
  // `node scripts/generate-public-pages.js`. Keep the single-quoted `name:` then `description:`
  // shape: renderAllowlist() in that generator and allRoutes() in StructuredDataService.test.ts
  // both parse this block as text and both require literals.
  '/shop': { name: 'Shop', type: 'WebPage', description: 'Every WECARE.DIGITAL product and service on one page, each linking to its own page.' },
  // Shipments is a non-clickable family label; Track and Pickup Request
  // are customer actions, not separate public pages.
};

/** Public redirect changes use scripts/provision_legacy_redirects.py and its ratified list.
 * Fetch live rules and plan before applying; static route refactors must preserve that ruleset.
 */
const SITE = 'https://wecare.digital';

const getPublicPageSchema = ( pathname: string ) => {
  const meta = PUBLIC_PAGE_META[ pathname ];
  if ( !meta ) {
    /**
     * THE FALLBACK IS PER-ROUTE NOW. It used to hardcode `@id: ${SITE}/#webpage` and
     * `url: ${SITE}/` for every route missing from PUBLIC_PAGE_META - and more than one route
     * qualifies: `/` (correctly), plus `/get`, which is public but deliberately not
     * marketing. So they shipped the SAME @id claiming to be the home page at the home
     * page's URL, which is a cross-route entity collision: two URLs defining one node with
     * different content is exactly the conflicting-copy case Google's guidance is about.
     *
     * seocheck.js could not see it. Its @id-clash check is per-route - it looks for the same
     * @id twice within one page - so a collision ACROSS routes was invisible to it, and /get
     * is not in its ROUTES list anyway.
     *
     * The home page still resolves to `${SITE}/#webpage` and `${SITE}/`, because pathname
     * is '/' there, so its markup is unchanged. Only /get moves, onto its own identity.
     * Still no breadcrumb: a trail whose only entry is the page you are on says nothing,
     * which is the original and correct reasoning for this branch existing.
     *
     * see the note on the isPublic chain below.
     */
    const url = pathname === '/' ? `${SITE}/` : `${SITE}${pathname}/`;
    return {
      '@context': 'https://schema.org',
      '@type': 'WebPage',
      '@id': `${url}#webpage`,
      url,
      name: 'WECARE.DIGITAL',
      isPartOf: { '@id': `${SITE}/#website` },
      inLanguage: 'en-IN',
    };
  }
  // trailingSlash is set, so the canonical URL carries the slash. Breadcrumb items
  // must match the canonical or they describe a URL that redirects.
  const url = `${SITE}${pathname}/`;
  /**
   * The Service node, only where PUBLIC_PAGE_META names a serviceType - see the note there for
   * which routes do and, more importantly, which deliberately do not.
   *
   * `provider` REFERENCES the Organization by @id rather than restating it. A second inline copy
   * of the company's name, logo and address per page would be eleven more places for it to drift
   * from the one in websiteSchema, and Google resolves @id references within the same page.
   *
   * name and description are the SAME STRINGS the WebPage uses, on purpose: they come from one
   * entry, so the page's own description and the Service's cannot disagree. The eleven
   * serviceType values are the only new prose, and each is close to the description beside it.
   *
   * areaServed is India, which is where the service is offered - not where a service might take
   * you. Elsewhere arranges travel abroad and is still offered to people in India.
   */
  const service = meta.serviceType ? {
    '@type': 'Service',
    '@id': `${url}#service`,
    name: meta.name,
    description: meta.description,
    serviceType: meta.serviceType,
    provider: { '@id': `${SITE}/#organization` },
    areaServed: { '@type': 'Country', name: 'India' },
    url,
  } : null;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': meta.type,
        '@id': `${url}#webpage`,
        url,
        name: meta.name,
        description: meta.description,
        isPartOf: { '@id': `${SITE}/#website` },
        inLanguage: 'en-IN',
        // Spread, not a conditional property set to undefined: JSON.stringify would drop an
        // undefined value anyway, but an explicit absent key keeps the emitted graph identical
        // to what it was on the routes that have no Service.
        ...( service ? { mainEntity: { '@id': `${url}#service` } } : {} ),
      },
      // Filtered rather than conditionally spread into the array, so the routes with no
      // serviceType emit only the WebPage node.
      ...( service ? [ service ] : [] ),
    ],
  };
};

/* `AuthGate` MOVED TO src/components/AuthShell.tsx. See the note where authTheme used to be
   declared, above: it uses `useAuthenticator`, so leaving it here would have kept
   @aws-amplify/ui-react in the shared bundle and defeated the split.
   Its documentation - why the sign-in screen is the third place site chrome is mounted, why
   SupportWidget belongs on it, why .ag-shell pads 108px rather than 96px, and why the
   Amplify ThemeProvider's hardcoded dir="ltr" had to be overridden - travelled with the code
   and is unchanged there. src/test/PublicWidgets.test.tsx now counts the three SupportWidget
   mounts across both files. */

// /vault/?file= is an authenticated exact-file handoff, never a public marketing page.
// Bare /vault/ navigates Home. All other former standalone request/tracking
// pages were retired; their old paths fall through to 404 and then Home.
const CUSTOMER_SERVICE_ROUTES = new Set( [
  '/vault',
] );

export default function App ( { Component, pageProps }: AppProps ) {
  const router = useRouter();


  // EXACT-MATCH allowlist. A public page missing from this list renders an empty
  // body with HTTP 200 — a 404 that does not look like one — so every new public
  // route has to be added here as well as created under src/pages.
  // Blog and post pages own their own <head> via SEO.tsx, so the sitewide Head below is
  // suppressed for them - that is stack's arrangement and it is kept.
  // '/blog/page/[page]' is pages 2..N of the paginated index. It MUST be here: the blog was
  // one 834-post document until it was split, and a missing entry would serve 34 empty
  // bodies at HTTP 200 while the sitemap advertised every one of them. It belongs in this
  // check rather than in PUBLIC_PAGE_META because, like /blog and /post/[slug], it declares
  // its own <head> and structured data - see components/BlogIndexHead.tsx.
  // '/blog/topic/[topic]' is one prerendered stream per non-default category. It MUST be here:
  // the default category is served at /blog/, so these are the only index pages that list their
  // own posts, and a missing entry would serve them as empty bodies at HTTP 200.
  const isContentPublic = router.pathname === '/blog'
    || router.pathname === '/blog/page/[page]'
    || router.pathname === '/blog/topic/[topic]'
    // The category streams paginate now - see src/pages/blog/topic/[topic]/page/[page].tsx.
    // Without this line every page but the first of every stream renders an empty body at
    // HTTP 200, which is the "404 that does not look like one" the note below describes.
    || router.pathname === '/blog/topic/[topic]/page/[page]'
    || router.pathname === '/post/[slug]'
    // The seven catalogue pages. They belong in THIS chain and not in PUBLIC_PAGE_META for the
    // same reason /post/[slug] does: the map is keyed on router.pathname, which for a dynamic
    // route is the pattern '/shop/[slug]', so the canonical, og:url, twitter:url and the WebPage
    // node's @id would all be computed from a literal '[slug]'. Being here suppresses the sitewide
    // Head below and makes components/ShopProductHead.tsx responsible for the whole of it -
    // including the Organization and WebSite entities, which otherwise would not exist on the page
    // for its Product.brand and Offer.seller references to resolve against.
    || router.pathname === '/shop/[slug]'
    // Pages 2..N of the catalogue listing - see src/pages/shop/page/[page].tsx. It belongs in
    // THIS chain and not in PUBLIC_PAGE_META for the same reason /shop/[slug] and
    // /blog/page/[page] do: the map is keyed on router.pathname, which here is the pattern
    // '/shop/page/[page]', so the canonical, og:url and the WebPage node's @id would all be
    // computed from a literal '[page]'. Being here suppresses the sitewide Head below and makes
    // components/ShopListingHead.tsx responsible for the whole of it.
    // WITHOUT THIS LINE every page but the first renders an empty body at HTTP 200 - a 404 that
    // does not look like one, with a 200 in the sitemap and a 200 in every uptime check.
    || router.pathname === '/shop/page/[page]';
  // [retired public path] and /partners are deliberately ABSENT. stack still lists them because this
  // branch's removal has not landed there yet; both pages were deleted on owner
  // instruction and re-adding the routes here would render blank 200s for them.
  // PUBLIC_PAGE_META is the single list of public marketing routes now. The seven new product
  // pages made the old inline chain of ORs unreadable and, worse, made it possible to add a
  // page to the menu and the sitemap while forgetting this one - which renders an empty body
  // with HTTP 200 and is invisible until someone loads the route. Deriving the allowlist from
  // the metadata map means a product cannot exist for structured data but not for rendering.
  // Bare /get is retired; the generic not-found rule sends it Home.
  // /get/<*> remains the necessary CloudFront media namespace.
  // '/contact-test' WAS LISTED HERE AND HAD TO COME OFF. It was the only route that was
  // both in this allowlist AND wrapped in the authenticated <Layout> by its own page file,
  // and the combination leaked the dashboard into public HTML: because the export is
  // prerendered with no session, Layout rendered in full, so
  // https://wecare.digital/contact-test/ returned HTTP 200 carrying the entire staff
  // sidebar - Inbox, Contacts, Broadcast, Payments, Service Ops, Store, Forms, Tasks - the
  // page search box and the BottomNav, to anyone who asked. Verified live before removal;
  //
  // It was also a duplicate: /contact is the real public contact page, and this one's form
  // resolved a setTimeout and threw the message away. De-listed rather than deleted so the
  // removal is one reversible line; PublicRouteRegistration.test.ts now fails any public
  // route that imports Layout, so this shape cannot return.
  // '/404' IS PUBLIC, and it has to be listed here rather than in PUBLIC_PAGE_META.
  // Header, Footer and SupportWidget are mounted once, below, inside `if ( isPublic )` - so
  // a page receives the three common pieces by being on this list and by no other means.
  //
  // THERE IS NO 404 PAGE: src/pages/404.tsx redirects to the home page. The file exists
  // because deleting it does not remove a 404 page, it restores Next's built-in one - 6.8KB
  // reading "404 This page could not be found", with no header, no footer, no widget and
  // ZERO links, which is what shipped before. Amplify's terminal `/<*>` -> `/404.html` rule at
  // `404-200` serves this page, with a real HTTP 404, for every mistyped path, and the page then
  // sends the visitor home. It also covers a direct request for /404/.
  //
  // NOT in PUBLIC_PAGE_META, because entries there acquire WebPage structured data and a
  // sitemap entry, and advertising a redirect stub to a crawler is the opposite of the
  // intent. The page sets its own robots noindex and canonicals to the destination.
  // The machine-readable AI surfaces are documented by MCP and the generated discovery
  // files; there is no separate public HTML documentation route to keep in sync.
  const isPublic = router.pathname === '/'
    || router.pathname === '/404'
    // Checkout, legacy cart handoff and customer OTP sign-in are customer-session surfaces: public chrome,
    // robots:noindex per page, and deliberately OUT of PUBLIC_PAGE_META, the sitemap and AI manifest.
    // /auth is a real Next page now. Only its state/step endpoints are rewritten to the auth API,
    // so it receives the exact same Header/search/cart, PublicShare, Footer and SupportWidget as
    // every other public route instead of carrying a copied backend shell.
    || router.pathname === '/auth'
    || router.pathname === '/cart'
    || router.pathname === '/checkout'
    // Checkout status + success are customer-session screens, not marketing pages: they carry the
    // public chrome (header/footer/support widget) but are deliberately kept OUT of
    // PUBLIC_PAGE_META so they are not treated as indexable marketing surfaces. Each page sets
    // robots:noindex itself. They render for a signed-in customer returning from an in-chat
    // payment; the per-route fallback WebPage schema above is the correct, minimal markup for them.
    || router.pathname === '/checkout/status'
    || router.pathname === '/checkout/success'
    || CUSTOMER_SERVICE_ROUTES.has( router.pathname )
    || Object.prototype.hasOwnProperty.call( PUBLIC_PAGE_META, router.pathname )
    || isContentPublic;

  // trailingSlash is set in next.config.js, so the canonical form of every route except
  // the root carries a trailing slash. A canonical pointing at the slashless URL names
  // a location that 308-redirects, which is a contradictory signal.
  const canonicalUrl = router.pathname === '/'
    ? `${SITE}/`
    : `${SITE}${router.pathname}/`;
  // NO showPublicWhatsApp FLAG ANY MORE. It gated a <Script> tag that injected the
  // external wecare-wa-widget.js, and that script is retired: the WhatsApp button is now
  // the left half of the SupportWidget component, which this file renders in the public branch
  // below - so the branch itself is the gate and a separate boolean would be a second
  // source of truth for the same question. A new public page picks the widget up by
  // being public, exactly as it picks up the header and footer.

  /**
   * A MISTYPED ADDRESS LANDS ON THE HOME PAGE, and the address bar says so.
   *
   * CURRENT RULE (2026-10-26): `/<*>` -> `/404.html` at `404-200`, so a mistyped path renders
   * src/pages/404.tsx, which redirects home itself. This effect only matters if a rule ever
   * serves index.html for a non-root path again, which is what the history below describes.
   *
   * Amplify's last custom rule was `/<*>` -> `/index.html` with status `404-200`. Despite
   * the name that is NOT "rewrite to 200" — the CDK enum calls it `NOT_FOUND_REWRITE`,
   * "Not found rewrite (404)". Measured on the live site: an unknown path returns HTTP
   * 404 with a body byte-identical to `/index.html`.
   *
   * Because the exported `index.html` carries `"page":"/"`, Next hydrates it as the home
   * route, so `router.pathname` is already `/` and the real home page renders. The only
   * thing left wrong is the address bar, which still shows whatever was typed. This
   * corrects it.
   *
   * WHY NOT DO IT AT THE CDN. A `200`/`301`/`302` rule on `/<*>` matches unconditionally
   * rather than only after the file lookup misses, so it would shadow all ~123 exported
   * pages and serve the home page for the whole site. Only the 404-family statuses are
   * conditional. The status therefore stays 404, which is also the honest answer: a URL
   * that was never published should not report 200, or anyone can mint unlimited
   * indexable addresses on the domain and Google records it as a soft 404.
   *
   * replaceState, not router.replace: this is a cosmetic correction of an address that
   * was never a route, so it must not add a history entry (Back would re-enter the typo)
   * and must not re-run the router. Guarded on the PATH ONLY, so `/?utm_source=x` and
   * `/#pricing` on the real home page are left alone.
   */
  useEffect( () => {
    if ( router.pathname !== '/' ) return;
    const typedPath = router.asPath.split( '?' )[ 0 ].split( '#' )[ 0 ];
    if ( typedPath === '/' || typedPath === '' ) return;
    const suffix = router.asPath.slice( typedPath.length );
    window.history.replaceState( window.history.state, '', '/' + suffix );
  }, [ router.pathname, router.asPath ] );

  useEffect( () => {

    // The web Service Worker/cache layer has been removed. Clean up any worker/cache
    // left behind in returning browsers without touching Cognito/OTP auth storage.
    if ( 'serviceWorker' in navigator )
    {
      navigator.serviceWorker.getRegistrations()
        .then( ( regs ) => Promise.all( regs.map( ( r ) => r.unregister() ) ) )
        .catch( () => { } );
    }
    if ( window.caches )
    {
      caches.keys()
        .then( ( keys ) => Promise.all( keys.map( ( k ) => caches.delete( k ) ) ) )
        .catch( () => { } );
    }
    // Init Capacitor native plugins - inside a native shell only, and loaded on demand there. On
    // the web nothing below runs and none of the plugin code is downloaded (see isNativeShell).
    // onPushToken arms push registration (SNS endpoint via POST /push/register); the API client it
    // needs is imported only when a token actually arrives, so it never joins the shared bundle.
    if ( !isNativeShell() ) return;
    const statusBarBackground = isPublic ? '#ffffff' : '#1a3a2a';
    void ( async () => {
      const { initCapacitor } = await import( '../lib/capacitor' );
      await initCapacitor( {
        push: ( p ) => router.push( p ),
        back: () => router.back(),
        onPushToken: ( token, platform ) => {
          void ( async () => {
            const { registerPushToken } = await import( '../lib/pushRegistration' );
            await registerPushToken( token, platform );
          } )();
        },
        // Public app shell is white with dark status icons; internal Stack CRM keeps its
        // established green Android status bar through initCapacitor's default.
        statusBarBackground,
      } );
    } )();
  }, [] );

  // NO client-mount gate here, deliberately.
  //
  // This used to be `if ( !mounted ) return null;`, which ran BEFORE the branches below
  // and therefore before their <Head>. The cost was total: every statically exported page
  // shipped an empty body AND an empty head - /grahak-os/index.html was 3,299 bytes with
  // no title, no description, no og tags, no canonical and no JSON-LD. Crawlers that do
  // not execute JS saw an untitled blank page, link previews had nothing to read, and any
  // webview where the bundle failed showed white.
  //
  // It guarded nothing specific: `mounted` was set in one effect and read in one place,
  // with no client-only value in the render path. The window.dataLayer and
  // window.fbAsyncInit references below are inside inline <script> strings, so they are
  // never evaluated during render and cannot cause a mismatch.
  //
  // If a hydration warning does surface, fix the element that causes it rather than
  // restoring this. Grammarly injecting attributes into <body> is the known one, and
  // suppressHydrationWarning on that element is the targeted answer - blanking the
  // document is not.

  // Redirect-only and private handoff routes must never render public chrome,
  // translations, sharing controls or a loading waypoint while navigating.
  // /404 and /cart render Head only. /vault displays its actual file content
  // only after an owner-scoped verification, or silently navigates Home.
  if ( router.pathname === '/404' || router.pathname === '/cart'
    || router.pathname === '/vault' )
  {
    return (
      <ErrorBoundary>
        <Component { ...pageProps } />
      </ErrorBoundary>
    );
  }

  // Public page
  if ( isPublic )
  {
    return (
      <ErrorBoundary>
        <PublicToastProvider>
        {/* THE ICON IS OUTSIDE THE `!isContentPublic` GATE BELOW, DELIBERATELY.
            These two tags used to sit inside that gate, and the gate itself is correct: /blog,
            its three paginated variants and /post/[slug] declare their own title, description,
            canonical and structured data - components/BlogIndexHead.tsx and the <Head> in
            pages/post/[slug].tsx - so inheriting the block below would give them two of each.
            The favicon was never part of that argument. It was collateral, and the cost was that
            all five content routes shipped NO icon at all.
            NOTHING DOWNSTREAM PUT IT BACK, which is why this went unnoticed: neither replacement
            head declares an icon, _document.tsx declares none either, and the implicit
            /favicon.ico fallback could not cover it, because Amplify's `/<*>` -> `/index.html`
            404-200 rule answers that request with 33KB of home-page HTML instead of an image.
            Measured on the live site before this change: / carried the icon tag, /blog/ and
            /post/<slug>/ carried none, and /favicon.ico returned 404 text/html.
            RENDERED HERE RATHER THAN IN _document.tsx - the obvious sitewide home - because
            MEDIA_BASE and the URLs derived from it are module-private to this file, and
            src/test/BrandAssets.test.ts pins those declarations to this file by source string.
            Reaching them from the document would mean importing this module into _document or
            restating MEDIA_BASE there, and a second source of truth for the brand asset base is
            the exact thing that test exists to prevent. Every public route passes through this
            branch, so the coverage is the same; the authenticated branch keeps its own pair.
            The keys are placed after href so the attribute order BrandAssets.test.ts matches on
            is preserved. next/head dedupes by key, so a page that wants a different icon
            overrides this one instead of appending a second. */}
        <Head>
          <link rel="icon" href={ FAVICON_URL } key="icon" />
          <link rel="apple-touch-icon" href={ LOGO_URL } key="apple-touch-icon" />
          {/* THE VIEWPORT, THEME COLOUR AND MANIFEST ARE OUT OF THE GATE TOO, for the favicon's
              reason. They describe the device shell, not the page's identity, and none of the
              replacement heads (BlogIndexHead, ShopListingHead, ShopProductHead, the post Head)
              declares them - so the 1,516 blog, post and shop-detail pages shipped Next's bare
              `width=device-width`, with no viewport-fit=cover, and env(safe-area-inset-*)
              resolved to 0 under every notch and home indicator on those routes. Measured on
              the export 2026-10-25. viewport-fit=cover opts the page into the full display on
              notched/cutout phones and foldables; the value is the one the steering file fixes.
              NO key ON THESE METAS, on purpose: next/head skips its name-based de-duplication
              for a keyed name-meta, so a key here would sit BESIDE the unkeyed viewport and
              theme-color /grahak-os/ declares instead of yielding to them. Unkeyed, the page's
              copy wins and Next's own default viewport is dropped by name. */}
          <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
          <meta name="theme-color" content="#ffffff" />
          <meta name="apple-mobile-web-app-capable" content="yes" />
          <meta name="apple-mobile-web-app-status-bar-style" content="default" />
          <meta name="mobile-web-app-capable" content="yes" />
          <link rel="manifest" href="/manifest.json" key="manifest" />
        </Head>
        { !isContentPublic && (
          <Head>
          {/* PRODUCT-NEUTRAL SITEWIDE TITLE. This read "WECARE.DIGITAL - WhatsApp Business
              API Platform | Multi-Channel Messaging CRM India" - 86 characters, of which
              Google shows about 60, and every word after the brand described a single
              product. It was the <title> for all 15 public routes, so the company home page
              was titled as a WhatsApp CRM. Kept short enough to survive truncation and
              worded to match the og/twitter/description copy below. */}
          <title>{ buildPageTitle( router.pathname === '/shop' ? 'Shop' : 'Everyday AI, built for Bharat' ) }</title>
          {/* THE INTER LINKS LIVE IN _document.tsx ONLY. They were declared here as well,
              and _document.tsx renders on every route, so the built head carried the Inter
              stylesheet TWICE - two render-blocking requests for one font - plus duplicate
              preconnects to fonts.googleapis.com and fonts.gstatic.com. Counted in
              out/grahak-os/index.html before this change: rel=stylesheet x2, preconnect
              googleapis x2, preconnect gstatic x2.
              next/head de-duplicates by `key`, not by href, and these had no key, so
              nothing was going to collapse them. _document.tsx is the right owner because
              the font is sitewide and unconditional, whereas this block is one branch of a
              route test - keeping a copy per branch is how the duplication happened.
              seocheck.js did not catch it: its "exactly one of each head tag" assertion
              covers the nine og/twitter/canonical/title/description tags, not <link>. */}
          {/* SITEWIDE FALLBACK, AND IT MUST STAY PRODUCT-NEUTRAL.
              This block is inherited by every public route that does not declare its own, so
              whatever it says becomes the identity of 15 pages. It used to read "Enterprise
              WhatsApp Business API platform for India..." with 22 WhatsApp keywords - copy
              written for ONE product - so the company home page was indexed as a WhatsApp
              product page and competed with /grahak-os/ for the same terms.
              /grahak-os/ is unaffected by this change: it already declares its own title,
              description and OG tags, so its WhatsApp positioning is stated where it belongs
              rather than leaking sitewide.
              NO meta keywords, anywhere on the public site. Google Search does not use the tag
              and the steering file says not to add it; it was deleted here and on /grahak-os/
              on 2026-10-25 rather than kept as a harmless leftover. */}
          <meta name="description" content={ COMPANY_DESCRIPTION } />
          {/* THE ICON PAIR, THE VIEWPORT, THE THEME COLOUR AND THE MANIFEST THAT USED TO BE HERE
              ARE NOW ABOVE, OUTSIDE THE GATE - see the notes at the top of this branch. */}
          {/* CANONICAL AND og:url ARE COMPUTED, and carry a key.
              Both were hardcoded to the site root, on every page. The result was that
              /contact/, /terms/, /privacy/, /grahak-os/ and /vayulok/ each shipped TWO
              canonical tags - this root one first, then the page's own correct one -
              which is ambiguous, and the most likely reading is that every page is a
              duplicate of the homepage. That alone would keep those URLs from ranking,
              and sitelinks with them.
              key="canonical" is what makes this safe to keep here: next/head dedupes by
              key and a page's Head is processed after _app's, so a page that sets its
              own canonical overrides this one instead of adding a second. Routes that
              set none now inherit a correct value rather than pointing at the root. */}
          <link rel="canonical" key="canonical" href={ canonicalUrl } />

          {/* Search Console / Bing Webmaster ownership.
              Rendered only when the env value is set. An empty content="" tag is worse
              than no tag: verification fails either way, but an empty one looks
              configured and stops anyone looking for the cause.
              Note the Bing property is registered as https://wecare.digital/, which
              301s to the apex this site now serves from, so the property may need
              re-pointing at https://wecare.digital/. */}
          { VERIFICATION.google && (
            <meta name="google-site-verification" content={ VERIFICATION.google } />
          ) }
          { VERIFICATION.bing && (
            <meta name="msvalidate.01" content={ VERIFICATION.bing } />
          ) }

          {/* Open Graph.
              EVERY og: TAG CARRIES A key, AND THAT IS LOAD-BEARING - not tidiness.
              next/head only de-duplicates meta by `name`, `httpEquiv`, `charSet` and
              `itemProp`. `property` is NOT in that list, so two og:title tags coexist
              happily where two twitter:title tags collapse to one. Measured on the built
              export, /grahak-os/index.html shipped TWO of every single og tag - type, url,
              title, description, image, site_name, locale - because that page declares its
              own set and nothing merged them. A link preview then reads whichever it meets
              first, which was this sitewide block, so the product page previewed with the
              sitewide copy.
              An explicit key is the documented escape hatch, but it only works when BOTH
              sides use the SAME key: og:url already had key="og:url" here and still
              duplicated, because /grahak-os/ declared its og:url without one. The keys
              below are therefore mirrored in src/pages/grahak-os/index.tsx, and any future
              page that declares og tags must use these same keys or it will double them
              again. Verify with:
                grep -o '"og:title"' out/grahak-os/index.html | wc -l   # must be 1 */}
          <meta property="og:type" key="og:type" content="website" />
          <meta property="og:url" key="og:url" content={ canonicalUrl } />
          {/* PRODUCT-NEUTRAL, for the same reason the description above is.
              These read "WECARE.DIGITAL - WhatsApp Business API Platform | WECARE.DIGITAL"
              and "Enterprise WhatsApp Business API platform. Send bulk messages, payments &
              automate customer engagement with AI." That is one product's copy, and because
              this block is inherited by every public route it was the share preview for all
              15 of them - including the company home page, which is not a WhatsApp product
              page. It also printed the brand name TWICE in a single og:title.
              The wording now mirrors the neutral description already agreed above, so the
              title, description, og and twitter tags finally describe the same company.
              /grahak-os/ keeps its WhatsApp positioning in its own Head, which is where a
              product claim belongs. */}
          <meta property="og:title" key="og:title" content="Everyday AI, built for Bharat | WECARE.DIGITAL" />
          <meta property="og:description" key="og:description" content={ COMPANY_DESCRIPTION } />
          {/* The branded 16:9 card, not the square mark. The dimensions are the FILE's, read
              off the object — they said 512x512 while the asset was 1080x1080, so the hint was
              wrong even before the asset changed. Crawlers use it to reserve layout before the
              image arrives, so a wrong one is worse than none. */}
          <meta property="og:image" key="og:image" content={ SOCIAL_CARD_URL } />
          <meta property="og:image:width" key="og:image:width" content={ SOCIAL_CARD_W } />
          <meta property="og:image:height" key="og:image:height" content={ SOCIAL_CARD_H } />
          <meta property="og:image:type" key="og:image:type" content="image/png" />
          {/* Alt text on the card, because a link preview is content a screen reader meets. */}
          <meta property="og:image:alt" key="og:image:alt" content="WECARE.DIGITAL — building digital railroads for Everyday Bharat" />
          <meta property="og:site_name" key="og:site_name" content="WECARE.DIGITAL" />
          <meta property="og:locale" key="og:locale" content="en_IN" />

          {/* Twitter. These need no key - next/head dedupes on `name`, which is why only
              the og: block above was doubling. twitter:url was hardcoded to the site root
              on every page, the same defect already fixed on canonical and og:url; it is
              computed now so a shared link resolves to the page that was shared. */ }
          {/* "summary", not summary_large_image: the image is the 1:1 icon and a large card
              centre-crops anything that is not roughly 1.91:1. See the docblock at the top. */}
          <meta name="twitter:card" content="summary" />
          <meta name="twitter:url" content={ canonicalUrl } />
          <meta name="twitter:title" content="Everyday AI, built for Bharat | WECARE.DIGITAL" />
          <meta name="twitter:description" content={ COMPANY_DESCRIPTION } />
          <meta name="twitter:image" content={ SOCIAL_CARD_URL } />
          <meta name="twitter:image:alt" content="WECARE.DIGITAL — building digital railroads for Everyday Bharat" />

          {/* SEO */ }
          {/* `robots` is keyed by name, so a noindex page's own robots meta replaces this one. A
              separate `googlebot` meta used to sit here saying "index, follow"; next/head dedupes
              that name independently, so it SURVIVED on /cart, /checkout, /get and the other
              noindex pages and contradicted their own directive. Google applies the most
              restrictive rule, so it was never harmful, only noise; robots alone says it. */}
          <meta name="robots" content={ CUSTOMER_SERVICE_ROUTES.has( router.pathname )
            ? 'noindex, nofollow'
            : 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1' } />
          <meta name="author" content="WECARE.DIGITAL" />
          <meta name="publisher" content="WECARE.DIGITAL" />
          <meta name="language" content="English" />
          <meta name="geo.region" content="IN" />
          <meta name="geo.placename" content="India" />

          {/* Structured Data.
              SITE-LEVEL ENTITIES ONLY, emitted once. Google's structured data
              guidelines require the markup to represent the page's actual content, and
              a page must not carry two conflicting copies of the same entity.

              faqSchema is GONE from here. Two reasons, either of which is sufficient:
              Google stopped showing FAQ rich results on 2026-05-07 and is dropping the
              search appearance and Rich Results Test support, so it earns nothing; and
              it was emitted on EVERY public page, including /terms, /privacy, /contact
              and /vayulok, none of which contain an FAQ. Marking up content that is not
              on the page is a guidelines violation, not merely useless.

              A per-route WebPage (plus a Service where the page describes one) is added
              below instead. There is no BreadcrumbList: public pages render no visible
              trail (components/Breadcrumbs.tsx returns null), and a trail in the markup
              that the reader cannot see is exactly what the steering file forbids. */}
          <script type="application/ld+json" dangerouslySetInnerHTML={ { __html: JSON.stringify( organizationSchema ) } } />
          {/* No SoftwareApplication here any more - see the note where softwareSchema was
              declared. /grahak-os/ declares its own, which is the one page it describes. */}
          <script type="application/ld+json" dangerouslySetInnerHTML={ { __html: JSON.stringify( websiteSchema ) } } />
          {/* serviceSchema IS SCOPED TO /grahak-os, as the deleted sitewide
              SoftwareApplication should have been. It declares serviceType "WhatsApp Business
              API Platform" and a hasOfferCatalog of WhatsApp / Bulk SMS / Email Marketing
              / Voice Calls - one product's offering - and it was being emitted on all 15
              public routes, so /terms, /privacy, /contact, /orders and the company home
              page each told Google they offer a WhatsApp messaging catalog.
              That is the same leak already fixed on description, keywords, title and the
              og block, and here it is also a guidelines problem rather than just wasted
              markup: Google requires structured data to represent the page's actual
              content, which a messaging offer catalog does not do on a privacy policy.
              On /grahak-os the entity is accurate, so the value needs no rewording - only
              the scope was wrong. */}
          { router.pathname === '/grahak-os' && (
            <script type="application/ld+json" dangerouslySetInnerHTML={ { __html: JSON.stringify( serviceSchema ) } } />
          ) }
          <script type="application/ld+json" dangerouslySetInnerHTML={ { __html: JSON.stringify( getPublicPageSchema( router.pathname ) ) } } />
        </Head>
        ) }
        {/* NO DIRECT gtag.js HERE - BY POLICY, and it was being violated.
            _document.tsx states that all Google tracking on this property is delivered
            exclusively through the GTM container, which fires GA4 (authoritative
            Measurement ID G-6GW8JXKKT7) and Google Ads (AW-18396505964), and that
            adding a direct snippet alongside it double-counts every pageview and
            conversion.
            This file was doing exactly that. Measured in a browser at the time, the
            home page requested gtag/js FOUR times: G-S3G6REP6Q7 bare from the snippet
            that used to be here, plus AW-18396505964, the container's then-served GA4
            id G-GNRPFFBXMF, and G-S3G6REP6Q7 again from the container. So G-S3G6REP6Q7
            was loaded twice on every page view.
            The snippet is injected client-side by next/script, so it never appeared in
            the static HTML and could not be found by grepping the export - only a
            request log shows it. tagcheck.js now asserts the container loads once and
            no direct gtag.js accompanies it. */}
        {/* PUBLIC MOBILE TYPOGRAPHY GUARD.
            Public-only: authenticated Workspace typography stays unchanged. On narrow phones,
            the canonical public display rungs scale fluidly instead of forcing fixed 40/32/24px
            sizes into smaller effective viewports. Balanced wrapping prevents short headings
            from leaving orphan words. Headings and body copy remain selectable: long-press
            selection is native browser behavior and must not be disabled sitewide.
            THE HERO FLOOR FITS THE WIDTH BELOW 262px, AND ONLY THERE. A fixed 34px floor
            clipped the hero at 200% zoom on a phone (a 160-215px layout): "enterprises" lost
            50px at 180px and "climate tech" lost 81px at 160px. The floor is now the smaller of
            34px and the content width divided by 6.75. Home's longest pill, "frontier tech"
            with its dot and padding, measures 6.5em in Chromium and WebKit, so 6.75 leaves a
            quarter-em of air. From 262px up the floor is still 34px, so every real device,
            the 280px Galaxy Fold included, renders exactly as before; only a zoomed layout
            narrower than that shrinks the heading rather than cutting text. Measured
            2026-10-26. */}
        <style jsx global>{`
          @media(max-width:767px){
            :root{
              --public-mobile-hero-size:clamp(min(34px,calc((100vw - 2 * var(--public-mobile-page-gutter)) / 6.75)),9.75vw,40px);
              --public-mobile-section-size:clamp(28px,7.75vw,32px);
              --public-mobile-card-size:clamp(22px,5.8vw,24px);
            }
            h1,h2,h3{text-wrap:balance}
          }
        `}</style>
        <Header />
        <Component { ...pageProps } />
        <PublicPolicyDetails />
        <div className="public-action-tail">
          <PublicShare />
        </div>
        <Footer />
        <style jsx>{`
          .public-action-tail{
            width:100%;
            max-width:var(--public-content-max);
            margin:0 auto;
            padding:0 var(--public-page-gutter) 48px;
            box-sizing:border-box;
            font-family:var(--font-sans);
            color:var(--public-text);
            /* CONTAIN THE SHARED RAIL. PublicShare renders a fixed-width icon row whose
               children (the share trigger and its nowrap hover tooltip) carry an intrinsic
               width that, at 200 percent zoom on a 320 device (layout viewport near 160 CSS
               px), set a page-level min-width floor and gave the document about 18px of
               horizontal scroll. min-width:0 stops this wrapper from passing that intrinsic
               floor up to the page, and overflow-x:clip lets the rail (and the tooltip that
               pops off its trigger) overflow THIS box instead of widening the document.
               overflow-x:hidden is declared first as the pre-clip fallback; clip wins where
               supported and, unlike hidden, never creates a scroll container. */
            min-width:0;
            overflow-x:hidden;
            overflow-x:clip;
          }
          @media(max-width:767px){
            .public-action-tail{padding-inline:16px;padding-bottom:40px}
          }
        `}</style>
        {/* WhatsApp contact + page translation. This comment used to read "translation +
            read-aloud, public pages only, and deliberately not on the authenticated
            dashboard" and both halves are now wrong, which is why it is rewritten rather
            than trimmed: read-aloud was removed (Amazon Polly has no voice for Tamil,
            Telugu, Bengali or most other Indic languages, so the button was hidden for
            nearly every language this serves), and the widget IS on the dashboard now -
            see the mount in the authenticated branch below for the one attribute that
            makes that safe. Three mounts total, all in this file: here, AuthGate, and the
            authenticated branch. PublicWidgets.test.tsx counts them. */}
        <SupportWidget />
        </PublicToastProvider>
      </ErrorBoundary>
    );
  }

  // Protected pages
  return (
    <ErrorBoundary>
      <Head>
        <title>WECARE.DIGITAL</title>
        {/* THE AMPLIFY UI COMPONENT STYLESHEET, AND THIS IS THE ONLY BRANCH THAT LOADS IT.
            It used to be a global import at the top of this file, which the pages router
            puts on every route: 310 kB on a marketing page for a sign-in card it never
            renders. Chrome's rule-usage tracker measured seven applied rules on `/`, and
            those seven are now `src/styles/amplify-base.css`.
            POSITION MATTERS AND next/head GIVES US THE RIGHT ONE. As an import the sheet was
            FIRST in the cascade, so `src/styles/*.css` overrode it - the five
            `.amplify-button--primary` rules in `inner-ux.css` need to win that tie. In the
            exported head, `data-next-head` tags precede the `data-n-g` bundle links, so this
            stays ahead of our stylesheets exactly as the import was.
            The file is written by `scripts/generate-vendor-css.js` during `npm run build`;
            it is gitignored so it cannot drift from the installed package. */}
        <link rel="stylesheet" href={ AMPLIFY_UI_STYLESHEET } key="amplify-ui-css" />
        {/* Inter comes from _document.tsx, which renders on every route. See the note on the
            public branch above: declaring it here too put the stylesheet in the built head
            twice, render-blocking both times. */}
        <meta name="description" content="Stack CRM Dashboard - Multi-channel messaging platform" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <link rel="icon" href={ FAVICON_URL } />
        <link rel="apple-touch-icon" href={ LOGO_URL } />
        <meta name="robots" content="noindex, nofollow" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="theme-color" content="#1a3a2a" />
        {/* The Workspace's OWN manifest. /manifest.json is the public site's identity
            (WECARE.DIGITAL, white theme) now that every public page links it; installing from
            here should still give the team app its own name, colour and /workspace/ start. */}
        <link rel="manifest" href="/manifest-workspace.json" />
        {/* No BreadcrumbList here any more: it was derived from the pathname rather than from
            the trail on screen, on pages that are noindex and robots-Disallowed anyway. */}
        <script type="application/ld+json" dangerouslySetInnerHTML={ { __html: JSON.stringify( organizationSchema ) } } />
      </Head>
        {/* NO DIRECT gtag.js HERE - BY POLICY, and it was being violated.
            _document.tsx states that all Google tracking on this property is delivered
            exclusively through the GTM container, which fires GA4 (authoritative
            Measurement ID G-6GW8JXKKT7) and Google Ads (AW-18396505964), and that
            adding a direct snippet alongside it double-counts every pageview and
            conversion.
            This file was doing exactly that. Measured in a browser at the time, the
            home page requested gtag/js FOUR times: G-S3G6REP6Q7 bare from the snippet
            that used to be here, plus AW-18396505964, the container's then-served GA4
            id G-GNRPFFBXMF, and G-S3G6REP6Q7 again from the container. So G-S3G6REP6Q7
            was loaded twice on every page view.
            The snippet is injected client-side by next/script, so it never appeared in
            the static HTML and could not be found by grepping the export - only a
            request log shows it. tagcheck.js now asserts the container loads once and
            no direct gtag.js accompanies it. */}
      {/* Facebook SDK for JavaScript */ }
      <Script id="facebook-sdk-init" strategy="afterInteractive">
        { `
          window.fbAsyncInit = function() {
            FB.init({
              appId: '${process.env.NEXT_PUBLIC_FB_APP_ID || ''}',
              cookie: true,
              xfbml: true,
              version: 'v25.0'
            });
            FB.AppEvents.logPageView();
          };
        `}
      </Script>
      <Script src="https://connect.facebook.net/en_US/sdk.js" strategy="afterInteractive" id="facebook-jssdk" />
      {/* The Amplify UI tree - ThemeProvider, Authenticator.Provider, AuthGate and the
          Authenticator itself - now lives in AuthShell and arrives as a dynamic chunk. The
          render function below is unchanged: the page, its signOut wiring and the two widget
          mounts stay here, because this file is where every other route decision is made. */}
      <AuthShell>
        { ( { signOut, user } ) => {
          if ( typeof window !== 'undefined' && ( window as any ).FB )
          {
            ( window as any ).FB.AppEvents.logEvent( 'CompletedRegistration' );
          }
          const handleSignOut = () => { signOut?.(); void router.push( '/' ); };
          const routedPage = (
            <Component { ...pageProps } signOut={ handleSignOut } user={ user as any } />
          );
          const authenticatedPage = router.pathname.startsWith( '/workspace' )
            ? (
              <WorkspaceShell user={ user as any } onSignOut={ handleSignOut }>
                { routedPage }
              </WorkspaceShell>
            )
            : routedPage;

          return (
            <ToastProvider>
              <ConfirmProvider>
                { authenticatedPage }
                <FloatingAgent />
                {/* THE SAME COMBINED WIDGET AS THE PUBLIC PAGES, so contact and
                    language are in one place on every route in the product rather
                    than only on the marketing side.
                    IT IS SAFE HERE BECAUSE OF ONE ATTRIBUTE. SupportWidget starts
                    its translation walk at `.layout`, and Layout.tsx marks
                    `.main-content` with data-wc-no-translate - so the sidebar's
                    navigation translates while every page's CONTENT (customer
                    names, numbers, message bodies) is exempt. Without that
                    attribute this mount would let an operator machine-translate
                    live customer data, which is why it was previously excluded.
                    FloatingAgent above is a different thing and stays: it is the
                    internal AI task assistant, not customer contact. */}
                <SupportWidget />
              </ConfirmProvider>
            </ToastProvider>
          );
        } }
      </AuthShell>
    </ErrorBoundary>
  );
}
