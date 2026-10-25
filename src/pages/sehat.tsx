import React from 'react';
import PageMeta from '../components/PageMeta';
import Breadcrumbs from '../components/Breadcrumbs';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';
import ProductBuyBox from '../components/ProductBuyBox';
import PolicyDetails from '../components/public/PolicyDetails';
import { PRODUCT_SKU_BY_SLUG, productPolicyCopy } from '../content/productCommerce';

/**
 * /sehat — the Sehat product page.
 *
 * WHY THIS EXISTS: Sehat was moved into the Products column of the mega menu but had
 * no page, so the row pointed at the generic Customer service landing page. A product listed
 * beside Grahak OS and VayuLok and then landing somewhere unrelated is worse than not
 * listing it.
 *
 * ROUTING: '/sehat' must be in the EXACT-MATCH allowlist in _app.tsx or this renders
 * an empty body with HTTP 200. trailingSlash means the URL is /sehat/.
 *
 * NO MEDICINE RETAIL. Confirmed by the owner: Sehat does not sell or deliver medicines.
 * I had briefly added an "Order medicines" track - prescription upload, stock and pricing,
 * doorstep delivery, refill reminders - after misreading the note that this page was "only
 * about appointments, not about ordering medicine" as a gap to fill rather than a statement
 * of scope. It was the second reading. The track is gone, the licensed-pharmacy line it
 * required is gone, and "medicines" is out of the rotating headline.
 *
 * WHAT IT DOES INSTEAD IS STILL PARTLY OPEN. The page describes the shape of the service -
 * a request, a qualified professional, a tracked record - which Terms sections 8 and 17
 * already support. The owner began to say what Sehat will have and the message ended
 * mid-sentence, so the specific proposition is still outstanding and is NOT invented here.
 *
 * COPY IS NON-COMMITTAL ABOUT CLINICAL CLAIMS, deliberately. Nothing states what Rx
 * diagnoses, prescribes or advises, because a health-adjacent page is the wrong place to
 * guess and the wrong place to be wrong.
 *
 * NO PRODUCT SCHEMA, ON PURPOSE. Grahak OS carries SoftwareApplication because it is a
 * real, describable product with a feature list. Marking this up the same way while the
 * copy is provisional would put claims into structured data that the page does not make -
 * and Google's guidelines require structured data to represent the page's actual content.
 * _app.tsx gives it a WebPage plus a breadcrumb, which is accurate.
 */

// NO "medicines". The owner has confirmed Sehat does not do medicine retail, so a
// rotating headline that leads with the word would promise a product that does not exist -
// which is the most expensive kind of copy error, because it is the first thing read.
// Tints and dots are reused verbatim from the Grahak OS hero - no new colours.
const CYCLE_WORDS: CycleWord[] = [
  { word: 'appointments', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'bookings', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'schedules', tint: '#fef3c7', dot: '#f0a818' },
];

const SEHAT_POLICY = productPolicyCopy( 'sehat', 'Sehat' );

const SehatPage: React.FC = () => (
  <>
    {/* The title and description restate only what the page itself says - the hero sub and
        the three booking steps below - in the "Name — what it is" shape the other product
        pages use. They were "Sehat" and a 42-character sentence, which tools/browser/seocheck.js
        fails as too thin to describe the page in a result. No clinical claims, by design. */}
    <PageMeta
      title="Sehat — appointments with qualified professionals"
      description="Sehat by WECARE.DIGITAL — book an appointment with a qualified professional, choose a preferred date and time, and get your booking confirmed before the visit."
      path="/sehat/"
    />
    <RotatingHero
      ariaLabel="Sehat"
      badgeLabel="Sehat by WECARE.DIGITAL"
      frame="Sehat"
      words={ CYCLE_WORDS }
      sub="Appointments with qualified professionals"
    >
      {/* THE VISIBLE BREADCRUMB mirroring _app.tsx's BreadcrumbList for this route:
          Home -> 'Sehat' (the exact PUBLIC_PAGE_META name). No page-level JSON-LD -
          _app.tsx owns the single BreadcrumbList for this PUBLIC_PAGE_META route. */}
      <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Sehat' } ] } />
      <section className="brx" aria-label="About Sehat">
        {/* ONE FLOW, and deliberately not a retail one. This briefly had a second "Order
            medicines" track with prescriptions, stock, pricing and doorstep delivery. That
            was my misreading of the owner's note that the page was "only about appointments,
            not about ordering medicine" - I took it as a gap to fill when it was a statement
            of scope. Sehat does not do medicine retail, so the whole track came out
            along with the licensed-pharmacy line it needed. */}
        <h2 className="sht-h2">Book an appointment</h2>
        {/* THE THREE STEP TITLES ARE h3, NOT strong. Same defect and same fix as the six
            capability cards on /grahak-os/ and the three points in ProductPage.tsx: measured
            before this change, this page's outline was exactly H1 + H2 and the three steps had
            no heading semantics, so a screen-reader user skimming by heading could not reach
            them. h3 is the right rung - they sit under the .sht-h2 above, so no level is
            skipped. .sht-step-t already declares display and margin outright, so the UA's 1em
            h3 margin never applies and the rung stays 22px/700/lh 27.94px/ls -.25px. */}
        <ol className="sht-steps">
          <li className="sht-step">
            <span className="sht-step-n">1</span>
            <div>
              <h3 className="sht-step-t">Choose an appointment</h3>
              <p className="sht-p">Choose the appointment you need and a preferred date and time.</p>
            </div>
          </li>
          <li className="sht-step">
            <span className="sht-step-n">2</span>
            <div>
              <h3 className="sht-step-t">Confirm your details</h3>
              <p className="sht-p">Share the details needed to arrange the appointment with the qualified professional.</p>
            </div>
          </li>
          <li className="sht-step">
            <span className="sht-step-n">3</span>
            <div>
              <h3 className="sht-step-t">Get your booking confirmation</h3>
              <p className="sht-p">Your appointment details and booking status are confirmed before the visit.</p>
            </div>
          </li>
        </ol>

        {/* One checkout entry. Payment mode is chosen after cart review. */}
        <ProductBuyBox slug="sehat" />

        <div className="sht-commerce">
          <p className="sht-sku" data-wc-no-translate="true"><strong>SKU:</strong> <span className="sht-sku-value">{ PRODUCT_SKU_BY_SLUG['sehat'] }</span></p>
          <PolicyDetails
            shipping={ SEHAT_POLICY.shipping }
            returns={ SEHAT_POLICY.returns }
            refunds={ SEHAT_POLICY.refunds }
            disclaimer={ SEHAT_POLICY.disclaimer }
          />
        </div>

        <style jsx>{`
          /* sht- prefixed. The globally imported src/styles/*.css declares unscoped rules
             for generic names and styled-jsx does not shield a page from them. */
          /* Back to 700px, a single column. It was widened to 1000px to fit two tracks
             side by side; with the retail track removed, holding 1000px would leave one
             short list floating in a measure built for two. The .sht-tracks and
             .sht-track-tag rules went with it rather than being left behind unused. */
          /* PHASE-1 UNIT: min-width:0 layered-defence containment, identical to the sibling
             ProductPage layout (.pdp), so a long unbreakable token - the SKU value, a long step
             heading - cannot force page-level horizontal scroll at the 200%-zoom extreme.
             RotatingHero already caps the hero band (minmax(0,1fr), Unit 1); this contains the
             body column. Containment-only: .sht-cta is var(--public-cta-height)=52px >= 44px so
             the tap floor is already met and the notch inset is owned upstream by Header/Layout. */
          .brx{max-width:700px;min-width:0}
          /* Section h2 is the contract's 700 rung - HEAVIER than the hero h1's 600. That
             inversion is intentional across the site. */
          .sht-h2{
            font-size:var(--public-section-size);font-weight:var(--public-section-weight);line-height:var(--public-section-leading);
            letter-spacing:var(--public-section-tracking);color:var(--public-heading);margin:0 0 22px;
          }
          .sht-steps{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:20px;min-width:0}
          .sht-step{display:flex;gap:16px;align-items:flex-start;min-width:0}
          .sht-step>div{min-width:0}
          /* The .22 lime tint: the contract's transient/quiet treatment, right for a
             counter that labels rather than acts. Full-strength lime is reserved for the
             single call to action below. */
          .sht-step-n{
            flex:0 0 auto;width:34px;height:34px;border-radius:50%;
            display:grid;place-items:center;
            background:var(--public-lime-tint);color:var(--public-brand-green);
            font-size:15px;font-weight:700;
          }
          /* Card-heading rung: 22px/700/-.25px/#000, same as .pp-strip-title. */
          .sht-step-t{display:block;margin:5px 0 6px;font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-heading);overflow-wrap:break-word}
          /* The one body level: 20px/400/1.4/-.125px. */
          .sht-p{font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-body);margin:0;overflow-wrap:break-word}
          /* THE CANONICAL BOUNDARY CARD, matched to .pdp-note on the product pages so every
             boundary note on the public site reads the same: near-white #fcfdfb surface, 1px
             hairline, 14px radius, 22px padding, and the legal-copy type rung 17px/400/1.55/-.05px
             on the single public body ink rgba(0,0,0,.898). It was a transparent 16px/faded aside;
             the quiet now comes from size and surface, not faded ink, so a statement that has to
             be read is legible. 1px static, per the rule: 1px static, 2px hoverable. */
          .sht-commerce{margin:22px 0 0}
          .sht-sku{
            margin:0;font-size:17px;font-weight:400;line-height:1.4;
            letter-spacing:-.05px;color:var(--public-muted);overflow-wrap:break-word;
          }
          .sht-sku strong{color:var(--public-brand-green);font-weight:700}
          /* word-break so the single unbroken SKU code can split at the 200%-zoom extreme. */
          .sht-sku-value{color:var(--public-muted);word-break:break-word}
        `}</style>
      </section>

    </RotatingHero>
  </>
);

export default SehatPage;
