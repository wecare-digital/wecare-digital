import { buildPageTitle } from '../lib/page-title';
import type { CycleWord } from '../components/RotatingHero';
import type { ProductDef } from './products';

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

/**
 * Shipments is a category-only navigation family.
 *
 * This module defines its Track child. Pickup Request is a separate child at /request-pickup/.
 * There is deliberately no /shipments/ parent page.
 */
export const SHIPMENT_TRACK: ProductDef = {
  slug: 'shipments-track',
  name: 'Track',
  blurb: 'Track what is already on its way.',
  title: buildPageTitle( 'Track — shipment and request status' ),
  description:
    'Track an order, delivery or service request already with WECARE.DIGITAL using the reference you have.',
  frame: 'Track your',
  words: cycle( 'order', 'request', 'parcel', 'delivery' ),
  sub: 'Ask where it stands and keep the reference in one conversation.',
  sectionHeading: 'Track what is already moving',
  lead:
    'Use Track when an order, delivery or service request is already with WECARE.DIGITAL. Start with the order number, payment reference or the conversation it came from so we can identify the right item quickly.',
  points: [
    {
      heading: 'Start with the reference',
      body: 'Share the order number, payment reference or request reference if you have it. If you do not, describe what you are waiting for.',
    },
    {
      heading: 'One status conversation',
      body: 'Tracking stays in one WhatsApp thread so updates and any follow-up question remain attached to the same reference.',
    },
    {
      heading: 'Know what is confirmed',
      body: 'We will distinguish what has already happened from what is still waiting on a courier, partner or internal hand-off.',
    },
  ],
  note:
    'Collections and deliveries can depend on couriers and partners. We can tell you the latest confirmed status, but we will not promise a delivery time that has not been confirmed.',
  ctaLabel: 'Track on WhatsApp',
  ctaHref: 'https://wa.me/message/WGN4NMFLFSJVB1',
  ctaNote: 'Continue on WhatsApp →',
};
