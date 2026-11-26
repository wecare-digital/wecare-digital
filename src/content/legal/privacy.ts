import type { LegalSection } from './types';

export const PRIVACY_UPDATED = '2026-11-26';

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
    inShort: 'The information we collect depends on the services you use.',
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
      'If you make a voluntary contribution, we may collect the contribution and article references, amount, currency, payment details and status, date, and any refund or reversal, to process and account for it.',
      'If you buy or use a gift card, coupon or credit, we may collect its code, balance, status and redemption history linked to your transaction. Relevant payment or commerce providers may also handle those details.',
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
      'We may automatically collect IP addresses, browser and device information, device and session identifiers, usage and timestamps, referral information, diagnostic and security information.',
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
      'We use cookies and similar technologies for sign-in, preferences, security, performance, analytics, communications and advertising, as applicable.',
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
      'We collect information when you create an account, browse, make an order or booking, submit documents or forms, contact us, join an offer or event, use payment or delivery services, leave a review or use cookies.',
      'We also receive data from authorised third parties where it is genuinely needed for a service you asked for, or for security, fraud prevention or verification.',
    ],
  },
  {
    number: '5', heading: 'Why we use it', id: 's5',
    inShort: 'To run your account, deliver what you asked for, take payment, support you, keep the platform safe, meet legal duties, and improve the service.',
    paragraphs: [
      'We use personal data to manage accounts, fulfil orders and service requests, coordinate providers and deliveries, process payments, refunds, contributions, gift cards and credits, handle documents and bookings, manage subscriptions, offers and referrals, personalise services, communicate with you, provide support, verify identity or eligibility, protect accounts, prevent fraud, improve services, resolve disputes and comply with law.',
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
      'We share personal data as needed to provide and support services, complete transactions, protect users and comply with law.',
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
      'We use service providers for hosting, communications, sign-in, customer support, analytics, security, payments, delivery, document processing and appointments.',
      'Service providers process data for the relevant service, subject to applicable confidentiality, contractual and data-protection requirements.',
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
    number: '13', heading: 'AI and automated processing', id: 's13',
    inShort: 'Some services use automated tools. You may request review or exercise applicable rights.',
    paragraphs: [
      'We may use automated tools, including AI where applicable, to provide communications, document and content assistance, organise requests, protect accounts, prevent fraud and improve services.',
      'Where processing materially affects you, we provide any disclosure, consent, review or other safeguard required by law. You may contact one@wecare.digital with questions or to request review.',
    ],
  },
  {
    number: '14', heading: 'Processing outside your country', id: 's14',
    inShort: 'Some of our suppliers operate abroad, so data may be processed outside the country you use us from. Transfers are subject to legal safeguards.',
    paragraphs: [
      'Some service providers may process personal data outside your country.',
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
      'Contribution, gift-card, coupon and redemption records may be retained for accounting, tax, refunds, fraud prevention and legal requirements, including after the transaction ends.',
      'Some transaction, security and financial records must be kept after you close your account or ask for deletion, because the law requires it. Section 18 explains how that interacts with a deletion request.',
      'When data is no longer needed we delete, anonymise or de-identify it.',
    ],
  },
  {
    number: '16', heading: 'Protecting your information', id: 's16',
    inShort: 'We use appropriate safeguards. Please keep account and verification details private.',
    paragraphs: [
      'We use reasonable safeguards appropriate to the personal data we handle, including access controls, authentication, encryption or masking, and security monitoring, as applicable.',
      'No method of electronic processing is completely secure. Please keep your sign-in and verification details private and contact us if you suspect unauthorised access.',
    ],
  },
  {
    number: '17', heading: 'Personal data incidents', id: 's17',
    inShort: 'We respond to personal data incidents and provide notifications as required by law.',
    paragraphs: [
      'If we become aware of a personal data breach, we take appropriate steps to assess and respond to it.',
      'We notify affected people and competent authorities when required by law. Notifications include the information required by applicable law, including relevant protective steps.',
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
      'Opting out of marketing does not stop messages needed for your account, order, booking, payment, security or complaint.',
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
      'We may update this policy to reflect changes in our services, data-handling practices or applicable law.',
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
    
    number: '23.1', heading: 'Governing law and where disputes are heard', id: 's23-1',
    paragraphs: [
      'This policy is governed by the laws of India.',
      'This policy describes how we handle personal data. It does not create warranties or obligations beyond the applicable law and expressly agreed terms. Section 32 of our Terms applies only to the extent permitted by law and does not restrict non-waivable privacy rights or remedies.',
      'Nothing in this policy removes any right to approach the Data Protection Board of India, another data-protection authority, a regulator, a Consumer Commission, a court or any other forum available to you under the law. Where the law requires our grievance process to be exhausted before a particular escalation, that procedural requirement applies.',
      'For a dispute about this policy that is not within the jurisdiction of a mandatory statutory, consumer or data-protection forum, the courts of competent jurisdiction in Kolkata, West Bengal have jurisdiction, subject to the law.',
      'See section 39 of our Terms of Service for the general dispute provisions. Mandatory statutory forums and any required grievance procedure take precedence.',
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
