import { buildPageTitle } from '../lib/page-title';
import type { CycleWord } from '../components/RotatingHero';
import type { ProductDef } from './products';
/**
 * The five public request pages, as data.
 *
 * These are the request actions that still have explanatory website pages. Leave Review is no longer part of this page catalogue. The Request menu section is
 * intentionally hidden; customer deep links, WhatsApp Flow and per-order review remain.
 *
 * The pages reuse ProductPage and the existing hero/content hierarchy. They make no turnaround,
 * price or outcome guarantees; where a third party controls an outcome, the copy says so.
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

/**
 * THE FALLBACK, NOT THE DESTINATION. ProductPage points the "Checkout on WhatsApp" pill at the
 * page's own conversation from src/config/whatsappServiceEntries.ts whenever one exists, and
 * every request page here has one, so none of them actually lands on /contact/ any more. This
 * is only what a page with no service entry would fall back to. Refer & Earn has no entry, so
 * it carries its own keyword deep link instead - otherwise its WhatsApp pill opened a web page.
 * Through a constant so `grep CUSTOMERSERVICE_CTA` lists them all, the way PRODUCT_CTA does.
 */
const CUSTOMERSERVICE_CTA = 'https://wecare.digital/contact/';

export const CUSTOMERSERVICE: ProductDef[] = [
  {
    slug: 'submit-request',
    name: 'Submit Request',
    blurb: 'Get help with your existing order.',
    title: buildPageTitle( 'Submit a request' ),
    description:
      'Raise a request for an existing WECARE.DIGITAL order. Select your order, explain what needs attention and follow its progress.',
    frame: 'Get help with',
    words: cycle( 'orders', 'details', 'requests', 'issues' ),
    sub: 'Your existing order, with the next step clearly linked.',
    sectionHeading: 'Help with an existing order',
    lead:
      'Select the order you need help with and describe what needs attention in your own words. Your order number keeps the request connected to the right purchase.',
    points: [
      { heading: 'Choose your order', body: 'Sign in with your verified WhatsApp number to view the orders linked to your account.' },
      { heading: 'Tell us what needs attention', body: 'Include the issue, the outcome you want and any relevant documents or dates.' },
      { heading: 'Keep the references clear', body: 'The order you need help with and any service payment have separate references, so you can follow the request and its receipt.' },
    ],
    ctaLabel: 'Submit a request',
    ctaHref: CUSTOMERSERVICE_CTA,
    ctaNote: 'Checkout on WhatsApp →',
  },
  {
    slug: 'request-amendment',
    name: 'Request Amendment',
    blurb: 'Change a detail on something already in motion.',
    title: buildPageTitle( 'Request an amendment' ),
    description:
      'Change a date, a detail or the scope of a request already with WECARE.DIGITAL. What can be amended, and what depends on someone else.',
    frame: 'Change the',
    words: cycle( 'date', 'detail', 'scope', 'address' ),
    sub: 'Plans move. Tell us what changed and the request changes with it.',
    sectionHeading: 'Amending something in progress',
    lead:
      'An amendment is a change to a request that already exists - a different date, a corrected spelling, a wider or narrower scope. It is the same conversation, not a new one, so you do not start again.',
    points: [
      { heading: 'Reference what you already have', body: 'Quote the request, the order or just the thread it happened in. If you cannot find it, describing it is enough for us to locate it.' },
      { heading: 'Say what changed, not everything', body: 'Only the difference matters. Everything you have already shared stays attached to the request.' },
      { heading: 'You are told what it affects', body: 'If a change moves a date or affects something already arranged, you hear that before it is actioned rather than after.' },
    ],
    note:
      'Some amendments need a third party\'s agreement - an airline, registry, supplier or government office. We will tell you what is possible and what it depends on, but cannot commit to a change that is not ours.',
    ctaLabel: 'Request an amendment',
    ctaHref: CUSTOMERSERVICE_CTA,
    ctaNote: 'Checkout on WhatsApp →',
  },
  {
    slug: 'drop-docs',
    name: 'Drop Docs',
    blurb: 'Send the paperwork a request needs, once.',
    title: buildPageTitle( 'Drop documents' ),
    description:
      'Send documents to WECARE.DIGITAL for a request already under way - what is usually needed, how it is handled, and what not to send.',
    frame: 'Send the',
    words: cycle( 'papers', 'proofs', 'scans', 'records' ),
    sub: 'Send what a request needs once, and it stays attached to it.',
    sectionHeading: 'Sending documents',
    lead:
      'Most requests need something in writing at some point - an identity proof, an address, a registration, a prior letter. Sending it attaches it to the request it belongs to, so it is not asked for twice.',
    points: [
      { heading: 'A photo is usually enough', body: 'A clear picture of a document is as useful as a scan. If a specific format is genuinely required, you are told which and why.' },
      { heading: 'It stays with the request', body: 'What you send is filed against the request it is for, so the next person who needs it already has it.' },
      { heading: 'Send only what is asked for', body: 'If you are not sure whether something is needed, ask first. Fewer documents held is better for you than more.' },
    ],
    note:
      'Please do not send original certificates, card numbers, passwords or one-time codes - we never need them. Documents are handled as our privacy policy describes.',
    ctaLabel: 'Send documents',
    ctaHref: CUSTOMERSERVICE_CTA,
    ctaNote: 'Checkout on WhatsApp →',
  },
  {
    /*
     * VAULT IS THE RETURN LEG OF DROP DOCS: one page sends paperwork in and the other
     * returns a copy. Both service pages stay available by direct link, not via the menu.
     *
     * /vault/ is the public service page and /vault/?file=<fileId> is the only exact-file
     * customer download surface. The approved WhatsApp delivery template lands on that query
     * route after identity verification; /get/ is no longer a second customer file collection.
     *
     * The boundary note is the important half. A page called Vault invites the assumption that
     * everything is kept forever and can be downloaded on demand, and neither is true - the
     * privacy policy sets retention, and a copy is released to the person it belongs to after
     * the same identity check the rest of the service uses.
     *
     * "DOCUMENTS" LEADS THE CYCLE on the owner's instruction, and it makes this page the
     * widest tail travel on the site. Measured at 1920px: documents 304px, copies 179px,
     * records 206px, reports 194px - a 125px spread, where /contact/'s 70px was the previous
     * maximum. It is NOT a layout defect and that is measured, not assumed: the 21-viewport
     * sweep (320-1920, 84 readings) shows the h1 height constant for every word here and on
     * the contact page, Hunar child pages and the review page, because RotatingHero gives the pill its own line.
     * What it is, is a livelier swing than anywhere else, which is a judgement the owner is
     * entitled to make - so it is recorded rather than quietly tuned away.
     *
     * If it ever reads as too elastic, the fix is one word and the numbers are already
     * measured at the same 1920px metrics: copies -> receipts (216px) gives 110px, and
     * receipts plus records -> statements (301px) gives 98px. "copies" is kept because it is
     * the page's own language - the CTA says "Request a copy" and the section heading is
     * "Getting a copy" - and dropping it to chase a feel metric would cost more than it buys.
     *
     * The sub-line says "paperwork" rather than "documents" deliberately: with "documents" now
     * in the pill, repeating it one line below put the same noun twice in the same breath.
     */
    slug: 'vault',
    name: 'Vault',
    blurb: 'Get a copy of a document we hold for you.',
    title: buildPageTitle( 'Vault — download your documents' ),
    description:
      'Ask WECARE.DIGITAL for a copy of a document held against one of your requests - what is kept, how long it is kept, and how a copy is released to you.',
    frame: 'Get back your',
    words: cycle( 'documents', 'copies', 'records', 'reports' ),
    sub: 'The paperwork a request produced, available to the person it belongs to.',
    sectionHeading: 'Getting a copy',
    lead:
      'A request usually leaves something behind - a filed document, a letter, a receipt, an outcome in writing. Vault is how you ask for a copy of it. Drop Docs is the same door in the other direction.',
    points: [
      {
        heading: 'Ask for it by the request',
        body: 'Name the request rather than the file. You are not expected to know what a document was called internally, and quoting the request is what lets us find it.',
      },
      {
        heading: 'Released to you, after a check',
        body: 'A copy goes to the person the document belongs to, after the same identity check the rest of the service uses. That check is the reason a copy cannot be handed over on a single message.',
      },
      {
        heading: 'A link, not an attachment',
        body: 'Files arrive as a private link you open, rather than as an attachment sitting in a mailbox. The link is yours, it expires, and it can be reissued if it lapses before you use it.',
      },
    ],
    note:
      'Documents are not kept indefinitely - our privacy policy sets how long each kind is held, after which a copy may no longer exist to send. We cannot release someone else\'s document to you, or any document to someone acting for you without your authority.',
    ctaLabel: 'Request a copy',
    ctaHref: CUSTOMERSERVICE_CTA,
    ctaNote: 'Checkout on WhatsApp →',
  },
  {
    /*
     * REQUEST PICKUP SITS DIRECTLY AFTER VAULT in this service data for continuity. The
     * public Request menu is intentionally hidden; deep links and the service data remain.
     *
     * IT IS THE THIRD DOOR IN THE SAME PAIR. Drop Docs sends paperwork in, Vault asks for a copy
     * back out, and this one has it collected rather than sent - the same documents, a different
     * leg. It became a real page on 2026-10-10, when the live catalogue began returning a fifth
     * variant of the services product visible and in stock.
     *
     * THE NOTE IS THE POINT OF THIS PAGE'S COPY. A collection is the one request action that
     * depends on somebody who is not us: a courier or partner has to turn up. So the page says
     * what is arranged rather than promised, and names no window, no price and no turnaround -
     * the three things this file's header forbids, and the three a pickup page is most tempted to
     * invent. A general courier-pickup concept without a backend is a different claim; this page asks for a
     * collection the same way every other row here asks - through /contact/.
     */
    slug: 'request-pickup',
    name: 'Request Pickup',
    blurb: 'Have the paperwork a request needs collected.',
    title: buildPageTitle( 'Request a pickup' ),
    description:
      'Ask WECARE.DIGITAL to collect documents for a request already under way - what to have ready, how a collection is arranged, and what depends on a courier.',
    frame: 'Collect your',
    words: cycle( 'papers', 'parcel', 'folder', 'docket' ),
    sub: 'Some paperwork is easier handed over than sent.',
    sectionHeading: 'Arranging a collection',
    lead:
      'A pickup is for the paperwork you would rather not scan, post or carry - a stack of originals, a folder a request needs seen, something too bulky for a photo. You say where it is and what it is for, and the collection is arranged around that.',
    points: [
      { heading: 'Say where it is', body: 'An address and the hours somebody can hand it over. A reachable number matters more than a precise time, because the person collecting will call before arriving.' },
      { heading: 'Name the request it belongs to', body: 'Quote the request the documents are for, so what arrives is filed against it rather than sitting unattached while somebody works out whose it is.' },
      { heading: 'Pack it as a single handover', body: 'One envelope or folder, sealed, with your name on it. Loose sheets handed over at a doorstep are the ones that go missing.' },
    ],
    note:
      'A collection depends on a courier or partner who is not us, so a pickup is arranged rather than guaranteed - if nobody can collect from where you are, you are told that instead of being left waiting. Please do not hand over original certificates unless we have asked for them specifically; a copy is usually what a request needs.',
    ctaLabel: 'Request a pickup',
    ctaHref: CUSTOMERSERVICE_CTA,
    ctaNote: 'Checkout on WhatsApp →',
  },
];

/** Throws rather than returning undefined, so a bad slug fails the build, not a visitor. */
export const customerserviceBySlug = ( slug: string ): ProductDef => {
  const found = CUSTOMERSERVICE.find( p => p.slug === slug );
  if ( !found ) throw new Error( `Unknown customerservice slug: ${slug}` );
  return found;
};
