/**
 * Terms of Service — rewritten in plain English.
 *
 * THIS REPO IS NOW THE SOURCE OF TRUTH. The text originally came from the old Wix site,
 * which is being retired, so there is no longer an upstream to sync with and no
 * extractor to re-run. Edit this file.
 *
 * WHAT THE REWRITE CHANGED, on owner instruction:
 *   - Active voice, short sentences, "we" and "you". The original was written almost
 *     entirely in the third person about itself ("WECARE.DIGITAL may request...") and
 *     averaged well over 30 words a sentence.
 *   - Cut the hedging that carried no meaning. "Where applicable law requires an
 *     appropriate mechanism, an appropriate mechanism will be used" is a sentence that
 *     says nothing; where a commitment is unconditional it now reads as one.
 *   - Cut repetition. The "nothing in this section limits your rights under applicable
 *     law" saver appeared fourteen times. It is a genuine and important protection, so
 *     it is stated once up front in section 2 AND kept in the specific places where a
 *     reader is most likely to be talked out of a remedy - sections 14, 14.2, 14.4,
 *     14.6, 14.8, 14.9, 14.10, 31, 32 and 33 - rather than sprinkled everywhere.
 *   - Added `inShort` to every top-level section. A 57-section contract with no summaries
 *     is not readable on a phone, which is where it gets opened.
 *   - REMOVED SCRAPED PAGE FURNITURE FROM THE CONTACT SECTION, which was 45 at the time of
 *     the rewrite and is now 47. The extractor had swept up the old
 *     site's footer and navigation into the contact section, so the signed-off Contact
 *     Information clause ended with "BUY GIFT CARD", "DECARBONIZING", "INVITE", "APP",
 *     the retired brand name, and the literal string "bottom of page". That was live.
 *
 * WHAT IT DID NOT CHANGE: any obligation, right, remedy, limitation, disclaimer or
 * liability cap. The rewrite kept every section's original NUMBER, id and scope, so
 * citations still resolve - including the two from elsewhere in this codebase, src/pages/
 * orders.tsx to section 14 and src/pages/bharat-rx.tsx to section 17. The ONLY numbers
 * that have moved since are the last three, when the contact clause was sent to the end of
 * the document; see the note above section 45 for exactly what changed. Nothing was
 * added that makes a commitment the original did not already make; in particular the
 * original's deliberate vagueness about which conditions attach to which service is
 * preserved, because that genuinely varies per service and inventing specifics here
 * would create terms the business has not agreed to.
 *
 * STILL NEEDS A LAWYER. Rewriting for clarity is not legal review. Two things I could
 * see but cannot fix by editing: section 32's liability cap at "the amount paid for the
 * product or Service giving rise to the claim" is untested against the Consumer
 * Protection Act 2019 for the regulated-professional services in section 17, and
 * section 39 names Kolkata courts while section 37 and section 39 both preserve consumer
 * forum rights - the interaction should be confirmed rather than assumed.
 */

import type { LegalSection } from './types';

/**
 * Bumped from 2026-09-23 when section 31.1 was added.
 *
 * NOT READER-FACING, and it is worth saying so here because the obvious assumption is wrong:
 * `grep -rn TERMS_UPDATED src/` outside this directory returns nothing. The "Last updated" line
 * was removed from the rendered document on instruction, and LegalDocument.tsx records that the
 * dates stay "for engineering". So this is the revision marker for whoever maintains the text,
 * not a notice to a returning visitor.
 *
 * Move it for any change to a clause; do not move it for a comment. If a reader-facing revision
 * notice is ever wanted back, this is the value it should read from rather than a second date.
 */
export const TERMS_UPDATED = '2026-09-30';

export const TERMS_INTRO: string[] = [
  'These Terms of Service govern your use of the websites, apps, products and services offered under the WECARE.DIGITAL name. We call all of it "the Services".',
  'WECARE.DIGITAL is a brand of WECARE.DIGITAL BHARATWORKS. In these Terms, "we", "us" and "our" mean that business, and "you" means anyone using the Services.',
  'By using the Services you agree to these Terms. If you do not agree, please do not use them.',
  'Read these Terms alongside our Privacy Policy at /privacy/, which explains what we do with personal data. Individual services sometimes add their own terms; where they do, those apply on top of these.',
  'Nothing in these Terms takes away a right the law gives you and does not let you sign away. Where something here conflicts with such a right, the law wins.',
];

export const TERMS_SECTIONS: LegalSection[] = [
  {
    number: '1', heading: 'The words we use', id: 's1',
    inShort: 'Defined once here so the rest of the document can stay short.',
    paragraphs: [
      'WECARE.DIGITAL is the brand the Services are offered under. WECARE.DIGITAL BHARATWORKS is the business that operates it.',
      'The Platform means any website, app, portal, interface, software or tool we operate under the WECARE.DIGITAL name.',
      'The Services means everything we make available through WECARE.DIGITAL, now or in future. That can include physical products; customised or made-to-order products; marketplace services; professional and expert services; consultations and assistance; documentation and processing work; bookings and appointments; travel and experiences; events and programmes; dispute-resolution and facilitation services; digital products and content; memberships and subscriptions; customer-service tools; technology-enabled workflows; payment and fulfilment facilitation; partner and referral programmes; gift cards, credits and promotions; and anything else we add later.',
      'A User - "you" - is any person or organisation using the Services.',
      'A Seller is anyone offering goods through the Platform. A Service Provider is any professional, expert, consultant, practitioner, institution, organisation or agency providing services through it. A Third-Party Provider means either of those, or any other independent business whose products or services you can reach through us.',
      'User Content means anything you submit: reviews, ratings, photographs, text, documents, comments, messages and files.',
      'Service-Specific Terms means the extra conditions that attach to a particular service - engagement terms, order or booking terms, cancellation conditions, or any other rules shown for that service.',
    ],
  },
  {
    number: '2', heading: 'What these Terms cover', id: 's2',
    inShort: 'Everything we offer now and anything we add later. Some services add their own terms, and those take precedence for that service only.',
    paragraphs: [
      'These Terms apply to all Services we currently offer and, unless we say otherwise, to Services we introduce later.',
      'We may add, change, expand, reorganise, replace or withdraw Services from time to time.',
      'Some Services carry additional Service-Specific Terms - for example professional or regulated services, Partner Up and other partner programmes, referral and affiliate programmes, gift cards, subscriptions, travel and experiences, digital products, events, enterprise services, customised products, and documentation or processing work.',
      'Where Service-Specific Terms apply, they form part of your agreement for that service.',
      'If Service-Specific Terms contradict these Terms, the Service-Specific Terms govern that service, to the extent of the contradiction. That is subject to the law: neither document can remove a right you hold under applicable law and cannot waive.',
    ],
  },
  {
    number: '3', heading: 'Who can use the Services', id: 's3',
    inShort: 'You need to be legally able to enter the transaction. Someone who is not can still use an eligible service where the law allows it and a parent or guardian is involved.',
    paragraphs: [
      'Unless a particular service says otherwise, you must be legally capable of entering into the transaction you are making.',
      'Someone who cannot independently enter a binding transaction may use an eligible service only where the law permits it, and with the involvement, authorisation or consent of a parent, legal guardian or other authorised person.',
      'We may ask you to verify your age, identity, authority or legal capacity where that is necessary.',
      'Do not misrepresent your age, identity, authority or legal capacity.',
    ],
  },
  {
    number: '4', heading: 'Using the Services for an organisation', id: 's4',
    inShort: 'If you are acting for a company or institution, you are confirming you have authority to. A signed agreement with us outranks these Terms on anything it covers.',
    paragraphs: [
      'If you use the Services on behalf of a company, institution, school, employer, association or other organisation, you confirm that you are authorised to act for it.',
      'Organisational and enterprise services may be covered by a separate proposal, memorandum of understanding, order form, engagement letter, service agreement or master services agreement.',
      'Where we have entered into such an agreement, it prevails over these Terms on the matters it specifically addresses.',
    ],
  },
  {
    number: '5', heading: 'Our role changes with the service', id: 's5',
    inShort: 'Sometimes we sell to you directly. Sometimes we are the marketplace and an independent business supplies what you bought. The listing, checkout or confirmation tells you which.',
    paragraphs: [
      'WECARE.DIGITAL runs a multi-service platform, and our role is not the same in every transaction.',
      'Depending on what you are buying, we may act as the direct seller of goods; the direct provider of a service; a marketplace; a technology platform; an intermediary or facilitator; a booking or appointment facilitator; a payment or transaction facilitator; a workflow or communication facilitator; a reseller or distributor; a fulfilment or administrative coordinator; or in another role we identify for that service.',
      'Where we are identified as the direct seller or provider, the product or service is supplied by us or on our behalf.',
      'Where an independent Third-Party Provider is identified as the Seller or Service Provider, the underlying goods or services may be supplied by that provider rather than by us.',
      'The listing, checkout, booking flow, confirmation or Service-Specific Terms may identify who is supplying what you are buying and what our role is.',
      'This section does not reduce any responsibility the law requires us to carry.',
    ],
  },
  {
    number: '6', heading: 'Independent sellers and providers', id: 's6',
    inShort: 'They are responsible for what they claim and what they supply. We verify what we can and can remove them, but our checks are not a guarantee of their work.',
    paragraphs: [
      'Third-Party Providers are responsible for what they tell you about their products, services, qualifications, licences, registrations, availability, prices and specifications.',
      'They must follow the law and the terms of their relationship with us.',
      'They must not give materially false or misleading information, misrepresent their qualifications or affiliations, offer unlawful or counterfeit goods, provide prohibited services, manipulate ratings or reviews, infringe intellectual-property rights, act fraudulently, or engage in unfair trade practices.',
      'We may ask a Third-Party Provider to verify its identity, qualifications, registrations, licences or business details.',
      'We may restrict, suspend or remove a provider or a listing where that is reasonably necessary for legal compliance, fraud prevention, the integrity of the Platform, user safety, consumer protection, or to enforce the terms that apply to them.',
      'Any verification we carry out is a check, not a guarantee. It does not warrant a provider\'s future conduct, the quality of their work, their suitability for your purpose, or any particular outcome.',
    ],
  },
  {
    number: '7', heading: 'Information you get before you buy', id: 's7',
    inShort: 'Before you commit we show what you need in order to decide: who is selling, what it is, what it costs in total, and how to cancel or complain.',
    paragraphs: [
      'Where we act as a marketplace or facilitator, we display or make available the information you need to make an informed decision, as appropriate to the transaction and as the law requires.',
      'Depending on the transaction that can include who the Seller or Service Provider is and how to contact them; the material characteristics of the product or service; the price and any compulsory charges; accepted payment methods; delivery and fulfilment information; the cancellation, return, replacement and refund conditions; warranty or guarantee information; and how to raise a grievance.',
      'Where the law requires it, we will also give you a Seller or Service Provider\'s details after a transaction so that you can pursue a grievance or dispute effectively.',
      'Where imported goods or services require importer or country-of-origin disclosures, we provide that information as the law requires.',
    ],
  },
  {
    number: '8', heading: 'Your account', id: 's8',
    inShort: 'Keep your details accurate and your password to yourself. Tell us if you think someone else has got into your account.',
    paragraphs: [
      'Some Services need an account.',
      'When you have one, please give us accurate, current and complete information; keep it reasonably up to date; look after your login credentials; keep your password and authentication details confidential; use the account lawfully; and tell us if you have reason to believe someone has accessed it without your authorisation.',
      'Do not sell, transfer or rent your account, or knowingly let someone else use it without authorisation.',
      'We may ask you to verify your identity, payment details, age, contact details or business details where that is necessary for security, legal compliance, fraud prevention, or to provide a service.',
    ],
  },
  {
    number: '9', heading: 'Orders, bookings and service requests', id: 's9',
    inShort: 'Your order is an offer. It becomes a deal when we accept it, confirm it, take payment or start the work - not when the automatic acknowledgement email arrives.',
    paragraphs: [
      'Everything is subject to availability and to the conditions shown for it.',
      'When you place an order, make a booking or submit a paid service request, you are generally offering to buy.',
      'An automated message telling you we have received your request is not necessarily our acceptance of it.',
      'Depending on the transaction, it becomes confirmed when we or the relevant provider accept it, when a confirmation is issued, when payment is confirmed, or when work on the service begins.',
      'We may decline, suspend or cancel a transaction where that is reasonably necessary: the item is unavailable, payment failed, we suspect fraud, the information given is incomplete or materially wrong, there is a material pricing or listing error, there is a legal or regulatory restriction, there is a safety concern, or there is another legitimate reason.',
      'If we cancel a transaction you have paid for and a refund is due to you by law or under these Terms, we will process it.',
    ],
  },
  {
    number: '10', heading: 'Nothing is bought by default', id: 's10',
    inShort: 'We do not charge you because you left a box ticked or did nothing at all. Buying takes a deliberate act from you.',
    paragraphs: [
      'We do not treat a paid product, service, subscription or optional charge as purchased because you were inactive, because a paid option was pre-selected, or because a checkbox was pre-ticked.',
      'A purchase, booking or subscription has to follow from something you actively did.',
      'We disclose the compulsory charges that apply to your transaction before you confirm it.',
    ],
  },
  {
    number: '11', heading: 'Prices, taxes and charges', id: 's11',
    inShort: 'The total can include tax, delivery and service fees. Everything compulsory is shown before you confirm, and a later price change does not reprice an order we already accepted.',
    paragraphs: [
      'Prices vary between Services.',
      'Depending on the transaction, the total may include the product price, a service fee, applicable taxes, delivery charges, booking charges, platform or facilitation charges, customisation charges, processing charges, or another charge we disclose.',
      'We disclose the compulsory charges before you finally confirm the transaction.',
      'We may change prices and fees for future transactions.',
      'A price change does not normally change the price of a transaction we have already accepted. The exceptions are where the law requires it, where you expressly agree, or where it is needed to correct an obvious material error before the work is done.',
    ],
  },
  {
    number: '12', heading: 'Paying', id: 's12',
    inShort: 'Use a payment method you are entitled to use. Banks and gateways actually move the money and their terms also apply. We are not a bank.',
    paragraphs: [
      'Where available, you can pay by UPI, credit card, debit card, internet banking, payment gateway, an approved wallet, bank transfer, or another authorised method.',
      'Payments are processed by independent banks, gateways and payment service providers, and their terms may apply to that processing as well as ours.',
      'Facilitating a payment does not make us a bank, a payment bank or a financial institution.',
      'Only use payment methods you are legally entitled to use.',
      'If a payment fails, is reversed, disputed or charged back, or looks like it may be fraudulent, we may suspend the related transaction while the matter is investigated or resolved.',
    ],
  },
  {
    number: '13', heading: 'Subscriptions, memberships and recurring payments', id: 's13',
    inShort: 'We tell you the price, the billing interval and how to cancel before you sign up. Cancelling stops the next renewal; it does not usually refund the period you are already in.',
    paragraphs: [
      'Some Services are provided on a subscription, membership or recurring-payment basis.',
      'Before you enrol we disclose the price, the billing interval, the material features, how renewal works, how the recurring payment is authorised, and how to cancel.',
      'Where a recurring payment needs your authorisation, we obtain it through the relevant payment mechanism.',
      'Unless we say otherwise or the law requires otherwise, cancelling stops future renewals but does not by itself entitle you to a refund for a billing period that is complete or already under way.',
      'Free trials, introductory offers and promotional subscriptions may carry extra conditions, which we disclose when you enrol.',
    ],
  },
  {
    number: '14', heading: 'Cancelling, changing and getting money back', id: 's14',
    inShort: 'What you can cancel, change or recover depends on what it was, why you are asking, and how far along it is. Nothing in this section removes a refund the law requires.',
    paragraphs: [
      'Whether you can cancel, return, replace, reschedule, change a service or get a refund depends on the type of product or service, the reason for the request, how far fulfilment has got, the costs already incurred, and the conditions disclosed for that transaction.',
      'Different conditions apply to physical products, customised products, professional services, consultations, appointments, documentation and processing work, bookings, events, travel and experiences, subscriptions, digital products and other specialised services.',
      'The conditions that apply to you may be shown on the service page, the order or booking form, the checkout page, the confirmation, the invoice, or the Service-Specific Terms.',
      'Nothing in this section or its sub-sections limits a refund, replacement, cancellation or other remedy the law requires us to provide.',
    ],
  },
  {
    number: '14.1', heading: 'How an eligible problem can be resolved', id: 's14-1',
    paragraphs: [
      'Depending on the transaction, and where the law permits, an eligible cancellation or service problem may be resolved by a refund to your original payment method, a WECARE.DIGITAL gift card or account credit, a replacement product, rescheduling, a change to another available service, a replacement booking, an adjustment against another WECARE.DIGITAL service, or another resolution we agree with you.',
      'Where the law requires us to refund money, we will not impose a gift card, account credit or replacement service instead - unless you choose to accept one, or the law allows it.',
    ],
  },
  {
    number: '14.2', heading: 'Gift card and account-credit refunds', id: 's14-2',
    paragraphs: [
      'For some eligible cancellations, promotional transactions and services, a refund may be available as a WECARE.DIGITAL gift card or account credit - where that option was disclosed for the transaction, or where you choose it.',
      'A gift card or account credit can be used towards eligible WECARE.DIGITAL products and services. It may carry restrictions we disclose when we issue it, may be non-transferable where we say so, and may be adjusted if the original transaction is later reversed, disputed, or found to involve fraud.',
      'Gift cards and account credits are not normally redeemable for cash, unless we say so or the law requires it.',
      'Where a transaction is identified before purchase as eligible for a gift card or credit refund only, that condition can apply to voluntary cancellations and changes - but only as far as the law permits, and it does not remove any refund or remedy the law requires.',
    ],
  },
  {
    number: '14.3', heading: 'Changing or rescheduling a service', id: 's14-3',
    paragraphs: [
      'If you no longer want the service you originally chose, we or the provider may - where it is available - let you switch to another service, change or reschedule your appointment, change provider, put what you have paid towards another eligible service, or take a gift card or account credit instead.',
      'If the replacement costs more, you may need to pay the difference.',
      'If it costs less, the difference may be refunded, issued as a gift card or account credit, or adjusted against another eligible service - depending on the Service-Specific Terms and the law - or resolved another way by agreement.',
      'Once you have accepted and used a replacement service or an agreed change, we may treat the original cancellation request as resolved to the extent appropriate.',
    ],
  },
  {
    number: '14.4', heading: 'Charges that may not come back', id: 's14-4',
    paragraphs: [
      'Some amounts may be non-refundable, where the law permits and where we disclosed that condition before or with the transaction.',
      'Depending on the transaction those can include professional time already worked; a consultation already given or started; documentation, research, drafting or processing already done; customisation already begun; government, statutory or filing fees already paid; non-recoverable third-party charges already incurred; confirmed booking or reservation charges we cannot recover from the provider; payment-processing charges actually incurred, where they are lawfully non-refundable; delivery or logistics charges already incurred; priority-processing charges once the priority work has started; digital products or services already activated, downloaded or consumed; event, travel or experience costs already committed to a provider; and any other charge we identified as non-refundable before the transaction.',
      'Calling a fee non-refundable does not make it so. Where the law requires an amount to be refunded, it is refunded.',
    ],
  },
  {
    number: '14.5', heading: 'Standard products', id: 's14-5',
    paragraphs: [
      'Whether you can return or replace a standard product, or get a refund for it, depends on the conditions disclosed for that product and on the law.',
    ],
  },
  {
    number: '14.6', heading: 'Customised and made-to-order products', id: 's14-6',
    paragraphs: [
      'Customised, personalised and made-to-order goods may stop being cancellable or returnable for change-of-mind reasons once production, procurement or customisation has started - where we disclosed that before you bought.',
      'This does not affect your rights if the product turns out to be defective, damaged, spurious, materially misdescribed or otherwise not what was agreed.',
    ],
  },
  {
    number: '14.7', heading: 'Services already started', id: 's14-7',
    paragraphs: [
      'Where a service involves professional time, research, documentation, filing, processing, administration, procurement, booking or customisation that has already started, what you can recover may depend on how far it has got, the work already done, the third-party costs already incurred, and the Service-Specific Terms.',
      'The refundable amount may be reduced by what was reasonably and lawfully spent on work already performed, third-party costs we cannot recover, statutory or government fees already paid, and other disclosed costs attributable to your request.',
      'Any such reduction is still subject to the law.',
    ],
  },
  {
    number: '14.8', heading: 'Faulty, deficient, damaged or misdescribed goods and services', id: 's14-8',
    paragraphs: [
      'Nothing in these Terms restricts the rights the law gives you where goods are defective, damaged or spurious; a service is deficient; what you received differs materially from its description; agreed specifications were not met; what you bought cannot be supplied as agreed; or any other legally recognised ground for a refund, replacement, return or other remedy applies.',
    ],
  },
  {
    number: '14.9', heading: 'When we or a provider cancel', id: 's14-9',
    paragraphs: [
      'If an accepted transaction cannot be fulfilled and we or the provider cancel it, we may - depending on the circumstances and the law - reschedule the service, provide a replacement, offer an alternative, issue a gift card or account credit, or refund you.',
      'Where the law entitles you to your money back, an alternative service, gift card or credit does not replace that entitlement unless you choose to accept it or the law allows it.',
      'Where we charge users for cancelling a confirmed transaction, we will meet the corresponding obligations that apply when the cancellation comes from us.',
    ],
  },
  {
    number: '14.10', heading: 'How a refund reaches you', id: 's14-10',
    paragraphs: [
      'An approved refund normally goes back to the payment method you used. It may go elsewhere if you agree to another method, if the service was expressly subject to a lawful gift card or credit-refund condition, if your original payment method cannot reasonably receive it, or if the law requires or permits another method.',
      'We may offer store credit, a gift card or account credit as an option, but not as a substitute for money where the law requires money.',
    ],
  },
  {
    number: '14.11', heading: 'How long a refund takes to appear', id: 's14-11',
    paragraphs: [
      'Once we have processed an approved refund, how long it takes to show up in your bank, card, wallet or other account is down to your bank, card issuer or payment provider.',
      'Depending on the provider, that can take up to 30 days or one billing cycle after we process it, unless the law or the provider requires it to be faster.',
      'That external delay does not change the date we initiated the refund.',
    ],
  },
  {
    number: '14.12', heading: 'Chargebacks and payment disputes', id: 's14-12',
    paragraphs: [
      'If you start a chargeback, payment dispute or reversal while we are already processing a refund, service change or other resolution, we may pause our processing until the payment dispute is settled, so that you are not refunded twice for the same thing.',
      'Please do not knowingly claim both a refund and a successful chargeback for the same amount.',
    ],
  },
  {
    number: '15', heading: 'Shipping, delivery and fulfilment', id: 's15',
    inShort: 'Delivery options, charges and timelines vary. Dates are estimates unless we guarantee them. Give us a complete, accurate address.',
    paragraphs: [
      'For physical products, delivery availability, charges and estimated timelines vary with the product, the Seller, any manufacturing or customisation needed, the destination, stock, and the logistics provider.',
      'We display or send you the delivery information for your transaction.',
      'Delivery dates are estimates unless we expressly say they are guaranteed.',
      'You are responsible for giving us a complete, accurate delivery address and the information needed to complete delivery.',
      'Where we ship internationally, customs duties, import duties, taxes and other destination charges may apply, as disclosed for the transaction or as the law provides.',
      'If an order is lost, materially delayed, damaged in transit or otherwise not fulfilled as agreed, we deal with it under the applicable policy for that service and under the law.',
    ],
  },
  {
    /*
     * ADDED for the customer-experience upgrade (/shipments, formerly /zip). WHY A SUB-CLAUSE OF 15, not a new numbered
     * section: numbers here are load-bearing (see types.ts) and "How to contact us" is the last
     * top-level section by owner instruction, so a new top-level section would either renumber
     * citations or push contact out of last place. Delivery and fulfilment live under 15, so the
     * tracking / rescheduling / failed-delivery detail belongs beneath it. Appointment-style pickups
     * cross-reference 16 rather than restate it.
     *
     * RENAMED, NOT REWRITTEN (2026-10-02). The page was called "Zip" and the owner retired the
     * name, so the route is /shipments/ and this clause now names the "Shipments page". The
     * SUBSTANCE is deliberately unchanged - no obligation added, removed, softened or strengthened,
     * and the clause number (15.1) and id (s15-1) are untouched so existing citations still hold.
     *
     * HONESTY CONSTRAINT: the Shipments page aggregates only capabilities that actually exist today -
     * tracking an order or request, amending a request, sending documents, the vault and leaving a
     * review - all of which are links to existing routes. General courier PICKUP and shipment
     * booking have NO integrated provider yet; the Shipments controls for them are inert "coming soon".
     * So this clause must NOT promise a general pickup or shipment-booking service. It frames those
     * as not currently offered and conditional on a future provider, and covers tracking, timing,
     * rescheduling, missed pickup and failed delivery only to the extent they apply to what exists.
     */
    number: '15.1', heading: 'Tracking, rescheduling and the Shipments page', id: 's15-1',
    paragraphs: [
      'Where a service supports it, you can track the status of an order, a request or a booking, ask us to amend an open request, send us documents, use your vault, and leave a review. These are the capabilities we actually offer, and we surface them together on the Shipments page at /shipments/.',
      'Any delivery date, dispatch window or turnaround time we show is an estimate unless we expressly say it is guaranteed, and it can be affected by stock, customisation, the destination, a third-party carrier, or circumstances beyond our reasonable control. Section 36 applies to events outside anyone\'s control.',
      'Where a delivery, dispatch or appointment can be rescheduled or cancelled, the conditions for doing so - including any cut-off, any missed-slot consequence and any charge - are the ones disclosed for that service and in section 16 for scheduled services. Please give us a complete and accurate address, contact number and any access or delivery instructions; a failed or missed delivery caused by details that are wrong, incomplete or out of date may lead to a re-delivery attempt, a charge, or a return, as disclosed for that service.',
      'If a delivery fails, is missed, is materially delayed, or arrives lost or damaged, tell us and we will handle it under the policy for that service and under the law. Where an independent carrier or fulfilment partner is involved, their handling conditions may also apply, but that does not reduce any right the law gives you against us.',
      'We do not currently offer a general courier-pickup or shipment-booking service. Where the Shipments page shows a pickup, visit or shipment option marked as not yet available, that option is not live and cannot be booked. If and when we integrate a provider for it, it will be offered on its own disclosed conditions, and until then nothing on that page is a promise that we will collect from, visit or ship for you.',
      'Nothing in this section limits a cancellation, refund, replacement or other remedy the law requires us to provide.',
    ],
  },
  {
    number: '16', heading: 'Appointments, consultations and scheduled services', id: 's16',
    inShort: 'Turn up at the agreed time and bring what is needed. If a provider cancels, you get a reschedule, an alternative, or a refund. A named professional is not swapped without telling you.',
    paragraphs: [
      'Some Services involve appointments, consultations, sessions, events or other scheduled engagements.',
      'Availability can change until your booking is confirmed.',
      'You are responsible for attending at the agreed time, giving us the information needed to provide the service, and meeting the booking requirements we disclose.',
      'Late arrival, missed appointments, rescheduling and cancellation may be subject to Service-Specific Terms.',
      'If a provider cancels a scheduled service, we may offer you a reschedule, an alternative arrangement, or a refund where one applies.',
      'Where the identity of a particular professional matters to your booking, we will not treat a different professional as an equivalent substitute without telling you or agreeing it with you.',
    ],
  },
  {
    number: '17', heading: 'Professional and regulated services', id: 's17',
    inShort: 'Independent professionals reachable through us remain responsible for their own professional judgment and licences. General information on the Platform is not personal professional advice, and we are not an emergency service.',
    paragraphs: [
      'Some Services give you access to independent professionals, experts, consultants, practitioners, institutions and other specialists.',
      'Unless we expressly say otherwise for a particular service, making an independent provider reachable through the Platform does not mean we perform that provider\'s regulated professional duties.',
      'The provider remains responsible for their own professional judgment, advice, qualifications, registrations, licences and professional obligations.',
      'General information on the Platform is general information. Do not treat it as individual legal, medical, financial, psychological, mental-health or other regulated professional advice about your situation.',
      'Nothing guarantees a particular professional, commercial, legal, medical or personal outcome simply because a service or professional is reachable through WECARE.DIGITAL.',
      'Where a service requires additional professional disclosures, engagement conditions or Service-Specific Terms, those apply as well.',
      'WECARE.DIGITAL is not an emergency service. If you need urgent medical, safety or other emergency help, contact the appropriate emergency service directly.',
    ],
  },
  {
    number: '18', heading: 'Travel, experiences and services others fulfil', id: 's18',
    inShort: 'The provider sets the rules for travel and experiences. We cannot guarantee visas, admission, schedules or the weather. Read the provider\'s conditions before booking.',
    paragraphs: [
      'Some Services involve travel, accommodation, transport, experiences, attractions or other activities fulfilled partly or entirely by Third-Party Providers.',
      'The provider may set availability, cancellation requirements, identification requirements, timing, eligibility, entry conditions and other restrictions.',
      'Please review the service-specific information before you book.',
      'We cannot guarantee government approvals, visas, admission, transport schedules, weather, or anything else controlled by an independent third party or a public authority.',
      'This section does not limit the rights the law gives you.',
    ],
  },
  {
    number: '19', heading: 'Documentation, processing and assistance', id: 's19',
    inShort: 'We help you prepare and submit things. Help is not a guarantee of approval by anyone else, and we will not submit information we know to be false.',
    paragraphs: [
      'Some Services help you with documentation, applications, submissions, administrative processes, research or coordination.',
      'Unless we expressly say otherwise, these services are assistance. They do not guarantee approval, issuance, acceptance, adjudication, or any decision by a government body, regulator or other third party.',
      'You are responsible for giving us accurate, complete and genuine information and documents.',
      'Do not ask us or a provider to submit information you know to be false, fraudulent, misleading or fabricated.',
    ],
  },
  {
    number: '20', heading: 'Digital products and digital services', id: 's20',
    inShort: 'Buying access is not buying the underlying rights. Do not redistribute or resell digital material. Refund rules change once you download or start using it.',
    paragraphs: [
      'Some Services include downloadable or online content, virtual services, digital materials, software-enabled features and online programmes.',
      'Buying access does not transfer ownership of the underlying intellectual property unless we expressly say it does.',
      'Do not reproduce, redistribute, resell, commercially exploit or publicly distribute digital materials unless we expressly authorise it.',
      'Cancellation and refund eligibility may change once digital access, download, activation or performance begins. That is subject to the law and to any Service-Specific Terms we disclosed before you bought.',
    ],
  },
  {
    number: '21', heading: 'Gift cards, credits and promotional balances', id: 's21',
    inShort: 'They can be bought, given as a promotion, or issued after a cancellation. Separate gift card terms govern the detail. They are not normally cash.',
    paragraphs: [
      'We may offer or issue gift cards, vouchers, account credits, promotional balances and refund credits.',
      'One may be bought by you, issued as part of a promotion, issued after an eligible cancellation, issued as an agreed alternative to a money refund, issued after a service change or adjustment, or provided through one of our programmes.',
      'Separate gift card or credit terms may govern purchase, activation, which services they work on, redemption, restrictions, transferability, refunds and cancellation.',
      'Gift cards, credits and promotional balances are not normally redeemable for cash, unless we say so or the law requires it.',
      'Issuing a gift card or credit instead of a money refund does not remove a mandatory consumer right that cannot lawfully be waived.',
    ],
  },
  {
    /*
     * ADDED for the customer-experience upgrade (Perks / gift cards). A SUB-CLAUSE OF 21, which
     * already covers gift cards, credits and promotional balances - the detail on purchase,
     * redemption and balances belongs beneath it rather than as a renumbering new section.
     *
     * HONESTY / CONFIG CONSTRAINT: gift cards are built but gated off and not on sale online yet,
     * and the live gift-card configuration (issuer, validity, any expiry, product restrictions) is
     * held in our commerce backend and cannot be asserted as fixed values from here. So specifics
     * are framed as "where applicable" / "as configured" / "as disclosed when the card is issued"
     * rather than stated as guarantees. NO third-party gift-card provider is named - the clause
     * refers only to WECARE.DIGITAL gift cards and "our commerce backend", because the provider is
     * an abstract seam in the code and naming a vendor here would be both wrong-if-it-changes and
     * outside what the business has agreed.
     */
    number: '21.1', heading: 'How WECARE.DIGITAL gift cards work', id: 's21-1',
    paragraphs: [
      'A WECARE.DIGITAL gift card may be bought by you, given to you by someone else, or issued by us as part of a promotion or as an agreed alternative to a money refund. When a gift card is bought or issued, it is activated and a balance is loaded onto it in Indian rupees, as disclosed at the time.',
      'You redeem a gift card at checkout against eligible WECARE.DIGITAL products and services. Redemption is applied by us server-side against the authoritative order total; the card pays part or all of what is owed, and any remaining amount is payable by your other chosen payment method. We do not treat a balance shown in your browser as the authority on what a card is worth - the balance we verify in our commerce backend is.',
      'Partial redemption is supported where the card balance is less than the amount owed: the card covers what it can and the rest is payable separately. Where a redemption is less than the full balance, the remaining balance stays on the card for a later eligible purchase, subject to any validity condition below.',
      'A gift card may carry validity, expiry, minimum-order, eligible-product or other restrictions where applicable. Any such condition is the one disclosed when the card is bought or issued and as configured in our commerce backend; where an expiry or restriction would reduce a right the law does not allow us to reduce, the law prevails and that condition does not apply to that extent.',
      'Keep a gift-card code secure and treat it like cash: anyone with the code may be able to redeem it. Tell us promptly if you believe a code has been lost, stolen, exposed or used without your authorisation, and we will take reasonable steps - which may include suspending the code while we investigate - but we cannot always recover a balance already spent by someone who had the code. We may void, suspend or reverse a gift card obtained or used through fraud, error, duplicate issuance, automated abuse or another material breach of these Terms.',
      'A promotional balance we give away may carry different conditions from a balance you paid for - for example a shorter validity, a narrower set of eligible products, or no cash-out - and those conditions are disclosed when it is issued. A purchased balance is treated as your money to the extent the law requires.',
      'Gift cards and balances are not normally redeemable for cash, and buying one is a purchase of a gift card rather than a deposit or a banking service. If an order paid for with a gift card is cancelled or refunded, the refund may be returned to the gift card or as account credit rather than as cash, where that is lawful and was disclosed; this does not remove a money refund the law requires. Gift cards are not on sale online at the time of writing, and this clause describes how they work when they are offered.',
    ],
  },
  {
    number: '22', heading: 'Partner, referral and affiliate programmes', id: 's22',
    inShort: 'Joining one means accepting its own terms. Taking part does not make you our employee, partner, franchisee or agent.',
    paragraphs: [
      'We may run partner, referral, affiliate and commission-based programmes, including Partner Up.',
      'Taking part may require you to accept separate programme terms.',
      'Those terms may cover eligibility, activation, which transactions qualify, how referrals are attributed, commissions, reversals, cancellations, payout thresholds and schedules, taxes, use of WECARE.DIGITAL branding, what you may say in advertising, prohibited referral practices, fraud prevention, confidentiality, suspension and termination.',
      'Taking part in a programme does not by itself make you our employee, partner, franchisee or agent.',
    ],
  },
  {
    number: '23', heading: 'Promotions, coupons and offers', id: 's23',
    inShort: 'Offers come with conditions and expiry dates, are not cash, and can be cancelled if they were obtained by abuse.',
    paragraphs: [
      'We may offer discounts, coupons, promotional codes, referral benefits, credits and limited-time offers.',
      'A promotion may have eligibility requirements, a validity period, a minimum transaction amount, usage limits, product restrictions and other terms.',
      'Promotional benefits cannot be exchanged for cash unless we say so or the law requires it.',
      'We may cancel a promotional benefit obtained through fraud, manipulation, automated abuse, duplicate accounts, or another material breach of the promotion\'s conditions.',
    ],
  },
  {
    /*
     * ADDED for the customer-experience upgrade (Perks / coupons). A SUB-CLAUSE OF 23, which
     * already covers promotions, coupons and offers; this adds the eligibility / validity /
     * stacking / refund-impact detail the new coupon field at checkout needs.
     *
     * CONFIG CONSTRAINT: coupons and offers are Wix-native and validated server-side, and the live
     * configuration (which codes exist, their validity, minimum order, eligible products, usage
     * limits, stacking rules) lives in our commerce backend and cannot be asserted as fixed values
     * from here. The /perks page is now a plain landing page and no longer lists offers; any
     * eligible coupon is applied server-side at checkout. So this clause is written in terms
     * of "as configured in our commerce backend" / "where applicable" rather than listing specific
     * values, and does not claim any particular offer is currently available.
     */
    number: '23.1', heading: 'How coupons and offers apply at checkout', id: 's23-1',
    paragraphs: [
      'Where a coupon or offer is available, whether it applies to your order is decided by us server-side against the conditions configured for it in our commerce backend, not by anything calculated in your browser. A code that looks accepted on screen is only a request until we validate and apply it, and the discount you actually receive is the one our systems confirm.',
      'A coupon or offer may be subject to eligibility conditions, a validity period and expiry, a minimum order value, a limited set of eligible products or services, per-customer or overall usage limits, and rules on whether it can be combined with other offers. Unless the offer expressly says codes can be stacked, assume only one applies to an order; where codes conflict, we apply them as configured for those offers.',
      'We may decline, withdraw or reverse a coupon or offer that has expired, that does not meet its conditions, or that was obtained or used through fraud, manipulation, automated abuse, duplicate accounts or another material breach of its terms. A coupon or offer has no cash value and cannot be exchanged for cash unless we say so or the law requires it.',
      'If an order that used a coupon or offer is later cancelled, returned or partially refunded, the refund reflects what you actually paid after the discount rather than the pre-discount price, and a discount tied to a condition you no longer meet after a change may be adjusted accordingly - subject always to any refund or remedy the law requires.',
    ],
  },
  {
    /*
     * ADDED for the customer-experience upgrade (Perks / rewards). HONESTY CONSTRAINT, and the
     * reason this clause is short: there is NO rewards backend. There is no rewards programme and
     * no /perks rewards section any more, and nothing offers points, balances, history, earning or
     * redemption. So this clause must NOT invent eligibility, earning, redemption or expiry mechanics for a
     * programme that does not exist. It states the truthful position - no rewards programme is
     * currently operating - and defers any future programme to its own published terms, which is
     * exactly as much as can be said truthfully today.
     */
    number: '23.2', heading: 'Rewards', id: 's23-2',
    paragraphs: [
      'We do not currently operate a rewards or loyalty programme. There are no reward points, balances, tiers or history to earn, hold or redeem, and anything shown as "coming soon" is a statement of intent, not a programme you are enrolled in or entitled to.',
      'If we launch a rewards programme in future, it will have its own published terms covering eligibility, how any benefit is earned and redeemed, any validity or expiry, misuse and fraud, and how we may change or end it. Those terms will govern that programme, and nothing here creates a reward entitlement before then.',
    ],
  },
  {
    number: '24', heading: 'Reviews, ratings and what you post', id: 's24',
    inShort: 'You keep ownership of what you post. You give us a licence to host and display it. Reviews must be genuine, and we need separate permission to use your content in advertising.',
    paragraphs: [
      'You keep ownership of User Content that is yours.',
      'By submitting User Content, you give WECARE.DIGITAL BHARATWORKS a non-exclusive, worldwide, royalty-free licence to host, store, reproduce, format, display and communicate it - as far as is reasonably necessary to provide the service, run the Platform, display content you intentionally submitted for publication, process your transactions or requests, keep the Platform secure, investigate disputes or complaints, and comply with the law.',
      'That licence does not transfer ownership of your content to us.',
      'If we want to use identifiable User Content in advertising or promotion, beyond the context you submitted it in, we will get the additional permission required.',
      'The licence normally ends when the content is permanently deleted - except where we still need it for backups, record-keeping, legal obligations, dispute resolution, fraud prevention, or another lawful purpose.',
      'You confirm you have the rights you need in order to submit your User Content.',
      'Reviews and ratings must reflect real experiences. Do not submit fake, manipulated or undisclosed paid reviews, unlawful material, defamatory content, infringing content, or anything under a deliberately false identity.',
      'We may moderate, restrict or remove User Content where that is reasonably necessary to comply with the law or enforce these Terms.',
    ],
  },
  {
    number: '25', heading: 'Intellectual property', id: 's25',
    inShort: 'The Platform and its content belong to us or our licensors. Using the site gives you a limited right to use it, not ownership of anything.',
    paragraphs: [
      'The Platform and its software, workflows, design, text, graphics, logos, interfaces, photographs, videos and databases belong to WECARE.DIGITAL BHARATWORKS or the relevant rights holder, or are licensed to us, and are protected by intellectual-property law.',
      'The WECARE.DIGITAL name, brand identity, logos and marks may not be copied, imitated or used without our authorisation.',
      'Using the Platform gives you a limited, non-exclusive, non-transferable, revocable right to use it for its intended purpose.',
      'Buying or accessing a service does not transfer any intellectual property to you.',
      'If you believe something on the Platform infringes your intellectual-property rights, email one@wecare.digital with enough detail for us to identify and review the complaint.',
    ],
  },
  {
    number: '26', heading: 'Acceptable use', id: 's26',
    inShort: 'Use the Platform lawfully. No fraud, impersonation, harassment, malware, scraping personal data, review manipulation or breaking our security.',
    paragraphs: [
      'Use WECARE.DIGITAL only for lawful purposes.',
      'Do not commit or help anyone commit fraud; impersonate another person; misrepresent who you are affiliated with; threaten, harass or abuse anyone; infringe intellectual-property or privacy rights; introduce malware or harmful code; interfere with the Platform\'s security; try to access systems or accounts you are not authorised to; get around technical restrictions; harvest personal information without authorisation; send unlawful spam; manipulate reviews or ratings; abuse promotions; materially disrupt how the Platform works; use automated tools abusively; list or request unlawful goods or services; or otherwise use the Platform in breach of the law.',
      'We may investigate suspected breaches and take proportionate action where necessary.',
    ],
  },
  {
    number: '27', heading: 'Other websites, tools and integrations', id: 's27',
    inShort: 'We rely on third-party services we do not control, and their terms apply to them. We cannot promise they will always be up.',
    paragraphs: [
      'The Services link to, or rely on, independent third-party websites, payment processors, logistics providers, authentication systems, maps, communication platforms, cloud infrastructure and software.',
      'Those services have their own terms and privacy policies.',
      'We do not control independent third-party systems and cannot guarantee they will be continuously available.',
      'This section does not exclude liability the law requires us to carry.',
    ],
  },
  {
    number: '28', heading: 'Privacy and personal data', id: 's28',
    inShort: 'Our Privacy Policy covers personal data and is a separate document worth reading. Using the Platform is not blanket consent to every possible use of your data.',
    paragraphs: [
      'We handle personal data in line with our Privacy Policy at /privacy/ and with data-protection law.',
      'The Privacy Policy is a separate document and should be read together with these Terms.',
      'Using the Platform is not unrestricted or blanket consent to every possible use of your personal data.',
      'Where the law requires your consent, or another specific authorisation, for a particular use of your data, we obtain it.',
      'Depending on the service, we may process personal data to create and administer your account, fulfil orders, manage bookings, process payments, communicate with you, provide support, verify identity, prevent fraud, keep the Platform secure, resolve grievances, comply with the law, and provide what you asked for.',
    ],
  },
  {
    number: '29', heading: 'Messages we send you', id: 's29',
    inShort: 'Messages about your account, order, payment or security come electronically and are part of the service. Marketing is handled separately and you can opt out of it.',
    paragraphs: [
      'By using the Services you accept that we may send you transactional and operational messages electronically, where the law permits.',
      'These include account notices, order and payment confirmations, booking confirmations, appointment reminders, delivery updates, security alerts, grievance correspondence and policy notices.',
      'We may send them by email, SMS, phone, messaging service, or as notifications on the Platform, using the contact details you gave us.',
      'Marketing is handled separately, and carries the consent or opt-out mechanism the law requires.',
    ],
  },
  {
    number: '30', heading: 'Availability and changes to the Services', id: 's30',
    inShort: 'We update and occasionally withdraw features, and outages happen. If we discontinue something you paid for before supplying it, you get whatever remedy applies.',
    paragraphs: [
      'We maintain, update, improve, modify, replace, suspend and sometimes discontinue functionality.',
      'Temporary interruptions can happen because of maintenance, technical failures, network problems, third-party infrastructure, cybersecurity incidents, regulatory requirements, logistics failures, or circumstances beyond our reasonable control.',
      'If we materially discontinue a paid service before it has been supplied, we provide whatever remedy the law or the Service-Specific Terms require.',
    ],
  },
  {
    number: '31', heading: 'What we do not promise', id: 's31',
    inShort: 'We do not promise the Platform is flawless or always up, or that you will get a particular outcome. Statutory warranties and consumer rights still stand.',
    paragraphs: [
      'To the maximum extent permitted by applicable law, the Platform and the Services are provided on an "as is" and "as available" basis, and we do not give any warranty, condition or representation that is not expressly set out in these Terms or required by law.',
      'We do not promise that every feature will be uninterrupted, always available, timely, secure, completely free of errors or defects, or suited to your particular purpose, or that any defect will be corrected.',
      'We do not promise a particular business, professional, legal, medical, personal, travel or financial outcome because a product, service or provider is reachable through WECARE.DIGITAL.',
      'This section does not exclude or limit any warranty, condition, obligation, consumer right or remedy that cannot lawfully be excluded or limited, including the statutory guarantees under India\'s consumer protection law. Where such a right applies, it continues in full and this section is read subject to it.',
    ],
  },
  {
    /*
     * ADDED 2026-09-30 on owner instruction ("terms page: add blog risk disclaimer").
     *
     * WHY IT IS 31.1 AND NOT A NEW NUMBERED SECTION. Numbers here are load-bearing - see the
     * note in types.ts - and the contact clause was deliberately moved to the end of the
     * document, so appending a 48 after "How to contact us" would both read oddly and push the
     * contact section out of last place. A sub-clause of 31 is additive, breaks no citation,
     * and lands where a reader already looks for what we do not promise.
     *
     * NO inShort: types.ts restricts summaries to top-level sections, because a sub-clause is
     * short enough that a summary of it would just be a worse copy.
     *
     * The blog was the largest piece of published text on the site with no clause covering it
     * at all: 1279 posts, and "blog" and "article" appeared ZERO times in this document.
     * It CROSS-REFERENCES rather than restates - 17 for professional services, 27 for outbound
     * links, 46 for AI-assisted preparation - because this document's own rewrite note records
     * that the same saver repeated fourteen times is what made the original unreadable.
     */
    number: '31.1', heading: 'Published articles and other editorial content', id: 's31-1',
    paragraphs: [
      'We publish articles, guides and explainers on WECARE.DIGITAL. All of it is general information about a subject, written for a general reader. None of it is advice about your situation.',
      'Nothing we publish is legal, medical, financial, tax, immigration, regulatory, investment or other professional advice, and reading it does not create a professional or advisory relationship between us. Where a Service involves a qualified professional, that professional is the source of advice for you - see section 17.',
      'An article is correct as far as we know on the day it is published, and it is not maintained after that. Rules, fees, eligibility criteria, timelines, government procedures, prices and third-party policies change, sometimes without notice. An older article may describe a position that no longer holds.',
      'Please do not act on anything we publish without checking it against the current official source, or asking us in writing about your own case. If an article disagrees with a Service-Specific Term, an official rule or something we have told you directly, the article is the one that is wrong.',
      'Some published material is prepared with the help of automated systems. Section 46 applies to it.',
      'Articles may mention or link to other websites, organisations and tools. Section 27 applies: a mention is not an endorsement, and we do not control what is on the other side of a link.',
      'Nothing in this section excludes a statutory warranty, obligation, consumer right or remedy that cannot lawfully be excluded.',
    ],
  },
  {
    /*
     * ADDED for the customer-experience upgrade (blog "Contribute" section). A SUB-CLAUSE OF 31,
     * beside 31.1 on editorial content, because a voluntary contribution attaches to the published
     * articles rather than to a purchase - there is no cart, no Wix order and no product. It
     * cross-references 12 for payments and 14 for refunds rather than restating them.
     *
     * FACTUAL BASIS (verified against amplify/.../ecommerce/blog_contribution.py and
     * src/config/contribution.ts): a BLOG_CONTRIBUTION is a voluntary payment the reader chooses,
     * in integer paise, processed through Razorpay on the same server-side verify / webhook /
     * idempotency path as the rest of checkout; it creates NO Wix order and adds no fee on top. It
     * is BUILT BUT GATED OFF (CHECKOUT_INITIATION_ENABLED default OFF) and not live. So the clause
     * describes it truthfully as voluntary and not currently charging, names Razorpay only as the
     * processor (consistent with 12), and makes none of the equity/investment/employment claims the
     * brief rules out.
     */
    number: '31.2', heading: 'Voluntary contributions to our published work', id: 's31-2',
    paragraphs: [
      'Some articles invite a voluntary contribution to support the work ("Contribute"). A contribution is a gift you choose to make. It is optional, it buys you nothing, and declining to contribute does not change your access to anything we publish or offer.',
      'A contribution is not an investment, equity, a loan, a security, a deposit, a subscription or a donation to a registered charity, and it is not necessarily tax-deductible - do not treat it as any of those. It does not make you an employee, partner, shareholder or agent of ours, and it does not give you any ownership, revenue share, control or other interest in WECARE.DIGITAL BHARATWORKS or its work.',
      'Contributing does not buy influence over what we publish. It does not entitle you to commission, edit, approve, remove or shape any article, and it creates no editorial, advisory or professional relationship. What we publish stays our own editorial decision, and section 31.1 continues to apply to that content.',
      'Where contributions are enabled, the amount is the one you choose and we confirm server-side, in Indian rupees, and it is processed by our payment provider (Razorpay) under section 12 - we do not add a fee on top of a contribution. A contribution does not create an order, a product or a shipment, and there is nothing to deliver.',
      'If a payment does not complete, is declined, or fails verification, no contribution is taken. Because a contribution is voluntary and buys nothing, it is generally not refundable once successfully processed; even so, we will review and, where appropriate, refund or reverse a contribution that was taken in error, duplicated, taken without authorisation, or taken through fraud, and we may reverse or decline a contribution we reasonably believe to be fraudulent. If you raise a chargeback or payment dispute, section 14.12 applies. Nothing in this clause removes a refund or remedy the law requires.',
    ],
  },
  {
    number: '32', heading: 'Limits on liability', id: 's32',
    inShort: 'Neither of us is liable for unforeseeable indirect losses, and our contractual liability for a paid transaction is normally capped at what you paid for it. These limits apply only as far as the law allows, and never to liability that cannot be excluded.',
    paragraphs: [
      'This section applies only to the maximum extent permitted by applicable law. We do not exclude or limit, and nothing in these Terms should be read as excluding or limiting, any liability that cannot lawfully be excluded or limited - including liability for death or personal injury caused by negligence, for fraud or fraudulent misrepresentation, for wilful misconduct or gross negligence, and any liability under India\'s consumer protection law or other mandatory law. This savings provision prevails over everything else in this section.',
      'Subject to that savings provision, and to the maximum extent permitted by applicable law, neither of us is responsible to the other for indirect, incidental, special, punitive or consequential losses, or for loss of profit, revenue, goodwill, data or anticipated savings, that were not reasonably foreseeable as a likely result of the matter complained of.',
      'Subject to that savings provision, and where our liability may lawfully be limited, our total aggregate liability arising directly from a particular paid transaction will not exceed the amount you paid us for the product or Service the claim is about.',
      'Where liability cannot lawfully be capped or excluded, the cap and exclusions above do not apply to it, and our liability for that matter is as the law provides.',
      'Nothing in this section restricts or affects your mandatory rights as a consumer.',
    ],
  },
  {
    number: '33', heading: 'When you are responsible to us', id: 's33',
    inShort: 'You cover losses that come from your unlawful use, your material breach, or unlawful content you posted. You never cover losses we caused ourselves.',
    paragraphs: [
      'As far as the law allows, you are responsible for losses, claims and reasonable costs arising directly from your unlawful use of the Services, your material breach of these Terms, your infringement of someone else\'s rights, or unlawful User Content you submitted.',
      'This does not ask a consumer to cover losses caused by our own unlawful conduct, or liability that cannot lawfully be transferred.',
    ],
  },
  {
    number: '34', heading: 'Fraud prevention and Platform security', id: 's34',
    inShort: 'We screen for fraud and account takeover, may briefly hold a transaction while we verify it, and cooperate with banks and authorities where the law allows.',
    paragraphs: [
      'We use reasonable technical, operational and manual measures to detect and prevent unauthorised transactions, account takeover, fraudulent payments, promotion abuse, identity misuse and other security risks.',
      'Where reasonably necessary, we may temporarily restrict a transaction or an account while verification is completed.',
      'We may cooperate with banks, payment providers, regulators, law enforcement and other competent authorities where the law permits or requires it.',
    ],
  },
  {
    number: '35', heading: 'Suspension and closing your account', id: 's35',
    inShort: 'You can stop using the Services whenever you like. We can restrict access for fraud, security or serious breach. Rights that arose before termination survive it.',
    paragraphs: [
      'You can stop using the Services at any time.',
      'Where account closure is available, you can request it through your account or through customer support.',
      'We may restrict, suspend or terminate access where that is reasonably necessary because of suspected fraud, a security risk, unlawful activity, a material breach of these Terms, abuse of other users or providers, repeated payment failure, misuse of the Platform, or another legitimate reason.',
      'Where it is appropriate and the law requires it, we will give you notice or a chance to put the problem right.',
      'Termination does not wipe out rights and obligations that already existed - including refund rights, payment obligations, dispute rights, confidentiality obligations, intellectual-property provisions, and anything else meant by its nature to survive.',
    ],
  },
  {
    number: '36', heading: 'Events outside anyone\'s control', id: 's36',
    inShort: 'Neither of us is liable for delays caused by things like disasters, war, government action or large-scale outages. Refund rights the law protects still stand.',
    paragraphs: [
      'Neither of us is responsible for a failure or delay caused by circumstances beyond our reasonable control, to the extent those circumstances actually prevent performance.',
      'That can include natural disasters, severe weather, epidemics and public-health restrictions, war, civil disturbance, government action, widespread utility or telecommunications failures, labour disruption, transport interruption, and large-scale cyber incidents.',
      'This section does not remove a cancellation, refund or other right the law requires to stay available.',
    ],
  },
  {
    number: '37', heading: 'Customer care and complaints', id: 's37',
    inShort: 'Email one@wecare.digital or call +91 9330994400. Formal complaints get a reference number. You can always go to a consumer commission or regulator instead.',
    paragraphs: [
      'Contact us about products, orders, bookings, payments, refunds, Sellers, Service Providers, your account, the Platform, privacy, or any other complaint.',
      'WECARE.DIGITAL Customer Grievance Desk, WECARE.DIGITAL BHARATWORKS. Email one@wecare.digital or call +91 9330994400. Our address is The W.B.S.I.D.C. Building, Unit 1/20 81/2/7, Phears Lane, Kolkata, West Bengal 700012, India.',
      'We record formal complaints submitted through that channel and, where it applies, give you a ticket or reference number so you can track it.',
      'Where the law sets a particular grievance process, acknowledgement period, resolution period or escalation route, we follow it.',
      'Using our complaints process does not stop you exercising any right you have before a Consumer Commission, regulator, statutory authority, court or other lawful forum.',
    ],
  },
  {
    number: '38', heading: 'Changes to these Terms', id: 's38',
    inShort: 'We update these Terms when the Services or the law change, and give notice where a change materially affects you. Changes normally apply going forward, not backwards.',
    paragraphs: [
      'We update these Terms where that is reasonably necessary to reflect changes in our Services, operations, technology, Platform functionality, security practices, or the law.',
      'Where the law requires it, or where a change materially affects your rights, we give you appropriate notice.',
      'Changes normally operate going forward.',
      'Continuing to use an affected service after revised Terms take effect counts as acceptance only as far as the law allows.',
      'Where the law requires fresh, affirmative acceptance, we ask for it.',
      'A new or materially different service may also carry its own Service-Specific Terms.',
    ],
  },
  {
    number: '39', heading: 'Governing law and disputes', id: 's39',
    inShort: 'Indian law applies. Please talk to us first. Nothing stops you going to a consumer commission or regulator; other disputes go to the courts in Kolkata.',
    paragraphs: [
      'These Terms are governed by the laws of India.',
      'Please contact our customer care team or the Customer Grievance Desk first, so we have a chance to look at the problem and, if we can, fix it.',
      'Nothing in these Terms stops a consumer approaching a Consumer Commission, regulator, statutory authority, court or other forum available under the law.',
      'For disputes that are not covered by a mandatory statutory or consumer forum, the courts of competent jurisdiction in Kolkata, West Bengal have jurisdiction, subject to the law.',
    ],
  },
  {
    number: '40', heading: 'If part of this is unenforceable', id: 's40',
    inShort: 'An invalid clause is narrowed or dropped. The rest still applies.',
    paragraphs: [
      'If a provision of these Terms is held invalid, unlawful or unenforceable, it is read down or limited to the minimum extent necessary.',
      'The rest of these Terms continue to apply.',
    ],
  },
  {
    number: '41', heading: 'Not enforcing something is not giving it up', id: 's41',
    inShort: 'If we do not enforce a term straight away, we have not waived it.',
    paragraphs: [
      'If we fail or delay in enforcing a provision or exercising a right, that is not a waiver of it.',
      'Where we do waive something, the waiver applies only to the circumstances we gave it for.',
    ],
  },
  {
    number: '42', heading: 'Transferring this agreement', id: 's42',
    inShort: 'You need our consent to transfer your account or rights. We may transfer ours in a genuine restructuring, without reducing your mandatory rights.',
    paragraphs: [
      'Do not transfer your account or your rights under these Terms in a way that materially affects the Services without our prior consent.',
      'WECARE.DIGITAL BHARATWORKS may transfer its rights or obligations as part of a genuine business restructuring, merger, acquisition, sale or reorganisation, subject to the law and without reducing your mandatory user or consumer rights.',
    ],
  },
  {
    number: '43', heading: 'The relationship between us', id: 's43',
    inShort: 'Using the Services does not make you our employee, partner or joint venturer, and a third-party provider does not become our employee by being listed.',
    paragraphs: [
      'Nothing in these Terms creates an employment relationship, partnership, franchise, fiduciary relationship or joint venture between you and WECARE.DIGITAL BHARATWORKS.',
      'A Third-Party Provider does not become our employee because its products or services are reachable through the Platform.',
      'Separate contracts may govern our relationships with individual Sellers, Service Providers, partners and affiliates.',
    ],
  },
  {
    number: '44', heading: 'The whole agreement', id: 's44',
    inShort: 'These Terms plus the Privacy Policy, the service-specific terms and your order details make up the agreement. A separately signed agreement outranks them on what it covers.',
    paragraphs: [
      'Your agreement with us is made up of these Terms, the Privacy Policy at /privacy/, any Service-Specific Terms, your order or booking information, the applicable cancellation, refund and delivery conditions, and any other policy expressly built into a particular transaction.',
      'Where a separately signed agreement, memorandum of understanding, engagement agreement, enterprise agreement or order form covers the same subject matter, that agreement prevails on the matters it specifically addresses.',
    ],
  },
  /**
   * "HOW TO CONTACT US" IS LAST, on owner instruction, and the two clauses that used to sit
   * behind it were renumbered to make room. It is now 47, at the foot of this file.
   *
   * This file previously appended Machine translation and AI as 46 and 47 AFTER the contact
   * clause, specifically to avoid renumbering anything. That left the document ending on a
   * disclaimer, and it contradicted src/content/legal/privacy.ts, which ends on 24 "Who we
   * are and how to reach us". Contact-last is now the convention in both documents.
   *
   * WHAT THE RENUMBER MOVED: Machine translation 46 -> 45, AI 47 -> 46, How to contact us
   * 45 -> 47. Every section's `id` is its in-page anchor and tracks its number, so
   * /terms/#s45 now resolves to Machine translation, #s46 to AI, and #s47 to contact.
   * Nothing in this repo links to any of the three: the only in-code citations of these
   * Terms are src/pages/orders.tsx to section 14 and src/pages/bharat-rx.tsx to section
   * 17, both untouched. 46 and 47 have never been published under any other number, so the
   * only real exposure is an external document citing "Terms section 45" for contact
   * details - which is the one thing this repo cannot check.
   *
   * NO WORDING CHANGED. Only the order and those three numbers.
   *
   * NOT LEGAL ADVICE AND NOT COUNSEL-REVIEWED, for 45 and 46 below. These are drafted to
   * the pattern used by public bodies and software vendors for the same two risks - see the
   * note in each `inShort` - and they should be read by whoever signs off this document
   * before being relied on. The engineering facts they describe are measured and accurate;
   * the legal effect of the wording is not something this repo can assert.
   */
  {
    number: '45', heading: 'Machine translation', id: 's45',
    inShort: 'The English version is the official one. Translations are automatic, offered as a convenience, and may be wrong or incomplete.',
    paragraphs: [
      'The Platform offers on-page translation into other languages. Those translations are produced automatically by machine translation, without human review.',
      'The English version of any page, these Terms, our Privacy Policy and every Service-Specific Term is the official text. Where a translated version differs from the English one - by error, omission, ambiguity or change of meaning - the English version prevails and is the version that governs.',
      'Translations are provided as a convenience and on an "as is" basis. We give no warranty, express or implied, as to their accuracy, reliability or completeness, and a discrepancy introduced by translation creates no obligation on us and has no legal effect.',
      'Parts of a page may not translate at all. Text that sits inside images, inside interface labels read by assistive technology, or inside decorative and duplicated elements may remain in English even when the rest of the page has changed language. A partly translated page is not a representation that the untranslated parts do not apply to you.',
      'Prices, fees, timelines, eligibility conditions, cancellation rules and any other commercial term should be confirmed against the English text before you rely on them. If a translated term matters to your decision, ask us in writing at one@wecare.digital and we will confirm it in English.',
      'Nothing in this section limits any right you have under applicable law to receive information in a language you understand, or any obligation we have to provide it.',
    ],
  },
  {
    number: '46', heading: 'Artificial intelligence and automated processing', id: 's46',
    inShort: 'Some parts of the Services use AI. Its output can be wrong, it is not professional advice, and a human decides anything that matters.',
    paragraphs: [
      'Some features of the Services use artificial intelligence, machine learning, large language models or other automated processing. That can include drafting and summarising messages, suggesting replies, classifying or routing a request, extracting information from a document you send us, generating descriptions or images, transcribing or translating speech and text, and prioritising work in a queue.',
      'AI output is generated by statistical prediction. It can be inaccurate, incomplete, out of date, internally inconsistent or entirely fabricated while appearing confident and well-formed. It may also reflect biases present in the data it was trained on. We do not warrant that any AI-generated output is accurate, complete, current or fit for a particular purpose.',
      'AI-generated output is not professional advice. It is not medical, legal, financial, tax, immigration, regulatory or other professional advice, and it does not create a professional relationship of any kind. Where a Service involves a qualified professional, that professional - not the automated system - is the source of the advice, and the Third-Party Provider terms for that Service apply.',
      'You must not rely on AI-generated output for any decision with legal, medical, financial or safety consequences without independent verification by a suitably qualified person. Verify anything material against the underlying document, the applicable rules, or us in writing.',
      'A human being remains responsible for decisions that materially affect you. We do not use solely automated processing to decide whether to accept or reject your order, booking, application or request, or to determine what you pay, without a person able to review that decision. If you believe an automated process has produced a wrong outcome, tell us at one@wecare.digital and a person will look at it.',
      'What you submit may be processed by automated systems, including systems operated by the third-party providers named in our Privacy Policy, in order to deliver the Service you asked for. How we handle that data, how long we keep it, and the choices you have are set out in the Privacy Policy, including the section on automated systems.',
      'We may add, change, limit or withdraw an AI-assisted feature at any time. Where an AI-assisted feature is offered alongside a human alternative, you may ask for the human route instead.',
      'Nothing in this section reduces any liability we cannot lawfully exclude, or any statutory right you have in relation to automated decision-making.',
    ],
  },
  {
    number: '47', heading: 'How to contact us', id: 's47',
    inShort: 'WECARE.DIGITAL BHARATWORKS, Kolkata. one@wecare.digital, +91 9330994400.',
    paragraphs: [
      'WECARE.DIGITAL is operated under the business name WECARE.DIGITAL BHARATWORKS.',
      'Our address is The W.B.S.I.D.C. Building, Unit 1/20 81/2/7, Phears Lane, Kolkata, West Bengal 700012, India.',
      'For customer care, email one@wecare.digital or call +91 9330994400.',
      'Use those details for any question, complaint or concern about these Terms or the Services. Our Privacy Policy is at /privacy/.',
    ],
  },
];
