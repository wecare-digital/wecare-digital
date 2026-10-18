/**
 * Privacy Policy — rewritten in plain English.
 *
 * THIS REPO IS THE SOURCE OF TRUTH. There is no upstream to sync with and no extractor to
 * re-run. Edit this file.
 *
 * WHAT THE REWRITE CHANGED, on owner instruction:
 *   - Active voice and short sentences. The original averaged 34 words a sentence and
 *     was almost entirely passive ("Personal Data may be processed to..."), which reads
 *     as evasive even where the underlying commitment is fine.
 *   - Removed circular hedging. "We will use an appropriate mechanism where applicable
 *     law requires an appropriate mechanism" says nothing; where a commitment is
 *     unconditional it is now stated as one.
 *   - Cut repetition. The contact block appeared three times and the
 *     verify-identity-before-acting caveat four; each now appears once.
 *   - Added `inShort` to every section. Legal prose is read by people deciding whether
 *     to trust you, and 24 sections of clauses with no summary is not readable on a
 *     phone.
 *
 * WHAT IT DID NOT CHANGE: any obligation, right, retention basis, lawful basis, or
 * limitation. Every section keeps its original NUMBER and scope, so cross-references
 * from elsewhere on the site still resolve. Nothing was added that makes a factual claim
 * about data handling that the original did not already make - in particular the
 * original's deliberate vagueness about WHICH data each service collects is preserved,
 * because that varies by service and inventing specifics would be a false statement.
 *
 * STILL NEEDS COUNSEL REVIEW for service-specific consent notices and any future designation
 * as a Significant Data Fiduciary. The DPDP Act requires publication of business contact
 * information for a Data Protection Officer where one is applicable, or otherwise a person
 * able to answer data-processing questions. This policy publishes the Privacy and Grievance
 * Desk contact; do not describe a statutory DPO as appointed unless the business has actually
 * made that appointment or is legally required to do so.
 *
 * THAT NOTE BELONGS HERE AND NOWHERE ELSE. It was briefly written into section 23 as a
 * rendered paragraph beginning "PENDING LEGAL REVIEW", which published an internal
 * engineering to-do inside the policy itself - telling every reader, and any regulator who
 * opened the page, that the document was known to be incomplete. Open questions about a
 * legal document go in this comment, which ships in the repo and not on the page.
 */

import type { LegalSection } from './types';

/**
 * Bumped from 2026-09-23 when section 23.1 was added, and again on 2026-10-01 when sections 3.2,
 * 5 and 15 were extended to cover voluntary blog contributions and gift-card/redemption data for
 * the customer-experience upgrade. Same rule, and the same caveat, as TERMS_UPDATED: this is an
 * engineering revision marker, not a line the reader sees - nothing outside src/content/legal/
 * reads it.
 */
export const PRIVACY_UPDATED = '2026-10-18';

export const PRIVACY_INTRO: string[] = [
  'This policy explains what personal data WECARE.DIGITAL collects, why we collect it, who we share it with, how long we keep it, and what you can ask us to do about it.',
  'WECARE.DIGITAL is a brand of WECARE.DIGITAL BHARATWORKS. In this policy, "we" and "us" mean that business, and "you" means anyone whose personal data we handle.',
  'Read it alongside our Terms of Service at /terms/. Some services show additional privacy information of their own; where they do, that information applies on top of this policy.',
  'Using our services is not blanket consent to every possible use of your data. Where the law requires your consent for something, we ask for it separately and specifically.',
];

export const PRIVACY_SECTIONS: LegalSection[] = [
  {
    number: '1', heading: 'What this policy covers', id: 's1',
    inShort: 'Everything we offer under the WECARE.DIGITAL name, and nothing that independent sellers do with your data for their own purposes.',
    paragraphs: [
      'This policy covers our websites and apps, your account, orders and deliveries, appointments and bookings, professional and expert services, documentation and processing work, travel and experience services, digital products, subscriptions and memberships, partner and referral programmes, gift cards and promotions, customer support and grievances, and enterprise or institutional services.',
      'Some things on our platform are provided by independent sellers, service providers or payment companies. Where they decide for themselves how to use your data, they are responsible for it and their own privacy terms apply, not ours.',
    ],
  },
  {
    number: '2', heading: 'What we mean by personal data', id: 's2',
    inShort: 'Any information that identifies you, or that can be linked back to you.',
    paragraphs: [
      'Personal data means information about a person who can be identified from it, or from it combined with something else we hold. Where the law you are covered by defines the term more broadly, that definition applies.',
      'It includes what you give us directly, what we observe as you use the platform, and what we receive from third parties who are allowed to share it.',
    ],
  },
  {
    number: '3', heading: 'What we collect', id: 's3',
    inShort: 'What we collect depends on the service. We ask for what that service needs and not more.',
    paragraphs: [
      'The categories below describe the kinds of data a service may involve. Which of them apply to you depends on which services you use.',
    ],
  },
  {
    number: '3.1', heading: 'Account and contact details', id: 's3-1',
    paragraphs: [
      'Your name, email address, phone number, username or account identifier, login credentials, contact preferences, and any profile details you choose to add or that a particular service requires.',
    ],
  },
  {
    number: '3.2', heading: 'Transactions', id: 's3-2',
    paragraphs: [
      'When you buy, book or request something we handle the order or booking details, what was requested, billing and delivery information, the amount, payment status, any refund or cancellation, invoices, gift card or account credit, and your transaction history.',
      'Payments are processed by independent banks and payment gateways. Depending on the method, we receive a transaction reference, a status, and limited payment details from the processor.',
      'Where a payment provider collects your card or bank credentials directly, those credentials are held under that provider\'s privacy and security practices, not ours.',
      'Where you make a voluntary contribution to our published work, we keep the records needed to identify, process and reconcile it: the contribution reference, the article it relates to, the amount and currency, payment references, payment status and timing, and any refund or reversal. The payment itself is processed by our payment provider as described in section 10.3. A contribution is voluntary and is not a priced supply in the way a product or booking is; this treatment matches section 31.2 of our Terms of Service, which also records that a contribution is not necessarily tax-deductible.',
      'Where you buy, hold or redeem a gift card, or use a coupon or credit, we hold the gift-card code, its balance and status, the coupon or credit applied, and the redemption records that link it to a transaction. We treat gift-card and redemption records as personal and transaction data. Where applicable, some of this is held in and governed by the commerce platform that issues and settles it.',
    ],
  },
  {
    number: '3.3', heading: 'Information you submit for a service', id: 's3-3',
    paragraphs: [
      'Depending on the service this can include documents, photographs, forms, application details, appointment information, instructions, preferences, identity or eligibility evidence, professional-service information, travel details, and anything else needed to complete your request.',
      'Some services necessarily involve sensitive information - health, financial, identity, legal or consultation details. We handle it only for the purpose it was given, under the law that applies to it and any additional privacy notice shown for that service.',
    ],
  },
  {
    number: '3.4', heading: 'Your messages to us', id: 's3-4',
    paragraphs: [
      'We process what you send by email, phone, messaging apps, platform chat, web forms, support requests and social media.',
      'Where we record a call, consultation or interaction, we give notice or obtain authorisation before doing so where the law requires it.',
    ],
  },
  {
    number: '3.5', heading: 'Device and usage data', id: 's3-5',
    paragraphs: [
      'This is collected automatically and includes your IP address, browser and device type, operating system, device or session identifiers, the pages and features you use, referring and exit pages, timestamps, diagnostic data and security logs.',
    ],
  },
  {
    number: '3.6', heading: 'Location', id: 's3-6',
    paragraphs: [
      'Some services use approximate or precise location - for delivery, local availability, navigation, or a feature that depends on where you are.',
      'Where a device permission or consent is required, we ask for it first. You can change or withdraw location permissions in your device or browser settings at any time.',
    ],
  },
  {
    number: '3.7', heading: 'Cookies and similar technologies', id: 's3-7',
    paragraphs: [
      'We use cookies, pixels, local storage and similar technologies to keep the platform working, hold your session, remember preferences, protect accounts, measure performance, understand how services are used, prevent fraud, and support analytics, communications or advertising.',
      'Where consent is legally required for a category of these technologies, we ask before setting them. Turning some of them off will stop parts of the platform working.',
    ],
  },
  {
    number: '3.8', heading: 'Data we receive from others', id: 's3-8',
    paragraphs: [
      'We may receive personal data about you from sellers and service providers, payment providers, delivery partners, login providers, an organisation arranging your access to a service, your authorised representative, referral partners, public sources, and public authorities where the law permits it.',
    ],
  },
  {
    number: '4', heading: 'How we collect it', id: 's4',
    inShort: 'Mostly from you, as you use the platform. Sometimes from partners, where that is necessary and lawful.',
    paragraphs: [
      'We collect data when you create or use an account, browse the platform, buy or book something, submit documents or forms, contact us, enter a promotion or event, deal with a seller through us, use a payment or delivery flow, leave a review, or interact with cookies.',
      'We also receive data from authorised third parties where it is genuinely needed for a service you asked for, or for security, fraud prevention or verification.',
    ],
  },
  {
    number: '5', heading: 'Why we use it', id: 's5',
    inShort: 'To run your account, deliver what you asked for, take payment, support you, keep the platform safe, meet legal duties, and improve the service.',
    paragraphs: [
      'We use personal data to set up and run accounts; provide the services you request; process orders and bookings; coordinate sellers and providers; take and verify payments; process voluntary contributions to our published work; issue, hold, redeem and reconcile gift cards, coupons and credits; deliver goods; manage appointments; handle documents and requests; personalise relevant features; message you about your transactions; provide support; run subscriptions and memberships; operate partner and referral programmes; manage promotions, credits and gift cards; verify identity, authority or eligibility; protect users and the platform; prevent fraud and abuse; detect and investigate security incidents; maintain service quality; analyse and improve what we offer; handle complaints and disputes; bring or defend legal claims; and comply with the law.',
      'If we ever want to use your data for something materially unrelated to the above, we will seek a fresh lawful basis first, including your consent where that is what the law requires.',
    ],
  },
  {
    number: '6', heading: 'Consent, and when we do not need it', id: 's6',
    inShort: 'Where we rely on consent we ask clearly and you can withdraw it. Withdrawing may mean we can no longer provide the service.',
    paragraphs: [
      'Where we rely on your consent, we ask for it with a clear affirmative action and tell you what you are agreeing to.',
      'You can withdraw consent at any time, using the mechanism shown for that service or by contacting us. Withdrawal stops future processing; it does not make lawful past processing unlawful.',
      'If we need particular data to provide something you asked for, withdrawing consent or asking us to delete that data may mean we cannot start or continue the service. We will tell you when that is the case.',
      'Some processing does not rely on consent - for example meeting a legal obligation, or preventing fraud. Where the law permits or requires us to process data on another basis, we do.',
    ],
  },
  {
    number: '7', heading: 'Children', id: 's7',
    inShort: 'Our services are built for adults. Where a child uses one and the law requires a guardian\'s consent, we obtain it. We do not target advertising at children.',
    paragraphs: [
      'Services that involve buying or entering into a contract are intended for people legally able to do so.',
      'Where a service is available to a child and the law requires parental or guardian authorisation, we take steps to obtain and verify it.',
      'We do not knowingly track, profile or target advertising at children where the law prohibits it.',
      'If you believe we hold data about a child without the required authorisation, email one@wecare.digital and we will act on it.',
    ],
  },
  {
    number: '8', heading: 'Professional and consultation information', id: 's8',
    inShort: 'What you tell a professional through us is still protected personal data. It is not shared just because it was said in a consultation.',
    paragraphs: [
      'Some services involve professionals, experts, practitioners or institutions.',
      'Information you give in connection with those services is personal data like any other. Access to it is limited to what the service requires, subject to the professional\'s own obligations and the law.',
      'We do not treat consultation information as falling outside privacy protection merely because it was given during a professional interaction.',
      'We will disclose it only where the law requires it, where it is necessary to address a serious and legally recognised safety risk, where you authorise it, where sharing is necessary to provide the service you asked for, or where another lawful basis applies.',
      'Individual professionals may owe you additional duties of confidentiality beyond this policy.',
    ],
  },
  {
    number: '9', heading: 'When an employer or institution arranges your access', id: 's9',
    inShort: 'They can see enough to confirm eligibility and pay for it. They do not get your consultation content just because they paid.',
    paragraphs: [
      'An employer, school, or other organisation may arrange or fund a service for you.',
      'In that case the organisation gives us what is needed to confirm you are eligible and to administer your access.',
      'What we report back to them depends on the arrangement, the service-specific terms and the law. Where we can report in aggregate or de-identified form, we do.',
      'Your personal consultation content is not disclosed to that organisation merely because it funded your access. We disclose it only if you authorise it, if it is necessary to provide the service and we have told you so, or if the law requires it.',
    ],
  },
  {
    number: '10', heading: 'Who we share it with', id: 's10',
    inShort: 'Only those who need it to deliver what you asked for, run the platform, or meet a legal obligation.',
    paragraphs: [
      'We share personal data only as far as necessary for a legitimate service, operational, security, transactional or legal purpose, and only as the law allows.',
    ],
  },
  {
    number: '10.1', heading: 'Sellers and service providers', id: 's10-1',
    paragraphs: [
      'When you order something supplied by an independent seller or provider, we pass on what they need to fulfil and support the transaction. They may have their own legal and professional duties over that information.',
    ],
  },
  {
    number: '10.2', heading: 'Suppliers who process data for us', id: 's10-2',
    paragraphs: [
      'We use third parties for cloud hosting, communications, authentication, support, analytics, security, payments, logistics, document processing, appointment systems and other infrastructure.',
      'They receive only what their function requires, and are bound by contract, confidentiality and security obligations.',
    ],
  },
  {
    number: '10.3', heading: 'Payment providers', id: 's10-3',
    paragraphs: [
      'What is needed to complete a payment, refund, chargeback or payment investigation passes between us and payment gateways, banks and card networks. They handle it under their own privacy terms and regulatory duties.',
    ],
  },
  {
    number: '10.4', heading: 'Delivery partners', id: 's10-4',
    paragraphs: [
      'Delivery names, addresses, phone numbers and other details needed to complete a delivery are shared with couriers, sellers, warehouses and other fulfilment partners.',
    ],
  },
  {
    number: '10.5', heading: 'Organisations that fund your access', id: 's10-5',
    paragraphs: [
      'Where an organisation arranges or pays for a service, we share what is needed to administer eligibility, billing and participation - as described for that service, and as the law allows. Section 9 sets the limits.',
    ],
  },
  {
    number: '10.6', heading: 'Legal and regulatory disclosure', id: 's10-6',
    paragraphs: [
      'We disclose data where it is necessary or legally required to comply with the law or legal process, respond to a competent authority, protect someone\'s rights or safety, investigate fraud, prevent a security incident, enforce our agreements, or bring or defend a legal claim.',
    ],
  },
  {
    number: '10.7', heading: 'If the business is restructured', id: 's10-7',
    paragraphs: [
      'If WECARE.DIGITAL is restructured, acquired, merged, financed or sold, personal data may transfer as part of that transaction, subject to the law and to appropriate safeguards.',
    ],
  },
  {
    number: '11', heading: 'What you post publicly', id: 's11',
    inShort: 'Reviews and public profile content are visible to others. Giving us data for one purpose does not let us use it in advertising.',
    paragraphs: [
      'Anything you submit for public display - reviews, ratings, public comments, profile content - can be seen by other people. Please do not publish anything you would not want public.',
      'Our rights over content you submit are set out in the Terms of Service at /terms/.',
      'Giving us personal data for one purpose does not authorise us to use it in promotion or advertising. Where the law requires separate permission for that, we obtain it.',
    ],
  },
  {
    number: '12', heading: 'Analytics, advertising and marketing', id: 's12',
    inShort: 'You can opt out of marketing. You cannot opt out of messages about your own order, payment or security - those are part of the service.',
    paragraphs: [
      'We use aggregated or de-identified information to understand how the platform performs and what people need.',
      'Marketing messages carry the consent, unsubscribe or opt-out mechanism the law requires.',
      'Messages necessary for your account, order, booking, payment, a security event, a grievance or a service you asked for continue even if you opt out of marketing. They are not marketing.',
      'Where personalised advertising uses your personal data and the law requires consent or a specific choice, we provide that choice.',
    ],
  },
  {
    number: '13', heading: 'Automated systems', id: 's13',
    inShort: 'We use software to route, secure and improve services. Where an automated decision materially affects you and the law requires review, you get it.',
    paragraphs: [
      'We use software and automated workflows to operate, secure, organise, route and improve our services, and for fraud detection, security monitoring, spam prevention and analytics.',
      'Where an automated process materially affects you and the law requires additional disclosure, consent, human review or another safeguard, we provide it.',
    ],
  },
  {
    number: '14', heading: 'Processing outside your country', id: 's14',
    inShort: 'Some of our suppliers operate abroad, so data may be processed outside the country you use us from. Transfers are subject to legal safeguards.',
    paragraphs: [
      'Some technology, cloud, communications, payment and analytics providers process data outside the country you are using our services from.',
      'Where data crosses a border we do so subject to the restrictions, requirements and safeguards that apply to that transfer.',
      'We will change, restrict or stop a transfer arrangement where the law or a government direction requires it.',
    ],
  },
  {
    number: '15', heading: 'How long we keep it', id: 's15',
    inShort: 'For as long as the purpose needs, or the law requires. Some financial and security records outlast your account.',
    paragraphs: [
      'We keep personal data for as long as the purpose it was collected for requires, or as long as a legal obligation requires. Different categories therefore have different retention periods.',
      'Data may be retained for an active transaction or ongoing service; account administration; financial, tax and accounting records; statutory record-keeping; transaction security; fraud prevention; a complaint or dispute; backups; legal claims; and enforcing our agreements.',
      'Contribution records and gift-card, coupon and redemption records are transaction records of this kind. We keep them for as long as we need them for accounting, tax, refund, fraud-prevention and legal purposes, which can be after the related activity ends. Where applicable, gift-card expiry or restrictions follow the terms recorded for that card.',
      'Some transaction, security and financial records must be kept after you close your account or ask for deletion, because the law requires it. Section 18 explains how that interacts with a deletion request.',
      'When data is no longer needed we delete, anonymise or de-identify it.',
    ],
  },
  {
    number: '16', heading: 'Security', id: 's16',
    inShort: 'We use access controls, encryption, monitoring, backups and vendor controls. No system is perfectly secure, so protect your own credentials too.',
    paragraphs: [
      'We use technical and organisational measures appropriate to the data and the risk. These include access controls, authentication, encryption or masking, monitoring and logging, backups, security testing, vendor controls, incident-response procedures and internal confidentiality rules.',
      'No electronic system can be guaranteed completely secure. Please take reasonable care of your account credentials and devices.',
    ],
  },
  {
    number: '17', heading: 'If there is a data breach', id: 's17',
    inShort: 'We contain it, investigate it, and tell you and the regulator where the law requires.',
    paragraphs: [
      'If we become aware of a personal data breach we assess it and take steps to contain, investigate and remedy it.',
      'We notify affected people and the competent authorities where, and in the manner, the law requires.',
      'A notification will describe what happened, the risks, what we have done, and what you can do to protect yourself.',
    ],
  },
  {
    number: '18', heading: 'Your rights', id: 's18',
    inShort: 'You can ask what we hold, correct it, complete it, have it deleted, withdraw consent, or complain. Email one@wecare.digital.',
    paragraphs: [
      'Subject to the law and any lawful exception, you can ask us to tell you what personal data we process about you; correct anything inaccurate; complete or update anything incomplete; delete data where the law allows; stop processing that relies on consent you have withdrawn; and consider a privacy grievance. Where the law gives you the right to nominate someone to exercise your rights, you can do that too.',
      'Send requests to one@wecare.digital. We may ask you for enough information to confirm who you are, or that you are authorised to act for someone else, before we act.',
      'A deletion request does not cover data we are legally required to keep, or that remains genuinely necessary for another lawful purpose. Where we cannot delete something, we tell you why.',
    ],
  },
  {
    number: '19', heading: 'Closing your account', id: 's19',
    inShort: 'You can close it. Some records are kept afterwards where the law requires.',
    paragraphs: [
      'Where account closure is available you can request it through the platform or through customer support.',
      'Closing an account does not delete every record immediately. Data may be kept for completed transactions, legal obligations, fraud prevention, security, an unresolved dispute, or backups. Section 15 explains the periods.',
    ],
  },
  {
    number: '20', heading: 'Your contact preferences', id: 's20',
    inShort: 'Manage them in the platform, by unsubscribe link, in device settings, or by asking us.',
    paragraphs: [
      'You can manage communication preferences through the platform, an unsubscribe link, your device settings, or by contacting us.',
      'Marketing preferences do not affect operational messages about your account, a transaction, a booking, a security matter or a grievance.',
    ],
  },
  {
    number: '21', heading: 'Other websites and services', id: 's21',
    inShort: 'We do not control third-party sites we link to. Read their terms.',
    paragraphs: [
      'The platform links to independent websites, apps and services. We do not control how they handle your data.',
      'When you leave our platform, or deal directly with an independent provider, their privacy information and terms apply.',
    ],
  },
  {
    number: '22', heading: 'Changes to this policy', id: 's22',
    inShort: 'We will tell you about material changes. Silence is never treated as consent where the law needs an explicit yes.',
    paragraphs: [
      'We update this policy when our services, technology, practices, security requirements or the law change.',
      'Where a change materially affects how we handle your data, or where the law requires notice, we give notice.',
      'We do not treat silence, inactivity or continued use as fresh consent where the law requires a separate affirmative consent.',
    ],
  },
  {
    number: '23', heading: 'Questions and complaints', id: 's23',
    inShort: 'Email one@wecare.digital or call +91 9330994400. Use our grievance process first where the law requires it; statutory escalation rights remain available.',
    paragraphs: [
      'For any question, request or complaint about your personal data, contact our Privacy and Grievance Desk: email one@wecare.digital, or call +91 9330994400. Our postal address is in section 24.',
      'We may ask for enough information to verify your identity or authority before acting on a request.',
      'If you are not satisfied with our response, you keep any right you have to approach the Data Protection Board of India, another competent authority, regulator, court or other lawful forum. Where applicable data-protection law requires you to exhaust our grievance process before approaching the Board, that requirement applies.',
    ],
  },
  {
    /*
     * ADDED 2026-09-30 on owner instruction ("add jurisdiction as Kolkata").
     *
     * THE TERMS ALREADY SAID KOLKATA; THIS POLICY SAID NOTHING. Terms section 39 has named the
     * courts of Kolkata, West Bengal for some time. In this document "Kolkata" appeared exactly
     * once, in section 24, as the postal address - there was no governing-law or forum clause at
     * all. So the instruction was already satisfied in one of the two documents and completely
     * unmet in the other, which is the opposite of how it looked.
     *
     * A SUB-CLAUSE OF 23, not a new section 25. Section 24 is the contact clause and belongs
     * last; governing law sits naturally under "Questions and complaints" because the question a
     * reader has at that point is where a complaint goes. Additive, so no number moves.
     *
     * THE CARVE-OUT IS THE IMPORTANT PART and it is worded to match Terms section 39 rather than
     * paraphrased. A privacy policy cannot contract a person out of a statutory data-protection
     * forum, and under the DPDP Act 2023 that forum is the Data Protection Board of India. If
     * this clause and a statutory route ever point in different directions, the statutory route
     * wins - stated explicitly rather than left to inference, because a reader who has got this
     * far is looking for permission to escalate.
     *
     * The saver in 23 above already says this. It is repeated here deliberately: this document's
     * rewrite note records that savers are kept "in the specific places where a reader is most
     * likely to be talked out of a remedy", and a jurisdiction clause is exactly such a place.
     */
    number: '23.1', heading: 'Governing law and where disputes are heard', id: 's23-1',
    paragraphs: [
      'This policy is governed by the laws of India.',
      'This policy describes our data-handling commitments and statutory obligations. It does not create a separate warranty, indemnity or assumption of liability beyond what applicable law requires. Any contractual limitation of liability in our Terms applies only to the extent it can lawfully apply to a privacy-related claim and never overrides a non-waivable data-protection right, remedy, direction or penalty.',
      'Nothing in this policy removes any right to approach the Data Protection Board of India, another data-protection authority, a regulator, a Consumer Commission, a court or any other forum available to you under the law. Where the law requires our grievance process to be exhausted before a particular escalation, that procedural requirement applies.',
      'For a dispute about this policy that is not within the jurisdiction of a mandatory statutory, consumer or data-protection forum, the courts of competent jurisdiction in Kolkata, West Bengal have jurisdiction, subject to the law.',
      'This matches section 39 of our Terms of Service, so one dispute is not directed to two different places. Where a statutory forum is available to you, that route prevails over this one, subject to any required grievance step before escalation.',
    ],
  },
  {
    number: '24', heading: 'Who we are and how to reach us', id: 's24',
    inShort: 'WECARE.DIGITAL BHARATWORKS, Kolkata. one@wecare.digital, +91 9330994400.',
    paragraphs: [
      'Brand: WECARE.DIGITAL, operated under the business name WECARE.DIGITAL BHARATWORKS.',
      'Address: The W.B.S.I.D.C. Building, Unit 1/20 81/2/7, Phears Lane, Kolkata, West Bengal 700012, India.',
      'Email one@wecare.digital or call +91 9330994400 with any question about this policy or about how we handle personal data. These are our published business contacts for privacy questions unless we separately identify another legally required contact.',
    ],
  },
];
