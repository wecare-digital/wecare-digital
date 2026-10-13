/**
 * Grahak OS public product page
 * Customer engagement platform by WECARE.DIGITAL
 */

import React, { useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import PageMeta from '../../components/PageMeta';
import BrandBadge from '../../components/BrandBadge';
import PublicShare from '../../components/PublicShare';

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
  const [cycleIndex, setCycleIndex] = useState(0);
  const [heroWidth, setHeroWidth] = useState<number | null>(null);
  const heroRefs = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const id = window.setInterval(
      () => setCycleIndex(i => (i + 1) % cycleWords.length),
      2400
    );
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // RE-MEASURE ON RESIZE AND FONT-LOAD, not only when the word changes - the same fix
    // index.tsx and RotatingHero.tsx carry. Running on [cycleIndex] alone left the pill's px
    // width stale: hero font-size is a clamp(...vw...), so each word's rendered width depends on
    // the viewport, and the Inter webfont swaps in after first paint and widens every word. With
    // overflow:hidden on .hero-cycle a stale, too-narrow width clips the tail of the word
    // ("WhatsApp" -> "WhatsAp"). Under prefers-reduced-motion the interval never starts, so it
    // never self-heals. Observe the active word (not the pill, which this effect sets).
    const el = heroRefs.current[cycleIndex];
    if (!el) return undefined;
    const measure = () => setHeroWidth(el.offsetWidth);
    measure();
    if (typeof document !== 'undefined' && (document as any).fonts?.ready?.then) {
      (document as any).fonts.ready.then(() => measure());
    }
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [cycleIndex]);

  // NOTE: the rotating pill markup must be written INLINE in the returned JSX.
  // styled-jsx only attaches its scoping class to elements it can statically see
  // in the return tree - extracting this into a variable silently drops every
  // style, which renders the words stacked inline with no pill.
  
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
    return () => obs.disconnect();
  }, []);

  const show = (id: string) => visible.has(id);

  const useCases = ['Promotional', 'Transactional', 'Appointments', 'OTPs', 'Orders', 'Surveys'];

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

  const capabilities = [
    { title: 'Customer Data Platform', desc: 'One profile across every channel', icon: "data:image/svg+xml,%3csvg width='100%25' height='100%25' xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3e%3cg fill='none' stroke='%23333333' stroke-miterlimit='10' stroke-width='1.5' data-name='roll brush'%3e%3cpath d='M22.51 4.36c0 .87-1.38 1.63-3.58 2.16a30.8 30.8 0 0 1-7 .72 31 31 0 0 1-7-.72C2.79 6 1.41 5.23 1.41 4.36c0-1.59 4.73-2.87 10.59-2.87s10.51 1.28 10.51 2.87Z'/%3e%3cpath d='M22.51 4.36V12c0 .86-1.38 1.63-3.58 2.15a30.2 30.2 0 0 1-7 .72 30.3 30.3 0 0 1-7-.72C2.79 13.67 1.41 12.9 1.41 12V4.36C1.41 5.23 2.79 6 5 6.52a31 31 0 0 0 7 .72 30.8 30.8 0 0 0 7-.72c2.13-.52 3.51-1.29 3.51-2.16Z'/%3e%3cpath d='M22.51 12v7.67c0 .86-1.38 1.63-3.58 2.16a30.8 30.8 0 0 1-7 .72 31 31 0 0 1-7-.72c-2.19-.53-3.57-1.3-3.57-2.16V12c0 .86 1.38 1.63 3.57 2.15a30.3 30.3 0 0 0 7 .72 30.2 30.2 0 0 0 7-.72c2.2-.48 3.58-1.25 3.58-2.15ZM11 11.08h1.92m1.91 0h1.92m-9.59 0h1.92M11 18.75h1.92m1.91 0h1.92m-9.59 0h1.92'/%3e%3c/g%3e%3c/svg%3e" },
    { title: 'Custom Data Modeling', desc: 'Model customers, events and business objects', icon: "data:image/svg+xml,%3csvg width='100%25' height='100%25' xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24'%3e%3cpath stroke='%23333333' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M14 20a2 2 0 1 1-4 0m4 0a2 2 0 0 0-2-2m2 2h7m-11 0a2 2 0 0 1 2-2m-2 2H3m9-2v-4m9-9c0 1.657-4.03 3-9 3S3 6.657 3 5m18 0c0-1.657-4.03-3-9-3S3 3.343 3 5m18 0v6c0 1.66-4 3-9 3M3 5v6c0 1.66 4 3 9 3'/%3e%3c/svg%3e" },
    { title: 'Multichannel Orchestration', desc: 'Coordinate WhatsApp, SMS, Email and Voice', icon: "data:image/svg+xml,%3csvg width='100%25' height='100%25' xmlns='http://www.w3.org/2000/svg' data-name='Layer 1' viewBox='0 0 24 24'%3e%3cpath fill='none' stroke='%23333333' stroke-miterlimit='10' stroke-width='1.5' d='M7.23 10.14H1.5v5.72m14.32-9.54L12 2.5 8.18 6.32M12 2.5v21'/%3e%3cpath fill='none' stroke='%23333333' stroke-miterlimit='10' stroke-width='1.5' d='m1.5 10.14 5.56 5.56a3.82 3.82 0 0 1 1.12 2.7v5.1m8.59-13.36h5.73v5.72'/%3e%3cpath fill='none' stroke='%23333333' stroke-miterlimit='10' stroke-width='1.5' d='m22.5 10.14-5.56 5.56a3.82 3.82 0 0 0-1.12 2.7v5.1'/%3e%3c/svg%3e" },
    { title: 'Smart Personalization', desc: 'Trigger messages from customer behavior', icon: "data:image/svg+xml,%3csvg width='100%25' height='100%25' xmlns='http://www.w3.org/2000/svg' fill='%23333333' viewBox='0 0 16 16'%3e%3cpath d='M9 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0m-9 8c0 1 1 1 1 1h10s1 0 1-1-1-4-6-4-6 3-6 4m13.5-8.09c1.387-1.425 4.855 1.07 0 4.277-4.854-3.207-1.387-5.702 0-4.276Z'/%3e%3c/svg%3e" },
    { title: 'Enterprise Infrastructure', desc: 'Secure APIs built to scale', icon: "data:image/svg+xml,%3csvg width='100%25' height='100%25' xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24'%3e%3cpath stroke='%23333333' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M13 2 3 14h9l-1 8 10-12h-9l1-8Z'/%3e%3c/svg%3e" },
    { title: 'Predictive Analytics', desc: 'Turn engagement signals into actionable insights', icon: "data:image/svg+xml,%3csvg width='100%25' height='100%25' xmlns='http://www.w3.org/2000/svg' fill='none' stroke-width='1.5' viewBox='0 0 24 24'%3e%3cpath stroke='%23333333' stroke-linecap='round' stroke-linejoin='round' d='m21 19.452-9-6.61m0 0V3m0 9.843-9 6.609m17.438-2.742L21 19.452 18.188 20M9.75 5.194 12 3l2.25 2.194M5.813 20 3 19.452l.563-2.742'/%3e%3c/svg%3e" },
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
        title="Grahak OS by WECARE.DIGITAL - Customer Engagement Platform"
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
            data:image/svg+xml URIs and the Meta mark is meta-icon.svg from our own media
            host. Counted in the built export: two icons8 hints, zero icons8 requests.
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

        <section className={`hero anim ${armed ? 'is-armed' : ''} ${show('hero') ? 'show' : ''}`} id="hero">
          <div className="hero-content">
            <div className="hero-left">
              {/* Shared with the home page, so it lives in BrandBadge rather than
                  twice in two stylesheets. It self-styles: styled-jsx would not
                  reach a composite component's class names from here, which is the
                  same reason BrandLockup owns its block. The wrapper exists purely
                  to carry the spacing, since that is the one thing the page rather
                  than the component should decide. */}
              <div className="hero-eyebrow">
                <BrandBadge label="Grahak OS · by WECARE.DIGITAL" />
              </div>
              <h1>
                Reach customers<br />across{ ' ' }
                <span
                  className="hero-mark"
                  style={ { background: cycleWords[cycleIndex].tint } }
                >
                  <i
                    className="hero-mark-dot"
                    style={ { background: cycleWords[cycleIndex].dot } }
                    aria-hidden="true"
                  />
                  <span
                    className="hero-cycle"
                    style={ heroWidth ? { width: `${heroWidth}px` } : undefined }
                  >
                    <span className="sr-only">{ cycleWords.map(c => c.word).join(', ') }</span>
                    { cycleWords.map((c, i) => (
                      <span
                        key={ c.word }
                        ref={ el => { heroRefs.current[i] = el; } }
                        className={ `hero-cyc-word ${i === cycleIndex ? 'on' : ''}`.trim() }
                      data-wc-translate="true"
                        aria-hidden="true"
                      >{ c.word }</span>
                    )) }
                  </span>
                </span>
              </h1>
              {/* The channel list came out. The headline directly above this cycles
                  WhatsApp, SMS, Email and Voice one at a time, so naming all four again in
                  the next breath repeated the element immediately above it - and the same
                  list appears again in the strip and once more under Trusted by Meta. The
                  four pillars stay, because this is the one place on the page that should
                  state them; api-desc used to restate them and no longer does. */}
              <p>One platform for customer data, messaging, automation and campaigns, so every conversation stays connected whichever channel it starts on.</p>
              <p className="hero-sub">Turn your WhatsApp number into your #1 revenue channel with Grahak OS.</p>
            </div>
            <div className="hero-right">
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
                    <div className="avatar">W</div>
                    <div className="contact-info">
                      {/* A company name, not copy. Without this the translation
                          widget rewrote it, so the mock WhatsApp thread showed a
                          Tamil rendering of "WECARE.DIGITAL" as the business name -
                          which is exactly the sender a real customer would be
                          checking to see they are talking to the right company. */}
                      <span className="contact-name" data-wc-no-translate="true">WECARE.DIGITAL</span>
                      <span className="contact-status">online</span>
                    </div>
                    <div className="verified-badge"></div>
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
                    <div className="msg sent"><p>Your order #WD-87A6G has been shipped</p><span className="msg-time">10:30</span></div>
                    <div className="msg sent"><p>Track here: wecare.digital/track</p><span className="msg-time">10:30</span></div>
                    <div className="msg received"><p>When will it arrive?</p><span className="msg-time">10:31</span></div>
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
                      +24px on .mockup-wrapper and .chat-area min-height exists to
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
        </section>

        {/*
          Full-bleed tint pattern: touchpoint and capabilities sit on a #fafafa
          canvas that has to reach both window edges, so the 1300px measure moves
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
              <p>Engage, support, and convert customers across their entire journey — from first contact to lasting loyalty</p>
            </div>
            <div className="usecase-pills">
              {useCases.map((title, i) => (
                <span key={i} className="pp-pill">{title}</span>
              ))}
            </div>
          </div>
        </section>

        <section className={`api anim ${armed ? 'is-armed' : ''} ${show('api') ? 'show' : ''}`} id="api">
          <div className="api-grid">
            <div className="api-info">
              <h2>Built for your stack</h2>
              {/* Rewritten because the old line repeated the hero almost word for word
                  - "messaging, customer data, automation and campaigns" appeared in
                  both, and the same four pillars were being restated a third and fourth
                  time further down the page. A developer section should say something
                  the hero does not.
                  Grounded rather than written to sound good: the spec really does
                  expose one outbound endpoint per channel (/outbound-whatsapp,
                  /outbound-sms, /outbound-email, /outbound-voice), auth really is a
                  bearer token, and the canonical message store is the one in
                  docs/UNIFIED_MESSAGE_TABLE_DESIGN.md. */}
              <p className="api-desc">One POST per channel and a bearer token. Every message lands in the same canonical store the workspace reads, so your API traffic and your inbox are never two separate histories.</p>
            </div>
            <div className="api-demo">
              <div className="code-tabs">
                {codeExamples.map((c, i) => (
                  <button key={i} className={`pp-tab ${activeCode === i ? 'active' : ''}`} onClick={() => setActiveCode(i)}>{c.lang}</button>
                ))}
              </div>
              <pre className="code-block">{codeExamples[activeCode].code}</pre>
            </div>
          </div>
        </section>

        {/* Capabilities as a strip, not cards - approved after side-by-side review.
            This one section replaces two: the six-card grid, and a separate
            "Why Grahak OS" block whose three items restated three of these same six
            points with a fourth copy of the page's four-pillar sentence as its intro.
            Same six items, same titles, same one-line descs - one section.

            The heading and the subtitle BOTH go, on the owner's explicit instruction:
            "Everything you need / to grow customer relationships" and "AI-powered
            lifecycle management that delivers results". Neither asserted anything a
            visitor could check, and six items that each name themselves do not need a
            label announcing that they exist.

            The section is therefore deliberately unheaded. That is not an oversight and
            it is not an accessibility regression: a section with no accessible name is
            not exposed as a landmark at all, so this reads as a plain grouping rather
            than as an unnamed region cluttering landmark navigation. If a heading is
            ever wanted back, it needs to say something specific - not restate the
            four-pillar sentence the page already makes three times.

            Note alt="" on the icons. The cards used alt={cap.title} directly beside an
            h3 of the same string, so every title was announced twice by a screen reader
            and appeared twice in extracted text. The glyphs are decorative; the title
            next to them is the content. */}
        <section className={`pp-strip anim ${armed ? 'is-armed' : ''} ${show('capabilities') ? 'show' : ''}`} id="capabilities">
          <div className="pp-inner">
            <div className="pp-strip-grid">
              { capabilities.map( ( cap, i ) => (
                <div key={ i } className="pp-strip-item">
                  <div className="pp-strip-icon">
                    <img src={ cap.icon.replace( /%23333333/g, '%231a3a2a' ) } alt="" aria-hidden="true" loading="lazy" />
                  </div>
                  <div className="pp-strip-text">
                    {/* h3, NOT a span. These six card titles were spans, so the page's
                        whole heading outline was h1 + four h2s and the six capabilities
                        had no heading semantics at all - a screen-reader user could not
                        navigate to them and they were absent from the document outline.
                        Measured in the built export before this change: zero h3 elements
                        on the page, and six "<span class=... pp-strip-title".
                        h3 is the correct rung, not h2: these sit inside #capabilities,
                        whose preceding heading is the .api h2, so h2 -> h3 is a step with
                        no skipped level. The .pp-strip-title rule below owns the visual
                        size (22px/700/1.27/-.25px, the card-heading rung) and now also
                        resets the UA margin, so promoting the tag changes semantics only
                        and moves nothing on screen. */}
                    <h3 className="pp-strip-title">{ cap.title }</h3>
                    <span className="pp-strip-sub">{ cap.desc }</span>
                  </div>
                </div>
              ) ) }
            </div>
          </div>
        </section>

        <section className={`trust-strip anim ${armed ? 'is-armed' : ''} ${show('trust-strip') ? 'show' : ''}`} id="trust-strip" aria-label="Trusted by Meta">
          <div className="trust-grid">
            {/* Neutral card, not lime. Framing another company's logo in our own
                brand colour made a credential look like a sticker we printed
                ourselves; a borrowed mark should look borrowed.
                DESIGNATION: SETTLED, WITH EVIDENCE.
                Meta's App Dashboard confirms this app has been granted WhatsApp
                TECH PROVIDER status - its own words, "You are now a Tech Provider",
                with a Tech Provider onboarding section, an Embedded Signup Builder and
                a Tech Provider Content Hub. That is a real, Meta-issued designation, so
                "Trusted by Meta" in the heading beside this card is backed rather than
                asserted.
                The caption stays "Built on WhatsApp Business Platform" by owner choice:
                it is true, it needs no portal screenshot to defend, and it avoids the
                brand-usage question entirely. "WhatsApp Tech Provider" would now also be
                accurate and is Meta's exact phrase if a stronger line is ever wanted.
                The previous caption claimed a partner title that Meta does NOT issue -
                deliberately not quoted here, because a test asserts that exact string is
                absent from this file and a comment repeating it would defeat the guard.
                The comment on the right-hand column already learned this lesson once.
                For reference, the genuine terms are "Meta Business Partner"
                (an ads/marketing certification, badged and directory-listed, awarded
                after review on ad spend and Blueprint criteria) and, on the WhatsApp
                Business Platform, "Solution Partner" and "Tech Provider". "Meta Tech
                Partner" blended two unrelated programmes.
                Nothing available could confirm a granted designation. It is not a
                Graph API field - the public app record for 2238810740192680 returns
                only name, category and link. The Developer Tools / Social
                Technologies MCP is developer tooling and does not carry partner
                status. Application Rate Limit reflects API call capacity, not a
                badge. And this repo's own META-BETA-REQUEST-EMAIL.md says to CC a
                "BSP contact if you have one", which reads as no confirmed relationship.
                "Built on WhatsApp Business Platform" is therefore what the page says:
                verifiable from this codebase, and claiming no title at all.
                Meta's brand guidance is also to use the logo files they publish
                rather than a re-typed wordmark, so the span below remains a stand-in
                for a proper lockup asset. Do not upgrade this to a stronger claim
                without a Business Manager or partner-directory screenshot to back it. */}
            <div className="trust-card">
              {/* alt="" because the span beside it already says Meta. With alt="Meta" the
                  lockup announced the name twice and read as "Meta Meta" in extracted
                  text - the same defect the capability cards had. The mark is the glyph,
                  the span is the word; together they are one lockup, so only one of them
                  should carry the accessible name. */}
              <div className="trust-logo">
                <img className="trust-mark meta-mark" src="https://wecare.digital/get/o/stream/media/m/meta-icon.svg" alt="" aria-hidden="true" loading="lazy" />
                <span className="trust-wordmark">Meta</span>
              </div>
              <div className="trust-divider" />
              <span className="trust-caption">Built on WhatsApp Business Platform</span>
            </div>
            <div className="trust-content">
              {/* A self-declared official-partner pill used to sit here. Removed: it
                  restated the card's own claim a third time in one section, and a
                  badge asserting official status is the most legally exposed string
                  on the page. The card states the partnership once; this heading
                  makes the section's claim. (The exact former wording is not
                  repeated here on purpose - a test asserts it is gone from the
                  source, and a comment quoting it would defeat that.) */}
              <h2 className="trust-heading">Trusted by Meta</h2>
              <p className="trust-subtext">Customer engagement across WhatsApp, SMS, Email &amp; Voice — powered by Grahak OS.</p>
              <div className="trust-pills">
                <span className="pill">WhatsApp</span>
                <span className="pill">SMS</span>
                <span className="pill">Email</span>
                <span className="pill">Voice</span>
              </div>
            </div>
          </div>
        </section>

        <section className={`gos-closer anim ${armed ? 'is-armed' : ''} ${show('gos-closer') ? 'show' : ''}`} id="gos-closer">
          {/* Explicit break so the product name lands alone on the last line. Needs a
              br rather than the pre-line trick .section-header h2 uses, because
              .gos-closer-head does not set white-space. */}
          <h2 className="gos-closer-head">Transform customer<br/>engagement with<br/>Grahak OS</h2>
        </section>

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
          .page{min-height:100vh;padding:0;background:#fff;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1a1a1a;overflow-x:hidden}
          @supports (overflow-x:clip){
            .page{overflow-x:clip}
          }
          
          /* Animations
             THE FINISHED STATE IS WHAT CSS SHIPS, and .is-armed is what opts out of it.
             This block used to declare .anim{opacity:0} as the BASE state, with .show
             added by an IntersectionObserver inside a useEffect - so the only thing
             standing between a visitor and this page was JavaScript running. Measured
             against the export with javaScriptEnabled:false, all six sections (hero,
             touchpoint, api, pp-strip, trust-strip, gos-closer) rendered at opacity:0.
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
          .hero{padding:140px 24px 80px;max-width:1300px;margin:0 auto}
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
          .hero-left h1{font-size:clamp(36px,4.3vw,60px);font-weight:600;line-height:1.04;margin:0 0 24px;/* TRACKING IN em, NOT px. A fixed px value against a fluid clamp() font means the
             OPTICAL tightness changes with the viewport: measured across the breakpoints it ran
             -2.22% to -6.11% of the font size, a 2.75x spread, worst at 768-820px where the font
             is still on its 36px floor while the tracking was chosen for 60px. -0.04em is -4% at
             every size, and it lets both media-query overrides go - restating it per breakpoint
             is what caused the spread. index.tsx fixed this; these three copies had not. */
          letter-spacing:-0.04em;color:rgba(0,0,0,.95)}
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
          .hero-left p{font-size:20px;color:rgba(0,0,0,.898);line-height:1.4;letter-spacing:-.125px;font-weight:400;margin:0 0 18px;max-width:400px}
          .hero-left p.hero-sub{font-size:20px;color:rgba(0,0,0,.898);line-height:1.4;letter-spacing:-.125px;font-weight:400;margin:0;max-width:400px}

          /* Rotating channel pill in the hero headline (Notion-style). The lime
             tint is a pseudo-element so it can wipe in from the left without
             reflowing the sentence, and each word is absolutely stacked so
             swapping causes no reflow - the measured width animates instead. */
          /* Fully-rounded pill whose tint transitions with the word, matching the
             notion.com treatment (radius 9999px, transition on the colour). The
             tint itself is set inline per word; the reveal wipe lives on ::before. */
          .hero-mark{
            position:relative;display:inline-block;white-space:nowrap;
            padding:.02em .3em .02em .22em;
            border-radius:9999px;
            background:#e0f7c8;
            transition:background-color .52s cubic-bezier(.16,1,.3,1);
          }
          .hero-mark::before{
            content:'';position:absolute;inset:0;
            background:#fff;border-radius:9999px;
            transform:scaleX(1);transform-origin:right center;
            transition:transform .78s cubic-bezier(.16,1,.3,1) .18s;
            z-index:0;
          }
          .hero.show .hero-mark::before{transform:scaleX(0)}
          .hero-mark-dot{
            position:relative;z-index:1;
            /* 0.33em matches notion.com's ratio (32px dot against a 96px h1).
               Tight 0.1em gap - at 0.2em the dot read as detached from the word. */
            display:inline-block;width:.33em;height:.33em;
            background:#d1f470;border-radius:50%;
            margin-right:.18em;vertical-align:.14em;
            transform:scale(0);
            transition:transform .5s cubic-bezier(.34,1.56,.64,1) .72s;
          }
          .hero.show .hero-mark-dot{transform:scale(1)}
          /* PORTED FROM THE HOME BAND. Four implementations of this hero exist and every one
           carried the same defects; see docs/home-design-audit-20260926.md.

           width:max-content is the RESTING width. cycleW starts null, so the first render
           writes no inline width - and with every word absolutely positioned this box had no
           intrinsic width at all. It computed to 0px and overflow:hidden clipped the word
           away: ~200ms on every load, permanently with no JavaScript. JS still writes an
           explicit px width over this, which is what animates, so the glide is unchanged. */
        .hero-cycle{
          width:max-content;
            position:relative;z-index:1;
            display:inline-block;
            height:1.06em;line-height:1.06em;
            vertical-align:baseline;
            overflow:hidden;
            transition:width .52s cubic-bezier(.16,1,.3,1);
            will-change:width;
          }
          .hero-cyc-word{
            position:absolute;left:0;top:0;
            white-space:nowrap;
            opacity:0;
            transform:translateY(.42em);
            transition:opacity .42s cubic-bezier(.16,1,.3,1),transform .42s cubic-bezier(.16,1,.3,1);
          }
          /* The ACTIVE word returns to flow, which is what gives the box above a real
           intrinsic width. The inactive words stay absolute and keep stacking.

           display:inline-block IS LOAD-BEARING: position:static alone makes this a
           non-replaced inline box whose offsetWidth is 0, so the measuring effect would
           write width:0px over max-content and the pill would collapse on every load WITH
           JavaScript - a 200ms flash turned permanent. */
        .hero-cyc-word.on{opacity:1;transform:translateY(0);position:static;display:inline-block}
          .sr-only{
            position:absolute;width:1px;height:1px;padding:0;margin:-1px;
            overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
          }
          @media(prefers-reduced-motion:reduce){
            .hero-mark::before,.hero-mark-dot{transition:none}
            /* scaleX(0) is the RESTING state. scaleX(1) is the START state - a white
             shutter covering the tint - which is what this used to set. It never bit only
             because .hero-layout.show out-specifies it (0,2,1 vs 0,1,1). */
          .hero-mark::before{transform:scaleX(0)}
            .hero-mark-dot{transform:scale(1)}
            .hero-cycle{transition:none}
            .hero-cyc-word{transition:none}
          }

          /* THE HEADLINE MUST NOT CHANGE HEIGHT WHEN THE PILL CHANGES WORD.
             The h1 reads "Reach customers / across <pill>", and the pill animates to each
             word's measured width. Those words run from "SMS" to "WhatsApp" - 116px to
             262px at 1280, a 146px spread - so on a narrow screen the pill no longer fits
             beside "across", the line breaks somewhere new, and the h1 grows. Everything
             below it on the page then jumps by that much on every rotation, every 2.4s.
             Measured across 18 viewports, the h1 had two different heights at:
               320px      128 / 168px  (delta 40px)
               340-360px   87 / 128px  (delta 41px)
             and one stable height at 375px and above.
             Giving the pill its own line below 374px fixes it: the text above can no longer
             be pushed around by the pill's width, so the line count is the same for every
             word. width:fit-content is required with display:block - a plain block would
             stretch the tinted pill to the full column width.
             DELIBERATELY NOT APPLIED ABOVE 374px. From 375px up the headline already
             measures a constant height for every word, and forcing the break there would
             turn a correct two-line headline into three lines on every desktop.
             Re-measure with node tools/browser/animcheck.js if the word list changes - a
             word longer than "WhatsApp" can push the threshold above 374px.
             (No backticks in this comment on purpose - it sits inside a style jsx template
             literal, where one stray backtick ends the literal and fails the build with a
             misleading "Expected '</', got 'ident'" pointing at the JSX below.) */
          @media(max-width:374px){
            .hero-mark{display:block;width:fit-content}
          }
          
          /* Trusted by Meta section */
          /* 60/60, same as touchpoint / api / the strip. It was 20px top and 0 bottom
             with a 28px margin doing the bottom's job, which made this the only section
             off the page's rhythm: the strip's 60px bottom plus 20px here gave an 80px
             gap where every other boundary is 120px, and the grey band ends exactly at
             the strip's edge so the eye reads the tint boundary and then content 20px
             later. Padding rather than margin, so the section is measured the same way
             as its neighbours. */
          .trust-strip{max-width:1300px;margin:0 auto;padding:60px 24px}
          /* stretch, not center: the card holds only a logo and a designation, so on
             its own it is much shorter than the heading + copy + pills beside it and
             floated as a small box against a tall column. Stretching makes both
             halves the same height and the card centres its own content inside. */
          /* Uncapped, like .hero-content and now .api-grid. The previous pass capped this
             at 1100px to agree with api and strip; the reference turned out to be wrong.
             All four grids now share the hero's content box, so every section's left edge
             sits on the same vertical line down the page. */
          .trust-grid{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:stretch}
          /* HAIRLINE RULE — 2px means hoverable, 1px means static, and the colour
             is always #e5e7eb.
             That split is deliberate, not drift: .pill, .pp-pill and .mockup-wrapper
             are 2px and each has a :hover that swaps the border to lime, which needs
             the extra weight to register. This card is static and sits at 1px. Do NOT
             "unify" the two weights — you would flatten a working signal.
             (.capability-card and .cap-icon were the other two examples here until the
             card grid became .pp-strip, which is borderless precisely because it is not
             interactive.)
             What was actually inconsistent was this card's colour: it alone used
             rgba(0,0,0,.1) where the other six light hairlines use #e5e7eb, the
             value the design contract calls the shared hairline. Same lightness, so
             the change is near-invisible; the point is one token for one job.
             (.code-body's 1.5px white stroke is exempt — it is the editor-pane
             detail on a black panel, documented at its own rule.) */
          /* margin:0, not margin:0 auto. Centring a 430px card inside a 606px column put
             its left edge 88px right of every other section's - measured at 182px against
             the hero's 94px in a real browser. The card still centres its own contents;
             it is the card itself that now starts on the page's left line. */
          .trust-card{border:1px solid #e5e7eb;background:#fff;border-radius:20px;padding:34px 30px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;width:100%;max-width:430px;margin:0;box-sizing:border-box}
          .trust-logo{display:flex;align-items:center;gap:12px}
          .trust-mark{width:44px;height:44px;flex:0 0 auto;object-fit:contain}
          /* Black, matching the mark. It was dark green while meta-icon.svg renders
             black, so one logo lockup carried two different colours - the thing that
             made this read as slightly broken. 32px/700 rather than 36px/800 so the
             wordmark sits with the mark instead of shouting over the caption. */
          /* Onto the ladder. 32px/-1px was its own private type level, which is why this
             card read as belonging to a different page than the strip above it. 22px/700
             is the card-heading rung - the same size and weight as .pp-strip-title - so
             the Meta lockup now sits at the same level as every other named thing on the
             page, and the mark drops 46 -> 44px to match the strip's icon size. */
          /* line-height:1.27 completes the card-heading rung, which this rule declared three
             quarters of. The comment above says "22px/700 is the card-heading rung - the same
             size and weight as .pp-strip-title", and the size, weight and tracking all matched;
             the line-height was simply never declared, so it inherited and measured 34.1px
             against the rung's 27.94px. .pp-strip-title, the other member of the rung, has
             always had it. One undeclared property is how a heading ends up 6px taller than the
             rung it is documented as belonging to. */
          .trust-wordmark{font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;color:#000}
          .trust-divider{width:100%;height:1px;background:rgba(0,0,0,.09)}
          /* Body level, 20px/400, not a second 22px/700 line. The designation describes the
             lockup above it rather than competing with it, and two bold 22px lines stacked
             gave the card no internal hierarchy at all. */
          .trust-caption{font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898);text-align:center}
          .trust-content{display:flex;flex-direction:column;align-items:flex-start;gap:16px;min-width:0}

          /* ===== Closing statement (Notion-style display type + motion) ===== */
          /* 1100 -> 1300 measure and 96/112 -> 60/80 padding, so this section is measured
             and spaced like every other one. The extra 36px of top padding was the only
             thing making the closer a special case in the rhythm, and 80px at the bottom
             still gives the page a softer landing into the footer than a flat 60 would. */
          .gos-closer{max-width:1300px;margin:0 auto;padding:60px 24px 80px;display:flex;justify-content:center}
          /* Hero h1 level, exactly: clamp(36px,4.3vw,60px) / 600 / -2.2px.
             It was clamp(38px,6vw,84px), which at any viewport above ~630px rendered
             LARGER than the hero headline and inverted the page's hierarchy - the closing
             line shouting over the opening one. This is a page-level statement rather than
             a section heading, which is why it takes the h1 rung and its 600 weight
             instead of the heavier 700 section level. */
          /* WAS WEARING THE HERO H1'S CLAMP: clamp(36px,4.3vw,60px) at weight 600, which
             resolved to 55.04px/600 - larger than the 54px the contract caps an h2 at, and
             inverting the contract's one hard rule that a section h2 is 700 and therefore
             HEAVIER than the h1's 600. It was an h2 dressed as an h1, and it made
             /grahak-os/ the only page carrying two different section-h2 sizes at once
             (53.76 and 55.04). Now on the same rung as every other section heading. */
          .gos-closer-head{
            font-size:clamp(28px,3.2vw,40px);
            font-weight:700;
            letter-spacing:-1.2px;
            line-height:1.08;
            color:rgba(0,0,0,.95);
            text-align:center;
            margin:0;
            max-width:960px;
          }

          .trust-heading{margin:0}
          .trust-subtext{font-size:20px;color:rgba(0,0,0,.898);line-height:1.4;letter-spacing:-.125px;font-weight:400;margin:0}
          .trust-pills{display:flex;flex-wrap:wrap;gap:12px}

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
          .mockup-wrapper{position:relative;width:100%;max-width:580px;min-height:638px;background:#fff;border-radius:28px;padding:28px 24px 24px}
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
          .phone-header{background:#1a3a2a;padding:12px 14px;display:flex;align-items:center;gap:10px}
          .avatar{width:40px;height:40px;background:#1a3a2a;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:16px}
          .contact-info{flex:1;display:flex;flex-direction:column}
          .contact-name{color:#fff;font-size:17px;font-weight:600}
          .contact-status{color:rgba(255,255,255,.7);font-size:13px}
          .verified-badge{width:22px;height:22px;background:#1a3a2a;border-radius:50%}
          /* 480 -> 504, the paired half of the +24 on .mockup-wrapper. Growing the
             wrapper alone would have left the panel overhanging the phone by 44px
             instead of ~20px; growing the phone by the same amount keeps that. The
             extra height lands as empty beige below the typing dots, which is what
             a real thread looks like anyway. */
          .chat-area{background:#ece5dd;padding:16px 14px;min-height:528px;display:flex;flex-direction:column;gap:9px}
          .msg{max-width:82%;padding:10px 13px;border-radius:8px;font-size:17px;line-height:1.42;color:#000}
          /* Received bubbles are capped narrower than sent ones. They sit low in the
             thread, inside the band the code panel laps, and at 82% they grew past
             the panel's left edge and got clipped on their RIGHT - which looks like
             a rendering fault rather than a deliberate overlap. 66% keeps them clear
             of it. */
          .msg.received{background:#fff;align-self:flex-start;max-width:66%;border-top-left-radius:3px}
          .msg.sent{background:#d1f470;align-self:flex-end;border-top-right-radius:3px}
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
          .msg-time{font-size:12px;color:#54656f;display:block;text-align:right;margin-top:3px}
          .typing-indicator{background:#fff;padding:10px 14px;border-radius:8px;align-self:flex-start;display:flex;gap:4px}
          .typing-indicator span{width:7px;height:7px;background:#1a3a2a;border-radius:50%;animation:bounce 1.4s infinite}
          .typing-indicator span:nth-child(2){background:#86b817;animation-delay:.2s}
          .typing-indicator span:nth-child(3){background:#c3e85a;animation-delay:.4s}
          @keyframes bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-3px)}}

          /* Code Box */
          /* Pure black, not slate. The panel reads as a terminal against the warm
             chat beige, and the slate #1e293b muddied that contrast. */
          .code-box{position:absolute;right:0;bottom:0;width:60%;max-width:340px;background:#000;border-radius:14px;overflow:hidden;box-shadow:0 20px 50px rgba(0,0,0,.2)}
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
          /* ONE section-heading rule for all three places that use the level. The value
             was declared identically three times - here, on .api-info h2 and on
             .trust-heading - which is three chances for the page to drift out of step
             with itself. Only the per-place differences stay separate below: margins,
             alignment and .section-header's pre-line. */
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
          .section-header h2,.api-info h2,.trust-heading{font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;letter-spacing:-1.2px;color:rgba(0,0,0,.95)}
          .section-header h2{margin:0 0 14px;text-align:center;width:100%;white-space:pre-line}
          .section-header p{font-size:20px;color:rgba(0,0,0,.898);line-height:1.4;letter-spacing:-.125px;font-weight:400;margin:0;text-align:center;width:100%}
          
          /* Touchpoint Section */
          .touchpoint{padding:60px 0;background:#fff}
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
             #fafafa band - passing AA, but only just, and it read washed out next to
             the near-black heading above. Body colour rgba(0,0,0,.898) is ~14:1 and
             makes the pills look deliberate rather than disabled.
             15px inside 14px/28px padding put the type-to-pill ratio near 3.1, the
             same proportion problem the 46px nav row had at 15px. 17px brings it to
             about 2.8. */
          .pill{padding:14px 28px;border:2px solid #e5e7eb;background:#fff;border-radius:50px;font-size:17px;font-weight:600;cursor:default;transition:all .25s;color:rgba(0,0,0,.898)}
          .pill:hover{border-color:#d1f470;color:#1a3a2a;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
          
          /* API Section */
          .api{padding:60px 24px;max-width:1300px;margin:0 auto;background:#fff}
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
          .api-desc{font-size:20px;color:rgba(0,0,0,.898);line-height:1.4;letter-spacing:-.125px;font-weight:400;margin:0;max-width:460px}
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
          .api-demo{background:#000;border-radius:14px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.12)}
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
          .pp-tab{display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;font-family:inherit;padding:10px 20px;min-height:44px;border:none;border-radius:8px;font-size:15px;font-weight:600;color:rgba(255,255,255,.54);background:transparent;box-shadow:none;cursor:pointer;transition:all .2s}
          /* Text-only hover: idle .54 white lifting to full white. The active tab
             already owns the filled-lime state, so a second fill competes with it. */
          .pp-tab:hover{color:#fff;background:transparent}
          .pp-tab.active{background:#d1f470;color:#1a3a2a;box-shadow:none}
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
          /* No background tint on hover — #fbfff0 is retired. The card already
             sits on #fff against the #fafafa canvas, so the lime border reads. */
          
          /* Why sits on plain white between the two grey canvases; borders and
             body text use the shared hairline/muted pair, not near-miss greens. */

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
            .code-box{position:relative;right:auto;left:auto;bottom:auto;width:100%;max-width:100%}
          }

          @media(max-width:1024px){
            
            .hero{padding:110px 20px 60px}
            .hero-content{grid-template-columns:1fr;gap:40px;text-align:left}
            .hero-left h1{letter-spacing:-1.8px;max-width:760px;margin:0 0 20px}
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
            .code-box{position:relative;right:auto;left:auto;bottom:auto;width:100%;max-width:100%}
            .phone{left:16px;top:16px;width:52%}
            .code-box{right:auto;left:12px;bottom:16px;width:55%}
            
            .section-header{padding:0 20px}
            
            .trust-strip{padding:50px 20px}
            .trust-grid{grid-template-columns:1fr;gap:28px}
            .trust-content{align-items:flex-start}

            .touchpoint{padding:50px 0}
            .usecase-pills{gap:10px}
            .pill{padding:12px 22px;font-size:14px}
            
            .api{padding:50px 20px}
            .api-grid{grid-template-columns:1fr;gap:36px;text-align:left}
            .api-info h2{text-align:left}
            .api-desc{max-width:100%;text-align:left}
            .api-demo{max-width:500px;margin:0}
            
            
          }

          /* ========== MOBILE (up to 767px) ========== */
          @media(max-width:767px){
            
            .hero{padding:calc(115px + env(safe-area-inset-top)) 20px 50px}
            .hero-content{display:flex;flex-direction:column;gap:32px;text-align:left;align-items:flex-start}
            .hero-right{order:-1;width:100%;display:flex;justify-content:center}
            .hero-left{text-align:left;order:1}
            .hero-left h1{letter-spacing:-1.2px;margin:0 0 20px;line-height:1.1;max-width:100%;text-align:left}
            .hero-left p{margin:0 0 16px;max-width:100%;text-align:left}
            
            .trust-strip{padding:44px 20px}
            .trust-grid{grid-template-columns:1fr;gap:24px}
            .trust-card{padding:36px 24px;gap:20px;max-width:100%}
            /* No .trust-mark or .trust-wordmark size overrides here any more. They
               forced 46px/32px, which was left behind when the lockup was moved onto
               the type ladder at 44px/22px - so the wordmark rendered LARGER on a
               phone than on a desktop, and sat 10px above the 22px .pp-strip-title in
               the strip directly overhead while the 20px caption beside it did not
               move at all. .pp-strip-icon and .pp-strip-title carry no breakpoint
               overrides, so the card now holds one scale at every width, which was
               the point of putting it on the ladder. */
            .trust-pills{gap:10px}

            .mockup-wrapper{display:flex;flex-direction:column;gap:14px;width:100%;max-width:380px;margin:8px auto 0;aspect-ratio:auto;padding:16px;background:#fff;border-radius:16px;border:2px solid #e5e7eb;align-items:flex-start;transition:all .25s;cursor:default}
            .mockup-wrapper:hover{border-color:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
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
            
            .code-box{position:relative;right:auto;bottom:auto;width:100%;max-width:100%;margin:0;border-radius:14px;box-shadow:0 4px 20px rgba(0,0,0,.1);align-self:flex-start}
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
            .api-demo{border-radius:14px;max-width:100%;margin:0}
            .code-tabs{padding:16px;gap:10px;justify-content:flex-start;flex-wrap:wrap}
            .pp-tab{padding:14px 24px;font-size:18px}
            .code-block{font-size:14px;padding:18px;min-height:auto;text-align:left;white-space:pre-wrap;word-break:break-word;overflow-x:visible;line-height:1.7}
            
            
          }

          /* ========== SMALL MOBILE (up to 480px) ========== */
          @media(max-width:480px){
            
            .hero{padding:calc(85px + env(safe-area-inset-top)) 16px 44px}
            .hero-left h1{letter-spacing:-1px;line-height:1.12}
            
            .section-header{padding:0 16px}
            .trust-strip{padding:36px 16px}
            .trust-card{padding:30px 20px}
            .gos-closer{padding:64px 20px 76px}
            .gos-closer-head{letter-spacing:-1.4px;line-height:1.1}
            /* .trust-mark 42px and .trust-wordmark 30px removed alongside the 1024px
               pair above - the same stale pre-ladder sizes. Padding still tightens
               here; only the type and the mark stop moving. */

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
            .pill{padding:12px 20px;font-size:18px}
            
            .api{padding:36px 16px}
            .api-info h2{text-align:left}
            .api-desc{text-align:left}
            .code-tabs{gap:8px;padding:14px}
            .pp-tab{padding:12px 20px;font-size:17px}
            .code-block{font-size:14px;padding:16px;min-height:auto;text-align:left;white-space:pre-wrap;word-break:break-word;overflow-x:visible;line-height:1.65}
            
            
          }
          
          /* ========== VERY SMALL SCREENS (up to 360px) ========== */
          @media(max-width:360px){
            
            /* 16px, not 14px. Every other section stays on 16px at this width - the 480px
               block sets api, trust-strip and .pp-inner to 16 and nothing overrides them
               here - so the hero alone sat 2px left of everything else. Measured at 360px:
               hero text at 14px, the rest at 16px. */
            .hero{padding:calc(80px + env(safe-area-inset-top)) 16px 36px}
            .hero-left h1{letter-spacing:-.8px}
            
            .pill{padding:12px 18px;font-size:17px}
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
          /* One responsive type hierarchy, declared after the legacy breakpoint
             rules so a single clamp() governs each size at every width. The hero
             h1 and p are intentionally absent: their base rule is the contract. */
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
          .pp-tab{font-size:15px}
          
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
             The grey canvases have to reach both window edges, so the 1300px
             measure moves off the section and onto .pp-inner: 100vw plus a
             centring negative margin makes the tint exactly window.innerWidth
             wide, where a plain background would stop short of each edge.
             .page already clips overflow-x, so this adds no horizontal scroll.
             Everything here is pp- prefixed because the globally imported
             src/styles/*.css declares unscoped rules for generic names like
             .pill / .stat / .phone / .chat-area that styled-jsx cannot shield
             the page from; the id selectors beat the shared section classes
             regardless of source order. */
          #touchpoint,#capabilities{max-width:none;width:100vw;margin-left:calc(50% - 50vw);background:#fafafa}
          /* 1252px, not 1300px, and the difference is the point. A section like .hero is a
             1300px box with 24px padding, so its CONTENT starts at 1300-48 = 1252px wide.
             The full-bleed sections put their padding on the outer 100vw element and then
             nest this, so at 1300px this inner box started 24px left of the hero's content
             edge. Measured in a real browser at 1440px: hero text at 94px, strip items at
             70px. 1252px makes both 94px. */
          .pp-inner{max-width:1300px;margin:0 auto;padding:0 24px;box-sizing:border-box}
          /* The share block's wrapper adds the sitewide bottom rhythm (.pp-inner has none), so the
             block's bottom air matches home / rh-layout / PageTopBand (96px, 64px under 768px). */
          .gos-share-wrap{padding-bottom:48px}
          @media(max-width:767px){ .gos-share-wrap{padding-bottom:40px} }

          /* ===== TEMPORARY: proposed Capabilities strip, for side-by-side review =====
             NO NEW TOKENS. Every value below already exists in the language:
               icon fill   rgba(209,244,112,.22)  the nav hover / active tint
               icon glyph  #1a3a2a                palette dark green
               title       22px/700/-.25px/#000   the card-heading level, unchanged
               subtitle    14px/400 rgba(0,0,0,.54) the label level
             22 over 14 is what produces the compact feel, using two rungs of the
             existing ladder rather than inventing a smaller heading.
             Borderless on purpose: the cards it replaces carry a 2px hairline and a
             lime hover while also being cursor:default, so they look clickable and are
             not. Per the hairline rule 2px means hoverable, so a non-interactive strip
             should carry no border and no hover at all. */
          .pp-strip{padding:60px 0}
          /* No .pp-strip .section-header rules here any more. They existed only to
             left-align and un-cap a heading this section no longer has, so they went
             with it rather than being left to look load-bearing. .section-header is
             still shared with #touchpoint, whose heading IS centred over centred
             pills - so anything re-added here must stay scoped to .pp-strip. */
          .pp-strip-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:30px 24px}
          .pp-strip-item{display:flex;align-items:flex-start;gap:14px;min-width:0}
          .pp-strip-icon{width:44px;height:44px;flex:0 0 auto;box-sizing:border-box;padding:10px;border-radius:50%;background:rgba(209,244,112,.22);display:flex;align-items:center;justify-content:center}
          .pp-strip-icon img{width:100%;height:100%;object-fit:contain;display:block}
          .pp-strip-text{display:flex;flex-direction:column;gap:5px;min-width:0}
          /* margin:0 is load-bearing now that this is an h3 rather than a span. Without it
             the UA stylesheet's h3 margin (1em top and bottom) would open ~22px above and
             below every card title and push the strip's height out. The rung values are
             unchanged - promoting the tag was a semantics fix, not a design change. */
          .pp-strip-title{font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;color:#000;margin:0}
          .pp-strip-sub{font-size:14px;font-weight:400;line-height:1.4;color:rgba(0,0,0,.54)}
          @media(max-width:1024px){
            .pp-strip-grid{grid-template-columns:repeat(2,1fr);gap:26px 20px}
            .pp-strip{padding:50px 0}
            .pp-inner{padding:0 20px}
          }
          @media(max-width:767px){
            .pp-strip-grid{grid-template-columns:1fr;gap:22px}
            .pp-strip{padding:44px 0}
            .pp-inner{padding:0 20px}
          }
          @media(max-width:480px){
            .pp-strip{padding:36px 0}
            .pp-inner{padding:0 16px}
          }

          /* Use-case pills as spans, since they carry no handler. Same paint as
             .pill; inline-flex restores the centring a button gets for free. */
          /* Paint matches .pill exactly — muted black label, no retired hover
             tint. min-height is dropped: at 15px with 14px of vertical padding the
             pill computes to ~48px, so a 32px floor never applied and only implied
             a constraint that was not doing anything. */
          .pp-pill{display:inline-flex;align-items:center;justify-content:center;padding:14px 28px;border:2px solid #e5e7eb;background:#fff;border-radius:50px;font-size:17px;font-weight:600;cursor:default;transition:all .25s;color:rgba(0,0,0,.898)}
          .pp-pill:hover{border-color:#d1f470;color:#1a3a2a;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}

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
