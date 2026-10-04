import React from 'react';
import PageMeta from '../components/PageMeta';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';

/**
 * /orders — where a customer checks what they have already asked for.
 *
 * RENAMED FROM [retired public path] ON OWNER INSTRUCTION, label and URL together. The old path is not
 * simply gone: it 301s to this one from the Amplify customRules written by
 * scripts/provision_legacy_redirects.py (RETIRED), because the page has been live and linked.
 * The same change repointed FROZEN_EXTERNAL["[retired public path]"], which is printed inside a DLT-approved
 * SMS template that cannot be edited and used to land on [retired public path]/ - leaving it alone would
 * have pointed an unchangeable template at a dead URL.
 *
 * ROUTING: '/orders' must be in the EXACT-MATCH allowlist in _app.tsx or this renders
 * an empty body with HTTP 200 - a 404 that does not look like one. trailingSlash means
 * the URL is /orders/. Three more lists have to agree or the suite fails: PUBLIC_EXACT in
 * scripts/generate-sitemap.js, and the path plus name in config/public-pages.json - whose
 * description must stay byte-identical to the one in _app.tsx.
 *
 * THIS REPLACED "Request Tracking" IN THE MENU rather than sitting beside it. The two are
 * the same function under different names, and a menu that offers both sends the same
 * visitor to two places to answer one question. If both are genuinely wanted - say
 * "Orders" for purchases and "Request Tracking" for service requests - that is a real
 * distinction and the row should come back, but it needs different destinations to be
 * worth the space.
 *
 * NOT YET WIRED TO ANY DATA. There is no order-lookup endpoint on the public site, and a
 * page that asks for an order number and then cannot answer would be worse than an
 * honest signpost. So this is the hero plus a route to contact, which is where a customer
 * can actually get an answer today. The moment an endpoint exists, the lookup form
 * belongs here.
 *
 * "CUSTOMERSERVICE" NAMING REMOVED 2026-09-27 (owner instruction). It named a portal that no
 * longer exists at any address: the in-repo [retired public path] stub went in commit 6bc44a35 and
 * nothing replaced it, so the word pointed customers at a concept with no page behind it.
 * The only [retired public path] route in the codebase now is the ADMIN flow dashboard under
 * /workspace/forms/, which is not a customer destination.
 */

// "Track your order / delivery / request / booking" - all four complete the frame and
// all are 5 to 8 characters, so the pill barely travels. Tints and dots reused verbatim
// from the Grahak OS hero; no new colours.
const CYCLE_WORDS: CycleWord[] = [
  { word: 'order', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'delivery', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'request', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'booking', tint: '#ede9fe', dot: '#9849e8' },
];

// A terminal URL, deliberately: `/contact/` is a real 200 page on the canonical host with
// no redirect hop. Two earlier values both ended in a 404 -
// '[retired public path]' (www 301s to apex, then [retired public path] 404s) and
// the apex '[retired public path]' on its own. Verify with curl before changing this again.
const CONTACT = 'https://wecare.digital/contact/';

const OrdersPage: React.FC = () => (
  <>
    <PageMeta
      title="Orders — WECARE.DIGITAL"
      description="Check the status of an order, delivery, request or booking with WECARE.DIGITAL, and find what to do if something needs changing."
      path="/orders/"
    />
    <RotatingHero
      ariaLabel="Orders"
      badgeLabel="Order tracking — WECARE.DIGITAL"
      frame="Track your"
      words={ CYCLE_WORDS }
      sub="Every order and request is tracked end to end, with one place to check where things stand."
    >
      <section className="mo" aria-label="Check an order">
        <h2 className="mo-h2">Check where something stands</h2>
        <p className="mo-p">
          Send us the reference from your confirmation message and we will tell you the
          current stage, what happens next, and who to speak to if something needs
          changing.
        </p>
        <a className="mo-cta" href={ CONTACT }>Contact us</a>

        <h2 className="mo-h2 mo-h2-spaced">If something needs changing</h2>
        <p className="mo-p">
          Amendments, cancellations and refunds go through the same route. What
          is possible depends on how far along the order is - the detail is in section 14
          of our{ ' ' }
          {/* Plain anchor, not next/link, for the reason Footer.tsx documents: styled-jsx
              does not scope composite components, so a Link carrying mo-link would arrive
              with no styling at all. */}
          { /* eslint-disable-next-line @next/next/no-html-link-for-pages */ }
          <a className="mo-link" href="/terms/">Terms of Service</a>, which covers
          cancellations, refunds and rescheduling.
        </p>
        <p className="mo-p">
          If you cannot find the reference, or the status looks wrong, reach us on{ ' ' }
          <a className="mo-link" href="tel:+919330994400">+91 9330994400</a> or{ ' ' }
          <a className="mo-link" href="mailto:one@wecare.digital">one@wecare.digital</a>.
        </p>

        <style jsx>{`
          /* mo- prefixed. The globally imported src/styles/*.css declares unscoped rules
             for generic names and styled-jsx does not shield a page from them. */
          .mo{max-width:700px}
          /* Section h2 is the contract's 700 rung - HEAVIER than the hero h1's 600. That
             inversion is intentional across the whole site. */
          .mo-h2{
            font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;
            letter-spacing:-1.2px;color:rgba(0,0,0,.95);margin:0 0 14px;
          }
          .mo-h2-spaced{margin-top:44px}
          /* The one body level: 20px/400/1.4/-.125px at rgba(0,0,0,.898). */
          .mo-p{
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);margin:0 0 14px;
          }
          /* Full-strength lime with #1a3a2a type: the contract's treatment for our own
             surfaces at full voice, the same pair as BrandBadge and .msg.sent. This is
             the page's single call to action, so it is the one place that earns it.
             2px border because it is hoverable - the hairline rule is that 2px means
             interactive and 1px means static. */
          .mo-cta{
            display:inline-flex;align-items:center;min-height:52px;margin-top:6px;
            padding:0 26px;border:2px solid #1a3a2a;border-radius:50px;
            background:#d1f470;color:#1a3a2a;
            font-size:17px;font-weight:600;text-decoration:none;
            transition:background-color .2s,border-color .2s,transform .2s,box-shadow .2s;
          }
          .mo-cta:hover{
            background:#fff;border-color:#1a3a2a;
            transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
          }
          .mo-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
          .mo-link{color:#1a3a2a;font-weight:600;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
          .mo-link:hover{background:rgba(209,244,112,.22)}
          @media(max-width:767px){
            .mo-p{font-size:18px}
            .mo-h2-spaced{margin-top:36px}
          }
        `}</style>
      </section>
    </RotatingHero>
  </>
);

export default OrdersPage;
