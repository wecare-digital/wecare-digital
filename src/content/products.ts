import type { CycleWord } from '../components/RotatingHero';

/**
 * The WECARE.DIGITAL product pages, as data.
 *
 * SEVEN PAGES, ONE SHAPE. Elsewhere, Expo Week, Dastavez, Clear Closure, Ritual Guru,
 * Anew and Niji Setu are all the same kind of page: a rotating hero, a short lead, three
 * points, an optional boundary note and one call to action. Seven copy-pasted page files
 * would mean seven places to fix a spacing bug and seven chances for them to drift apart,
 * which is exactly how the old site ended up with a different footer on every page. The
 * copy lives here, the layout lives in ProductPage.tsx, and each route is a thin file.
 *
 * WHERE THE COPY CAME FROM. The six existing products were read off the old Wix pages with
 * a real browser (pwtest/wixscrape.js). curl returns nothing usable - those pages ship JS
 * bundles and an empty body, so the copy only exists after hydration. Each product's
 * one-line positioning statement is the owner's own, taken from the "X IS A WECARE.DIGITAL
 * BRAND FOR ..." line on its page, then rewritten into sentence case and plain English.
 *
 * WHAT WAS LEFT BEHIND, deliberately: the old site's page furniture, which the scrape picks
 * up on every single page - "A passionate team of solvers...", "MICROSERVICE COMPANY",
 * "DECARBONIZING", "OPERATIONS", "THE FUTURE IS ENGAGED", "Any amount. Message included.",
 * "CLEAR CLOSURE STORE". That is the same chrome that had leaked into section 45 of the
 * Terms and sat live for a session. It is navigation and slogans, not product copy, and
 * none of it is here.
 *
 * NIJI SETU HAS NO WIX PAGE. Its copy comes from the owner's description: a QR code people
 * scan to reach you on a masked call, with your real number never shown.
 *
 * TINTS AND DOTS ARE REUSED VERBATIM from the Grahak OS hero - four pairs, no new colours.
 * Cycle words are held close in length on purpose so the pill barely travels; the animation
 * harness sweeps 21 viewports and a long word is what makes the headline reflow.
 */

/**
 * THE FOUR HERO PAIRS, EXPORTED SO A HUE IS NAMED RATHER THAN RETYPED.
 *
 * They were module-private until /shop/'s listing needed the same rotation for its own hero
 * (src/components/ShopListingView.tsx). Four separate consts rather than one CYCLE_HUES map,
 * deliberately: a map would be a new public name with no consumer, and the thing a consumer
 * actually wants is either `cycle()` or one pair by name.
 *
 * AMBER IS NOT A SPINE COLOUR. These are large pale tints behind dark type, which is the only
 * place amber works on this site - at a 3px stroke it was measured at 2.04:1 and rejected, so the
 * card spines in ShopListingView and BlogIndexView use green, blue and purple only.
 */
export const BLUE = { tint: '#dbeafe', dot: '#2563eb' };
export const AMBER = { tint: '#fef3c7', dot: '#f0a818' };
export const GREEN = { tint: '#e0f7c8', dot: '#3da35a' };
export const PURPLE = { tint: '#ede9fe', dot: '#9849e8' };

/**
 * EXPORTED, so every hero that rotates four words composes them the same way.
 *
 * Adding the keyword cannot disturb `contentModule()` in scripts/generate-public-pages.js: that
 * reader slices from `export const PRODUCTS`, which is declared below this.
 */
export const cycle = ( a: string, b: string, c: string, d: string ): CycleWord[] => [
  { word: a, ...BLUE },
  { word: b, ...AMBER },
  { word: c, ...GREEN },
  { word: d, ...PURPLE },
];

export interface ProductPoint {
  heading: string;
  body: string;
}

export interface ProductDef {
  /** Route slug. The page lives at /{slug}/ - trailingSlash is on. */
  slug: string;
  /** Display name, used in the menu and the badge. */
  name: string;
  /**
   * One short line for the home-page directory. Separate from `sub` because that is a hero
   * line with room to breathe, and from `description` because that is written for a search
   * result. A card in a ten-item grid needs to be scannable in one glance.
   */
  blurb: string;
  /** <title> */
  title: string;
  /** Meta description. Written to stand alone in a search result. */
  description: string;
  /** Hero frame text, before the rotating word. */
  frame: string;
  words: CycleWord[];
  /** Hero sub-line. One sentence, per the design contract. */
  sub: string;
  /** Section heading above the points. */
  sectionHeading: string;
  lead: string;
  points: ProductPoint[];
  /** Boundary statement, where the service is regulated or easily misread. */
  note?: string;
  ctaLabel: string;
  ctaHref: string;
  /**
   * Optional microcopy under the primary CTA. A very short, muted line (the "Continue on
   * WhatsApp →" treatment used by the blog post page's Subscribe/Contribute pills) that names
   * where the button goes when the label itself does not. Rendered aria-hidden, so the anchor's
   * own text/label remains the accessible name. Omit it and no line renders.
   */
  ctaNote?: string;
  /**
   * Optional SECOND call to action. When both are present, ProductPage renders a second pill
   * beside the first; omit them (every entry except /shipments/ does) and the page renders one
   * pill exactly as before. Unlike the first CTA, `ctaHref2` is rendered LITERALLY and is never
   * routed through whatsappServiceLink() — that resolves by slug, and a slug can carry only one
   * service link, so a second door has to name its own destination.
   */
  ctaLabel2?: string;
  ctaHref2?: string;
}

// Every product's call to action lands here until the real per-product destinations
// exist. Referenced through a constant so `grep PRODUCT_CTA` lists them all.
//
// Was '[retired public path]' until 2026-09-25, which was broken twice
// over: `www` 301s to the apex, and `[retired public path]` was deleted with the retired-URL stubs
// in commit 6bc44a35, so the chain ran 301 -> 301 -> 404. Now the apex directly, and
// /contact/ because it is a real 200 page and is the destination the retirement note in
// _app.tsx nominated for /customerservice.
const PRODUCT_CTA = 'https://wecare.digital/contact/';

export const PRODUCTS: ProductDef[] = [
  {
    slug: 'elsewhere',
    name: 'Elsewhere',
    blurb: 'Travel, visas and journeys, handled end to end.',
    title: 'Elsewhere — travel, visas and journeys | WECARE.DIGITAL',
    description:
      'Elsewhere by WECARE.DIGITAL — end-to-end travel: visas, bookings, group and individual journeys, planned and handled for you.',
    frame: 'We handle the',
    words: cycle( 'travel', 'visas', 'bookings', 'journey' ),
    sub: 'A full-service travel club for people who would rather arrive than arrange.',
    sectionHeading: 'What Elsewhere does',
    lead:
      'Elsewhere is the WECARE.DIGITAL brand for end-to-end travel — visas, bookings, and both group and individual journeys, from the first idea to the last transfer.',
    points: [
      { heading: 'Visas and documentation', body: 'The paperwork a trip needs, prepared and tracked, so an application is not the thing that delays you.' },
      { heading: 'Groups and individuals', body: 'Whether it is one traveller or a company offsite, the itinerary is built around who is actually going.' },
      { heading: 'One point of contact', body: 'Flights, stays, transfers and changes stay with one team, so nothing falls between two suppliers.' },
    ],
    note:
      'Visas, entry permissions and travel approvals are granted by governments and airlines, not by us. We prepare and submit what is needed and keep you informed; we cannot guarantee an outcome another authority controls.',
    ctaLabel: 'Plan a journey',
    ctaHref: PRODUCT_CTA,
  },
  {
    slug: 'expo-week',
    name: 'Expo Week',
    blurb: 'A virtual travel fair you can walk through from home.',
    title: 'Expo Week — India\'s virtual travel fair | WECARE.DIGITAL',
    description:
      'Expo Week by WECARE.DIGITAL — a virtual travel fair and immersive digital expo. Explore beaches, mountains, hidden gems and global icons, and plan from home.',
    frame: 'Explore',
    words: cycle( 'beaches', 'mountains', 'hideaways', 'icons' ),
    sub: 'A virtual travel fair: see the place before you commit to the trip.',
    sectionHeading: 'What Expo Week does',
    lead:
      'Expo Week is virtual tourism — India\'s definitive virtual travel fair, bringing beach escapes, mountain retreats, hidden gems and global icons into one immersive destination you can walk through from home.',
    points: [
      { heading: 'Visit before you go', body: 'Browse destinations immersively rather than from a brochure, so the trip you book is the trip you pictured.' },
      { heading: 'Handpicked, not endless', body: 'Curated experiences and exclusive offers, chosen so the shortlist is short enough to decide from.' },
      { heading: 'Plan with purpose', body: 'Built around sustainable travel, so seeing more of a place does not mean costing it more.' },
    ],
    ctaLabel: 'Enter the expo',
    ctaHref: PRODUCT_CTA,
  },
  {
    slug: 'dastavez',
    name: 'Dastavez',
    blurb: 'Business documentation and registrations in India.',
    title: 'Dastavez — business documentation and registrations | WECARE.DIGITAL',
    description:
      'Dastavez by WECARE.DIGITAL — affordable business documentation, registrations and paralegal support in India, done reliably with minimal effort from you.',
    frame: 'Paperwork without the',
    words: cycle( 'queues', 'guesswork', 'delays', 'runaround' ),
    sub: 'Business documentation and registrations in India, handled properly the first time.',
    sectionHeading: 'What Dastavez does',
    lead:
      'Dastavez is the WECARE.DIGITAL brand for business documentation and registrations in India — affordable documentation and paralegal support, so legal paperwork gets done reliably with minimal effort from you.',
    points: [
      { heading: 'Registrations and filings', body: 'The documents a business needs to exist and stay compliant, prepared correctly and filed on time.' },
      { heading: 'Told what it costs first', body: 'Fees are set out before work starts, including the statutory ones that are not ours to waive.' },
      { heading: 'Tracked to completion', body: 'You can see where a matter is, rather than wondering whether it moved this week.' },
    ],
    note:
      'Dastavez is not a law firm and is not a substitute for a lawyer\'s advice. We prepare and process documentation; where a matter needs legal representation or an opinion, that is work for a qualified advocate.',
    ctaLabel: 'Start a filing',
    ctaHref: PRODUCT_CTA,
  },
  {
    slug: 'clear-closure',
    name: 'Clear Closure',
    blurb: 'Settle a dispute online, without a courtroom.',
    title: 'Clear Closure — online dispute resolution | WECARE.DIGITAL',
    description:
      'Clear Closure by WECARE.DIGITAL — an online dispute resolution (ODR) platform. Resolve matters faster, more flexibly and at lower cost, fully online.',
    frame: 'Disputes resolved',
    words: cycle( 'online', 'faster', 'calmly', 'fairly' ),
    sub: 'Online dispute resolution: one secure place to settle a matter without a courtroom.',
    sectionHeading: 'What Clear Closure does',
    lead:
      'Clear Closure is a technology platform for online dispute resolution, bringing the key processes and tools into one secure interface. The mission is plain: improve access to justice with calm, dignified, technology-led resolution.',
    points: [
      { heading: 'Independent professionals', body: 'A network of neutrals who are not employed by either side, so the process is not the other party\'s process.' },
      { heading: 'Faster and cheaper', body: 'Smart workflows replace the scheduling and travel that make conventional disputes slow and expensive.' },
      { heading: 'Fully online', body: 'Filings, evidence, hearings and the outcome live in one place, reachable from wherever you are.' },
    ],
    note:
      'Clear Closure provides the platform and connects you to independent professionals. It does not act for either party, and nothing here removes your right to approach a consumer commission, regulator or court — Terms sections 37 and 39 set that out.',
    ctaLabel: 'Open a matter',
    ctaHref: PRODUCT_CTA,
  },
  {
    slug: 'ritual-guru',
    name: 'Ritual Guru',
    blurb: 'Temple-grade puja kits, packed in small batches.',
    title: 'Ritual Guru — temple-grade puja kits | WECARE.DIGITAL',
    description:
      'Ritual Guru by WECARE.DIGITAL — curated, temple-grade puja kits for festivals, vrats, housewarmings and daily worship, packed in small batches and clearly labelled.',
    frame: 'Puja kits for',
    words: cycle( 'festivals', 'vrats', 'new homes', 'daily use' ),
    sub: 'India\'s living traditions, brought home in a kit that has everything and explains itself.',
    sectionHeading: 'What Ritual Guru does',
    lead:
      'Ritual Guru brings India\'s living traditions into your home with curated, temple-grade puja kits — for festivals, vrats, housewarmings and daily worship.',
    points: [
      { heading: 'Packed in small batches', body: 'Made in small runs for freshness and fragrance, rather than sitting in a warehouse losing both.' },
      { heading: 'Every component labelled', body: 'You know what each item is and what it is for, so the kit works whether or not you grew up with it.' },
      { heading: 'Standard quantities, fair price', body: 'Measured consistently and priced openly, with responsible sourcing behind it.' },
    ],
    ctaLabel: 'Browse kits',
    ctaHref: PRODUCT_CTA,
  },
  {
    // RENAMED TWICE, and the slug moved with the name both times: Swdhya -> Open
    // Possibility -> Anew.
    //
    // Legacy public aliases were retired by owner instruction on 2026-10-01.
    // Link directly to /anew/; do not recreate SEO redirects.
    //
    // THE SANSKRIT EPIGRAPH WAS REMOVED by owner instruction. It was the etymology of the
    // FIRST name ("Swdhya", from svādhyāya / self-study) and never named "Anew"; with the
    // page recast as a written-reflection service the lead now opens on what Anew does.
    slug: 'anew',
    name: 'Anew',
    blurb: 'A considered written reflection on a decision that matters.',
    title: 'Anew — a considered written reflection | WECARE.DIGITAL',
    description:
      'A considered written reflection on a decision that matters — read in your own time, no calls.',
    frame: 'Reflection into',
    words: cycle( 'clarity', 'action', 'direction', 'focus' ),
    sub: 'A considered written reflection on a decision that matters — read in your own time, no calls.',
    sectionHeading: 'What Anew does',
    lead:
      'Tell us about a decision in your own words. We read it carefully and reflect back what appears important, what may be shaping your thinking, where the real tension is, and what could deserve another look before you act.',
    points: [
      {
        heading: 'Written, not a meeting',
        body: 'No calls, no scheduling, no questionnaire. You write naturally; we respond in writing you can save and return to whenever you need another look.',
      },
      {
        heading: 'A reflection, not a verdict',
        body: 'We weigh the assumptions, priorities, tensions and trade-offs in your situation — not a generic pros-and-cons list, and not a decision made for you.',
      },
      {
        heading: 'Usually within 2–3 business days',
        body: 'Once we have what we need to review, you receive your personalised reflection. One short written clarification is included if something needs it.',
      },
    ],
    note:
      'Anew is a guided written reflection, not therapy, counselling, or medical, legal, financial or tax advice. It does not make decisions on your behalf. The conclusions you draw and any action you take remain yours.\n\nIf you need mental-health support, please speak to a qualified professional; in an emergency, contact local emergency services.',
    ctaLabel: 'Start a conversation',
    ctaHref: 'https://wa.me/message/F2D7PVR5Q45MP1',
    // Text-only pill plus the quiet "Continue on WhatsApp →" microcopy, matching the blog post
    // page's Subscribe/Contribute pills. The arrow is part of the text, not an icon.
    ctaNote: 'Continue on WhatsApp →',
  },
  {
    /*
     * HUNAR - hunar is skill, the thing a person actually has, which is the whole argument of
     * the page: a CV is a claim about skill and most of them make it badly.
     *
     * "SKILLS" LEADS THE CYCLE because hunar IS skill, so the word the brand is named after
     * should be the first one the pill says. It replaced "story", which was the vaguest of
     * the four and the only one that named nothing a visitor could ask for. The order then
     * walks outward from the thing itself to how it is presented: skills -> résumé ->
     * profile -> pitch.
     *
     * THE WORDS ARE CLOSE IN LENGTH FOR TRAVEL, NOT FOR REFLOW. The note at the top of this
     * file says a long word makes the headline reflow, and that is true of the two INLINE
     * hero copies but not of RotatingHero, which reserves the pill its own line - see the
     * guarantee recorded in RotatingHero.tsx. Measured across 21 viewports (320-1920) on
     * /hunar/, /vault/, /contact/ and /leave-review/, 84 readings: the h1 height is constant
     * for every word on every route, and the per-viewport ladder is identical on all four -
     * 69.59px at 320 through 142.55px at 1440+ - even on /contact/, whose widest word is
     * 449px. So length here is a movement-feel choice, not a layout constraint.
     *
     * At 1920px: skills 133px, résumé 203px, profile 170px, pitch 133px. That is a 70px tail
     * travel, the same spread /contact/ ships. Swapping "story" (138px) for "skills" (133px)
     * left it unchanged. A longer word would not break the layout - it would only make the
     * pill swing further, which is why the sub-line carries the full "curriculum vitae" idea
     * instead of the pill.
     *
     * THE PAGE DIVIDES THE SKILL FROM THE THINGS THAT CARRY IT, on owner instruction, and the
     * division is stated rather than implied. The skill is what a person actually has; the CV,
     * the profile and the pitch are three places it has to come across. Everything below is
     * ordered on that split - the sub-line names it, the lead explains it, and the points run
     * skill first, then the two artefacts, instead of opening on the CV.
     *
     * It is worth being clear about WHY the split is content rather than colour. The obvious
     * way to set "skills" apart is to give it a distinct pill hue, and that is exactly what
     * the note at the top of this file forbids: the four tint/dot pairs are reused verbatim
     * from the Grahak OS hero with no new colours, and the one lime surface a page is allowed
     * is already spent on the call to action. A fifth hue invented for one word would break
     * both rules to make a point the words can make on their own.
     */
    slug: 'hunar',
    name: 'Hunar',
    blurb: 'Skills, CV and the pitch that carries them.',
    title: 'Hunar — skills, CV profiles and professional identity | WECARE.DIGITAL',
    description:
      'Hunar by WECARE.DIGITAL — sharpen a CV, build a skills profile, and get the short pitch that introduces you. Written to be read by a person in under a minute.',
    frame: 'Sharpen your',
    words: cycle( 'skills', 'résumé', 'profile', 'pitch' ),
    sub: 'The skill is yours. The CV, the profile and the pitch are only how it travels.',
    sectionHeading: 'What Hunar does',
    lead:
      'Hunar means skill, and that is the division this page works to: the skill is what you have, while the CV, the profile and the pitch are the three places it has to come across. Most CVs are not short of achievements; they are short of a reader who can find them.',
    points: [
      {
        heading: 'The skill itself, stated as evidence',
        body: 'First, what you can actually do and what shows it — not a list of words anyone could type. Where a claim has no evidence behind it yet, that is said plainly so you can go and get it rather than dress it up.',
      },
      {
        heading: 'Then a CV read the way it is read',
        body: 'Reviewed for what a hiring reader does in the first twenty seconds: what you did, where the evidence is, and whether the claim survives a second glance. Vague lines are named, not quietly rewritten.',
      },
      {
        heading: 'And a pitch, in two lines',
        body: 'The answer to "what do you do" that works in a message, a call and a room. Built from the same evidence so all three agree, because a pitch that contradicts the document is worse than no pitch.',
      },
    ],
    note:
      'Hunar improves how your experience is presented. It does not place candidates, guarantee interviews or employment outcomes, and it will not add experience you do not have — an inflated CV fails at the point it is checked, which is later and more expensively.',
    ctaLabel: 'Sharpen a CV',
    ctaHref: PRODUCT_CTA,
  },
  {
    slug: 'niji-setu',
    name: 'Niji Setu',
    blurb: 'A QR code that reaches you on a masked call.',
    title: 'Niji Setu — a QR code that reaches you privately | WECARE.DIGITAL',
    description:
      'Niji Setu by WECARE.DIGITAL — a QR code people scan to reach you on a masked call. Your real number is never shown and never shared.',
    frame: 'Your number stays',
    words: cycle( 'private', 'masked', 'hidden', 'yours' ),
    sub: 'A QR code people can scan to reach you on a masked call — your real number is never shown.',
    sectionHeading: 'What Niji Setu does',
    lead:
      'Niji Setu is a bridge that does not hand over your phone number. Put the code where someone might need to reach you; if there is ever a problem, they scan it and get through on a masked call. Your number stays completely private.',
    points: [
      { heading: 'They scan, they do not see', body: 'The scan starts a call. It does not reveal a number, so there is nothing to save, copy or pass on.' },
      { heading: 'Calls are masked both ways', body: 'The connection runs through us, so neither side ends up holding the other\'s personal number.' },
      { heading: 'Useful exactly when it matters', body: 'A blocked car, a lost bag, a delivery at a gate — reachable in the moment, unreachable afterwards.' },
    ],
    ctaLabel: 'Get a code',
    ctaHref: PRODUCT_CTA,
  },
];

/** Lookup by slug, for the thin route files. */
export const productBySlug = ( slug: string ): ProductDef => {
  const found = PRODUCTS.find( p => p.slug === slug );
  if ( !found ) throw new Error( `Unknown product slug: ${slug}` );
  return found;
};
