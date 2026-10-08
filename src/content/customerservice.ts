import type { CycleWord } from '../components/RotatingHero';
import type { ProductDef } from './products';
import { featureFlags } from '../config/featureFlags';
import { reviewWaLink } from '../lib/reviewLink';

/**
 * The five Customer service pages, as data.
 *
 * WHY THESE EXIST. The header's Customer service column offers six rows - Submit Request, Request
 * Amendment, Drop Docs, Leave Review, Refer & Earn and Contact us - and until now every one
 * of them resolved to /contact/. Measured on the built home page: six distinct labels, one
 * destination, on all 872 documents. The menu made six promises and kept one.
 *
 * Header.tsx recorded that as a placeholder and spelled out the way out of it: "To give these
 * rows their own pages, build PUBLIC ones ... and register each in PUBLIC_PAGE_META -
 * otherwise they render a blank 200 or a login wall." This is that. Contact us keeps
 * /contact/, which is its real destination, so five pages are needed rather than six.
 *
 * THEY ARE PUBLIC, AND NOT THE [retired public path]/ PAGES. [retired public path]/submit-request and its siblings
 * already exist and are AUTHENTICATED by design - they render the dashboard Layout and read
 * the requester from a Cognito session. Pointing a public menu row at one shows an anonymous
 * visitor a login wall; Header.tsx measured that at 144,800 bytes of auth shell against
 * 35,738 for public /contact/. These pages import ProductPage, which is public-safe, and
 * nothing here touches Layout or a session.
 *
 * WHAT THEY DO AND DO NOT DO. Each explains one action - what it is, what to have ready, what
 * happens next - and hands off to /contact/ to start it. None of them collects anything:
 * there is no upload control, no form and no account, because none of that exists publicly
 * yet. That is the honest shape today, and it is still a large improvement on six labels
 * sharing one page: a visitor who clicks "Drop Docs" now reads about sending documents
 * instead of landing on a generic contact page and having to work out why.
 *
 * NO TURNAROUND TIMES, NO PRICES, NO GUARANTEES. Every one of those would be a promise with
 * nothing behind it, and the closing band on the home page already carries the one
 * falsifiable claim the site makes. Where an outcome is not ours to control - a reward, a
 * published review, an amendment a supplier has to accept - `note` says so on the page.
 *
 * ONE SHAPE, REUSED. These take the same ProductDef interface and the same ProductPage
 * layout as the seven product pages: the home page's rotating hero, then a heading, a lead,
 * three numbered points and one call to action. Seven copy-pasted page files is how the old
 * site ended up with a different footer on every page; twelve would be worse. The type is
 * imported from products.ts rather than redeclared so the two sets cannot drift.
 *
 * CYCLE WORDS ARE HELD CLOSE IN LENGTH, for the reason products.ts already documents: the
 * pill animates to each word's measured width, so a wide spread makes the headline's tail
 * swing on every tick. Each set below is within two characters end to end.
 *
 * TINTS ARE THE SAME FOUR PAIRS reused verbatim from the Grahak OS hero. No new colours.
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
 * Every CTA lands on the public contact page, which is the real entry point - its own badge
 * reads "Customer service by WECARE.DIGITAL" and its rotation already names these five actions.
 * Through a constant so `grep CUSTOMERSERVICE_CTA` lists them all, the way PRODUCT_CTA does.
 */
const CUSTOMERSERVICE_CTA = 'https://wecare.digital/contact/';

export const CUSTOMERSERVICE: ProductDef[] = [
  {
    slug: 'submit-request',
    name: 'Submit Request',
    blurb: 'Start something new, with the details in one place.',
    title: 'Submit a request | WECARE.DIGITAL',
    description:
      'Start a new request with WECARE.DIGITAL. What to include, what happens after you send it, and how to follow it without chasing.',
    frame: 'Ask us to',
    words: cycle( 'begin', 'arrange', 'prepare', 'handle' ),
    sub: 'One message with the details, and it starts moving from there.',
    sectionHeading: 'What to send, and what follows',
    lead:
      'A request is how anything starts here. You describe what you need in your own words - there is no form to decode and no category to pick - and it is routed to whoever handles that kind of work.',
    points: [
      { heading: 'Say it however is easiest', body: 'Type it, send a voice note, or forward something you already have. Your language is fine; nothing needs to be rewritten into ours.' },
      { heading: 'Useful to include', body: 'What you want to happen, any date that matters, and anything you have already been told or sent. Missing details are asked for rather than assumed.' },
      { heading: 'You will not have to chase it', body: 'Updates come to you where you already are, and you can ask where something stands at any point without repeating the background.' },
    ],
    ctaLabel: 'Submit a request',
    ctaHref: CUSTOMERSERVICE_CTA,
  },
  {
    slug: 'request-amendment',
    name: 'Request Amendment',
    blurb: 'Change a detail on something already in motion.',
    title: 'Request an amendment | WECARE.DIGITAL',
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
      'Some amendments depend on a third party accepting them - an airline, a registry, a supplier or a government office. We will tell you what is possible and what it depends on, but we cannot commit to a change that is not ours to make.',
    ctaLabel: 'Request an amendment',
    ctaHref: CUSTOMERSERVICE_CTA,
  },
  {
    slug: 'drop-docs',
    name: 'Drop Docs',
    blurb: 'Send the paperwork a request needs, once.',
    title: 'Drop documents | WECARE.DIGITAL',
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
      'Please do not send original certificates, and do not send card numbers, passwords or one-time codes - we never need them. Documents are handled under the practices described in our privacy policy.',
    ctaLabel: 'Send documents',
    ctaHref: CUSTOMERSERVICE_CTA,
  },
  {
    /*
     * VAULT IS THE RETURN LEG OF DROP DOCS, and the pair is why it sits directly beneath it in
     * the menu: one page is for sending paperwork in, this one is for getting it back out.
     *
     * IT IS NOT A SECOND /get/. /get/ is the mechanism - verify a number over WhatsApp, then
     * collect what was shared with you - and it is noindex,nofollow with no inbound link
     * anywhere in the export, because it is reached from the message carrying the link.
     * Somebody whose document was never shared into it lands on an empty screen. This page is
     * the part that belongs in a menu: what is kept, how long, how you ask for a copy, and
     * what we will not do. The third point describes the mechanism; the CTA still goes to
     * /contact/, like every other row in this group, because asking always works.
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
     * /contact/, /hunar/ and /leave-review/, because RotatingHero gives the pill its own line.
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
    title: 'Vault — download your documents | WECARE.DIGITAL',
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
      'Documents are not kept indefinitely - our privacy policy sets how long each kind is retained, and once a period ends a copy may no longer exist to send. We also cannot release someone else\'s document to you, or a document to someone acting on your behalf without your authority.',
    ctaLabel: 'Request a copy',
    ctaHref: CUSTOMERSERVICE_CTA,
  },
  {
    slug: 'leave-review',
    name: 'Leave Review',
    blurb: 'Say how it actually went.',
    title: 'Leave a review | WECARE.DIGITAL',
    description:
      'Tell WECARE.DIGITAL how something went - what is useful to say, what happens to a complaint, and how feedback is used.',
    frame: 'Rate the',
    words: cycle( 'service', 'outcome', 'support', 'handover' ),
    sub: 'Whether it went well or it did not, it is worth telling us.',
    sectionHeading: 'Telling us how it went',
    lead:
      'Feedback is read by the people who did the work, not filed as a metric. That is also true when it is critical - a problem described plainly is more useful than a score, and it is the only way something gets fixed for the next person.',
    points: [
      { heading: 'Specific is more useful than kind', body: 'What happened, what you expected, and where the two parted company. One concrete sentence beats five general ones.' },
      { heading: 'A complaint is not a review', body: 'If something went wrong and still needs fixing, say so - it is treated as a request to resolve it, not just as a comment.' },
      { heading: 'You can be as brief as you like', body: 'A line is fine. There is no rating to complete and no questionnaire to finish.' },
    ],
    note:
      'Nothing you send is published anywhere without asking you first, and asking is not a condition of anything. Reviews you choose to leave on an external platform are governed by that platform, not by us.',
    ctaLabel: 'Leave a review',
    /**
     * THE ONE CTA ON THIS PAGE THAT IS NOT THE CONTACT PAGE — when `reviewCta` is on.
     *
     * This is the canonical, UNATTRIBUTED review door: a visitor reading /leave-review/ has
     * no order in context, so the link carries the bare `review` keyword and the Flow shows
     * "General feedback" instead of an order. The attributed door is the per-order button in
     * /orders/, which is the only place a real order number exists.
     *
     * Falls back to `CUSTOMERSERVICE_CTA` with the flag off, so the page always has a
     * working CTA rather than a dead or missing one. The lime `.pdp-cta` pill renders this
     * href unchanged either way — no new component, no new tokens, and the hero is untouched.
     */
    ctaHref: featureFlags.reviewCta ? reviewWaLink() : CUSTOMERSERVICE_CTA,
  },
  {
    slug: 'refer-and-earn',
    name: 'Refer & Earn',
    blurb: 'Introduce someone who would find this useful.',
    title: 'Refer and earn | WECARE.DIGITAL',
    description:
      'Introduce someone to WECARE.DIGITAL - how a referral is recorded, what is recognised, and what depends on the outcome.',
    frame: 'Refer a',
    words: cycle( 'friend', 'family', 'client', 'partner' ),
    sub: 'If this has been useful to you, it may be useful to someone you know.',
    sectionHeading: 'Introducing someone',
    lead:
      'A referral is an introduction, not a lead form. You tell us who to expect and what they are trying to do, or you tell them to mention you - either way the connection is recorded against both of you.',
    points: [
      { heading: 'Either direction works', body: 'Introduce them to us, or have them mention your name when they get in touch. Nothing is lost by doing it the informal way.' },
      { heading: 'They are not cold-called', body: 'An introduction is not permission to market to someone. We wait for them to make contact, or we reach out once because you asked us to.' },
      { heading: 'You can see where it stands', body: 'Ask at any point whether an introduction you made went anywhere. You will get a straight answer.' },
    ],
    note:
      'What a referral is worth depends on what the person you introduced goes on to do, so it is recognised case by case rather than at a fixed rate. Anyone who introduces people regularly should talk to us about a partner arrangement instead - that is a different conversation with terms written down.',
    ctaLabel: 'Introduce someone',
    ctaHref: CUSTOMERSERVICE_CTA,
  },
];

/** Throws rather than returning undefined, so a bad slug fails the build, not a visitor. */
export const customerserviceBySlug = ( slug: string ): ProductDef => {
  const found = CUSTOMERSERVICE.find( p => p.slug === slug );
  if ( !found ) throw new Error( `Unknown customerservice slug: ${slug}` );
  return found;
};
