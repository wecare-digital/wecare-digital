/**
 * Grahak OS public product page
 * Customer engagement platform by WECARE.DIGITAL
 */

import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import PageMeta from '../../components/PageMeta';
import PublicShare from '../../components/PublicShare';
import ProductBuyBox from '../../components/ProductBuyBox';
import PolicyDetails from '../../components/public/PolicyDetails';
import RotatingHero from '../../components/RotatingHero';
import { productPolicyCopy } from '../../content/productCommerce';
import { productCheckoutLine } from '../../config/productCheckout';

const GRAHAK_POLICY = productPolicyCopy( 'grahak-os', 'Grahak OS' );
const GRAHAK_REFUNDS = 'Cancellation may not be available once work has started. Eligible approved cancellations or adjustments are issued as WECARE.DIGITAL store credit valid for 30 calendar days. We do not issue cash or original-payment-method refunds unless applicable law requires otherwise.';
const GRAHAK_CHECKOUT = productCheckoutLine( 'grahak-os' );
const GRAHAK_DISPLAY_PRICE = GRAHAK_CHECKOUT?.formattedPrice.replace( /\.00$/, '' ) ?? null;
const GRAHAK_SKU = GRAHAK_CHECKOUT?.variantId ?? null;

const GrahakOsPage: React.FC = () => {
  const [visible, setVisible] = useState<Set<string>>(new Set());
  // False until the reveal effect below has confirmed it can run. While false, .anim
  // sections carry no .is-armed and the CSS shows them in their finished state.
  const [armed, setArmed] = useState(false);
  const [activeCode, setActiveCode] = useState(0);

  // Hero headline cycles the channel in the lime pill, the way notion.com
  // rotates the highlighted verb. Width is measured so the pill resizes
  // smoothly instead of snapping between "WhatsApp" and "SMS".
  // Each channel carries its own pill tint AND a matching dot, mirroring the
  // notion.com treatment measured from their hero: the pill is a pale tint and
  // the leading dot is a saturated version of the same hue, both swapping with
  // the word (e.g. pill rgb(230,243,254) with dot rgb(9,127,232)).
  const cycleWords = [
    { word: 'WhatsApp', tint: '#e0f7c8', dot: '#3da35a' },
    { word: 'SMS', tint: '#dbeafe', dot: '#2563eb' },
    { word: 'Email', tint: '#fef3c7', dot: '#f0a818' },
    { word: 'Voice', tint: '#ede9fe', dot: '#9849e8' },
  ];
  // The rotation, the width re-measure and all the pill CSS now live in RotatingPill.
  // This page keeps only the entrance machinery (armed + show('hero')) that drives the
  // shared pill's one-shot reveal via its `phase` prop.

  // ARM ONLY AFTER CONFIRMING WE CAN ANIMATE, AND SEED WHATEVER IS ALREADY ON SCREEN.
  //
  // Two things have to happen in ONE render here, or the no-JS fix trades a blank page
  // for a flash. Arming hides every .anim section; the observer then reveals them. If
  // those land in separate commits, anything already in the viewport paints
  // visible -> hidden -> animated-in, which is a more obvious artefact than the bug was.
  //
  // So the sections currently intersecting the viewport are measured synchronously and
  // seeded into `visible` in the same batch that sets `armed`. React batches both
  // setState calls inside this effect, so the first armed paint already carries .show on
  // the hero and nothing above the fold ever blinks.
  //
  // The viewport test is deliberately more generous than the observer's 0.1 threshold:
  // any intersection at all counts. A section 5% visible at load therefore appears
  // without animating, which is the right trade against a flash.
  //
  // If IntersectionObserver is missing - or this effect never runs at all, which is the
  // no-JS and failed-hydration case - `armed` stays false and the CSS resting state is
  // the finished one. That is the capability check; there is no user-agent sniffing here.
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;

    const sections = Array.from(document.querySelectorAll<HTMLElement>('.anim'));
    const onScreenNow = sections
      .filter((el) => {
        const r = el.getBoundingClientRect();
        return r.top < window.innerHeight && r.bottom > 0;
      })
      .map((el) => el.id);

    setVisible((p) => new Set([...p, ...onScreenNow]));
    setArmed(true);

    const obs = new IntersectionObserver(
      (entries) => entries.forEach((e) => {
        if (e.isIntersecting) setVisible((p) => new Set([...p, e.target.id]));
      }),
      { threshold: 0.1 }
    );
    sections.forEach((el) => obs.observe(el));

    // SAFETY NET so a section can never stay stuck at opacity:0. Arming hides every
    // .anim section and the observer is then meant to reveal each one as it scrolls
    // into view - but on the built export the observer's reveal was not firing for the
    // sections below the fold, so the whole page below the hero rendered blank while the
    // text was still in the DOM (which is why the no-JS body-text count stayed green and
    // the bug went unseen). This timer reveals anything still hidden a short time after
    // arming, so a visitor always ends on the finished state. It does not disable the
    // scroll animation: sections the observer DOES catch animate normally; this only
    // backstops the ones it misses. 1200ms is long enough for a genuine on-scroll reveal
    // to win first and short enough that a stuck section is never visibly blank.
    const failsafe = window.setTimeout(() => {
      setVisible((p) => new Set([...p, ...sections.map((el) => el.id)]));
    }, 1200);

    return () => { obs.disconnect(); window.clearTimeout(failsafe); };
  }, []);

  const show = (id: string) => visible.has(id);

  // Six outcome-led touchpoint pills. Each keeps the hue previously associated with its
  // concrete example, drawn from the HOMEPAGE's deliberate 4-subject palette
  // (amber/purple/green/red), the homepage blue border and this page's brand lime.
  // No invented colours. Each hue is now a thin COLOURED BORDER on a WHITE background -
  // the earlier filled tint fills were dropped on owner instruction. The pill TEXT stays
  // dark (rgba(0,0,0,.898) / #1a3a2a) on white, so every pill clears WCAG AA - amber
  // (#f0a818, 2.04:1) and green (#3da35a, 3.19:1) are UNSAFE as text and are used only as
  // borders. `hue` maps to a .pp-pill--<hue> modifier class whose CSS lives beside .pp-pill.
  const useCases = [
    { title: 'Acquire', example: 'Promotional', hue: 'amber' },
    { title: 'Notify', example: 'Transactional', hue: 'blue' },
    { title: 'Verify', example: 'OTPs', hue: 'purple' },
    { title: 'Support', example: 'Appointments', hue: 'green' },
    { title: 'Transact', example: 'Orders', hue: 'red' },
    { title: 'Retain', example: 'Surveys', hue: 'lime' },
  ];

  // These are real calls, checked against docs/openapi.yaml and the handler rather
  // than written to look plausible. All three used to POST /v1/messages, which does
  // not exist: the spec has no /v1 prefix at all, its server is
  // https://wecare.digital/api, and /messages is GET-only for reading a paginated
  // list. The hero panel was worse - /v1/send exists nowhere in the spec.
  //
  // The documented way to send is POST /outbound-whatsapp ("Send outbound WhatsApp
  // message (text, template, media)"). The handler validates
  // "contactId or recipientPhone is required" and takes the body text as `content`,
  // so `to` and `message` were both wrong field names on top of the wrong path.
  // Auth is securitySchemes: type http, scheme bearer, bearerFormat JWT - a Cognito
  // access token, which is why Bearer is correct here.
  //
  // Keep these in step with the hero .code-body sample: same endpoint, same fields.
  const codeExamples = [
    { lang: 'Python', code: `import requests

response = requests.post(
  "https://wecare.digital/api/outbound-whatsapp",
  headers={
    "Authorization": f"Bearer {access_token}"
  },
  json={
    "recipientPhone": "+919330994400",
    "content": "Your order #WD-87A6G has been shipped"
  }
)` },
    { lang: 'JavaScript', code: `const response = await fetch(
  "https://wecare.digital/api/outbound-whatsapp",
  {
    method: "POST",
    headers: {
      "Authorization": \`Bearer \${accessToken}\`
    },
    body: JSON.stringify({
      recipientPhone: "+919330994400",
      content: "Your order #WD-87A6G has been shipped"
    })
  }
);` },
    { lang: 'cURL', code: `curl -X POST \\
  "https://wecare.digital/api/outbound-whatsapp" \\
  -H "Authorization: Bearer $ACCESS_TOKEN" \\
  -d '{"recipientPhone": "+919330994400",
       "content": "Your order #WD-87A6G has been shipped"}'` },
  ];

  return (
    <>
      {/* TITLE, DESCRIPTION, CANONICAL AND THE SHARE PREVIEW ALL COME FROM ONE PAIR OF
          STRINGS NOW. Measured on the built export, this page previously carried THREE
          different titles and THREE different descriptions simultaneously:
            title                "Grahak OS by WECARE.DIGITAL - Customer Engagement Platform"
            og:title             "Grahak OS - Customer Engagement Platform | WECARE.DIGITAL"
            twitter:title        "Grahak OS - Customer Engagement Platform"
            description          "Grahak OS is the customer engagement product in ..."
            og:description       "Enterprise WhatsApp Business API platform. Send bulk ..."
            twitter:description  "Enterprise WhatsApp Business API platform. Multi-channel ..."
          Nothing chose between them - whichever a crawler or unfurler read first won, so
          the same page described itself three ways depending on where the link was pasted.
          The pair kept below is the page's own <title> and <meta description>, which are the
          best-written of the six and which preserve this page's WhatsApp/SMS/Email/Voice
          positioning. The og: and twitter: copy that mentioned "Enterprise WhatsApp Business
          API platform" is gone, not because of the positioning but because it was a third
          unreconciled variant.
          PageMeta is a SIBLING of the <Head> below, not nested inside it - a <Head> within a
          <Head> is invalid. It also owns the canonical, which is why there is no
          <link rel="canonical"> here any more, and the og:type / og:image / og:site_name /
          og:locale / twitter:card / twitter:image tags that used to be duplicated here come
          from _app.tsx with identical values. */}
      <PageMeta
        title="Grahak OS - Customer Engagement Platform"
        description="Grahak OS is the customer engagement product in WECARE.DIGITAL, unifying WhatsApp, SMS, Email, Voice, automation and customer data in one experience."
        path="/grahak-os/"
      />
      <Head>
        <meta name="keywords" content="WhatsApp Business API, WhatsApp CRM, bulk WhatsApp messaging, WhatsApp marketing India, business messaging platform, SMS API India, email marketing, voice calls API, Razorpay WhatsApp payments, customer engagement platform, multi-channel CRM, WhatsApp automation, WhatsApp chatbot, business communication, enterprise messaging, WhatsApp templates, promotional messages, transactional messages, OTP WhatsApp, order notifications" />
        <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1" />
        <meta name="googlebot" content="index, follow" />
        <meta name="author" content="WECARE.DIGITAL" />
        <meta name="publisher" content="WECARE.DIGITAL" />
        <meta name="copyright" content="WECARE.DIGITAL" />
        <meta name="language" content="English" />
        <meta name="geo.region" content="IN" />
        <meta name="geo.placename" content="India" />
        <meta name="theme-color" content="#000000" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="Grahak OS" />
        <meta name="application-name" content="Grahak OS" />
        <meta name="format-detection" content="telephone=no" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        
        {/* Preload the header lockup, which is the first paint on the page. */}
        <link rel="preload" href="https://wecare.digital/get/o/stream/media/m/wecaredigital.png" as="image" />
        {/* THE img.icons8.com preconnect AND dns-prefetch ARE GONE, because this page makes
            no icons8 request. Every glyph here is drawn: the six capability icons are inline
            data:image/svg+xml URIs, and the one remaining hosted image is the preloaded
            header lockup. Counted in the built export: two icons8 hints, zero icons8 requests.
            A preconnect to an unused origin is not free - it opens a TCP and TLS handshake
            that competes with the requests the page actually makes. Re-add these only
            alongside a real icons8 <img> on this route. */}
        
        {/* Structured Data - PAGE-SPECIFIC ONLY.
            This page used to emit a second Organization, a second FAQPage and a second
            WebSite on top of the five site-level entities _app.tsx already renders -
            nine blocks with four duplicated types, including two WebSite entities with
            DIFFERENT names and different SearchActions. Google's guidelines do not
            allow conflicting duplicate entities for one page, and two WebSite nodes
            claiming to be the site is exactly that.

            Removed here: Organization and WebSite (site-level, owned by _app.tsx) and
            FAQPage (Google stopped showing FAQ rich results on 2026-05-07, and it
            duplicated the sitewide copy anyway).

            Kept: SoftwareApplication, because it is genuinely about THIS product rather
            than the platform, and it carries the richer featureList. @id is set so it
            is a distinct node from the platform-level one and the two cannot be read as
            contradicting each other. */}
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify({
          "@context": "https://schema.org",
          "@type": "SoftwareApplication",
          "@id": "https://wecare.digital/grahak-os/#software",
          "name": "Grahak OS by WECARE.DIGITAL",
          "applicationCategory": "BusinessApplication",
          "operatingSystem": "Web Browser",
          "url": "https://wecare.digital/grahak-os/",
          "publisher": { "@id": "https://wecare.digital/#organization" },
          // offers REMOVED - it declared price "0" INR, i.e. that Grahak OS is free. The
          // platform-level node in _app.tsx carried the identical claim on 22 other routes and
          // was removed for the same reason; this was the last copy of it in the export.
          // Not replaced with a number: no price for this product exists anywhere in the
          // repository, and inventing one is the same class of error as the fabricated
          // aggregateRating removed alongside it. An Offer here needs a real price, ideally
          // derived from the catalogue rather than typed into a page.
          "description": "Customer engagement product in WECARE.DIGITAL with WhatsApp Business API, SMS, Email, Voice, customer data and AI automation.",
          "featureList": ["WhatsApp Business API", "Bulk Messaging", "SMS API", "Email Marketing", "Voice Calls", "Razorpay Payments", "AI Responses", "Analytics"]
        })}} />
      </Head>
      
      {/* <main>, NOT <div>. This page shipped with no main landmark at all:
          document.querySelector('main') returned null, so assistive tech had no way to skip
          to content, and SupportWidget's contentRoot() fell through to `.page` here while
          every other public page resolved `main`. The class is unchanged, so no CSS moves. */}
      <main className="page">

        {/* NO hero CTA. The hero is only the headline, sub and mockup. The single
            "Open demo in WhatsApp" link now belongs to the large API code panel in the
            enterprise-outcomes section below, while paid checkout stays in the api-steps
            block. RotatingHero's children slot is left unset. */}
        <RotatingHero
          insideMain
          noShare
          ariaLabel="Grahak OS"
          badgeLabel="Grahak OS by WECARE.DIGITAL"
          frame="Run customer conversations"
          pillPrefix="across"
          words={ cycleWords }
          sub={ <>One customer layer for messaging, AI agents and automation—connected across every channel.</> }
          visual={ (
          <div className="hero-right">
            <div className="hero-visual-col">
              <div className="mockup-wrapper">
                <div className="phone">
                  <div className="phone-header">
                    {/* The empty <span className="back-arrow" /> that used to sit here is
                        GONE. It had no content and no size, so it drew nothing - but as a
                        zero-width item in a flex row with gap:10px it still claimed a gap,
                        and Chromium resolves that gap differently by direction: measured
                        children of .phone-header put .contact-info at 84px from the inline
                        start in ltr and 74px in rtl. 74 is the arithmetically correct value
                        (14 padding + 10 gap = 24 for the avatar, which is 40 wide and ends at
                        64, + 10 gap = 74), so ltr was carrying a phantom gap.
                        rtlcheck.js reported it as a 10px mirror asymmetry and it was briefly
                        allowlisted as a browser quirk. It is not a quirk worth keeping: the
                        element was dead markup, and deleting it removes the asymmetry and 10px
                        of unintended space at the same time. If a back chevron is ever wanted
                        in this mock, give it content and mirror it under rtl. */}
                    {/* The WECARE.DIGITAL logo mark as the chat DP, not a bare "W". Same
                        transparent 1080x1080 asset the header lockup uses (LOGO_URL,
                        already preloaded on this page at line ~203), so no new request. It
                        sits on a white disc with a little padding so the mark reads as a
                        real profile photo in the thread. Decorative: alt="" + aria-hidden,
                        because .contact-name beside it already announces the business. */}
                    <div className="avatar"><img className="avatar-img" src="https://wecare.digital/get/o/stream/media/m/wecaredigital.png" alt="" aria-hidden="true" width="80" height="80" decoding="async" /></div>
                    <div className="contact-info">
                      {/* A company name, not copy. Without this the translation
                          widget rewrote it, so the mock WhatsApp thread showed a
                          Tamil rendering of "WECARE.DIGITAL" as the business name -
                          which is exactly the sender a real customer would be
                          checking to see they are talking to the right company. */}
                      <span className="contact-name" data-wc-no-translate="true">WECARE.DIGITAL</span>
                      <span className="contact-status">online</span>
                    </div>
                    <span className="verified-badge" aria-hidden="true"><svg viewBox="0 0 12 12" width="11" height="11" focusable="false"><path d="M4.8 8.4 2.4 6l-.9.9 3.3 3.3L10.5 4.4l-.9-.9z" fill="#fff"/></svg></span>
                  </div>
                  <div className="chat-area">
                    {/* Order is load-bearing, not arbitrary. The code panel laps the
                        phone's lower-right corner, so anything RIGHT-aligned low in
                        the thread disappears behind it. Both sent bubbles therefore
                        sit at the top, and the lapped band below holds only the
                        received bubble and the typing dots, which are left-aligned
                        and clear the panel.
                        The reference design solved this by left-aligning the lower
                        sent bubbles instead - which put two business replies on the
                        customer's side of the thread. This keeps the composition and
                        the WhatsApp semantics. Verified by measuring bubble rects
                        against the panel rect, not by eye. */}
                    {/* This bubble is the code panel's output, character for character.
                        It previously read "Hi! Your order #WD-ORD-87A6G has been
                        shipped" while the panel beside it sent "Your OTP: 847291" on
                        a different order id — the two halves of the same demo
                        contradicting each other. Keep this string and the panel's
                        "message" value identical; that is the whole point of showing
                        them side by side. */}
                    <div className="msg sent msg-home-green"><p>Your order #WD-87A6G has been shipped</p><span className="msg-meta"><span className="msg-time">10:30</span><svg className="msg-ticks" viewBox="0 0 16 11" width="16" height="11" aria-hidden="true" focusable="false"><path d="M11.07.65 5.3 8.6 2.3 5.6 1.2 6.7l4.2 4.2L12.2 1.75z" fill="currentColor"/><path d="M15.07.65 9.3 8.6l-.9-.9 6.17-8.4z" fill="currentColor"/></svg></span></div>
                    <div className="msg sent msg-home-blue"><p>Track here: wecare.digital/track</p><span className="msg-meta"><span className="msg-time">10:30</span><svg className="msg-ticks" viewBox="0 0 16 11" width="16" height="11" aria-hidden="true" focusable="false"><path d="M11.07.65 5.3 8.6 2.3 5.6 1.2 6.7l4.2 4.2L12.2 1.75z" fill="currentColor"/><path d="M15.07.65 9.3 8.6l-.9-.9 6.17-8.4z" fill="currentColor"/></svg></span></div>
                    <div className="msg received msg-home-amber"><p>When will it arrive?</p><span className="msg-time">10:31</span></div>
                    <div className="msg received"><p>Can I change the delivery address?</p><span className="msg-time">10:32</span></div>
                    <div className="typing-indicator"><span></span><span></span><span></span></div>
                  </div>
                </div>
                {/* dir="ltr": the panel is a Python call. Code is left-to-right by syntax, not
                    by convention, so it must not mirror when an Arabic reader translates the
                    page - the brackets and the dotted path reverse and it stops parsing.
                    LanguageBar already skips CODE and PRE for the same underlying reason.
                    It also pins .file-name, which uses margin-left:auto to push the filename
                    to the far end of the header; inside a locked subtree that physical
                    property is now correct rather than accidentally correct. */}
                <div className="code-stack">
                  <div className="code-box" dir="ltr">
                  <div className="code-header">
                    <div className="dots"><span className="dot-red"></span><span className="dot-yellow"></span><span className="dot-green"></span></div>
                    {/* A filename. The code body below is already safe because
                        LanguageBar skips CODE and PRE, but this title sits outside
                        those tags and was being translated - a Tamil send_message.py
                        is not a file anyone can open. */}
                    <span className="file-name" data-wc-no-translate="true">send_message.py</span>
                  </div>
                  {/* The full, real call - not an abbreviation. An earlier pass cut
                      this down to fit a 248px panel, which lost the assignment, the
                      API version and the auth header, so it stopped looking like
                      code someone would actually ship.
                      "message" must stay identical to the first .msg.sent bubble.
                      It used to send an OTP while the phone showed a shipping
                      notification, so the panel and the thread told two different
                      stories. "type": "text" became "channel": "whatsapp" because
                      the channel is the thing this demo is actually about.
                      LINE LENGTH IS GEOMETRY HERE. The panel is ~340px, which fits
                      36 monospace characters at 14px; the "message" line is 54 and
                      therefore wraps to two. That one extra line makes the panel
                      ~22px taller, and because .code-box is anchored bottom:0 a
                      taller panel pushes its TOP edge up into the sent bubbles. The
                      extra height on .mockup-wrapper and .chat-area min-height exists to
                      absorb exactly that. Lengthen any line here and you move the
                      panel over the thread - re-measure, do not eyeball. */}
                  <pre className="code-body">{`response = requests.post(
  "wecare.digital/api/outbound-whatsapp",
  json={
    "recipientPhone": "+919330994400",
    "content": "Your order #WD-87A6G has been shipped"
  },
  headers={"Authorization": bearer}
)`}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
          ) }
        />

        {/*
          Full-bleed layout: the touchpoint section keeps the 100vw + centring
          negative-margin pattern even though the page is now all white, so its
          content still aligns on the page's left line via .pp-inner (and so the
          pattern is ready if a tint is ever reintroduced). The 1300px measure moves
          off the section and onto .pp-inner while the section itself goes 100vw
          with a centring negative margin. Every class this pattern introduces is
          pp- prefixed on purpose: src/styles/*.css (loaded globally by _app.tsx)
          declares unscoped rules for generic names like .pill / .stat / .phone,
          and styled-jsx does not shield the page from those. As with the hero
          pill, the markup stays inline in the return - styled-jsx only scopes
          what it can statically see there.
        */}

        <section className={`touchpoint anim ${armed ? 'is-armed' : ''} ${show('touchpoint') ? 'show' : ''}`} id="touchpoint">
          <div className="pp-inner">
            <div className="section-header">
              <h2>Every touchpoint<br/>One seamless experience</h2>
              <p>Engage, support and convert customers across their entire journey, from first contact to lasting loyalty.</p>
            </div>
            <div className="usecase-pills">
              {useCases.map(({ title, example, hue }) => (
                <span
                  key={title}
                  className={`pp-pill pp-pill--${hue}`}
                  title={example}
                  aria-label={`${title}: ${example}`}
                >
                  {title}
                </span>
              ))}
            </div>
          </div>
        </section>

        <section className={`api anim ${armed ? 'is-armed' : ''} ${show('api') ? 'show' : ''}`} id="api">
          <div className="api-grid">
            {/* LEFT column rebuilt into the owner-approved numbered-steps block. The code
                panel (.api-demo) stays in the RIGHT column, unchanged. The /anew/ page's
                1-2-3 step pattern is emulated here (visible number + short title + one
                supporting line); only the PATTERN is borrowed, not Anew's copy or palette.
                Everything reuses this page's existing tokens, the existing ₹899 price,
                SKU GOS7K4M2 (PRODUCT_SKU_BY_SLUG['grahak-os']), the existing WhatsApp
                checkout mechanism (.gos-wa-cta pill) and the existing demo link. */}
            <div className="api-info api-steps">
              {/* Owner-approved heading theme (consulting positioning). Reuses the
                  .api-info h2 type rung. */}
              <h2>Deploy AI agents to drive enterprise outcomes</h2>
              <ol className="api-steps-list" aria-label="How Grahak OS works">
                <li className="api-step">
                  <span className="api-step-num" aria-hidden="true">1</span>
                  <div className="api-step-body">
                    <h3 className="api-step-title">Map the outcomes</h3>
                    <p className="api-step-line">Define the outcomes and conversations that matter.</p>
                  </div>
                </li>
                <li className="api-step">
                  <span className="api-step-num" aria-hidden="true">2</span>
                  <div className="api-step-body">
                    <h3 className="api-step-title">Deploy the agents</h3>
                    <p className="api-step-line">Connect AI agents to your channels and customer context.</p>
                  </div>
                </li>
                <li className="api-step">
                  <span className="api-step-num" aria-hidden="true">3</span>
                  <div className="api-step-body">
                    <h3 className="api-step-title">Own the result</h3>
                    <p className="api-step-line">Measure, tune and improve outcomes continuously.</p>
                  </div>
                </li>
              </ol>
              {/* Checkout + demo buttons. The paid-checkout door on this page is the
                  WhatsApp CTA pill (.gos-wa-cta) - ProductBuyBox was deliberately removed,
                  so this reuses that exact pill mechanism and surfaces the existing ₹899
                  price. The separate demo link lives below the large API code panel opposite. */}
              <div className="api-steps-buy">
                {/* UNIFIED WHATSAPP CTA STYLE (owner instruction): the WhatsApp
                    call-to-action here renders as the single .gos-wa-cta pill. The redundant
                    second "See it on WhatsApp" .gos-wa-cta that used to sit beside it was
                    REMOVED on owner instruction - this steps block now carries just the one
                    "Checkout on WhatsApp" pill; the demo link sits below the API code panel. */}
                <div className="api-steps-ctas">
                  <a className="gos-wa-cta" href="https://wa.me/message/APDM5HUWH26SG1" target="_blank" rel="noopener noreferrer">Checkout on WhatsApp &#8594;</a>
                </div>
                <ProductBuyBox slug="grahak-os" showPrice={ false } />
                { GRAHAK_DISPLAY_PRICE && (
                  <p className="gos-price" data-wc-no-translate="true">{ GRAHAK_DISPLAY_PRICE }</p>
                ) }
                <p className="gos-offer-note">One-time consultation · full deployment separate</p>
                {/* Price + SKU come from the same checkout mapping as the checkout action.
                    They are presented as commerce metadata; page-specific policy wording
                    remains in the shared PolicyDetails disclosure below. */}
                <div className="gos-commerce">
                  { GRAHAK_SKU && (
                    <p data-wc-no-translate="true"><strong>SKU:</strong> <span className="gos-sku-value">{ GRAHAK_SKU }</span></p>
                  ) }
                  <PolicyDetails
                    shipping={ GRAHAK_POLICY.shipping }
                    returns={ GRAHAK_POLICY.returns }
                    disclaimer={ GRAHAK_POLICY.disclaimer }
                    overview={ null }
                    refunds={ GRAHAK_REFUNDS }
                  />
                </div>
              </div>
            </div>
            <div className="api-demo-stack">
              <div className="api-demo">
                <div className="code-tabs">
                  {codeExamples.map((c, i) => (
                    <button key={i} className={`pp-tab ${activeCode === i ? 'active' : ''}`} onClick={() => setActiveCode(i)}>{c.lang}</button>
                  ))}
                </div>
                <pre className="code-block">{codeExamples[activeCode].code}</pre>
              </div>
              <div className="api-wa-row">
                <a className="api-wa-link" href="https://wa.me/message/APDM5HUWH26SG1" target="_blank" rel="noopener noreferrer">
                  Open demo in WhatsApp <span aria-hidden="true">↗</span>
                </a>
              </div>
            </div>
          </div>
        </section>

        {/* The capabilities strip section was REMOVED here on owner instruction (the six
            items: Customer Data Platform / Custom Data Modeling / Multichannel Orchestration
            / Smart Personalization / Enterprise Infrastructure / Predictive Analytics). The
            `capabilities` data array, the <section id="capabilities"> markup and all the
            .pp-strip* / #capabilities CSS went with it. A test guards the removal by
            substring, so this note avoids repeating the old class names and wording. */}

        {/* The Meta credential section was REMOVED here on owner instruction. The whole
            band (the Meta lockup card and the channel pills beside it) is gone, along with
            all of its CSS and the hosted Meta mark reference. A test asserts the removal by
            substring, so this note deliberately avoids repeating the old class names and
            wording. The channel positioning still lives in the hero's rotating pill. */}

        {/* OTP / Verifications section REMOVED on owner instruction. Its content overlapped the
            touchpoint "OTPs" pill and the capabilities strip, and the dedicated section was not
            needed. The QR lived only in this section and goes with it; the WhatsApp CTA remains
            beneath the API code panel as "Open demo in WhatsApp" and the API section also keeps its
            "Checkout on WhatsApp" pill. If the QR is ever wanted back, the verified asset is
            still at public/images/grahak-os-whatsapp-qr.svg. */}

        {/* The bottom closer section (<section id="gos-closer">) was REMOVED here on owner
            instruction. It had been stripped to a single "See it on WhatsApp" WhatsApp pill;
            that duplicate CTA is gone, and the page's only "Open demo in WhatsApp" link now lives
            directly below the large API code panel (.api-wa-link). The .gos-closer* CSS and the
            gos-closer entrance-animation target went with it; a test guards the removal by
            substring. The api-steps "Checkout on WhatsApp" pill and the ₹899 price/SKU/policy
            stay in the same section. */}

        {/* Subscribe + Share. The page's sections are full-bleed, so the block is wrapped in a
            .pp-inner column - the same 1300px / 24px measure the rest of the page content uses -
            so it aligns with the content rather than spanning the viewport. Last thing in <main>.
            THE 96px/64px BOTTOM PADDING IS DELIBERATE AND MATCHES EVERY OTHER PAGE. .pp-inner on
            its own has padding:0 24px - no bottom space - so after the share block dropped its own
            bottom padding (Option A, shared across all pages via PublicShare), grahak-os alone had
            the block hugging the viewport bottom while home/rh/PageTopBand pages kept their 96px
            wrapper rhythm. This restores that rhythm here so the block's bottom air is consistent
            sitewide. */}
        <div className="pp-inner gos-share-wrap">
          <PublicShare />
        </div>


        <style jsx>{`
          /* ========== BASE STYLES ========== */
          /* overflow-x:clip, not hidden. The full-bleed tint bands are width:100vw, and
             100vw includes the scrollbar, so under the old hidden value - which makes this
             element a scroll container - the bands were being clipped about 25px short of
             the true viewport edge. The clip value suppresses overflow without creating a
             scroll container, so the tint reaches the edge. Expect every section to shift by
             roughly 7.5px when this lands; that is the scrollbar no longer being
             double-counted, not a regression. */
          /* overflow-x:hidden is the BASE, and the clip upgrade lives in a @supports block
             below. Do not merge them back into two declarations on one rule.
             overflow-x:clip ships from Chrome 90, Firefox 81 and Safari 16, so anything
             older needs hidden or the full-bleed bands - width:100vw plus a centring
             negative margin - make the whole page horizontally scrollable, because 100vw
             counts the scrollbar.
             The usual two-declaration fallback does NOT work here: written as
             overflow-x:hidden then overflow-x:clip on the same rule, the CSS minifier sees
             one property declared twice, drops the first as redundant, and the fallback
             disappears from the shipped bundle. Verified in out/ - only clip survived.
             A @supports block cannot be collapsed that way. */
          /* padding:0 is load-bearing, not tidiness. Pages.css:76 declares
             .page{padding:0 12px} unscoped, and this rule never mentioned padding, so 12px
             was leaking in - the fourth generic class name to do this after .tab,
             .code-block and .nav-item.
             It was the whole reason section left edges disagreed below 1300px. The 12px sat
             on .page's content box, so .hero and .api started 12px in and then added their
             own 24px = 36px, while the full-bleed bands escape that box via
             margin-left:calc(50% - 50vw) and their inner started its 24px from 0 = 24px.
             Measured in a browser at 1280px: hero text 36px, strip items 24px. At 1440px
             they agreed only because both inner boxes were centred rather than padded. */
          .page{min-height:100vh;padding:0;background:var(--public-bg);font-family:var(--font-sans);color:var(--public-text);overflow-x:hidden}
          @supports (overflow-x:clip){
            .page{overflow-x:clip}
          }
          
          /* Animations
             THE FINISHED STATE IS WHAT CSS SHIPS, and .is-armed is what opts out of it.
             This block used to declare .anim{opacity:0} as the BASE state, with .show
             added by an IntersectionObserver inside a useEffect - so the only thing
             standing between a visitor and this page was JavaScript running. Measured
             against the export with javaScriptEnabled:false, every .anim section (hero,
             touchpoint, api) rendered at opacity:0.
             The whole page was blank.
             It went unnoticed for a reason worth recording: opacity does not remove text
             from the DOM, so the no-JS body-text count the design contract cites stayed
             correct at 2,448 chars and every harness suite stayed green while nothing was
             visible. A text measurement cannot see a paint bug.
             So the resting state is now VISIBLE, and the page arms itself only after the
             script has confirmed it can drive the reveal - the same shape Footer.tsx
             already uses for .ft-tagline. No JS, no IntersectionObserver, or a hydration
             failure all land on the same safe outcome: the finished state.
             DO NOT move opacity:0 back onto .anim. */
          .anim{opacity:1;transform:none}
          .anim.is-armed{opacity:0;transform:translateY(30px);transition:all .7s cubic-bezier(.16,1,.3,1)}
          .anim.is-armed.show{opacity:1;transform:translateY(0)}
          
          /* Hero Section */
          .hero{padding:140px 24px 80px;max-width:var(--public-content-max);margin:0 auto}
          /* Left column gets the extra room: the display type is large and the
             headline must hold to two lines ("Reach customers" / "across <pill>")
             so the rotating pill always lands on the last line without reflowing
             the line above it. */
          /* align-items:start, not center. The mockup column is taller than the
             copy column, and centring lifted its top edge ~70px above the copy -
             far enough to slide under the 108px fixed header, which clipped the
             phone's title bar. Starting both columns at the hero's top padding
             keeps the mockup clear of the header at every width. */
          .hero-content{display:grid;grid-template-columns:1fr 1fr;gap:56px;align-items:start}
          /* 60px cap is deliberate: at 64px "across <WhatsApp pill>" needs ~562px
             of the 564px column, so the pill wrapped to a third line. 60px leaves
             ~35px of slack so the headline holds two lines on every channel. */
          /* The row is start-aligned so the taller mockup clears the fixed header,
             but that left ~100px of empty column under the shorter copy. Centring
             just the copy fixes the imbalance without moving the mockup. */
          .hero-left{align-self:center}
          /* Spacing only. The badge's own paint lives in BrandBadge; styled-jsx
             cannot style a composite component from here, so anything visual added
             to this rule would silently do nothing. */
          .hero-eyebrow{margin:0 0 20px}
          .hero-left h1{font-size:var(--public-hero-size);font-weight:var(--public-hero-weight);line-height:var(--public-hero-leading);margin:0 0 24px;/* TRACKING IN em, NOT px. A fixed px value against a fluid clamp() font means the
             OPTICAL tightness changes with the viewport: measured across the breakpoints it ran
             -2.22% to -6.11% of the font size, a 2.75x spread, worst at 768-820px where the font
             is still on its 36px floor while the tracking was chosen for 60px. -0.04em is -4% at
             every size, and it lets both media-query overrides go - restating it per breakpoint
             is what caused the spread. index.tsx fixed this; these three copies had not. */
          letter-spacing:var(--public-hero-tracking);color:var(--public-heading)}
          /* Lede plus a muted supporting line. Two paragraphs rather than one long
             run-on: it reads better and gives the left column enough vertical mass
             to sit against the mockup opposite (which was 221px taller). Measures
             are capped so each wraps to a comfortable 2-3 lines. */
          /* Text colours measured from notion.com rather than picked off a grey
             ramp: their hero subtext is rgba(0,0,0,.898) at 20px and their
             secondary copy rgba(0,0,0,.54). The previous #9ca3af sat far lighter
             than anything they use for body text, which is why it read washed out. */
          /* Body copy matches notion.com exactly. Measured from their hero subtext:
             Inter 400 at 20px, line-height 28px (1.4), letter-spacing -0.125px,
             colour rgba(0,0,0,.898). The previous rule used line-height 1.6 and no
             tracking, which is why it still read differently from theirs even once
             the colour matched. */
          /* Measure set in px, not ch: Inter's "0" is ~12.6px at 20px, so 38ch
             resolved to 479px - nearly the full column - which is why the copy
             still looked like it ran edge to edge. 400px holds a comfortable
             ~60-70 characters per line and wraps to more lines, which also closes
             part of the height difference against the mockup column. */
          .hero-left p{font-size:var(--public-body-size);color:var(--public-body);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);font-weight:var(--public-body-weight);margin:0 0 18px;max-width:400px}
          .hero-left p.hero-sub{font-size:var(--public-body-size);color:var(--public-body);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);font-weight:var(--public-body-weight);margin:0;max-width:400px}

          /* The hero no longer has a CTA pill (the .gos-buy block was removed on owner
             instruction), and the bottom closer was removed too, so .gos-wa-cta now styles
             ONLY the api-steps "Checkout on WhatsApp" pill. The old closer-only .gos-ctas
             row wrapper went with the closer. */
          /* Primary WhatsApp pill: full-lime, the page's one allowed lime surface for the
             primary action - mirrors ProductPage's .pdp-cta. 52px min target. */
          .gos-wa-cta{display:inline-flex;align-items:center;justify-content:center;min-height:var(--public-cta-height);padding:0 26px;border:var(--public-cta-border) solid var(--public-brand-green);border-radius:var(--public-cta-radius);background:var(--public-brand-lime);color:var(--public-brand-green);font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);text-decoration:none;transition:background-color .2s,transform .2s,box-shadow .2s}
          .gos-wa-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:var(--public-lift-shadow)}
          .gos-wa-cta:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
          /* Hero Python panel only. Its demo link moved to the large API editor below. */
          .code-stack{position:absolute;right:0;bottom:24px;width:60%;max-width:340px;display:flex;flex-direction:column;align-items:stretch}
          .hero-visual-col{display:flex;flex-direction:column;align-items:flex-end;gap:10px;width:100%;box-sizing:border-box}
          /* Price in the card rung, dark green (lime is reserved for the pill). 22px of air
             above it matches the CTA row's own top gap, same as .pdp-price / .pbb-price. */
          .gos-price{display:block;margin-top:22px;font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-brand-green);font-variant-numeric:tabular-nums}
          .gos-offer-note{max-width:620px;margin:7px 0 0;font-size:17px;font-weight:400;line-height:1.4;letter-spacing:-.05px;color:var(--public-muted)}
          @media(prefers-reduced-motion:reduce){
            .gos-wa-cta{transition:background-color .2s}
            .gos-wa-cta:hover{transform:none;box-shadow:none}
            .api-wa-link{transition:none}
            .api-wa-link:hover{transform:none}
          }
          /* .api-wa-link's reduced-motion override lives beside the .api-wa-link base rule
             further down, so it is written AFTER that base rule — otherwise an override placed
             before the base declaration is clobbered by it at equal specificity. */

          /* The rotating channel pill - its lozenge, dot, width glide, word fade,
             entrance and the narrow-width "drop to its own line below 375px" fix - now
             lives in RotatingPill, which self-scopes its own rp-* CSS and takes the
             blockBelow={375} prop in place of the old @media(max-width:374px) rule here.
             styled-jsx cannot reach a child component's markup, which is why the pill owns
             its own styles; this page keeps only the headline around it and drives the
             entrance through the phase prop. */

          /* THE HEADLINE MUST NOT CHANGE HEIGHT WHEN THE PILL CHANGES WORD. The h1 reads
             "Run customer conversations / across <pill>" and the pill animates to each word's measured
             width ("SMS" to "WhatsApp" is a ~146px spread), so on a narrow screen the pill
             stops fitting beside "across", the line re-breaks and the h1 grows - which jumps
             everything below it on every rotation. The fix is to give the pill its own line
             below 375px; that now lives in RotatingPill, driven by blockBelow={375} on the
             <RotatingPill> above, which adds .is-block-narrow and its own
             @media(max-width:374px) rule inside the component's self-scoped CSS. Nothing to
             do here. */
          
          /* The Meta credential section's CSS was removed here with its markup (owner
             instruction) - the card, its lockup, the divider, the caption, the heading, the
             copy and the pills - including their @media overrides in the tablet/mobile/small
             blocks below. Class names are not repeated: a test guards the removal by
             substring. */

          /* ===== Closing statement (Notion-style display type + motion) ===== */
          /* OTP / Verifications CSS removed with its section (owner instruction). The .gos-otp*
             and .gos-qr* rules are gone; the verified QR asset remains at
             public/images/grahak-os-whatsapp-qr.svg if the section is ever reinstated. */

          /* The bottom closer section was REMOVED on owner instruction, so its
             .gos-closer / .gos-closer-buy / .gos-closer-buy .gos-ctas rules are gone with it.
             .gos-commerce / .gos-price below are still used by the api-steps block above, so
             their rules stay. */
          .gos-commerce{
            margin-top:14px;max-width:700px;font-family:inherit;font-size:17px;font-weight:400;line-height:1.4;
            letter-spacing:-.05px;color:var(--public-muted);text-align:left;
          }
          .gos-commerce strong{color:var(--public-brand-green);font-weight:700}
          .gos-sku-value{color:var(--public-muted)}
          .gos-commerce p{margin:0}
          /* The .gos-closer-head rule was REMOVED with the closer heading markup on owner
             instruction (the "Transform customer engagement with Grahak OS" h2 is gone). */

          /* Hero Right - Mockup */
          .hero-right{display:flex;justify-content:center}
          /* The phone's content is ~458px tall, so the wrapper is sized from that
             rather than a ratio that would crop it. */
          /* These three heights are solved together, not tuned by eye. The panel is
             anchored bottom:0, so panelTop = wrapperHeight - panelHeight(277).
             Constraints:
               1. panelTop must clear the bottom of the lowest RIGHT-aligned bubble
                  (~300px) or the panel eats its text  -> wrapperHeight >= 577
               2. the panel should overhang the phone by only ~20px, as in the
                  reference -> phoneBottom ~= wrapperHeight - 20 -> phone ~= 542
                  -> chat-area min-height 480 (phone = 62 header + 480)
             Hence 590 / 480. Shrinking the wrapper to 540 in an earlier pass moved
             the panel UP and swallowed a whole bubble - the opposite of the fix. */
          /* 590 -> 614, paired with the same +24 on .chat-area below. The code
             panel's "message" line now wraps to two lines, making the panel ~22px
             taller, and since .code-box is anchored bottom:0 its top edge would
             otherwise rise by that much into the sent bubbles.
             Both constraints are differential, which is why the two values move
             together: panelTop = wrapperHeight - panelHeight stays put when the
             wrapper grows by what the panel grew, and the ~20px panel-over-phone
             overhang stays put when the phone grows by the same amount as the
             wrapper. Change one without the other and the composition breaks. */
          /* 614 -> 638, paired with the same +24 on .chat-area. The sample moved to the
             real endpoint, and the longer path plus the recipientPhone field push two
             more lines past the panel's 36-character measure while the old "channel"
             line went away - net one extra rendered line, so about 22px more panel.
             Over-allocating by a couple of px is the safe direction here: if a line
             turns out to fit, the panel is shorter than the wrapper expects and its top
             edge sits LOWER, which only increases the clearance above the bubbles. */
          /* 638 -> 558, paired with the same -80 on .chat-area below, to make the mock more
             COMPACT. The four bubbles + typing indicator need ~360px of chat; at 528px the
             bottom ~80px rendered as empty beige under the typing dots. Trimming BOTH the
             wrapper and the chat-area by the same 80px removes that dead space while leaving
             the composition untouched: panelTop = wrapperHeight - panelHeight and the
             ~20px panel-over-phone overhang are both DIFFERENTIAL, so an equal cut to both
             values holds them exactly (the trap the geometry notes above warn about is
             changing ONE of the pair). Verified in a real render: the code panel still laps
             the lower-right corner with the same overhang and eats no bubble. Keep the two
             values in lockstep - never change one alone. */
          .mockup-wrapper{position:relative;width:100%;max-width:580px;min-height:610px;background:#fff;border-radius:28px;padding:28px 24px 24px}
          /* The two panels OVERLAP on purpose - the code panel laps the phone's
             lower-right corner, which is the whole composition. 56% + 60% = 116%
             of the wrapper, so the lap is ~16%.
             History worth keeping: an earlier pass set these to 50%/44%, which
             left a visible gap and read as two unrelated cards sitting side by
             side. Before that, 55%/58% lapped so far that the panel covered the
             message column and hid bubble text. 16% is the band that laps the
             corner without eating a message.
             top:28px, not 8px. At 8px the phone sat flush with the wrapper's top
             edge, so its dark title bar ran under the fixed header and read as
             clipped. */
          /* inset-inline-start:0 so the phone mock sits on the reader's starting edge. Unlike
             the code panel above it, a chat interface SHOULD mirror - WhatsApp itself is
             mirrored in Arabic - so this one follows the document instead of being locked.
             Measured at 260px out of position under rtl before the change. */
          .phone{position:absolute;inset-inline-start:0;top:28px;width:56%;max-width:320px;background:#fff;border-radius:20px;overflow:hidden;box-shadow:0 20px 50px rgba(0,0,0,.12)}
          /* WhatsApp's own header teal, not the brand's flat #1a3a2a. This is a
             SIMULATION of WhatsApp, so the chrome should read as WhatsApp's rather than as a
             custom green panel - the flat dark-forest block was the single biggest tell that
             this was a brand mockup and not a real thread.
             The teal is #0a7265: a darker rung of WhatsApp's published teal-green chrome,
             chosen so the white .contact-name clears the 4.5:1 WCAG AA floor for normal text
             (white on #0a7265 is 5.82:1). The lighter #128c7e used before only reached
             4.14:1 and failed the axe-core contrast check that kept this page at
             accessibility 95. #0a7265 still reads as an authentic WhatsApp header green.
             NOT #075e54. That darker WhatsApp green is RETIRED by name in the design contract
             (scripts/check_design_drift.py RETIRED_COLOURS) and the drift gate rejects it in
             real CSS - an earlier pass used it here and failed the gate. #0a7265 is a
             non-retired WhatsApp header green and reads the same at this size. */
          .phone-header{background:#0a7265;padding:12px 14px;display:flex;align-items:center;gap:10px}
          /* Avatar reads as a contact photo, not a flat tile the same colour as the header
             behind it. A LIME #d1f470 disc (the site's brand lime, owner choice) holds the
             WECARE.DIGITAL logo mark as the DP - the mark is dark green and reads clearly on
             lime, and lime pops off the #128c7e header bar. 2px white ring lifts the disc off
             the bar; the logo is contained with a little inset so it is not cropped. */
          .avatar{width:40px;height:40px;background:var(--public-brand-lime);border-radius:50%;display:flex;align-items:center;justify-content:center;overflow:hidden;flex:0 0 auto;box-shadow:0 0 0 2px rgba(255,255,255,.6)}
          /* Fill most of the disc so the 1080x1080 logo mark reads as a real profile photo
             and stays crisp: the <img> carries intrinsic 80x80 attributes (2x the 40px disc)
             so a 2x/retina screen maps it close to 1:1 device pixels instead of smearing a
             1080px source down to ~34 CSS px. object-fit:contain keeps the mark uncropped;
             the 90% box leaves a hair of lime padding around it. */
          .avatar-img{width:90%;height:90%;object-fit:contain;display:block}
          .contact-info{flex:1;display:flex;flex-direction:column}
          .contact-name{color:#fff;font-size:17px;font-weight:600}
          /* 'online' stays visibly lighter than the name so the hierarchy reads, but the old
             rgba(255,255,255,.7) composited to ~#b8ddd8 on the header and only reached 2.83:1,
             under the 3:1 any-text floor. Raised to alpha .92 so it composites high on the
             darker #0a7265 teal and clears the floor while staying a secondary white. */
          .contact-status{color:rgba(255,255,255,.92);font-size:13px}
          /* A real verified tick, not a blank disc. The empty circle read as a loading
             state; a small check on WhatsApp's brand green is the business-verified badge
             a customer would actually see beside a company name. */
          .verified-badge{width:18px;height:18px;background:#25d366;border-radius:50%;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
          .verified-badge svg{display:block}
          /* The paired phone-height adjustment keeps the lapped desktop composition clear. Growing the
             wrapper alone would have left the panel overhanging the phone by 44px
             instead of ~20px; growing the phone by the same amount keeps that. The
             extra height lands as empty beige below the typing dots, which is what
             a real thread looks like anyway. */
          /* 528 -> 448, the paired half of the -80 compacting cut on .mockup-wrapper above.
             This is the ~80px of empty beige that sat under the typing indicator; the four
             bubbles + dots still clear it. Must move in lockstep with the wrapper (see the
             note there) - cutting one alone slides the bottom-anchored code panel into the
             bubbles. */
          .chat-area{background:#ece5dd;padding:16px 14px;min-height:448px;display:flex;flex-direction:column;gap:9px}
          .msg{max-width:82%;padding:10px 13px;border-radius:8px;font-size:17px;line-height:1.42;color:#000}
          /* Received bubbles are capped narrower than sent ones. They sit low in the
             thread, inside the band the code panel laps, and at 82% they grew past
             the panel's left edge and got clipped on their RIGHT - which looks like
             a rendering fault rather than a deliberate overlap. 66% keeps them clear
             of it. */
          .msg.received{background:#fff;align-self:flex-start;max-width:66%;border-top-left-radius:3px}
          /* Keep WhatsApp's soft mint as the sent-bubble fallback, then borrow three
             HOME hero tints for the first three visible bubbles: green, blue and amber.
             The fourth received bubble stays white, so the mock still reads as a chat
             rather than a row of branded cards. All three tints keep black body text and
             the #54656f timestamp comfortably readable. */
          .msg.sent{background:#d9fdd3;align-self:flex-end;border-top-right-radius:3px}
          .msg.msg-home-green{background:#e0f7c8}
          .msg.msg-home-blue{background:#dbeafe}
          .msg.msg-home-amber{background:#fef3c7}
          /* Bubble tails match each bubble fill exactly. */
          .msg.sent::before{content:'';position:absolute;top:0;right:-7px;width:0;height:0;border-top:8px solid #d9fdd3;border-right:8px solid transparent}
          .msg.received::before{content:'';position:absolute;top:0;left:-7px;width:0;height:0;border-top:8px solid #fff;border-left:8px solid transparent}
          .msg.sent.msg-home-green::before{border-top-color:#e0f7c8}
          .msg.sent.msg-home-blue::before{border-top-color:#dbeafe}
          .msg.received.msg-home-amber::before{border-top-color:#fef3c7}
          .msg{position:relative}
          /* Every sent bubble sits on the right. Two of them previously carried a
             left-msg override that forced them to flex-start, so outgoing messages
             appeared on both sides of the same thread. */
          .msg p{margin:0}
          /* #54656f, not #667781. Both are WhatsApp's own greys, and that is the point - this is
             a simulation of their UI, so the timestamp should look like theirs. But on a lime
             sent bubble #667781 measures 3.74:1, and at 12px that is normal text needing 4.5:1.
             #54656f is WhatsApp's DARKER secondary grey and measures 4.87:1 on the same fill, so
             the simulation stays authentic and the text becomes readable. Found by Lighthouse's
             axe pass, not by the focus-ring sweep - that sweep measured indicators and specific
             label colours, and never looked at body text inside the mockup. */
          /* Time + delivery ticks on one baseline-aligned row at the bubble's bottom
             right, the way WhatsApp lays out message meta. Received bubbles keep a bare
             timestamp (no ticks), so .msg-time still works standalone there. */
          .msg-meta{display:flex;align-items:center;justify-content:flex-end;gap:4px;margin-top:3px}
          .msg-time{font-size:12px;color:#54656f;display:block;text-align:right;margin-top:3px}
          .msg-meta .msg-time{margin-top:0}
          /* The read-receipt double tick in WhatsApp's "read" blue (#53bdeb). This is the
             strongest single cue that a thread is a real WhatsApp conversation - a
             mockup almost never has it. Drawn as an inline SVG rather than a Unicode
             check so it renders identically on every platform (the U+2713 glyph is
             missing from some font stacks and falls back to tofu) and matches WhatsApp's
             actual overlapping double-tick shape. color drives the fill via
             currentColor. */
          .msg-ticks{color:#53bdeb;flex:0 0 auto;display:block}
          .typing-indicator{background:#fff;padding:10px 14px;border-radius:8px;align-self:flex-start;display:flex;gap:4px}
          .typing-indicator span{width:7px;height:7px;background:#1a3a2a;border-radius:50%;animation:bounce 1.4s infinite}
          .typing-indicator span:nth-child(2){background:#86b817;animation-delay:.2s}
          .typing-indicator span:nth-child(3){background:#c3e85a;animation-delay:.4s}
          @keyframes bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-3px)}}

          /* Code Box */
          /* Pure black, not slate. The panel reads as a terminal against the warm
             chat beige, and the slate #1e293b muddied that contrast. */
          .code-box{position:relative;width:100%;max-width:none;background:#000;border-radius:14px;overflow:hidden;box-shadow:0 20px 50px rgba(0,0,0,.2)}
          .code-header{display:flex;align-items:center;padding:10px 14px;background:#000}
          .dots{display:flex;gap:5px}
          .dot-red,.dot-yellow,.dot-green{width:10px;height:10px;border-radius:50%}
          .dot-red{background:#ff5f57}
          .dot-yellow{background:#febc2e}
          .dot-green{background:#28c840}
          .file-name{margin-left:auto;font-size:15px;color:#fff}
          /* pre-wrap rather than pre: at narrower viewports the panel shrinks and
             the longest lines were cut off mid-token behind overflow:auto, with no
             visible scrollbar to reveal them. NOTE: no backticks in comments here -
             this whole block is a template literal and a backtick ends it. */
          /* The hairline outline is the detail that makes this read as an editor
             pane rather than a flat dark rectangle. Both this and .code-box are
             #000, so the rounded corners of the two simply coincide and only the
             stroke shows. */
          /* width:auto for the same reason as .code-block: the global rule targets bare
             "pre" too, and its 768px block widens every pre by 24px. This panel clips
             with overflow:hidden so it was never visibly broken, but it was being
             overdrawn. */
          .code-body{margin:0;width:auto;padding:15px 16px;border:1.5px solid rgba(255,255,255,.92);border-radius:14px;background:#000;font-family:'SF Mono',Monaco,Consolas,monospace;font-size:14px;line-height:1.6;color:#fff;white-space:pre-wrap;overflow-wrap:break-word}
          
          /* Section Header */
          .section-header{text-align:center;margin:0 auto 32px;max-width:700px;padding:0 24px;display:flex;flex-direction:column;align-items:center}
          /* ONE section-heading rule for the two places that use the level: .section-header
             h2 and .api-info h2. The value was declared identically in each, which is a chance
             for the page to drift out of step with itself. Only the per-place differences stay
             separate below: margins, alignment and .section-header's pre-line. */
          /* THE SITE SECTION-H2 RUNG, not this page's own. Measured with
             tools/browser/typecheck.js: 13 headings across 10 public pages render
             clamp(28px,3.2vw,40px)/700/1.08/-1.2px - .home-flow-title, .home-close-title,
             .cl-h2, .mo-h2, .brx-h2 and .pdp-h2 on all seven product pages. This page was
             the ONLY marketing page still on clamp(32px,4.2vw,54px), which resolved to
             53.76px against everyone else's 40px.
             The design contract still names 54px, so the contract is now the thing that is
             out of step rather than the code - 13 headings beat 3. Worth amending
             .kiro/steering/grahak-os-design.md to match.
             There was also a real reason to move: at 1280px the hero h1 resolves to 55.04px,
             so a 53.76px section h2 sat 1.28px below its own h1 and the size hierarchy
             collapsed - only the 700/600 weight inversion separated them. */
          .section-header h2,.api-info h2{font-size:var(--public-section-size);font-weight:var(--public-section-weight);line-height:var(--public-section-leading);letter-spacing:var(--public-section-tracking);color:var(--public-heading)}
          .section-header h2{margin:0 0 14px;text-align:center;width:100%;white-space:pre-line}
          .section-header p{font-size:var(--public-body-size);color:var(--public-body);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);font-weight:var(--public-body-weight);margin:0;text-align:center;width:100%}
          
          /* Touchpoint Section */
          .touchpoint{padding:60px 0;background:var(--public-bg)}
          /* Grid, not wrapped flex, so the six use cases land 3 + 3 deterministically.
             Under flex with a 700px cap they broke 4 + 2 — the first row fitted four
             pills at ~607px and the fifth pushed past the cap — which reads as a wrap
             failure rather than a decision. Tightening the cap instead would have put
             the break point ~27px from the boundary, close enough that a copy edit or
             a fallback font could silently flip it back to 4 + 2.
             max-content keeps each pill its natural width and justify-items centres it
             in its column, so row two sits under row one on the same three axes. */
          .usecase-pills{display:grid;grid-template-columns:repeat(3,max-content);justify-content:center;justify-items:center;gap:12px;max-width:700px;margin:0 auto}
          /* Label colour is the palette's muted black, not a slate. #4b5563 is
             blue-tinted and read visibly cooler than the neutral body copy above
             it. Hover drops its background tint entirely: the old #fbfff0 is on
             the retired list, and a near-miss green is exactly what the why-section
             comment warns against. Lime border plus dark green text is affordance
             enough, and it keeps the borrowed-vs-ours colour rule intact. */
          /* Two changes, same reasoning as the nav dropdown: the label was both too
             faint and too small for the pill around it.
             rgba(0,0,0,.54) is the contract's LABEL value and measured ~4.5:1 on the
             section background - passing AA, but only just, and it read washed out next to
             the near-black heading above. Body colour rgba(0,0,0,.898) is ~14:1 and
             makes the pills look deliberate rather than disabled.
             15px inside 14px/28px padding put the type-to-pill ratio near 3.1, the
             same proportion problem the 46px nav row had at 15px. 17px brings it to
             about 2.8. */
          .pill{padding:14px 28px;border:2px solid var(--public-hairline);background:#fff;border-radius:50px;font-size:17px;font-weight:600;cursor:default;transition:all .25s;color:var(--public-body)}
          .pill:hover{border-color:var(--public-brand-lime);color:var(--public-brand-green);transform:translateY(-2px);box-shadow:var(--public-lift-shadow)}
          
          /* API Section */
          .api{padding:60px 24px;max-width:var(--public-content-max);margin:0 auto;background:var(--public-bg)}
          /* start, not center. The left column is ~200px tall against a ~360px code
             panel, so centring dropped the heading roughly 80px below the panel's top
             edge and the text read as floating rather than as the other half of a pair.
             This was the only section using center. */
          /* No max-width, and the gap matches the hero's 56px rather than 60px. The HERO
             is the page's reference line: .hero-content has no cap, so it fills the
             1252px content box and starts 24px in. This grid was capped at 1100px and
             centred, which put it 100px in - so the heading and copy here began 76px
             right of the hero's, and the eye reads that as the section being indented.
             A previous pass aligned api / strip / trust to each other at 1100px, which
             made three sections agree with one another and all three disagree with the
             top of the page. Aligning to the hero instead is the fix. */
          .api-grid{display:grid;grid-template-columns:1fr 1fr;gap:56px;align-items:start}
          .api-info h2{margin:0 0 20px}
          /* Capped for line length, the way .hero-left p is capped at 400px. Removing
             the grid's 1100px cap widened this column to ~596px, and 20px body text at
             that width runs past a comfortable measure. The cap belongs on the text, not
             on the grid - that is what let the grid align with the hero while the
             paragraph stays readable. */
          .api-desc{font-size:var(--public-body-size);color:var(--public-body);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);font-weight:var(--public-body-weight);margin:0;max-width:460px}
          /* "In action" block in the left column, sitting under the API copy and
             opposite the code panel. 36px top margin separates it from the paragraph
             without needing a divider. */
          .api-action{margin:36px 0 0;max-width:460px}
          /* h3 on the card-heading rung (22px/700), one step below the section h2 above
             it in the same column, so the outline is h2 -> h3 with no skipped level. */
          .api-action-head{font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-heading);margin:0 0 16px}
          /* The .api-action-link lighter text-link CSS was REMOVED with its markup: every
             WhatsApp CTA now uses the single unified .gos-wa-cta pill (owner instruction),
             so the second style is dead. A test guards that the class name no longer
             appears, so it is not repeated here. */
          /* ===== Numbered 1-2-3 step block (new LEFT column) =====
             Emulates the /anew/ step pattern (number + short title + one supporting
             line) using ONLY this page's existing tokens: lime #d1f470, dark-green
             #1a3a2a, body rgba(0,0,0,.898), muted rgba(0,0,0,.6), hairline #e5e7eb.
             No new colours, no Anew palette. */
          .api-steps h2{margin:0 0 28px}
          .api-steps-list{list-style:none;margin:0 0 36px;padding:0;display:flex;flex-direction:column;gap:24px;max-width:460px}
          /* Each step: a lime disc with the number, dark-green text, next to the copy. */
          .api-step{display:flex;align-items:flex-start;gap:16px}
          /* Lime number disc in the page's own #d1f470 with dark-green #1a3a2a text,
             matching the .pp-tab.active / .api-action-link treatment. 44px disc also
             anchors the row vertically. */
          .api-step-num{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:50%;background:var(--public-brand-lime);color:var(--public-brand-green);font-size:20px;font-weight:700;line-height:1;letter-spacing:-.25px;font-variant-numeric:tabular-nums}
          .api-step-body{min-width:0}
          /* Card-heading rung (22px/700), one step below the section h2 in the same
             column, so the outline is h2 -> h3 with no skipped level. */
          .api-step-title{font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-heading);margin:0 0 6px}
          /* Supporting line uses the same 20px body rung as Home. */
          .api-step-line{font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-body);margin:0}
          /* Buy block: WhatsApp checkout pill, then price + muted supporting note, then SKU
             and the compact policy disclosure. Only layout gaps are page-local here. */
          .api-steps-buy{max-width:700px}
          .api-steps-ctas{display:flex;flex-wrap:wrap;gap:12px;align-items:center}
          .api-steps-buy .gos-price{text-align:left}
          /* Pure black, matching the hero .code-box. This panel was the last slate
             holdout: #1e293b is on the contract's retired list specifically "as the
             code panel body", yet it survived here after the hero panel was moved to
             #000 for muddying contrast. Two code panels on one page reading as two
             different materials was the clearest language break left.
             #0f172a and #94a3b8 went with it — they were the rest of that same
             undocumented slate ramp. The tab strip keeps its separation from a white
             hairline at .12 rather than a second background colour, and idle tab text
             is rgba(255,255,255,.54), the dark-panel mirror of the rgba(0,0,0,.54)
             the pills use. Code text goes to #fff to match .code-body. */
          /* 16px -> 14px to match the hero .code-box. The two panels are the same
             object at two sizes, and the mobile override was already 14px, so this
             also stops the radius changing across breakpoints. */
          .api-demo-stack{display:flex;flex-direction:column;align-items:stretch;gap:12px;min-width:0}
          .api-demo{background:#000;border-radius:14px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.12)}
          /* Secondary demo action: aligned to the code panel's left edge and deliberately
             lighter than the paid WhatsApp pill. It is transparent at rest; hover/focus
             borrows the active-tab lime so the relationship to the editor is immediate. */
          .api-wa-row{display:flex;justify-content:flex-start}
          .api-wa-link{display:inline-flex;align-items:center;gap:5px;width:max-content;margin-left:-10px;padding:8px 10px;border-radius:10px;color:var(--public-brand-green);font-size:17px;font-weight:600;line-height:1.4;letter-spacing:-.05px;text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:3px;transition:background-color .18s,color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s}
          .api-wa-link:hover{background:var(--public-brand-lime);color:var(--public-brand-green);text-decoration-color:transparent;transform:translateY(-1px);box-shadow:0 6px 18px rgba(26,58,42,.12)}
          .api-wa-link:focus-visible{background:var(--public-brand-lime);color:var(--public-brand-green);text-decoration-color:transparent;outline:3px solid var(--public-brand-green);outline-offset:3px}
          @media(prefers-reduced-motion:reduce){
            .api-wa-link{transition:none}
            .api-wa-link:hover{transform:none}
          }
          /* No border-bottom. The .12 hairline here was standing in for structure
             that the code pane's own stroke now provides - the hero solves this the
             same way, with .code-header carrying nothing and .code-body's outline
             doing the work. Two separators stacked read as a seam. */
          .code-tabs{display:flex;gap:6px;padding:14px 16px;background:#000}
          /* RENAMED .tab -> .pp-tab, for the same reason .pill became .pp-pill.
             Patching individual properties was losing this battle. The bare .tab class
             is declared unscoped in BOTH Pages.css and Layout.css, and eight properties
             this rule did not mention were arriving from them.
             (No backticks anywhere in this comment - this whole block is a template
             literal and one backtick ends it. Writing .tab in backticks here is what
             broke the build a minute ago: TypeScript then read .tab as a property
             access on the truncated string.)

               min-height:44px      forced the pill taller than its own padding
               box-shadow           Pages.css:842 puts 0 1px 3px rgba(26,58,42,.15)
                                    under .tab.active - a dark edge beneath the lime,
                                    which is what made the fill look off rather than
                                    the lime itself being wrong
               font-family          var(--font-sans), not this page's stack
               display, align-items, justify-content, gap, white-space

             Pages.css:846 also sets .tab.active:hover{background:#f9fafb}, which ties
             my rule on specificity and was decided only by stylesheet order - the
             active tab was one load-order change away from turning near-white on
             hover.

             A pp- prefixed name matches nothing global, so the page owns the control
             outright and every property below is the one that renders. Note the lime
             was always correct: the #d1f470 here is what shipped. What changed is the
             shadow and the height around it. */
          /* min-height:44px IS THE WCAG 2.5.8 TARGET FLOOR, and it was missed by 0.7px.
             10px of padding either side of a 15px/normal line box measured 43.3px tall in
             a browser - so all three of these tabs, which are the ONLY interactive
             controls inside this page's <main>, sat just under the 44px minimum.
             min-height rather than more padding: the element is already an inline-flex
             with centred content, so the box grows without moving the label, and the
             mobile breakpoints below (which raise padding to 14px and 12px) were already
             past 44px and are left untouched. */
          .pp-tab{display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;font-family:inherit;padding:10px 20px;min-height:44px;border:none;border-radius:8px;font-size:17px;font-weight:600;color:rgba(255,255,255,.54);background:transparent;box-shadow:none;cursor:pointer;transition:all .2s}
          /* Text-only hover: idle .54 white lifting to full white. The active tab
             already owns the filled-lime state, so a second fill competes with it. */
          .pp-tab:hover{color:#fff;background:transparent}
          .pp-tab.active{background:var(--public-brand-lime);color:var(--public-brand-green);box-shadow:none}
          /* The editor-pane stroke, carried over from the hero's .code-body, where the
             comment calls it the detail that stops a dark panel reading as a flat
             rectangle. It was the last thing separating these two panels visually:
             both were already #000 with #fff code, but only the hero looked like an
             editor. Radius matches .api-demo at 14px so the corners coincide and only
             the stroke shows, exactly as the hero pairs .code-body with .code-box. */
          /* background:#000 and width:auto are the two properties that make this rule
             actually take effect, and both exist because of a global leak rather than
             for their own sake.
             Pages.css:3228 declares ".code-block, .api-example, pre" with
             background:#1e1e1e - the slate this page retired - plus, inside its 768px
             media query, width:calc(100% + 24px) with negative side margins and squared
             corners. This rule declared neither property, so the pane rendered #1e1e1e
             over the panel's #000 and the black treatment looked like it had not
             applied at all. The jsx class already outranks the global; it simply had
             nothing to outrank it WITH.
             Declared in the base rule, not the breakpoint, so the global's 768px
             boundary cannot slip through the 767px override below. */
          .code-block{margin:0;width:auto;padding:20px;border:1.5px solid rgba(255,255,255,.92);border-radius:14px;background:#000;font-family:'SF Mono',Monaco,Consolas,monospace;font-size:15px;line-height:1.65;color:#fff;overflow-x:auto;white-space:pre}
          /* Same global, mobile half: it attaches a 24px rgba(30,30,30,.8) gradient as
             a scroll hint that fades in on hover. On a black pane that reads as a dark
             smudge appearing under the cursor, so it is switched off for both panels. */
          .code-block::after,.code-body::after{content:none}
          
          /* Capabilities Section - Card Grid */
          /* No background tint on hover — #fbfff0 is retired. The whole page is white
             now, so cards sit on #fff and the lime border reads against it. */

          /* ========== TABLET (768px - 1024px) ========== */
          /* The lapped hero mockup needs a WIDE column, and 1024px is not where that stops
             being true. Browser check at 1025px: one bubble covered, "Track here:
             wecare.digital/track". At 1280px and 1440px, none.
             The arithmetic explains it. .code-box is 60% of the wrapper capped at 340px, and
             the 36-character line budget the sample is written to assumes it is AT that cap.
             340/0.6 = 567px of wrapper, which needs a hero column of 567px, which needs
             567*2 + 56 gap + 48 padding = about 1238px of viewport. Below that the panel
             narrows, the sample wraps onto more lines, the panel grows taller, and because
             it is anchored bottom:0 its top edge climbs into the thread.
             So the lap gets used above ~1240px only. This range keeps the two-column hero
             but stacks the mockup, which is the same arrangement the 1024px block uses and
             which the browser reports collision-free. */
          @media(min-width:1025px) and (max-width:1240px){
            .mockup-wrapper{display:flex;flex-direction:column;gap:14px;aspect-ratio:auto;min-height:0;align-items:flex-start}
            .phone{position:relative;left:auto;top:auto;width:100%;max-width:100%}
            .chat-area{min-height:320px}
            .code-stack{position:relative;right:auto;left:auto;bottom:auto;width:100%;max-width:none;align-self:stretch}
            .code-box{position:relative;right:auto;left:auto;bottom:auto;width:100%;max-width:100%}
            .hero-visual-col{padding-bottom:0}
          }

          @media(max-width:1024px){
            
            .hero{padding:110px 20px 60px}
            .hero-content{grid-template-columns:1fr;gap:40px;text-align:left}
            .hero-left h1{max-width:760px;margin:0 0 20px}
            .hero-left p{max-width:520px;margin:0 0 28px}
            
            /* STACKED here, not lapped. Verified in a real browser at 768px: the lapped
               composition was covering three bubbles - "Track here", "When will it arrive?"
               and "Can I change the delivery address?" - the exact collision the hero
               geometry notes warn about.
               The cause is structural and predates the recent height changes.
               aspect-ratio:1.15 on a 480px wrapper forces it to 417px tall, while
               .chat-area carries min-height:528px and is only overridden below 767px. So
               the phone was ~590px inside a 417px box, and .code-box at bottom:16px is
               positioned against the wrapper - landing it in the middle of the thread. It
               was broken at the old 480px chat height too.
               Below 1024px the hero is a single column anyway, so the mockup is already
               full width at 480px, too narrow for a 52% + 55% lap to breathe. Stacking is
               what the 767px breakpoint already does, and the browser check reports zero
               collisions there. aspect-ratio goes to auto so height follows content. */
            .mockup-wrapper{display:flex;flex-direction:column;gap:14px;max-width:480px;aspect-ratio:auto;min-height:0;margin:0;padding:20px;align-items:flex-start}
            .phone{position:relative;left:auto;top:auto;width:100%;max-width:100%}
            .chat-area{min-height:300px}
            .code-stack{position:relative;right:auto;left:12px;bottom:16px;width:55%;max-width:none;align-self:flex-start}
            .code-box{position:relative;right:auto;left:auto;bottom:auto;width:100%;max-width:100%}
            .phone{left:16px;top:16px;width:52%}
            .hero-visual-col{padding-bottom:0}
            
            .section-header{padding:0 20px}

            .touchpoint{padding:50px 0}
            .usecase-pills{gap:10px}
            .pill{padding:12px 22px}
            
            .api{padding:50px 20px}
            .api-grid{grid-template-columns:1fr;gap:36px;text-align:left}
            .api-info h2{text-align:left}
            .api-desc{max-width:100%;text-align:left}
            .api-demo-stack{max-width:500px;margin:0}
            .api-demo{max-width:100%;margin:0}
            
            
          }

          /* ========== MOBILE (up to 767px) ========== */
          @media(max-width:767px){
            
            .hero{padding:calc(115px + env(safe-area-inset-top)) 20px 50px}
            .hero-content{display:flex;flex-direction:column;gap:32px;text-align:left;align-items:flex-start}
            .hero-right{order:-1;width:100%;display:flex;justify-content:center}
            /* On the stacked mobile hero the below-code link re-centres under the mockup
               (desktop right-aligns it; here flex-end would push it to the column edge). */
            .hero-visual-col{align-items:center}
            .hero-left{text-align:left;order:1}
            .hero-left h1{margin:0 0 20px;line-height:1.1;max-width:100%;text-align:left}
            .hero-left p{margin:0 0 16px;max-width:100%;text-align:left}

            .mockup-wrapper{display:flex;flex-direction:column;gap:14px;width:100%;max-width:380px;margin:8px auto 0;aspect-ratio:auto;padding:16px;background:#fff;border-radius:16px;border:2px solid var(--public-hairline);align-items:flex-start;transition:all .25s;cursor:default}
            .mockup-wrapper:hover{border-color:var(--public-brand-lime);transform:translateY(-2px);box-shadow:var(--public-lift-shadow)}
            .phone{position:relative;left:auto;top:auto;width:100%;max-width:100%;margin:0;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,.08)}
            .phone-header{padding:14px 16px;gap:10px}
            .avatar{width:42px;height:42px;font-size:18px}
            .contact-name{font-size:18px}
            .contact-status{font-size:15px}
            .verified-badge{width:24px;height:24px}
            .chat-area{min-height:200px;padding:14px 12px;gap:10px}
            .msg{font-size:17px;padding:12px 14px;max-width:85%}
            .typing-indicator{padding:12px 16px}
            .typing-indicator span{width:8px;height:8px}
            
            .code-stack{position:relative;right:auto;left:auto;bottom:auto;width:100%;max-width:100%;align-self:stretch}
            .code-box{position:relative;right:auto;left:auto;bottom:auto;width:100%;max-width:100%;margin:0;border-radius:14px;box-shadow:0 4px 20px rgba(0,0,0,.1);align-self:flex-start}
            .code-header{padding:14px 16px}
            .dots{gap:6px}
            .dot-red,.dot-yellow,.dot-green{width:12px;height:12px}
            .file-name{font-size:15px}
            .code-body{font-size:15px;padding:16px;line-height:1.6;text-align:left}
            
            .section-header{margin-bottom:28px;padding:0 20px;text-align:center}
            .section-header h2{margin-bottom:12px;line-height:1.15;text-align:center}
            .section-header p{text-align:center}
            
            .touchpoint{padding:44px 0}
            /* 2 + 2 + 2 from tablet down; three max-content columns plus gaps do
               not fit a 360px viewport once section padding is taken off. */
            .usecase-pills{grid-template-columns:repeat(2,max-content);justify-content:center;justify-items:center;gap:12px;padding:0;margin:0}
            /* font-size dropped, not changed: the TYPOGRAPHY CONTRACT block below is
               later in source order at equal specificity, so its 15px already won and
               this 20px never rendered. It only made the pill look under-specified. */
            .pill{padding:14px 26px}
            
            .api{padding:44px 20px}
            .api-grid{gap:36px;text-align:left}
            .api-info{text-align:left}
            .api-info h2{margin-bottom:16px;text-align:left}
            .api-desc{max-width:100%;text-align:left}
            /* Stacked order: the step block comes FIRST (above the code panel). It is
               already first in source order so the grid stacks it first; the explicit
               order makes that intent survive any future markup reordering. */
            .api-steps{order:0}
            .api-demo-stack{order:1;max-width:100%;margin:0}
            .api-demo{border-radius:14px;max-width:100%;margin:0}
            .api-steps-list{max-width:100%}
            .api-steps-buy{max-width:100%}
            .code-tabs{padding:16px;gap:10px;justify-content:flex-start;flex-wrap:wrap}
            .pp-tab{padding:14px 24px}
            .code-block{font-size:14px;padding:18px;min-height:auto;text-align:left;white-space:pre-wrap;word-break:break-word;overflow-x:visible;line-height:1.7}
            .api-wa-row{justify-content:flex-start}
            .api-wa-link{margin-left:-8px;padding:8px}
            
            
          }

          /* ========== SMALL MOBILE (up to 480px) ========== */
          @media(max-width:480px){
            
            .hero{padding:calc(85px + env(safe-area-inset-top)) 16px 44px}
            
            .section-header{padding:0 16px}

            .mockup-wrapper{padding:14px;border-radius:14px;gap:12px;max-width:100%}
            .phone{border-radius:14px}
            .phone-header{padding:12px 14px}
            .avatar{width:38px;height:38px;font-size:16px}
            .contact-name{font-size:17px}
            .chat-area{min-height:170px;padding:12px 10px}
            .msg{font-size:16px;padding:10px 12px}
            
            .code-box{border-radius:12px}
            .code-body{font-size:14px;padding:14px}
            
            .touchpoint{padding:36px 0}
            .usecase-pills{gap:10px}
            .pill{padding:12px 20px}
            
            .api{padding:36px 16px}
            .api-info h2{text-align:left}
            .api-desc{text-align:left}
            .code-tabs{gap:8px;padding:14px}
            .pp-tab{padding:12px 20px}
            .code-block{font-size:14px;padding:16px;min-height:auto;text-align:left;white-space:pre-wrap;word-break:break-word;overflow-x:visible;line-height:1.65}
            
            
          }
          
          /* ========== VERY SMALL SCREENS (up to 360px) ========== */
          @media(max-width:360px){
            
            /* 16px, not 14px. Every other section stays on 16px at this width - the 480px
               block sets api and .pp-inner to 16 and nothing overrides them here - so the
               hero alone sat 2px left of everything else. Measured at 360px: hero text at
               14px, the rest at 16px. */
            .hero{padding:calc(80px + env(safe-area-inset-top)) 16px 36px}
            
            .pill{padding:12px 18px}
          }
          
          /* ========== LANDSCAPE ORIENTATION FIX ========== */
          @media(max-height:500px) and (orientation:landscape){
            .hero{padding:90px 24px 40px}
            .hero-content{flex-direction:row;gap:24px;text-align:left}
            .hero-right{order:0;flex:1}
            .hero-left{order:0;flex:1;text-align:left}
            .hero-left h1{margin:0 0 16px}
            .hero-left p{margin:0 0 20px}
            .mockup-wrapper{max-height:260px;aspect-ratio:auto;max-width:100%}
            .phone{max-width:180px}
            .code-box{max-width:200px}
            .chat-area{min-height:120px}
          }

          /* ========== TYPOGRAPHY CONTRACT ========== */
          /* Match Home's public-page ladder: 60px hero, 40px section heading,
             22px card title, 20px body and 17px controls. Code text and the phone
             mock remain intentional interface exceptions. The hero h1 and body
             already own the exact Home values in their base rules. */
          .section-header h2{font-size:clamp(28px,3.2vw,40px);line-height:1.08;letter-spacing:-1.2px}
          .section-header p{font-size:20px;line-height:1.4;letter-spacing:-.125px}
          /* 17px explicit, not var(--text-base). That token is declared twice —
             tokens.css:83 says 16px, Pages.css:59 says 15px — and only Pages.css is
             imported by _app.tsx, so the pills were 15px by accident of import
             order. Importing tokens.css would silently have resized every pill.
             .pp-pill is listed here too; it was missing from this contract block
             despite being the class the touchpoint section actually renders.

             THIS COMMENT SAID 15px UNTIL 2026-09-29 AND THE DECLARATION NEVER DID.
             Measured in a browser, .pill and .pp-pill resolve to 17px, and a git log -S
             search for the 15px form of this very declaration returns nothing - that string
             has never existed in this file. The comment, the 17px declaration and the design
             contract's "an explicit 15px" row all arrived together in 457cc883, so the
             15px was wrong the moment it was written rather than having drifted later.
             Corrected to 17px in all three places, because 17px is what has shipped and
             been reviewed since the rebuild; changing the code to match a number nobody
             ever saw would be a real visual change made to satisfy a stale note.
             NOTE: no backticks anywhere in this comment. This block is a template literal
             and one backtick ends it - quoting that git command with backticks is what broke
             the build while this note was being written, which is the trap documented at the
             top of the design contract. */
          .pill,.pp-pill{font-size:17px}
          .api-info h2{font-size:clamp(28px,3.2vw,40px);line-height:1.08;letter-spacing:-1.2px}
          .api-desc{font-size:20px;line-height:1.4;letter-spacing:-.125px}
          .pp-tab{font-size:17px}
          
          /* ========== REDUCED MOTION ========== */
          @media(prefers-reduced-motion:reduce){
            /* Both selectors, because the reveal transition moved onto .anim.is-armed when
               the base state became the finished one. Matching .anim alone would leave the
               armed sections still transitioning under reduced motion. */
            .anim,.anim.is-armed{transition:none}
            .typing-indicator span{animation:none}
            .pill{transition:none}
          }

          /* ========== FULL-BLEED SECTIONS (pp-*) ==========
             The page is all white now, but these sections keep the full-bleed
             geometry so their content lines up with the rest of the page (and the
             pattern is ready if a tint returns). The 1300px measure moves off the
             section and onto .pp-inner: 100vw plus a centring negative margin would
             make a background exactly window.innerWidth
             wide, where a plain background would stop short of each edge.
             .page already clips overflow-x, so this adds no horizontal scroll.
             Everything here is pp- prefixed because the globally imported
             src/styles/*.css declares unscoped rules for generic names like
             .pill / .stat / .phone / .chat-area that styled-jsx cannot shield
             the page from; the id selectors beat the shared section classes
             regardless of source order. */
          /* White throughout (owner instruction): the #fafafa tint bands are gone, so the
             whole page is one white canvas. The full-bleed geometry stays - these two
             sections keep width:100vw and the centring negative margin so their content
             still aligns on the page's left line via .pp-inner - but with no background
             they simply read as white like every other section. */
          #touchpoint{max-width:none;width:100vw;margin-left:calc(50% - 50vw);background:var(--public-bg)}
          /* 1252px, not 1300px, and the difference is the point. A section like .hero is a
             1300px box with 24px padding, so its CONTENT starts at 1300-48 = 1252px wide.
             The full-bleed sections put their padding on the outer 100vw element and then
             nest this, so at 1300px this inner box started 24px left of the hero's content
             edge. Measured in a real browser at 1440px: hero text at 94px, strip items at
             70px. 1252px makes both 94px. */
          .pp-inner{max-width:var(--public-content-max);margin:0 auto;padding:0 24px;box-sizing:border-box}
          /* The share block's wrapper adds the sitewide bottom rhythm (.pp-inner has none), so the
             block's bottom air matches home / rh-layout / PageTopBand (96px, 64px under 768px). */
          .gos-share-wrap{padding-bottom:48px}
          @media(max-width:767px){ .gos-share-wrap{padding-bottom:40px} }

          /* The capabilities strip CSS (.pp-strip, .pp-strip-grid, .pp-strip-item,
             .pp-strip-icon, .pp-strip-text, .pp-strip-title, .pp-strip-sub and all their
             responsive variants) was REMOVED with the #capabilities section on owner
             instruction. The .pp-inner padding overrides in the media queries below are
             KEPT because #touchpoint and the share wrapper still use .pp-inner. A test
             guards that the pp-strip* class names no longer appear. */
          @media(max-width:1024px){
            .pp-inner{padding:0 20px}
          }
          @media(max-width:767px){
            .pp-inner{padding:0 20px}
          }
          @media(max-width:480px){
            .pp-inner{padding:0 16px}
          }

          /* Use-case pills as spans, since they carry no handler. Same paint as
             .pill; inline-flex restores the centring a button gets for free. */
          /* Paint matches .pill exactly — muted black label, no retired hover
             tint. min-height is dropped: at 15px with 14px of vertical padding the
             pill computes to ~48px, so a 32px floor never applied and only implied
             a constraint that was not doing anything. */
          /* Base pill geometry/type is shared; the HUE is set by a .pp-pill--<hue> modifier
             as a thin COLOURED BORDER on a WHITE background, so the six touchpoints read as a
             clean, varied set instead of six identical grey outlines. The earlier filled
             tint backgrounds (#fef3c7/#e0f7c8/#ede9fe/#fee2e2) were dropped on owner
             instruction - they looked too candy/artificial; every pill is now white with
             only its hue as the outline. Each border colour is lifted verbatim from the
             HOMEPAGE subject palette (amber/purple/green/red dot hues in
             src/pages/index.tsx CYCLE_WORDS), the homepage blue border #2563eb, and this
             page's own brand lime #d1f470 - no new colours are introduced. Text stays dark
             (rgba(0,0,0,.898)) on white, which keeps each pill well above the 4.5:1 WCAG AA
             floor; the amber (2.04:1) and green (3.19:1) hues that fail as text are used
             ONLY as borders here, never as the text colour. */
          .pp-pill{display:inline-flex;align-items:center;justify-content:center;padding:14px 28px;border:2px solid var(--public-hairline);background:#fff;border-radius:50px;font-size:17px;font-weight:600;cursor:default;transition:all .25s;color:var(--public-body)}
          .pp-pill--amber{border-color:#f0a818;background:#fff}
          .pp-pill--blue{border-color:#2563eb;background:#fff}
          .pp-pill--green{border-color:#3da35a;background:#fff}
          .pp-pill--purple{border-color:#9849e8;background:#fff}
          .pp-pill--red{border-color:#dc2626;background:#fff}
          .pp-pill--lime{border-color:var(--public-brand-lime);background:#fff;color:var(--public-brand-green)}
          .pp-pill:hover{transform:translateY(-2px);box-shadow:var(--public-lift-shadow)}

          @media(max-width:1024px){
            .pp-pill{padding:12px 22px}
          }
          @media(max-width:767px){
            .pp-pill{padding:14px 26px}
          }
          @media(max-width:480px){
            .pp-pill{padding:12px 20px}
          }
          @media(max-width:360px){
            .pp-pill{padding:12px 18px}
          }
          @media(prefers-reduced-motion:reduce){
            .pp-pill{transition:none}
          }
        `}</style>
      </main>
    </>
  );
};

export default GrahakOsPage;
