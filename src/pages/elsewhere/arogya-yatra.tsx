import React from 'react';
import PageMeta from '../../components/PageMeta';
import Breadcrumbs from '../../components/Breadcrumbs';
import RotatingHero, { type CycleWord } from '../../components/RotatingHero';
import PolicyDetails from '../../components/public/PolicyDetails';
import AppointmentAccess from '../../components/public/AppointmentAccess';
import { PRODUCT_SKU_BY_SLUG, productPolicyCopy } from '../../content/productCommerce';

/** Arogya Yatra: authenticated appointment planning and provider catalogue reads.
 * Provider inventory and confirmed booking require a verified server integration.
 * This route covers appointments and medical travel; it does not retail medicines.
 */
const CYCLE_WORDS: CycleWord[] = [
  { word: 'appointments', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'bookings', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'schedules', tint: '#fef3c7', dot: '#f0a818' },
];

const SEHAT_POLICY = productPolicyCopy( 'sehat', 'Arogya Yatra' );

const SehatPage: React.FC = () => (
  <>
    {/* The title and description restate only what the page itself says - the hero sub and
        the three booking steps below - in the "Name — what it is" shape the other product
        pages use. They were "Arogya Yatra" and a 42-character sentence, too
        thin to describe the page in a result. No clinical claims, by design. */}
    <PageMeta
      title="Arogya Yatra — medical travel and appointments"
      description="Arogya Yatra by Elsewhere — plan appointment-related medical travel and request an appointment with a qualified professional. Travel arrangements and clinical decisions remain subject to provider confirmation."
      path="/elsewhere/arogya-yatra/"
    />
    <RotatingHero
      mobileFoundation
      ariaLabel="Arogya Yatra"
      badgeLabel="Arogya Yatra by WECARE.DIGITAL"
      frame="Arogya Yatra"
      words={ CYCLE_WORDS }
      sub="Medical travel planning and appointments with qualified professionals"
    >
      {/* THE VISIBLE BREADCRUMB mirroring _app.tsx's BreadcrumbList for this route:
          Home -> 'Arogya Yatra' (the exact PUBLIC_PAGE_META name). No page-level JSON-LD -
          _app.tsx owns the single BreadcrumbList for this PUBLIC_PAGE_META route. */}
      <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Arogya Yatra' } ] } />
      <section className="brx" aria-label="About Arogya Yatra">
        <AppointmentAccess />
        {/* ONE FLOW, and deliberately not a retail one. This briefly had a second "Order
            medicines" track with prescriptions, stock, pricing and doorstep delivery. That
            was my misreading of the owner's note that the page was "only about appointments,
            not about ordering medicine" - I took it as a gap to fill when it was a statement
            of scope. Arogya Yatra does not do medicine retail, so the whole track came out
            along with the licensed-pharmacy line it needed. */}
        <h2 className="sht-h2">Plan an appointment-related journey</h2>
        {/* THE THREE STEP TITLES ARE h3, NOT strong. Same defect and same fix as the six
            capability cards on /relay-os/ and the three points in ProductPage.tsx: measured
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
              <p className="sht-p">Choose the appointment you need, the destination and your preferred date and time.</p>
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
              <p className="sht-p">Confirm the appointment details with the provider before making travel arrangements.</p>
            </div>
          </li>
        </ol>

        {/* Do not collect a service fee without an owned provider-verified booking intent. */}
        <h3 className="sht-step-t">WECARE website service fee</h3>
        <p className="sht-p">₹550 base service fee, plus 18% GST. Checkout applies the existing Express and Delight rules, a 2.5% convenience fee and GST on that fee. Hospital consultation, registration, treatment and travel charges are separate.</p>
        <p className="sht-p" role="status">Checkout is unavailable until appointment requests can be securely linked to a verified booking. No payment is taken for a draft.</p>

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
