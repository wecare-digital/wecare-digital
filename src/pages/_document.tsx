import { Html, Head, Main, NextScript } from 'next/document';

import { META } from '../config/analytics';

/**
 * Custom Document — Security meta tags + Google Tag Manager.
 *
 * NOTE: Content-Security-Policy should be configured at the hosting layer
 * (CloudFront response headers policy) rather than as a meta tag, since
 * this app uses output: 'export' (static site) and has many external
 * dependencies (Cognito, Razorpay, GA, Facebook SDK, etc.).
 *
 * GOOGLE TAGS — single-layer policy.
 * Google tracking on this property is delivered EXCLUSIVELY through the GTM
 * container below. Do not add a direct gtag.js / GA4 / Google Ads snippet
 * here or in any page: the container already fires GA4 (authoritative
 * Measurement ID G-6GW8JXKKT7) and Google Ads (AW-18396505964). Adding a
 * direct tag alongside the container double-counts every pageview and
 * conversion — which is the exact defect the old wecare.digital property had.
 * Which GA4 id the container fires is configured in Tag Manager (out of repo),
 * so updating it is a GTM-side action, not a code change here.
 *
 * Set NEXT_PUBLIC_GTM_ID to '' to disable all Google tracking at build time.
 */
const GTM_ID = process.env.NEXT_PUBLIC_GTM_ID ?? 'GTM-TXZ8JT78';

/**
 * GOOGLE TAG GATEWAY (first-party serving) — OPT-IN, OFF BY DEFAULT.
 *
 * When NEXT_PUBLIC_GTM_GATEWAY_PATH is set to a measurement path (e.g. '/y9dq'),
 * the container, the gtm.js loader, and the noscript iframe are served from that
 * SAME-ORIGIN path instead of www.googletagmanager.com. The hosting edge must
 * reverse-proxy that path to <container>.fps.goog, forwarding viewer geo headers
 * (set up outside this repo: an Amplify Console rewrite of /<path>/<*> ->
 * https://GTM-TXZ8JT78.fps.goog/<*>, or an owner-managed CloudFront behavior).
 *
 * UNSET (the default) keeps the proven third-party loader below byte-for-byte, so
 * a missing or broken gateway can never take tracking down. Flip it on only after
 * the path answers `ok` at https://wecare.digital/<path>/?validate_geo=healthy.
 *
 * Same-origin means no CSP change is needed: script-src/img-src/frame-src 'self'
 * in customHttp.yml already permits it.
 */
const GTM_GATEWAY_PATH = ( process.env.NEXT_PUBLIC_GTM_GATEWAY_PATH ?? '' ).replace( /\/+$/, '' );

/**
 * Google Consent Mode v2 defaults. Denied-by-default means GA4 and Ads send
 * only cookieless pings until consent is granted, so analytics never loads
 * ahead of a consent decision. Grant it by calling, from your consent UI:
 *
 *   gtag('consent', 'update', { analytics_storage: 'granted', ... })
 *
 * Override the default with NEXT_PUBLIC_ANALYTICS_CONSENT_DEFAULT=granted
 * only if you have established a lawful basis for doing so.
 */
const CONSENT_DEFAULT =
  process.env.NEXT_PUBLIC_ANALYTICS_CONSENT_DEFAULT === 'granted' ? 'granted' : 'denied';

const consentBootstrap = `
window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('consent', 'default', {
  ad_storage: '${CONSENT_DEFAULT}',
  ad_user_data: '${CONSENT_DEFAULT}',
  ad_personalization: '${CONSENT_DEFAULT}',
  analytics_storage: '${CONSENT_DEFAULT}',
  wait_for_update: 500
});
`.trim();

// When the gateway is on, src becomes '<path>?id=<container>&l=<layer>' on this origin;
// when off, it stays the canonical 'https://www.googletagmanager.com/gtm.js?id=<container>...'.
// The '?id=' prefix carries the container id to the gateway exactly as GTM's own loader does.
const GTM_SRC_BASE = GTM_GATEWAY_PATH
  ? `${GTM_GATEWAY_PATH}?id=`
  : 'https://www.googletagmanager.com/gtm.js?id=';

const gtmLoader = `
(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});
var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';
j.async=true;j.src='${GTM_SRC_BASE}'+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','${GTM_ID}');
`.trim();

/**
 * META PIXEL — the ONE browser Pixel on this property.
 *
 * Same argument as the GOOGLE TAGS note above: a second loader anywhere would
 * double-count every PageView, so the base code lives here and nowhere else. Do not add
 * an fbq snippet to a page or a component.
 *
 * It is NOT the Facebook JS SDK that _app.tsx loads. That one is FB.init with
 * NEXT_PUBLIC_FB_APP_ID, for social plugins, and it sends no pixel events — the two are
 * different assets with different ids and neither substitutes for the other.
 *
 * Only META.pixelId is interpolated. META.datasetId is the server-side Conversions API
 * destination and must never appear in browser code or be passed to fbq().
 *
 * Set NEXT_PUBLIC_META_PIXEL_ID to '' to disable the Pixel at build time.
 */
const pixelBootstrap = `
!function(f,b,e,v,n,t,s)
{if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};
if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];
s.parentNode.insertBefore(t,s)}(window,document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '${META.pixelId}');
fbq('track', 'PageView');
`.trim();

/**
 * dir IS DECLARED, not left to the user agent. SupportWidget rewrites it to "rtl" when a
 * visitor picks Arabic, Persian, Hebrew, Urdu, Pashto or Sindhi, and back to "ltr"
 * otherwise. Stating the default in the served HTML means the document says which direction
 * it is in rather than depending on a browser default - the same argument as declaring
 * color-scheme instead of letting a browser infer one. Asserted by rtlcheck.js, which reads
 * the exported index.html before any script has run.
 */
/**
 * DEPLOY-SKEW GUARD: one reload when the page's own build files fail to load.
 *
 * Every Amplify deploy replaces the whole export, so the previous build's /_next/static/ files
 * stop existing the moment it lands. A visitor whose HTML arrived just before that then asks
 * for files that are gone, the scripts fail, and the page stays un-hydrated: no menu, no
 * language panel, no checkout. This was caught live on 2026-10-26, when a deploy landed
 * mid-audit and both Chromium and WebKit refused the old _buildManifest.js. This branch
 * deploys many times an hour, so the window keeps reopening.
 *
 * Reloading fetches fresh HTML (the site is no-store) that names the new files. That is the
 * fix rather than Amplify's skew protection, which pins a browser to the deployment it first
 * loaded - the stale-after-deploy behaviour PR #1467 removed the cache layer to get rid of.
 *
 * BOUNDED FOUR WAYS, so it can never loop or cost anyone their work:
 *   - only files under this origin's /_next/static/ count; a third-party failure never reloads
 *   - only before the visitor's first interaction (pointer, key, touch, input or change, which
 *     also covers autofill): once anyone has started using the page, nothing reloads it, so no
 *     typed input can be thrown away
 *   - only until the window load event, which ends it even with no interaction at all
 *   - once per tab session (sessionStorage); a clean load clears the flag, and if storage is
 *     unavailable it does nothing at all
 * DOES THE RELOAD DOUBLE-COUNT A PAGE VIEW? Measured, not assumed, on 2026-10-26: 48 simulated
 * mid-deploy loads of the live home page across Chromium, WebKit and Firefox, cold and warm cache.
 * The first build file failed 290-610ms in, every time before either tracker had sent anything:
 * the Meta Pixel's PageView went out only after its library loaded, later than that, and GA4 sent
 * nothing at all on these loads. With this guard active, every tab recorded at most one Meta
 * PageView and never two. A duplicate would need the page view to beat a same-origin 404, which
 * did not happen once; no suppression code is warranted for it.
 * Resource errors do not bubble, so the listener is on the capture phase. This is the first
 * script in the head. Next's three stylesheet preload hints are emitted above it, but a fetch
 * fails asynchronously, after this inline script has run, and the stylesheet and script tags
 * those hints point at all come after it in the document anyway.
 */
const deploySkewGuard = `
(function(){
  var KEY='wc-build-reload',failed=false,used=false,base=location.origin+'/_next/static/';
  var INTERACT=['pointerdown','keydown','touchstart','input','change'];
  function onUse(){used=true;}
  function onError(e){
    var t=e.target,u=t&&(t.tagName==='SCRIPT'?t.src:(t.tagName==='LINK'?t.href:''));
    if(!u||u.indexOf(base)!==0)return;
    failed=true;
    if(used)return;
    try{if(sessionStorage.getItem(KEY))return;sessionStorage.setItem(KEY,'1');}catch(x){return;}
    location.reload();
  }
  window.addEventListener('error',onError,true);
  for(var i=0;i<INTERACT.length;i++)window.addEventListener(INTERACT[i],onUse,true);
  window.addEventListener('load',function(){
    window.removeEventListener('error',onError,true);
    for(var j=0;j<INTERACT.length;j++)window.removeEventListener(INTERACT[j],onUse,true);
    if(!failed){try{sessionStorage.removeItem(KEY);}catch(x){}}
  });
})();
`.trim();

export default function Document () {
  return (
    <Html lang="en" dir="ltr">
      <Head>
        {/* First script in the head, so it is listening before any build file can fail. */}
        <script dangerouslySetInnerHTML={ { __html: deploySkewGuard } } />
        <meta httpEquiv="X-Content-Type-Options" content="nosniff" />
        {/* THERE IS DELIBERATELY NO X-Frame-Options META TAG HERE. Browsers honour XFO
            only as an HTTP header and ignore the meta form entirely, so it provided zero
            clickjacking protection while logging "X-Frame-Options may only be set via an
            HTTP header" to the console on EVERY page load of the site. That error was
            measured on /, /grahak-os/, /vayulok/ and /contact/, and it was the single
            known failing assertion in the browser harness - a real error permanently
            occupying the channel that exists to surface real errors.
            The protection itself is not lost: amplify.yml sets the actual header
            (X-Frame-Options: SAMEORIGIN) under customHeaders for every path, and that is
            what ships, because the app is a static export and Next's own headers() never
            runs. Do not re-add this as a meta tag; to change the policy, edit amplify.yml.
            Note for future comments here: a JSX comment cannot contain a glob like the
            one in that customHeaders pattern, because the slash-star sequence closes the
            comment and the build fails with "Unterminated string constant". */}
        <meta name="referrer" content="strict-origin-when-cross-origin" />
        {/* Public product is intentionally light-only. Make that explicit so browsers and
            WebViews do not infer a dark control palette against the fixed light UI. */}
        <meta name="color-scheme" content="light" />
        {/* Inter font for better readability and modern look */ }
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
        <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400..600,0..1,0&display=block" rel="stylesheet" />
        { GTM_ID ? (
          <>
            {/* Consent Mode v2 must run BEFORE the container loads. */ }
            <script dangerouslySetInnerHTML={ { __html: consentBootstrap } } />
            {/* Preconnect only helps the third-party host; first-party serving is same-origin. */ }
            { GTM_GATEWAY_PATH ? null : (
              <link rel="preconnect" href="https://www.googletagmanager.com" />
            ) }
            <script dangerouslySetInnerHTML={ { __html: gtmLoader } } />
          </>
        ) : null }
        {/* After the GTM block on purpose, so Consent Mode still runs first. */ }
        { META.pixelId ? (
          <>
            <link rel="preconnect" href="https://connect.facebook.net" />
            <script dangerouslySetInnerHTML={ { __html: pixelBootstrap } } />
          </>
        ) : null }
      </Head>
      <body>
        { GTM_ID ? (
          <noscript
            dangerouslySetInnerHTML={ {
              __html:
                `<iframe src="${
                  GTM_GATEWAY_PATH
                    ? `${GTM_GATEWAY_PATH}/ns.html?id=${GTM_ID}`
                    : `https://www.googletagmanager.com/ns.html?id=${GTM_ID}`
                }"` +
                ` height="0" width="0" style="display:none;visibility:hidden"></iframe>`,
            } }
          />
        ) : null }
        { META.pixelId ? (
          <noscript
            dangerouslySetInnerHTML={ {
              __html:
                `<img height="1" width="1" style="display:none" alt=""` +
                ` src="https://www.facebook.com/tr?id=${META.pixelId}&ev=PageView&noscript=1" />`,
            } }
          />
        ) : null }
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
