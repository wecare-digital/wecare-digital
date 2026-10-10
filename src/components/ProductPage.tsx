import { whatsappServiceLink } from '../config/whatsappServiceEntries';
import React from 'react';
import PageMeta from './PageMeta';
import RotatingHero from './RotatingHero';
import type { ProductDef } from '../content/products';

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
 * THE NOTE IS A QUIET TINTED CARD, NOT A LIME ONE. Several of these products are regulated
 * or easily misread - Dastavez is not a law firm, Clear Closure does not act for either
 * party, Anew is not therapy, Elsewhere cannot promise a visa. Those statements have to be
 * read, but lime on this site means "actionable", and the single lime surface on the page is
 * already spent on the call to action. A boundary statement competing with the CTA for the
 * same signal would be a worse outcome than a quiet one that is actually legible. So the box
 * takes the house quiet-card geometry and the faint #fcfdfb lime-white used by the nav menu
 * - part of the brand system, with no lime signal of its own. See the rule itself below.
 */

interface ProductPageProps {
  product: ProductDef;
}

// The SITE constant that used to live here is gone: PageMeta owns the origin now, so
// keeping a second copy of it here would be a second place for it to be wrong.

const ProductPage: React.FC<ProductPageProps> = ( { product } ) => (
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

        <a className="pdp-cta" href={ whatsappServiceLink( product.slug ) || product.ctaHref }>{ product.ctaLabel }</a>

        { product.note && <p className="pdp-note">{ product.note }</p> }

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

          /* Full-strength #d1f470 with #1a3a2a type - the contract's own-surface pairing -
             and 2px because the hairline rule is that 2px means hoverable. */
          .pdp-cta{
            display:inline-flex;align-items:center;min-height:52px;margin-top:30px;
            padding:0 26px;border:2px solid #1a3a2a;border-radius:50px;
            background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;text-decoration:none;
            transition:background-color .2s,transform .2s,box-shadow .2s;
          }
          .pdp-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
          .pdp-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

          /* A QUIET TINTED CARD, STILL A 1px HAIRLINE. Geometry is the house quiet-card trio
             - padding:22px, 1px #e5e7eb, 14px radius - the same declaration as
             CheckoutIdentityCard, CheckoutProfile, .lgd-toc and .ord-nodetails, and the 14px
             the home page's closing panel uses. #fcfdfb is the site's faint lime-white
             surface (Header's .nav-menu, Layout's dropdown): part of the lime system without
             being lime. NOT rgba(209,244,112,.22) - that is the actionable lime surface and
             the page's one lime signal is the CTA above. No lime top border for the same
             reason, which also keeps the border rule intact: 1px static, 2px hoverable.
             Type is the legal-copy rung 17px/400/-.05px from .lgd-p, at .cl-value's 1.55
             line-height, on the single public body colour rgba(0,0,0,.898). It was
             16px/rgba(0,0,0,.54) - the faintest text on the page, which is the wrong
             treatment for a statement that has to be read. It stays quiet through size and
             surface, not faded ink. No mobile step-down: 17px is already the base size. */
          .pdp-note{
            margin:34px 0 0;padding:22px;
            border:1px solid #e5e7eb;border-radius:14px;
            background:#fcfdfb;
            font-size:17px;font-weight:400;line-height:1.55;letter-spacing:-.05px;
            color:rgba(0,0,0,.898);
          }

          @media(max-width:767px){
            .pdp-lead{font-size:18px}
            .pdp-p{font-size:18px}
            .pdp-point-t{font-size:20px}
          }
        `}</style>
      </section>
    </RotatingHero>
  </>
);

export default ProductPage;
