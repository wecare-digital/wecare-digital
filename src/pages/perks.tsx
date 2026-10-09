import React, { useEffect, useRef } from 'react';
import PageMeta from '../components/PageMeta';
import RotatingHero from '../components/RotatingHero';
import type { CycleWord } from '../components/RotatingHero';

/**
 * /perks — a little extra for the people we look after.
 *
 * SECTION 4 of the customer-experience brief, and the repaired destination for the several
 * systems that link customers to a gift-card URL. The page's customer-facing name is "Perks",
 * matching its /perks/ route, and the brand badge carries the full house form
 * "Perks by WECARE.DIGITAL".
 *
 * IT WAS BRIEFLY RENAMED "EXTRAS" AND THE OWNER REVERSED THAT (2026-10-02). The nav was rendering
 * a row labelled "Extras" directly beneath a group heading also reading "Extras" — the same word
 * twice, one under the other — and PUBLIC_PAGE_META still carried `name: 'Extras'`, which feeds
 * this route's WebPage schema and config/public-pages.json, so the wrong name was being published
 * regardless of the label. The name is "Perks" everywhere now. The group HEADING in the header
 * stays "Extras" (it is the category); the ROW is this page's name, "Perks".
 *
 * MATCHES THE HOME PAGE, by owner request — exactly as /shipments/ does. Perks previously used
 * components/PageTopBand (the fixed-statement band) and carried three in-page sections — Gift
 * Cards (#gift-cards), Offers (#offers) and Rewards (#rewards) — rendered as non-transacting
 * "coming soon" placeholders. The owner asked to make Perks share the HOME PAGE's look (its
 * animated hero and its scroll-reveal closing band) AND to remove those gift-card / offers /
 * rewards sections. Both are done here.
 *
 * This page now reuses the SAME two mechanisms the home page animates with — the proven
 * /shipments/ pattern — rather than copying their markup or inventing a lookalike:
 *   1. THE ROTATING HERO. components/RotatingHero is the reusable, self-styling version of the
 *      home page's headline pill (identical interval, easings, white entrance shutter and dot;
 *      tools/browser/animcheck.js asserts the family shares one computed transition set). It is
 *      what /shipments/, /shop/, /blog/ and every product page already reuse. The hero owns the page's
 *      single <h1> and single <main>; the page must not add a second of either. The rotation
 *      cycles words that are TRUE OF PERKS — thanks / care / extra / you — rather than the home
 *      page's marketing audiences, so the words are the page's own and are not borrowed from
 *      /shipments/.
 *   2. THE SCROLL-REVEAL CLOSING BAND. The home page's closing band reveals once when it scrolls
 *      into view: a lime rule draws itself across and the lines stagger in behind it. It is an
 *      OPT-IN entrance — the CSS ships the final, visible state and JavaScript adds .is-armed only
 *      once it has confirmed it can animate, so no JS, no IntersectionObserver or reduced motion
 *      all leave the band fully readable. This page replicates that exact mechanism (closeRef +
 *      a one-shot IntersectionObserver at threshold 0.18, armed through the node's classList, the
 *      final state shipped as the CSS default), so the degradation and accessibility guarantees
 *      are the same ones the home page and /shipments/ proved.
 *
 * SECTIONS REMOVED, per owner instruction. The Gift Cards (#gift-cards), Offers (#offers) and
 * Rewards (#rewards) sections and their anchors are gone. They were honest-empty, non-transacting
 * placeholders with no backend, so removing them loses no capability. The Header "Perks" group was
 * collapsed from three anchor rows (Gift Cards/Rewards/Offers) to a single link to /perks/ so that
 * nothing points at a removed anchor. The active gift-card CTAs in the WhatsApp, AI and SEO-tools
 * handlers already point at https://wecare.digital/perks/ (the page itself, not #gift-cards), so
 * removing the anchors leaves no dead backend link. The gift-card / coupon / rewards TERMS in
 * src/content/legal still stand (those features exist conceptually and coupons still apply at
 * checkout); only the now-false comment claims that a "/perks Rewards section" or "/perks offers"
 * exists were corrected for truthfulness.
 *
 * NO THIRD-PARTY PROVIDER NAME. "Gift Up", "GiftUp" and any vendor name are absent on purpose —
 * the brief forbids surfacing one in customer-facing UI.
 *
 * NON-TRANSACTING BY DESIGN. There is no gift-card, rewards or offers backend in this repository,
 * so this page carries no buy/redeem/check-balance/apply control. It is an honest, home-styled
 * landing page that points customers at pages that already work; it invents no points, balances,
 * reward history or live offers.
 *
 * SHARED SHELL, NOT A NEW ONE. Header, Footer and the support widget are mounted once in _app.tsx,
 * so this page must not import them. RotatingHero provides the one <main> and the one <h1>.
 *
 * ROUTING: '/perks' is registered in PUBLIC_PAGE_META (_app.tsx), PUBLIC_EXACT
 * (scripts/generate-sitemap.js) and config/public-pages.json (generated, group 'perks').
 * trailingSlash means the URL is /perks/.
 */

// The hero's rotating nouns. Chosen to be TRUE OF PERKS rather than borrowed from the home page's
// audiences or from the Shipments request/delivery/pickup set: Perks is a small thank-you for the people
// we look after, so the rotation names that — thanks / care / extra / you. Tints/dots are the four
// per-subject pairs the shared hero family already uses verbatim; no new colour. Lengths are
// 6 / 4 / 5 / 3 characters, inside RotatingHero's narrow-breakpoint fit.
const PERKS_WORDS: CycleWord[] = [
  { word: 'thanks', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'care', tint: '#ede9fe', dot: '#9849e8' },
  { word: 'extra', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'you', tint: '#fef3c7', dot: '#f0a818' },
];

const PerksPage: React.FC = () => {
  // The scroll-reveal closing band, armed through this node — the SAME mechanism the home page and
  // /shipments/ use. No React state: the reveal is a visual side-effect with no bearing on what React
  // renders, so it is driven by classList on the node itself.
  const closeRef = useRef<HTMLElement | null>( null );

  useEffect( () => {
    const el = closeRef.current;
    if ( !el ) return undefined;

    // THE ANIMATION IS OPT-IN, NOT OPT-OUT, ported from index.tsx's closing band. The CSS ships
    // the FINAL state — everything visible — and this effect adds .is-armed to hide the start
    // state only once it knows it can animate. No JS, no IntersectionObserver, or reduced motion
    // all leave the band fully readable.
    if ( typeof IntersectionObserver === 'undefined' ) return undefined;
    // typeof guard as well as the call: jsdom does not implement matchMedia and throws rather than
    // returning undefined, so a page must not depend on the test setup stubbing it.
    const reduce = typeof window.matchMedia === 'function'
      && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
    if ( reduce ) return undefined;

    el.classList.add( 'is-armed' );

    const io = new IntersectionObserver(
      entries => {
        if ( entries.some( e => e.isIntersecting ) ) {
          el.classList.add( 'is-in' );
          io.disconnect(); // One-shot: it is an entrance, not a scroll effect.
        }
      },
      // 18% visible before it plays — the same threshold the home page and /shipments/ use.
      { threshold: 0.18 }
    );
    io.observe( el );

    return () => io.disconnect();
  }, [] );

  return (
    <>
      <PageMeta
        title="Perks — WECARE.DIGITAL"
        description="A little extra for the people we look after. An honest, uncluttered place for the small thank-yous we send your way, and nothing here asks for payment."
        path="/perks/"
      />
      {/* badgeLabel carries the FULL "<Name> by WECARE.DIGITAL" house form, which is what the owner
          asked for and what /submit-request/, /bharat-rx/ and /contact/ already render. It was bare
          "Extras" before — both the wrong name AND missing the suffix, which is the omission the
          owner reported. The badge is the first, prominent, translation-safe line on the page while
          the hero owns the <h1> and the one <main> landmark. */}
      <RotatingHero
        badgeLabel="Perks by WECARE.DIGITAL"
        frame="A little extra, made for"
        words={ PERKS_WORDS }
        sub="A small thank-you for the people we look after."
        ariaLabel="Perks"
      >
        <section className="pk-in" aria-label="About Perks">
          <h2 className="pk-h2">A little extra, made for you</h2>
          <p className="pk-p">
            Perks is where the small thank-yous live. We would rather keep this honest and quiet
            than fill it with points balances or offers we cannot stand behind — so right now it is
            a calm landing page, and nothing here asks for payment.
          </p>
          <p className="pk-p">
            When there is something real to give you, this is where it will show up. Until then, the
            pages below are the ones that already work.
          </p>
        </section>

        {/* THE CLOSING BAND, replicating the home page's scroll-reveal treatment. It is a direct
            child of RotatingHero's .rh-layout, so the 96px section gap and the page measure are
            already applied — no margin-top. The reveal is OPT-IN: everything below ships visible as
            the CSS default and the closeRef effect only hides the start state once it can animate. */}
        <section className="pk-close" aria-labelledby="pk-close-title" ref={ closeRef }>
          <div className="pk-close-panel">
            <p className="pk-close-eyebrow">Perks</p>
            <h2 className="pk-close-title" id="pk-close-title">A little extra, honestly done.</h2>
            <p className="pk-close-lead">
              We will not show you a points balance that is not real or an offer we cannot honour.
              When there is a genuine thank-you to give, it lands here — in your language, your way.
            </p>
            <span className="pk-close-rule" aria-hidden="true" />
            <ul className="pk-close-points">
              <li>Nothing here asks for payment.</li>
              <li>We say plainly what is not ready yet.</li>
              <li>Any eligible coupon is applied at checkout, not here.</li>
            </ul>
            {/* A PLAIN <a>, and it must stay one: styled-jsx only scopes lowercase DOM tags, so a
                next/link carrying pk-close-cta would render unstyled. Every CTA on the public pages
                is a plain <a> for the same reason. */}
            <a className="pk-close-cta" href="/shop/">See what we offer</a>
          </div>
        </section>

        <style jsx>{`
          /* pk- prefixed: the globally imported src/styles/*.css declares unscoped rules for
             generic names and styled-jsx does not shield a page from them. */
          .pk-in{max-width:900px}
          /* Section h2 is the contract's 700 rung — HEAVIER than the hero h1's 600, the site's
             deliberate inversion. */
          .pk-h2{
            font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;
            letter-spacing:-1.2px;color:rgba(0,0,0,.95);margin:0 0 14px;
          }
          /* The one body rung: 20px/400/1.4/-.125px at rgba(0,0,0,.898). */
          .pk-p{
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);margin:0 0 18px;max-width:640px;
          }
          .pk-p:last-of-type{margin-bottom:0}

          /* THE CLOSING BAND — the home page's .home-close treatment, kept pk- prefixed.
             A tinted own-surface panel: the same 14px radius and rgba(209,244,112,.22) lime tint
             the rest of the site uses, with a 2px #d1f470 edge — no new colour. */
          .pk-close-panel{
            padding:clamp(28px,4vw,56px);
            border:2px solid #d1f470;border-radius:14px;
            background:rgba(209,244,112,.22);
          }
          .pk-close-eyebrow{
            margin:0 0 14px;font-size:12px;font-weight:700;
            letter-spacing:.08em;text-transform:uppercase;color:#1a3a2a;
          }
          /* Section h2 on the 700 rung — heavier than the hero h1's 600, the site's inversion.
             Same clamp as the other section headings so they read as siblings. */
          .pk-close-title{
            margin:0 0 16px;max-width:19ch;
            font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;
            letter-spacing:-1.2px;color:rgba(0,0,0,.95);
          }
          .pk-close-lead{
            margin:0;max-width:62ch;
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);
          }

          /* READ THE .is-armed PATTERN BEFORE CHANGING ANY OF THIS. Every rule below ships its
             FINAL, visible state as the default. .is-armed is added by JavaScript only when it has
             confirmed it can animate, and that is what hides the start state; .is-in then plays the
             reveal. The effect is therefore additive, and no JS / no IntersectionObserver /
             reduced motion all leave this section fully readable. */

          /* THE RULE DRAWS ITSELF. transform:scaleX is compositor-only, so it cannot cause layout
             on any frame the way animating width would. transform-origin:left makes it grow from
             the left edge. */
          .pk-close-rule{
            display:block;height:3px;margin:30px 0;background:#d1f470;
            transform-origin:left center;
            transition:transform .62s cubic-bezier(.22,.61,.36,1);
          }
          .pk-close.is-armed .pk-close-rule{transform:scaleX(0)}
          .pk-close.is-armed.is-in .pk-close-rule{transform:scaleX(1)}

          .pk-close-points{margin:0;padding:0;max-width:62ch;list-style:none;display:flex;flex-direction:column;gap:12px}
          .pk-close-points li{
            position:relative;padding-inline-start:26px;
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898);
            transition:opacity .5s ease,transform .5s ease;
          }
          /* A tick drawn with two borders on a rotated box: no asset, cannot 404. The three ticks
             carry the home band's green / blue / purple, in the same top-to-bottom order, so the
             pages read as a family. */
          .pk-close-points li:nth-child(2)::before{border-left-color:#2563eb;border-bottom-color:#2563eb}
          .pk-close-points li:nth-child(3)::before{border-left-color:#9849e8;border-bottom-color:#9849e8}
          .pk-close-points li::before{
            content:'';position:absolute;inset-inline-start:2px;top:7px;
            width:11px;height:6px;
            border-left:2.5px solid #3da35a;border-bottom:2.5px solid #3da35a;
            transform:rotate(-45deg);
          }
          .pk-close.is-armed .pk-close-points li{opacity:0;transform:translateY(8px)}
          .pk-close.is-armed.is-in .pk-close-points li{opacity:1;transform:none}
          /* Staggered behind the rule, which finishes at .62s. Three 90ms steps read as one
             settling movement rather than three separate events. */
          .pk-close.is-armed.is-in .pk-close-points li:nth-child(1){transition-delay:.34s}
          .pk-close.is-armed.is-in .pk-close-points li:nth-child(2){transition-delay:.43s}
          .pk-close.is-armed.is-in .pk-close-points li:nth-child(3){transition-delay:.52s}

          /* Full-strength lime with #1a3a2a type and a #1a3a2a border — the contract's own-surface
             pairing, and the border is #1a3a2a (not the lime fill) so the control's boundary
             clears WCAG 1.4.11's 3:1 against the pale panel. */
          .pk-close-cta{
            display:inline-flex;align-items:center;min-height:52px;margin-top:32px;
            padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;
            background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;text-decoration:none;
            transition:opacity .5s ease,transform .5s ease,background-color .2s,box-shadow .2s;
          }
          /* opacity:0 (not visibility:hidden) so the control stays in the accessibility tree and
             the tab order; pointer-events:none so a hidden control is not clickable. FOCUS REVEALS
             IT — sequential focus scrolls the band on screen, the :focus rule makes the button
             visible in the same moment, and the observer fires too. */
          .pk-close.is-armed .pk-close-cta{opacity:0;transform:translateY(8px);pointer-events:none}
          .pk-close.is-armed.is-in .pk-close-cta{opacity:1;transform:none;pointer-events:auto;transition-delay:.62s}
          /* After .is-in on purpose: same specificity, so source order decides and focus wins.
             transition:none because a reader who has just tabbed to a control should see it now. */
          .pk-close.is-armed .pk-close-cta:focus{opacity:1;transform:none;pointer-events:auto;transition:none}
          .pk-close-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
          .pk-close-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

          @media(max-width:767px){
            .pk-p{font-size:18px}
            .pk-close-title{max-width:none}
          }

          @media(prefers-reduced-motion:reduce){
            /* Belt and braces: the effect already never arms under reduced motion (the JS returns
               before adding .is-armed), so these rules guard the case where the preference changes
               after arming, when the class is already on the node. They kill the movement without
               hiding anything. */
            .pk-close-rule,.pk-close-points li,.pk-close-cta{transition:none}
            .pk-close.is-armed .pk-close-rule{transform:scaleX(1)}
            .pk-close.is-armed .pk-close-points li,
            .pk-close.is-armed .pk-close-cta{opacity:1;transform:none}
            .pk-close.is-armed .pk-close-cta{pointer-events:auto}
            .pk-close-cta:hover{transform:none}
          }
        `}</style>
      </RotatingHero>
    </>
  );
};

export default PerksPage;
