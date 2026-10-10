import { whatsappServiceLink } from '../config/whatsappServiceEntries';
import React from 'react';
import PageMeta from './PageMeta';
import RotatingHero from './RotatingHero';
import ProductBlogPanel from './ProductBlogPanel';
import ShareLinks from './ShareLinks';
import type { ProductDef } from '../content/products';
import type { BlogCard } from '../lib/public-blog';

/**
 * One layout for every product page. Copy comes from src/content/products.ts.
 *
 * SELF-STYLING, like BrandBadge, RotatingHero, WorkflowTerminal and LegalDocument:
 * styled-jsx cannot scope a composite component from its parent, so this owns every rule
 * it needs and the route file owns nothing but which product to render.
 *
 * Classes are pdp- prefixed. The globally imported src/styles/*.css declares unscoped rules
 * for generic names and styled-jsx does not shield a page from them.
 *
 * TYPE COMES OFF THE DESIGN CONTRACT and matches bharat-rx.tsx exactly, because these pages
 * sit beside it in the same menu column and any difference would read as an accident:
 * section h2 on the 700 rung (heavier than the hero h1's 600, which is the site's deliberate
 * inversion), card headings at 22px/700/-.25px, and the single body level at
 * 20px/400/1.4/-.125px.
 *
 * THE NOTE IS A QUIET HAIRLINE CARD ON A NEAR-WHITE FILL, NOT A LIME ONE. Several of these
 * products are regulated or easily misread - Dastavez is not a law firm, Clear Closure does
 * not act for either party, Anew is not therapy, Elsewhere cannot promise a visa. Those
 * statements have to be read, but lime on this site means "actionable": full-strength
 * #d1f470 is the call to action, and the .22 tint is already working on this page as the
 * numbered point markers. A boundary statement wearing either would read as a third lime
 * element in the same column. So the box takes the house quiet-card geometry and #fcfdfb,
 * the site's near-white - a step off the hero's #fff rather than a colour of its own, so it
 * is the hairline, the padding and the body-weight ink that make it legible. The rule below
 * carries the full reasoning.
 */

interface ProductPageProps {
  product: ProductDef;
  /**
   * OPTIONAL RIGHT-HAND BLOG PANEL. When cards are passed (today only /anew/, from its
   * getStaticProps), the page becomes a two-column grid on a wide screen: product copy left, the
   * ProductBlogPanel right. Omit it - every other product page does - and the layout is byte-for-
   * byte what it was: one 700px column, no grid, no panel. That is why the grid rules below are
   * scoped to .pdp-wrap.has-aside.
   */
  blogCards?: BlogCard[];
  /**
   * OPTIONAL PRICE LINE under the CTA, so a reader sees what they will pay before they open the
   * chat. A short string like "₹599" plus an optional unit. Omitted on pages that do not sell a
   * fixed-price item here.
   */
  price?: string;
  priceUnit?: string;
  /**
   * OPTIONAL SHARE ROW. When an absolute URL is passed, the same ShareLinks component the blog and
   * post pages use is rendered under the left column.
   */
  shareUrl?: string;
}

// The SITE constant that used to live here is gone: PageMeta owns the origin now, so
// keeping a second copy of it here would be a second place for it to be wrong.

const ProductPage: React.FC<ProductPageProps> = ( {
  product,
  blogCards,
  price,
  priceUnit,
  shareUrl,
} ) => {
  const hasAside = Array.isArray( blogCards ) && blogCards.length > 0;
  return (
  <>
    {/* All seven product pages get their share preview from the same two strings that make
        their <title> and <meta description>, so there is nothing to keep in sync. Before
        this, none of them declared og: tags at all and all seven inherited the sitewide
        company preview from _app.tsx - seven distinct products previewing as one page. */}
    <PageMeta
      title={ product.title }
      description={ product.description }
      path={ `/${product.slug}/` }
    />
    <RotatingHero
      ariaLabel={ product.name }
      badgeLabel={ `${product.name} by WECARE.DIGITAL` }
      frame={ product.frame }
      words={ product.words }
      sub={ product.sub }
    >
      <div className={ hasAside ? 'pdp-wrap has-aside' : 'pdp-wrap' }>
      <section className="pdp" aria-label={ `About ${product.name}` }>
        <h2 className="pdp-h2">{ product.sectionHeading }</h2>
        <p className="pdp-lead">{ product.lead }</p>

        <ul className="pdp-points">
          { product.points.map( ( point, i ) => (
            <li className="pdp-point" key={ point.heading }>
              <span className="pdp-point-n">{ i + 1 }</span>
              <div>
                {/* h3, NOT a strong. This is the same defect fixed on /grahak-os/ for its six
                    capability cards, and the same fix - see the note beside .pp-strip-title
                    there. Measured before this change: every one of the fourteen routes this
                    component renders had an outline of exactly H1 + H2, so the three points
                    that carry the actual argument of the page had no heading semantics at
                    all. A screen-reader user skimming by heading - which is the primary way
                    that is done - could not reach them, and they were absent from the
                    document outline entirely.

                    h3 is the correct rung, not h2: these sit under .pdp-h2 inside the same
                    section, so h2 -> h3 is a step with no level skipped.

                    NOT a <dl>. That was floated as "more precise" and it is the worse
                    choice: a <dt> cannot be a heading, so it would fix the outline for
                    nobody while giving up the heading navigation that is the entire point,
                    and screen-reader support for description lists is uneven. These are
                    three titled points, and a titled thing wants a heading.

                    The .pdp-point-t rule below already declares display and margin outright,
                    so the UA stylesheet's 1em h3 margin never applies and promoting the tag
                    moves nothing: the card-heading rung stays 22px/700/lh 27.94px/ls -.25px
                    with a 6px gap to the body copy, measured identical before and after. */}
                <h3 className="pdp-point-t">{ point.heading }</h3>
                <p className="pdp-p">{ point.body }</p>
              </div>
            </li>
          ) ) }
        </ul>

        {/* ONE pill for every page that sets only ctaLabel/ctaHref; a SECOND pill appears only
            when the product carries both ctaLabel2 and ctaHref2 (today just /shipments/, which
            has a tracking door and a pickup door). The first anchor is byte-for-byte what it was
            before this wrapper — same whatsappServiceLink() resolution — so single-CTA pages are
            unchanged. The second anchor uses ctaHref2 directly and is NOT routed through
            whatsappServiceLink(): the slug resolves to one service link, so the pickup button
            would otherwise open the tracking conversation. The 30px top gap now lives on
            .pdp-ctas (it was on .pdp-cta), so single-CTA spacing is identical to the pixel. */}
        <div className="pdp-ctas">
          <a className="pdp-cta" href={ whatsappServiceLink( product.slug ) || product.ctaHref }>{ product.ctaLabel }</a>
          { product.ctaHref2 && product.ctaLabel2 && (
            <a className="pdp-cta" href={ product.ctaHref2 }>{ product.ctaLabel2 }</a>
          ) }
        </div>

        {/* MICROCOPY under the CTA, rendered only when the product declares one (today just
            /anew/). Very small and quiet, naming where the button goes. aria-hidden because the
            anchor's own label is the accessible name. Matches the blog post page's
            Subscribe/Contribute pills (.bc-cta-note / .blog-wa-note). */}
        { product.ctaNote && <p className="pdp-cta-note" aria-hidden="true">{ product.ctaNote }</p> }

        {/* PRICE, so a reader knows what they will pay before they open the chat. Opt-in: a page
            that passes no price renders nothing here, which is every product page except /anew/.
            (The "See everything on WECARE.DIGITAL" catalogue link that used to sit beside the
            price was removed on owner instruction 2026-10-10.) */}
        { price && (
          <p className="pdp-buy">
            <span className="pdp-price" data-wc-no-translate="true">
              { price }{ priceUnit && <span className="pdp-price-unit"> { priceUnit }</span> }
            </span>
          </p>
        ) }

        { product.note && <p className="pdp-note">{ product.note }</p> }

        {/* SHARE - the same component the blog and post pages use, so the Anew page can be sent
            on in one tap. Rendered only when an absolute URL is supplied. */}
        { shareUrl && (
          <div className="pdp-share">
            <ShareLinks url={ shareUrl } title={ product.title } label="Share Anew" />
          </div>
        ) }

        <style jsx>{`
          .pdp{max-width:700px}
          .pdp-h2{
            font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;
            letter-spacing:-1.2px;color:rgba(0,0,0,.95);margin:0 0 22px;
          }
          /* The lead runs at the body level but slightly tighter, because it is a paragraph
             of context rather than a point being made. */
          .pdp-lead{font-size:20px;font-weight:400;line-height:1.45;letter-spacing:-.125px;color:rgba(0,0,0,.898);margin:0 0 34px}

          .pdp-points{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:20px}
          .pdp-point{display:flex;gap:16px;align-items:flex-start}
          /* The .22 lime tint: the contract's quiet treatment, right for a counter that
             labels rather than acts. Full-strength lime is reserved for the CTA below. */
          .pdp-point-n{
            flex:0 0 auto;width:34px;height:34px;border-radius:50%;
            display:grid;place-items:center;
            background:rgba(209,244,112,.22);color:#1a3a2a;
            font-size:15px;font-weight:700;
          }
          .pdp-point-t{display:block;margin:5px 0 6px;font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;color:#000}
          .pdp-p{font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898);margin:0}

          /* The CTA row. One or two pills, wrapping rather than overflowing on a narrow
             viewport. margin-top:30px lives HERE, not on .pdp-cta, so a page with a single pill
             keeps the exact gap it had before the wrapper existed — the anchor's own line box
             contributed no height, so moving the margin up one level is a no-op for single-CTA
             pages (RequestNotes.test.ts pins this). gap:12px separates the pair on /shipments/. */
          .pdp-ctas{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-top:30px}
          /* Full-strength #d1f470 with #1a3a2a type - the contract's own-surface pairing -
             and 2px because the hairline rule is that 2px means hoverable. */
          .pdp-cta{
            display:inline-flex;align-items:center;min-height:52px;
            padding:0 26px;border:2px solid #1a3a2a;border-radius:50px;
            background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;text-decoration:none;
            transition:background-color .2s,transform .2s,box-shadow .2s;
          }
          .pdp-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
          .pdp-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
          /* MICROCOPY under the CTA row - the twin of .bc-cta-note / .blog-wa-note on the blog
             post page. 13px/rgba(0,0,0,.54) is the muted-metadata rung; 10px of air sits it close
             to the button it belongs to. Only /anew/ carries one today.
             HOVER CARRIES THE FOOTER TAGLINE'S COLOUR SWEEP (see .ft-tagline in Footer.tsx and the
             long note on .bc-cta-note in BlogContribution.tsx): a brand-green band runs through
             the muted text on hover. Clip + transparent fill live under :hover only so the resting
             line stays solid grey, not invisible; both stops are measured on white (4.61:1 and
             12.48:1) so the band only darkens the text. */
          /* MATCHED TO THE FOOTER TAGLINE, "Trusted everyday services for Bharat" (.ft-tagline
             in Footer.tsx): same 16px/1.6 muted-grey type, and the lime colour sweep runs ONCE
             ON HOVER rather than looping on its own. The continuous auto-sweep was the right
             idea but kept moving with no interaction, which pulled the eye to a line of quiet
             microcopy - so it now behaves like the footer line: solid grey at rest, the lime
             band passing through the glyphs when the reader hovers. The gradient, the text clip
             and the transparent fill live on the base rule so the band is clipped to the glyphs,
             and both stops are measured on white (rgba(0,0,0,.54) 4.61:1, #1a3a2a 12.48:1) so the
             band only darkens the text, never erases it. At rest background-position sits off to
             one side so no band shows; :hover plays it across once. */
          .pdp-cta-note{
            font-size:16px;line-height:1.6;color:rgba(0,0,0,.54);margin:10px 0 0;
            background-image:linear-gradient(100deg,
              rgba(0,0,0,.54) 44%, #1a3a2a 50%, rgba(0,0,0,.54) 56%);
            background-size:300% 100%;background-repeat:no-repeat;background-position:100% 0;
            -webkit-background-clip:text;background-clip:text;
            -webkit-text-fill-color:transparent;
          }
          .pdp-cta-note:hover{animation:pdp-cta-note-sweep 1.1s cubic-bezier(.22,.61,.36,1) 1}
          @keyframes pdp-cta-note-sweep{from{background-position:100% 0}to{background-position:-100% 0}}
          /* Motion-sensitive readers get the line static and solid grey: no sweep, no transparent
             fill, no gradient - the WCAG carve-out for motion on interaction. */
          @media(prefers-reduced-motion:reduce){
            .pdp-cta-note,.pdp-cta-note:hover{
              animation:none;background-image:none;
              -webkit-text-fill-color:currentColor;color:rgba(0,0,0,.54);
            }
          }

          /* A ROOMIER QUIET CARD, STILL A 1px HAIRLINE. Geometry is the house quiet-card trio
             - padding:22px, 1px #e5e7eb, 14px radius - the same declaration as
             CheckoutIdentityCard, CheckoutProfile, .lgd-toc and .ord-nodetails, and the 14px
             the home page's closing panel uses. #fcfdfb is the site's near-white (Header's
             .nav-menu, Layout's dropdown), and it is honestly about one step per channel off
             the hero's #fff: it is not a tint that registers on its own, so what reads as a
             card here is the hairline, the padding and the ink, with the fill only keeping
             the block from looking like loose text. Deliberately NOT rgba(209,244,112,.22):
             that tint is this page's quiet marker treatment and is already spent on
             .pdp-point-n eleven lines up, while full-strength #d1f470 is the CTA - a boundary
             statement in either would be a third lime element in one column. No lime top
             border for the same reason (Header and SupportWidget pair #fcfdfb with a 3px
             #d1f470 edge), which also keeps the border rule intact: 1px static, 2px
             hoverable. Type is the legal-copy rung 17px/400/-.05px from .lgd-p, at
             .cl-value's 1.55 line-height, on the single public body colour rgba(0,0,0,.898).
             It was 16px/rgba(0,0,0,.54) - the faintest text on the page, which is the wrong
             treatment for a statement that has to be read, so the quiet now comes from size
             and surface rather than faded ink. No mobile step-down: 17px is the base size. */
          .pdp-note{
            margin:34px 0 0;padding:22px;
            border:1px solid #e5e7eb;border-radius:14px;
            background:#fcfdfb;
            font-size:17px;font-weight:400;line-height:1.55;letter-spacing:-.05px;
            color:rgba(0,0,0,.898);
          }

          /* PRICE line. The price is the card rung in dark green (lime means actionable and the
             pill owns lime). 22px of air above it, matching the CTA row's own top gap. */
          .pdp-buy{display:flex;flex-wrap:wrap;align-items:baseline;gap:16px;margin:22px 0 0}
          .pdp-price{font-size:22px;font-weight:700;line-height:1.2;letter-spacing:-.25px;color:#1a3a2a;font-variant-numeric:tabular-nums}
          .pdp-price-unit{font-size:15px;font-weight:600;color:rgba(0,0,0,.54)}

          /* The share row sits below the boundary note with its own air. */
          .pdp-share{margin:28px 0 0}

          /* THE TWO-COLUMN WRAP, SCOPED TO .has-aside so every other product page is untouched.
             Default (no aside): a plain block, so .pdp keeps its own 700px measure exactly as
             before. With an aside: a grid - a flexible product column on the left and a fixed
             blog rail on the right, with a 48px gutter. The split starts at 960px (not 1024px)
             so a ~1024px desktop window - the common case - gets the panel on the right rather
             than stacked under the copy; below 960px it stacks and the panel drops below. These
             classes live on nodes OUTSIDE .pdp, but styled-jsx scopes by component not by
             element, so one block styles the whole return tree. */
          .pdp-wrap{display:block}
          .pdp-aside{margin:64px 0 0}

          @media(max-width:767px){
            .pdp-lead{font-size:18px}
            .pdp-p{font-size:18px}
            .pdp-point-t{font-size:20px}
          }
          @media(min-width:960px){
            .pdp-wrap.has-aside{
              display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,400px);
              column-gap:48px;align-items:start;
            }
            /* The product column keeps its own 700px cap inside the flexible track so the copy
               measure is unchanged; the grid track just stops it stretching under the panel. */
            .pdp-wrap.has-aside .pdp{max-width:700px}
            .pdp-wrap.has-aside .pdp-aside{margin:0}
          }
        `}</style>
      </section>

      { hasAside && (
        <div className="pdp-aside">
          <ProductBlogPanel cards={ blogCards! } />
        </div>
      ) }
      </div>
    </RotatingHero>
  </>
  );
};

export default ProductPage;
