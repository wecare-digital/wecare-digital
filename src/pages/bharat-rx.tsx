import React from 'react';
import PageMeta from '../components/PageMeta';
import Breadcrumbs from '../components/Breadcrumbs';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';
import ProductBuyBox from '../components/ProductBuyBox';
import PolicyDetails from '../components/public/PolicyDetails';
import { PRODUCT_SKU_BY_SLUG, productPolicyCopy } from '../content/productCommerce';

/**
 * /bharat-rx — the Bharat Rx product page.
 *
 * WHY THIS EXISTS: Bharat Rx was moved into the Products column of the mega menu but had
 * no page, so the row pointed at the generic Customer service landing page. A product listed
 * beside Grahak OS and VayuLok and then landing somewhere unrelated is worse than not
 * listing it.
 *
 * ROUTING: '/bharat-rx' must be in the EXACT-MATCH allowlist in _app.tsx or this renders
 * an empty body with HTTP 200. trailingSlash means the URL is /bharat-rx/.
 *
 * NO MEDICINE RETAIL. Confirmed by the owner: Bharat Rx does not sell or deliver medicines.
 * I had briefly added an "Order medicines" track - prescription upload, stock and pricing,
 * doorstep delivery, refill reminders - after misreading the note that this page was "only
 * about appointments, not about ordering medicine" as a gap to fill rather than a statement
 * of scope. It was the second reading. The track is gone, the licensed-pharmacy line it
 * required is gone, and "medicines" is out of the rotating headline.
 *
 * WHAT IT DOES INSTEAD IS STILL PARTLY OPEN. The page describes the shape of the service -
 * a request, a qualified professional, a tracked record - which Terms sections 8 and 17
 * already support. The owner began to say what Bharat Rx will have and the message ended
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

// NO "medicines". The owner has confirmed Bharat Rx does not do medicine retail, so a
// rotating headline that leads with the word would promise a product that does not exist -
// which is the most expensive kind of copy error, because it is the first thing read.
// Tints and dots are reused verbatim from the Grahak OS hero - no new colours.
const CYCLE_WORDS: CycleWord[] = [
  { word: 'consults', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'appointments', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'reminders', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'records', tint: '#ede9fe', dot: '#9849e8' },
];

const BHARAT_RX_POLICY = productPolicyCopy( 'bharat-rx', 'Bharat Rx' );

const BharatRxPage: React.FC = () => (
  <>
    <PageMeta
      title="Bharat Rx"
      description="Bharat Rx by WECARE.DIGITAL — book a consult or appointment with a qualified professional, with reminders and records kept in one place."
      path="/bharat-rx/"
    />
    <RotatingHero
      ariaLabel="Bharat Rx"
      badgeLabel="Bharat Rx by WECARE.DIGITAL"
      frame="One place for"
      words={ CYCLE_WORDS }
      sub="Requests go to a qualified professional, and every one is tracked end to end with transparent pricing."
    >
      {/* THE VISIBLE BREADCRUMB mirroring _app.tsx's BreadcrumbList for this route:
          Home -> 'Bharat Rx' (the exact PUBLIC_PAGE_META name). No page-level JSON-LD -
          _app.tsx owns the single BreadcrumbList for this PUBLIC_PAGE_META route. */}
      <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Bharat Rx' } ] } />
      <section className="brx" aria-label="About Bharat Rx">
        {/* ONE FLOW, and deliberately not a retail one. This briefly had a second "Order
            medicines" track with prescriptions, stock, pricing and doorstep delivery. That
            was my misreading of the owner's note that the page was "only about appointments,
            not about ordering medicine" - I took it as a gap to fill when it was a statement
            of scope. Bharat Rx does not do medicine retail, so the whole track came out
            along with the licensed-pharmacy line it needed. */}
        <h2 className="brx-h2">How it works</h2>
        {/* THE THREE STEP TITLES ARE h3, NOT strong. Same defect and same fix as the six
            capability cards on /grahak-os/ and the three points in ProductPage.tsx: measured
            before this change, this page's outline was exactly H1 + H2 and the three steps had
            no heading semantics, so a screen-reader user skimming by heading could not reach
            them. h3 is the right rung - they sit under the .brx-h2 above, so no level is
            skipped. .brx-step-t already declares display and margin outright, so the UA's 1em
            h3 margin never applies and the rung stays 22px/700/lh 27.94px/ls -.25px. */}
        <ol className="brx-steps">
          <li className="brx-step">
            <span className="brx-step-n">1</span>
            <div>
              <h3 className="brx-step-t">Send a request</h3>
              <p className="brx-p">Describe what you need and attach anything relevant — a report, a photograph, a previous record.</p>
            </div>
          </li>
          <li className="brx-step">
            <span className="brx-step-n">2</span>
            <div>
              <h3 className="brx-step-t">A professional reviews it</h3>
              <p className="brx-p">Requests that need a qualified opinion get one. What that involves depends on the request, and is set out in section 17 of the Terms.</p>
            </div>
          </li>
          <li className="brx-step">
            <span className="brx-step-n">3</span>
            <div>
              <h3 className="brx-step-t">Track it, and keep the record</h3>
              <p className="brx-p">Status, changes and history stay in one place, alongside every other request you have made.</p>
            </div>
          </li>
        </ol>

        {/* One checkout entry. Payment mode is chosen after cart review. */}
        <ProductBuyBox slug="bharat-rx" />

        <div className="brx-commerce">
          <p className="brx-sku" data-wc-no-translate="true"><strong>SKU:</strong> <span className="brx-sku-value">{ PRODUCT_SKU_BY_SLUG['bharat-rx'] }</span></p>
          <PolicyDetails
            shipping={ BHARAT_RX_POLICY.shipping }
            returns={ BHARAT_RX_POLICY.returns }
            refunds={ BHARAT_RX_POLICY.refunds }
            disclaimer={ BHARAT_RX_POLICY.disclaimer }
          />
        </div>

        <style jsx>{`
          /* brx- prefixed. The globally imported src/styles/*.css declares unscoped rules
             for generic names and styled-jsx does not shield a page from them. */
          /* Back to 700px, a single column. It was widened to 1000px to fit two tracks
             side by side; with the retail track removed, holding 1000px would leave one
             short list floating in a measure built for two. The .brx-tracks and
             .brx-track-tag rules went with it rather than being left behind unused. */
          /* PHASE-1 UNIT: min-width:0 layered-defence containment, identical to the sibling
             ProductPage layout (.pdp), so a long unbreakable token - the SKU value, a long step
             heading - cannot force page-level horizontal scroll at the 200%-zoom extreme.
             RotatingHero already caps the hero band (minmax(0,1fr), Unit 1); this contains the
             body column. Containment-only: .brx-cta is var(--public-cta-height)=52px >= 44px so
             the tap floor is already met and the notch inset is owned upstream by Header/Layout. */
          .brx{max-width:700px;min-width:0}
          /* Section h2 is the contract's 700 rung - HEAVIER than the hero h1's 600. That
             inversion is intentional across the site. */
          .brx-h2{
            font-size:var(--public-section-size);font-weight:var(--public-section-weight);line-height:var(--public-section-leading);
            letter-spacing:var(--public-section-tracking);color:var(--public-heading);margin:0 0 22px;
          }
          .brx-steps{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:20px;min-width:0}
          .brx-step{display:flex;gap:16px;align-items:flex-start;min-width:0}
          .brx-step>div{min-width:0}
          /* The .22 lime tint: the contract's transient/quiet treatment, right for a
             counter that labels rather than acts. Full-strength lime is reserved for the
             single call to action below. */
          .brx-step-n{
            flex:0 0 auto;width:34px;height:34px;border-radius:50%;
            display:grid;place-items:center;
            background:var(--public-lime-tint);color:var(--public-brand-green);
            font-size:15px;font-weight:700;
          }
          /* Card-heading rung: 22px/700/-.25px/#000, same as .pp-strip-title. */
          .brx-step-t{display:block;margin:5px 0 6px;font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-heading);overflow-wrap:break-word}
          /* The one body level: 20px/400/1.4/-.125px. */
          .brx-p{font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-body);margin:0;overflow-wrap:break-word}
          /* THE CANONICAL BOUNDARY CARD, matched to .pdp-note on the product pages so every
             boundary note on the public site reads the same: near-white #fcfdfb surface, 1px
             hairline, 14px radius, 22px padding, and the legal-copy type rung 17px/400/1.55/-.05px
             on the single public body ink rgba(0,0,0,.898). It was a transparent 16px/faded aside;
             the quiet now comes from size and surface, not faded ink, so a statement that has to
             be read is legible. 1px static, per the rule: 1px static, 2px hoverable. */
          .brx-commerce{margin:22px 0 0}
          .brx-sku{
            margin:0;font-size:17px;font-weight:400;line-height:1.4;
            letter-spacing:-.05px;color:var(--public-muted);overflow-wrap:break-word;
          }
          .brx-sku strong{color:var(--public-brand-green);font-weight:700}
          /* word-break so the single unbroken SKU code can split at the 200%-zoom extreme. */
          .brx-sku-value{color:var(--public-muted);word-break:break-word}
        `}</style>
      </section>

    </RotatingHero>
  </>
);

export default BharatRxPage;
