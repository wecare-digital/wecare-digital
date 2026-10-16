import React from 'react';
import ClosingBand from '../components/public/ClosingBand';
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
 *      all leave the band fully readable. ClosingBand owns that shared mechanism (a ref +
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
  return (
    <>
      <PageMeta
        title="Perks"
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

        <ClosingBand id="pk-close" eyebrow="Perks" title="A little extra, honestly done."
          lead="We will not show you a points balance that is not real or an offer we cannot honour. When there is a genuine thank-you to give, it lands here — in your language, your way."
          points={ [ 'Nothing here asks for payment.', 'We say plainly what is not ready yet.', 'Any eligible coupon is applied at checkout, not here.' ] }
          href="/shop/" action="See what we offer" />

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

          @media(max-width:767px){.pk-p{font-size:18px}}
        `}</style>
      </RotatingHero>
    </>
  );
};

export default PerksPage;
