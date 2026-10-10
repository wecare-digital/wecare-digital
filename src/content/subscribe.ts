import type { CycleWord } from '../components/RotatingHero';
import type { ProductDef } from './products';

/**
 * The Subscribe page, as data.
 *
 * WHY IT IS ITS OWN FILE AND NOT A SIXTH ENTRY IN CUSTOMERSERVICE. src/test/ReviewCta.test.tsx
 * requires every CUSTOMERSERVICE entry except leave-review to point at the contact page, so a
 * later swap to a real subscription flow would fail that guard for the wrong reason. And
 * scripts/generate-public-pages.js slices src/content/customerservice.ts from the array to the
 * end of the file, so anything appended there is swept into the `customerservice` catalogue
 * group, which has a fixed page count in tests/test_mcp_server.py. Subscribe is a way to get in
 * touch, so it sits in the `start` group beside /contact/ (see STRUCTURAL in that script).
 *
 * WHAT THIS PAGE DOES AND DOES NOT DO. It explains what subscribing means and hands the visitor
 * to the contact page, where they send their own message. It has no form, no email field and no
 * backend, and it must never say or imply that anything is stored or added automatically:
 * nothing is. The copy says so plainly.
 *
 * Same ProductDef shape and the same ProductPage layout as the product and customer service
 * pages, so the hero is the shared RotatingHero (the home page's animated headline pill) and the
 * page cannot drift from its siblings.
 *
 * TINTS ARE THE SAME FOUR PAIRS reused verbatim from customerservice.ts. No new colours.
 */

/**
 * OWNER DECISION: the primary CTA goes to the public contact page. The subscription backend does
 * not exist yet and the owner will build it later. When it does, this label and href are the one
 * place to change, together with the three copy lines below that mention the contact page and
 * the test in src/test/SubscribePage.test.tsx that pins them.
 */
export const SUBSCRIBE_CTA_LABEL = 'Open WhatsApp';
export const SUBSCRIBE_CTA_HREF = 'https://wa.me/message/WUDPTMYSO6XII1';

const BLUE = { tint: '#dbeafe', dot: '#2563eb' };
const AMBER = { tint: '#fef3c7', dot: '#f0a818' };
const GREEN = { tint: '#e0f7c8', dot: '#3da35a' };
const PURPLE = { tint: '#ede9fe', dot: '#9849e8' };

const WORDS: CycleWord[] = [
  { word: 'updates', ...BLUE },
  { word: 'news', ...AMBER },
  { word: 'posts', ...GREEN },
  { word: 'notices', ...PURPLE },
];

export const SUBSCRIBE: ProductDef = {
  slug: 'subscribe',
  name: 'Subscribe',
  blurb: 'Ask to hear from WECARE.DIGITAL.',
  title: 'Subscribe | WECARE.DIGITAL',
  description:
    'Subscribe to WECARE.DIGITAL updates. Open WhatsApp to start the subscription conversation. What you receive, how it works, and what we do not do.',
  frame: 'Get our',
  words: WORDS,
  sub: 'Open WhatsApp to start your subscription conversation.',
  sectionHeading: 'How subscribing works',
  lead:
    'Subscribers receive updates, service news and new posts from WECARE.DIGITAL. Use the button below to open WhatsApp and send the Subscribe message.',
  points: [
    { heading: 'Open WhatsApp', body: 'Use the button below to open the verified WECARE.DIGITAL WhatsApp conversation with Subscribe ready to send.' },
    { heading: 'Say you would like to subscribe', body: 'Tell us your name and whether you want updates by phone or by email, and give the number or address to use.' },
    { heading: 'Nothing is saved by this page', body: 'There is no form here, and nothing you do on this page is stored. Your request starts only when you send the message in WhatsApp.' },
  ],
  note:
    'We do not sign anyone up without being asked, and this page does not store anything you do. You can ask us to stop at any time. Messages about your own orders and payments are not marketing, so they carry on whatever you choose here. Our privacy policy explains how your details are handled.',
  ctaLabel: SUBSCRIBE_CTA_LABEL,
  ctaHref: SUBSCRIBE_CTA_HREF,
};
