import React from 'react';
import PageMeta from './PageMeta';
import RotatingHero from './RotatingHero';
import { whatsappServiceLink } from '../config/whatsappServiceEntries';

/**
 * Three read-only, public service front doors that do NOT ask for customer identity on load.
 * Opening their WhatsApp conversation is an explicit click, never a page-view send.
 * Order ownership, status, payment and document access stay behind their existing gates.
 */
export type DirectEntryKind = 'shipments-track' | 'leave-review' | 'subscribe';

const ENTRIES = {
  'shipments-track': {
    name: 'Shipment Tracking',
    title: 'Track your shipment',
    path: '/shipments/track/',
    word: 'shipment',
    intro: 'Track a shipment linked to your WECARE.DIGITAL request.',
    details: 'Open the verified shipment-tracking conversation to share or confirm the shipment reference. Personal tracking details are not exposed on this public page.',
    cta: 'Track in WhatsApp',
    note: 'Tracking results depend on the shipment and carrier records that are actually available.',
  },
  'leave-review': {
    name: 'Leave Review',
    title: 'Share your experience',
    path: '/leave-review/',
    word: 'feedback',
    intro: 'Tell us about your experience with WECARE.DIGITAL.',
    details: 'The approved review conversation lets you share feedback from your own WhatsApp account. Nothing is submitted just by opening this page.',
    cta: 'Leave a Review in WhatsApp',
    note: 'You choose what to share. Opening this page does not send a review request.',
  },
  'subscribe': {
    name: 'Subscribe',
    title: 'Manage your updates',
    path: '/subscribe/',
    word: 'updates',
    intro: 'Manage the contact and profile details used for WECARE.DIGITAL updates.',
    details: 'Continue in the approved Subscribe WhatsApp conversation. Only your verified account can update private customer details.',
    cta: 'Continue to Subscribe in WhatsApp',
    note: 'Visiting this page does not subscribe you or send a WhatsApp message.',
  },
} as const;

export default function DirectServiceEntry ( { kind }: { kind: DirectEntryKind } ): React.ReactElement {
  const entry = ENTRIES[ kind ];
  const conversation = whatsappServiceLink( kind );
  return (
    <>
      <PageMeta title={ entry.title } description={ entry.intro } path={ entry.path } />
      <RotatingHero
        frame={ entry.title }
        words={ [ { word: entry.word, tint: '#e0f7c8', dot: '#3da35a' } ] }
        sub={ entry.intro }
        ariaLabel={ entry.name }
        mobileFoundation
      >
        <section className="direct-service" aria-label={ entry.name }>
          <h2>{ entry.name }</h2>
          <p>{ entry.details }</p>
          { conversation && (
            <a className="direct-service-cta" href={ conversation }>
              { entry.cta }
            </a>
          ) }
          <p className="direct-service-note">{ entry.note }</p>
        </section>
      </RotatingHero>
      <style jsx>{`
        .direct-service {
          box-sizing:border-box;
          max-width:720px;
          margin:0 auto 56px;
          padding:30px clamp(20px,4vw,40px);
          border:1px solid var(--public-hairline,#dde6db);
          border-radius:20px;
          color:var(--public-brand-green,#1a3a2a);
          background:#f9fcf6;
          font-family:var(--font-sans,Inter,sans-serif);
        }
        .direct-service h2 {
          margin:0 0 14px;
          font-size:clamp(24px,3vw,32px);
          font-weight:700;
          line-height:1.2;
        }
        .direct-service p {margin:0 0 22px;font-size:18px;line-height:1.6}
        .direct-service-cta {
          display:inline-flex;align-items:center;justify-content:center;
          min-height:48px;padding:13px 22px;
          border-radius:12px;text-decoration:none;
          background:#1a3a2a;color:#fff;font-weight:650;
          text-align:center;
        }
        .direct-service-cta:focus-visible {outline:3px solid #90c83e;outline-offset:3px}
        .direct-service .direct-service-note {margin:18px 0 0;font-size:14px;opacity:.76}
        @media(max-width:520px){.direct-service{margin-bottom:35px}.direct-service p{font-size:16px}}
      `}</style>
    </>
  );
}
