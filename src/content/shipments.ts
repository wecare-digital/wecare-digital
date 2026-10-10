import type { CycleWord } from '../components/RotatingHero';
import type { ProductDef } from './products';

/**
 * The Shipments page, as data.
 *
 * WHY IT IS ITS OWN FILE AND NOT A SEVENTH ENTRY IN CUSTOMERSERVICE, the same three reasons
 * src/content/subscribe.ts records for itself:
 *   - src/test/ReviewCta.test.tsx requires every CUSTOMERSERVICE entry except leave-review to
 *     point at the contact page, and both CTAs here are wa.me message links.
 *   - scripts/generate-public-pages.js sweeps every CUSTOMERSERVICE entry into the
 *     `customerservice` catalogue group, while already declaring '/shipments' in STRUCTURAL
 *     under `start`. A page claimed by two groups makes that script refuse, and it is the
 *     first command in `npm run build`.
 *   - the `customerservice` group's page count is fixed in tests/test_mcp_server.py, so a page
 *     joining it is a decision rather than a silent event.
 * /shipments stays in the `start` group beside /orders/ and /contact/, which is where the owner
 * filed it: it is a front door, not a sixth customer-service row.
 *
 * WHAT THIS PAGE DOES AND DOES NOT DO. It explains the two things Shipments covers - asking
 * where something already with us stands, and asking us to arrange a pickup - and hands the
 * visitor to WhatsApp to start either. It tracks nothing and books nothing itself: there is no
 * form, no carrier integration and no delivery feed behind it, and the copy says so plainly.
 *
 * TWO CALL TO ACTIONS, which is why ProductDef carries the optional ctaLabel2 / ctaHref2 pair.
 * Both are the owner's own Meta message links. CTA 2 is rendered from ctaHref2 LITERALLY and
 * deliberately bypasses whatsappServiceLink(): that resolves by slug, and this slug's entry in
 * src/config/whatsappServiceEntries.ts is the TRACKING link, so routing the pickup button
 * through it would open the wrong conversation. CTA 1's href and that config entry are the same
 * string today, and src/test/ShipmentsPage.test.tsx pins the equality so they cannot diverge.
 *
 * Same ProductDef shape and the same ProductPage layout as the product and customer service
 * pages, so the hero is the shared RotatingHero and the page cannot drift from its siblings.
 *
 * NO PRICES, NO TURNAROUND TIMES, NO GUARANTEES. Collections and deliveries are carried out by
 * couriers and partners, so the dates are not ours to promise; `note` says that on the page.
 *
 * THE PAGE WAS CALLED "ZIP" AND THE NAME IS GONE, on owner instruction (2026-10-02). It must
 * not return anywhere, including in schema output.
 *
 * TINTS ARE THE SAME FOUR PAIRS reused verbatim from customerservice.ts. No new colours. The
 * cycle words are held close in length for the reason products.ts documents - the pill animates
 * to each word's measured width - and these four are 5 / 7 / 6 / 6 characters, a two-character
 * spread end to end, with each one literally true of what the page covers.
 */

const BLUE = { tint: '#dbeafe', dot: '#2563eb' };
const AMBER = { tint: '#fef3c7', dot: '#f0a818' };
const GREEN = { tint: '#e0f7c8', dot: '#3da35a' };
const PURPLE = { tint: '#ede9fe', dot: '#9849e8' };

const cycle = ( a: string, b: string, c: string, d: string ): CycleWord[] => [
  { word: a, ...BLUE },
  { word: b, ...AMBER },
  { word: c, ...GREEN },
  { word: d, ...PURPLE },
];

export const SHIPMENTS: ProductDef = {
  slug: 'shipments',
  name: 'Shipments',
  blurb: 'Track what is on its way, or arrange a pickup.',
  title: 'Shipments - tracking and pickups | WECARE.DIGITAL',
  description:
    'Everything about your request, delivery or pickup in one place. Track what you already have with WECARE.DIGITAL, or ask us to arrange a pickup, on WhatsApp.',
  frame: 'Everything about your',
  words: cycle( 'order', 'request', 'pickup', 'parcel' ),
  sub: 'Track it. Arrange it. Keep it moving.',
  sectionHeading: 'Tracking and pickups',
  lead:
    'Two things happen here. If something is already with us, you can ask where it stands. If something needs collecting, you can ask us to arrange a pickup. Both start as a WhatsApp message, because that is where your references and your history already are - this page does not track or book anything itself.',
  points: [
    {
      heading: 'Track an order or a request',
      body: 'Ask where an order, a delivery or a service request stands. Quote the order number or reference if you have it, and describe it if you do not.',
    },
    {
      heading: 'Ask us to arrange a pickup',
      body: 'Tell us what needs collecting, where it is and who will hand it over. We come back with what is possible before anything is booked.',
    },
    {
      heading: 'Have the reference ready',
      body: 'An order number, a payment reference or the thread it happened in is enough to find it. Tracking and pickups are separate conversations, so each keeps its own reference.',
    },
  ],
  note:
    'Collections and deliveries are carried out by couriers and partners, so dates and times depend on them rather than on us. We will tell you what has been arranged and what is still being confirmed, and we will not promise a slot we cannot hold.',
  ctaLabel: 'Shipments tracking',
  ctaHref: 'https://wa.me/message/WGN4NMFLFSJVB1',
  ctaLabel2: 'Request pickup',
  ctaHref2: 'https://wa.me/message/NRWQFXOPGL7OO1',
};
