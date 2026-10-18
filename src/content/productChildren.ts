import type { ProductDef } from './products';
import { cycle } from './products';
import { whatsappKeywordLink } from '../config/whatsappServiceEntries';

export interface ProductChildPage {
  path: string;
  parent: string;
  product: ProductDef;
}

/**
 * Product-family children shown in the public menu.
 *
 * These are real public pages under non-clickable family labels. The family names themselves
 * have no route; only these destinations render. Each child uses the shared ProductPage /
 * RotatingHero detail-page contract.
 */
export const PRODUCT_CHILDREN: readonly ProductChildPage[] = [
  {
    path: '/elsewhere/visa/',
    parent: 'Elsewhere',
    product: {
      slug: 'elsewhere-visa',
      name: 'Visa',
      blurb: 'Visa paperwork, preparation and tracking for a planned trip.',
      title: 'Visa — travel document assistance | WECARE.DIGITAL',
      description: 'Visa assistance from WECARE.DIGITAL — understand the document list, prepare the application and keep track of what is still needed.',
      frame: 'Visa work, kept',
      words: cycle( 'clear', 'ready', 'tracked', 'orderly' ),
      sub: 'Know what is needed, what is still missing and what happens next before an application is submitted.',
      sectionHeading: 'What Visa does',
      lead: 'Visa helps organise the application side of a trip: document requirements, preparation, submission readiness and follow-up in one place.',
      points: [
        { heading: 'A clear document list', body: 'We set out the documents the stated route requires and flag what is missing before the application moves forward.' },
        { heading: 'Prepared before submission', body: 'Forms and supporting material are checked for completeness and consistency so avoidable gaps are found early.' },
        { heading: 'Tracked after hand-off', body: 'You can see what has been submitted, what is pending and whether another document or action has been requested.' },
      ],
      note: 'Visa decisions, entry permission and processing times are controlled by the relevant government, mission or authorised provider. WECARE.DIGITAL can prepare and track an application but cannot guarantee approval or a decision date.',
      ctaLabel: 'Start visa assistance',
      ctaHref: whatsappKeywordLink( 'Visa Assist' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/elsewhere/trip/',
    parent: 'Elsewhere',
    product: {
      slug: 'elsewhere-trip',
      name: 'Trip',
      blurb: 'A trip planned around the people actually taking it.',
      title: 'Trip — travel planning and coordination | WECARE.DIGITAL',
      description: 'Trip planning from WECARE.DIGITAL — itinerary, stays, transfers and practical coordination organised around the journey you actually want to take.',
      frame: 'Plan the',
      words: cycle( 'route', 'stay', 'journey', 'details' ),
      sub: 'One practical itinerary for the trip, the people taking it and the changes that happen along the way.',
      sectionHeading: 'What Trip does',
      lead: 'Trip brings the moving parts of a journey into one plan so flights, stays, transfers and timing are considered together instead of as separate bookings.',
      points: [
        { heading: 'Built around the traveller', body: 'The starting point is who is travelling, why, when and what matters to them — not a pre-built package that has to be forced to fit.' },
        { heading: 'One working itinerary', body: 'Transport, stays, transfers and key timings are kept in one plan so a change in one place can be reflected everywhere else.' },
        { heading: 'A single point of coordination', body: 'Questions and changes stay in one conversation rather than being spread across several suppliers and confirmation threads.' },
      ],
      note: 'Prices, availability, entry rules and supplier conditions can change until a booking is confirmed. WECARE.DIGITAL coordinates the trip but does not control airlines, hotels, transport operators or government entry decisions.',
      ctaLabel: 'Plan a trip',
      ctaHref: whatsappKeywordLink( 'Trip Assist' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/elsewhere/activities/',
    parent: 'Elsewhere',
    product: {
      slug: 'elsewhere-activities',
      name: 'Activities',
      blurb: 'Things to do that fit the place, time and people on the trip.',
      title: 'Activities — travel experiences and day planning | WECARE.DIGITAL',
      description: 'Activities by WECARE.DIGITAL — shortlist and coordinate things to do around the location, timing and people already in your trip plan.',
      frame: 'Make room for',
      words: cycle( 'culture', 'nature', 'food', 'time' ),
      sub: 'A practical shortlist of things to do that fits the route instead of competing with it.',
      sectionHeading: 'What Activities does',
      lead: 'Activities helps turn free time in an itinerary into a workable plan, with options chosen around location, timing, pace and who is travelling.',
      points: [
        { heading: 'Shortlists, not endless lists', body: 'Options are narrowed to the places and experiences that make sense for the route, available time and group.' },
        { heading: 'Timed around the rest of the trip', body: 'Travel time, opening hours and the commitments already in the itinerary are considered before an activity is suggested.' },
        { heading: 'Flexible when plans move', body: 'Where an activity can be changed or replaced, the alternatives are kept close enough to the original plan that the day still works.' },
      ],
      note: 'Activities may be operated by independent third parties. Availability, weather, local rules, safety restrictions and operator terms remain outside WECARE.DIGITAL control and should be checked before confirmation.',
      ctaLabel: 'Plan activities',
      ctaHref: whatsappKeywordLink( 'Elsewhere Activities' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/dastavez/drafting/',
    parent: 'Dastavez',
    product: {
      slug: 'dastavez-drafting',
      name: 'Drafting',
      blurb: 'Structured business documents prepared from the facts you provide.',
      title: 'Drafting — business document preparation | WECARE.DIGITAL',
      description: 'Drafting by Dastavez — structured business document preparation from the facts and instructions you provide, with a clear review step before use.',
      frame: 'Draft with',
      words: cycle( 'structure', 'clarity', 'context', 'review' ),
      sub: 'Turn the facts and instructions you provide into a document that is organised, readable and ready for your review.',
      sectionHeading: 'What Drafting does',
      lead: 'Drafting turns a stated business need into a structured working document, with the assumptions and missing information made visible rather than guessed.',
      points: [
        { heading: 'Starts from your facts', body: 'Names, dates, commercial terms and the purpose of the document come from you; missing inputs are identified before they are silently filled in.' },
        { heading: 'Uses a clear structure', body: 'The document is arranged so the obligations, dates and practical steps can be read and checked without hunting through the text.' },
        { heading: 'Leaves room for review', body: 'You receive a draft to review before final use, including a clear prompt where professional legal advice may be appropriate.' },
      ],
      note: 'Dastavez provides document preparation and paralegal support, not legal representation or a lawyer\'s opinion. A document with legal consequences should be reviewed by a qualified advocate when the circumstances require legal advice.',
      ctaLabel: 'Start drafting',
      ctaHref: whatsappKeywordLink( 'Dastavez Drafting' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/dastavez/registration/',
    parent: 'Dastavez',
    product: {
      slug: 'dastavez-registration',
      name: 'Registration',
      blurb: 'Registration paperwork and filing steps organised end to end.',
      title: 'Registration — business registration support | WECARE.DIGITAL',
      description: 'Registration by Dastavez — understand the filing path, prepare the required documents and track the registration process in one place.',
      frame: 'Registration without',
      words: cycle( 'queues', 'guesswork', 'gaps', 'drift' ),
      sub: 'Know the filing path, the document list and the current status before the next step is due.',
      sectionHeading: 'What Registration does',
      lead: 'Registration organises the paperwork and filing steps around a stated business registration so requirements, fees and status are visible from the start.',
      points: [
        { heading: 'The filing path first', body: 'The applicable registration route and required information are set out before documents are prepared.' },
        { heading: 'Documents prepared together', body: 'Supporting documents and form inputs are checked as a set so names, addresses, identifiers and dates stay consistent.' },
        { heading: 'Status kept visible', body: 'Submission, authority queries and the next required action are tracked until the process reaches its available outcome.' },
      ],
      note: 'Registrations are decided and processed by the relevant authority. Dastavez can prepare and file documentation where supported, but cannot guarantee acceptance, processing time or an authority decision.',
      ctaLabel: 'Start a registration',
      ctaHref: whatsappKeywordLink( 'Dastavez Registration' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/dastavez/legal-reference/',
    parent: 'Dastavez',
    product: {
      slug: 'dastavez-legal-reference',
      name: 'Legal Reference',
      blurb: 'Find the source material behind a legal or compliance question.',
      title: 'Legal Reference — laws, judgments and source material | WECARE.DIGITAL',
      description: 'Legal Reference by Dastavez — locate relevant laws, rules, judgments and public source material so you can see what a requirement is based on.',
      frame: 'Find the',
      words: cycle( 'law', 'rule', 'source', 'reference' ),
      sub: 'Locate the source material behind a question without turning reference research into legal advice.',
      sectionHeading: 'What Legal Reference does',
      lead: 'Legal Reference helps locate and organise publicly available legal and regulatory source material around a stated question or topic.',
      points: [
        { heading: 'Source-first research', body: 'The result points back to the law, rule, judgment, notification or official material it relies on wherever that source is available.' },
        { heading: 'Relevant passages organised', body: 'Material is grouped around the question so you can see why a source may matter without reading an unrelated document end to end.' },
        { heading: 'Clear boundary on interpretation', body: 'Reference material is separated from legal opinion so research is not presented as personalised advice.' },
      ],
      note: 'Legal Reference is research and source-finding support, not legal advice, representation or an opinion on how a court or authority will decide a matter. Use a qualified advocate for legal advice about your circumstances.',
      ctaLabel: 'Start legal research',
      ctaHref: whatsappKeywordLink( 'Dastavez Legal Reference' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/ritual-guru/ritva/',
    parent: 'Ritual Guru',
    product: {
      slug: 'ritual-guru-ritva',
      name: 'Ritva',
      blurb: 'Astrology & Vastu, made personal.',
      title: 'Ritva — personal astrology & Vastu guidance | WECARE.DIGITAL',
      description: 'Ritva by Ritual Guru — personal astrology and Vastu guidance built around your questions, timing and space, with clear next steps.',
      frame: 'Guidance for your',
      words: cycle( 'timing', 'space', 'choices', 'next move' ),
      sub: 'Astrology & Vastu, made personal.',
      sectionHeading: 'What Ritva does',
      lead: 'Ritva brings astrology and Vastu into one personal guidance flow. Start with the question, timing or space you want to understand, then get the relevant context in plain language.',
      points: [
        { heading: 'Start with your question', body: 'Choose astrology, Vastu or both and share only the context needed for the question you want to explore.' },
        { heading: 'See the reasoning', body: 'Key chart or space observations are explained in plain language, including where interpretation can vary.' },
        { heading: 'Leave with practical next steps', body: 'The guidance is translated into a small set of actions or considerations you can use without treating a reading as certainty.' },
      ],
      note: 'Astrology and Vastu are traditional interpretive practices. Ritva offers guidance and reflection, not guaranteed predictions or a substitute for medical, legal, financial or other professional advice.',
      ctaLabel: 'Start with Ritva',
      ctaHref: whatsappKeywordLink( 'Ritva' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/ritual-guru/puja-guidance/',
    parent: 'Ritual Guru',
    product: {
      slug: 'ritual-guru-puja-guidance',
      name: 'Puja Guidance',
      blurb: 'Clear step-by-step guidance for a puja you are doing yourself.',
      title: 'Puja Guidance — step-by-step ritual guidance | WECARE.DIGITAL',
      description: 'Puja Guidance by Ritual Guru — a clear sequence, item list and practical explanation for a puja you are performing yourself.',
      frame: 'Puja with',
      words: cycle( 'sequence', 'meaning', 'care', 'clarity' ),
      sub: 'Know what comes next, what each item is for and what can be prepared before you begin.',
      sectionHeading: 'What Puja Guidance does',
      lead: 'Puja Guidance gives you a practical sequence for a ritual you are performing yourself, with preparation and item use explained in plain language.',
      points: [
        { heading: 'Preparation first', body: 'The item list and basic setup are explained before the sequence starts so you are not searching for something halfway through.' },
        { heading: 'A step-by-step sequence', body: 'The order is kept clear enough to follow at your own pace, including the points where traditions commonly differ.' },
        { heading: 'Meaning where it helps', body: 'Short context is included for important steps so the process is more than a list of instructions.' },
      ],
      note: 'Ritual practices vary by family, region, sampradaya and priestly tradition. Puja Guidance is practical guidance for self-led worship, not a claim that one sequence is the only correct form for every tradition.',
      ctaLabel: 'Ask for puja guidance',
      ctaHref: whatsappKeywordLink( 'Ritual Guru Puja Guidance' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/ritual-guru/diy-puja-kit/',
    parent: 'Ritual Guru',
    product: {
      slug: 'ritual-guru-diy-puja-kit',
      name: 'DIY Puja Kit',
      blurb: 'A clearly labelled set of puja essentials for self-led worship.',
      title: 'DIY Puja Kit — labelled puja essentials | WECARE.DIGITAL',
      description: 'DIY Puja Kit by Ritual Guru — a clearly labelled set of puja essentials with a checklist and simple use guidance for self-led worship.',
      frame: 'A kit that is',
      words: cycle( 'complete', 'labelled', 'simple', 'ready' ),
      sub: 'A practical set of puja essentials with a checklist so you know what is included and what each item is for.',
      sectionHeading: 'What the DIY Puja Kit does',
      lead: 'The DIY Puja Kit brings the essential items for a stated puja together in one clearly labelled set, with a simple checklist for preparation.',
      points: [
        { heading: 'Items clearly labelled', body: 'Each included item is named so you can identify it quickly instead of relying on packaging colour or memory.' },
        { heading: 'A checklist before you begin', body: 'The kit shows what is included and what common household items, if any, you still need to arrange separately.' },
        { heading: 'Packed for practical use', body: 'Quantities are prepared for the stated ritual format and kept together so the kit is easy to store and lay out.' },
      ],
      note: 'Exact contents can vary by puja, tradition and availability. The final item list should be checked before confirmation, especially where your family or priest follows a specific regional or sampradaya practice.',
      ctaLabel: 'Ask about a kit',
      ctaHref: whatsappKeywordLink( 'Ritual Guru DIY Puja Kit' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/hunar/kaushal/',
    parent: 'Hunar',
    product: {
      slug: 'hunar-kaushal',
      name: 'Kaushal',
      blurb: 'Skills and learning built around what you want to do next.',
      title: 'Kaushal — skills and learning | WECARE.DIGITAL',
      description: 'Kaushal by Hunar — identify the skills worth building, follow a focused learning path and turn progress into evidence you can use.',
      frame: 'Build skills with',
      words: cycle( 'focus', 'practice', 'proof', 'progress' ),
      sub: 'Know what to learn next, why it matters and how to turn learning into evidence you can use.',
      sectionHeading: 'What Kaushal does',
      lead: 'Kaushal turns a broad learning goal into a practical path: the skills to build, the order to build them in and the evidence that shows the learning is real.',
      points: [
        { heading: 'Find the skill gap', body: 'Start from the role, goal or work you want to do and separate what you already know from the capabilities that still need to be built.' },
        { heading: 'Build a focused learning path', body: 'Turn the gap into a practical sequence of learning, practice and useful resources instead of collecting courses without a clear next step.' },
        { heading: 'Turn learning into evidence', body: 'Use projects, examples and completed work to show what changed, so a new skill is supported by something another person can actually inspect.' },
      ],
      note: 'Kaushal can structure a learning path and help you present evidence of progress. It does not issue accredited qualifications, guarantee proficiency, interviews or employment, and it will not present unfinished learning as proven skill.',
      ctaLabel: 'Start Kaushal',
      ctaHref: whatsappKeywordLink( 'Kaushal' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },
  {
    path: '/hunar/prastuti/',
    parent: 'Hunar',
    product: {
      // Each Hunar child owns its own catalogue identity; the retired parent owns none.
      slug: 'hunar-prastuti',
      name: 'Prastuti',
      blurb: 'CV, professional profile and pitch deck built from the same evidence.',
      title: 'Prastuti — CV, profile and pitch deck | WECARE.DIGITAL',
      description: 'Prastuti by Hunar — turn real experience into a clearer CV, professional profile and concise pitch deck without inventing claims.',
      frame: 'Present your',
      words: cycle( 'experience', 'CV', 'profile', 'pitch' ),
      sub: 'Turn your work into a CV, professional profile and pitch deck that tell the same clear story.',
      sectionHeading: 'What Prastuti does',
      lead: 'Prastuti takes the experience you already have and makes it easier to understand quickly — first as evidence, then as a CV or profile, then as a concise pitch or deck.',
      points: [
        { heading: 'Find the strongest evidence', body: 'Pull out the work, responsibilities and results that actually support the story instead of leading with generic claims or a long list of adjectives.' },
        { heading: 'Build the CV and profile', body: 'Structure the experience for fast reading, with the important evidence easy to find and the same professional story carried into the profile.' },
        { heading: 'Build the pitch and deck', body: 'Turn that same evidence into a short spoken or written pitch and, where needed, a concise deck that does not contradict the CV.' },
      ],
      note: 'Prastuti improves how your experience is presented. It does not invent achievements or guarantee interviews, jobs, funding or other outcomes; every claim should remain true when checked.',
      ctaLabel: 'Build your Prastuti',
      ctaHref: whatsappKeywordLink( 'Prastuti' ),
      ctaNote: 'Checkout on WhatsApp →',
    },
  },

];

export const productChildByPath = ( path: string ): ProductChildPage => {
  const found = PRODUCT_CHILDREN.find( child => child.path === path );
  if ( !found ) throw new Error( `Unknown product child path: ${path}` );
  return found;
};
