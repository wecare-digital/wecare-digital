/**
 * SEO Component - WECARE.DIGITAL
 * Reusable SEO meta tags for all pages
 */

import Head from 'next/head';
import { buildPageTitle } from '../lib/page-title';

interface SEOProps {
  title: string;
  description: string;
  keywords?: string;
  canonical?: string;
  noindex?: boolean;
  ogImage?: string;
}

const BASE_URL = 'https://wecare.digital';
const SITE_NAME = 'WECARE.DIGITAL';
/**
 * The branded 16:9 card, NOT the square mark — and for the same measured reason as in
 * _app.tsx, where the full note lives. In short: this fed og:image and twitter:image with
 * `wecaredigital.png`, which is 1080x1080 and 68.4% FULLY TRANSPARENT with a black mark. The
 * platforms that render a link preview flatten alpha themselves, commonly onto black, so the
 * preview could come out as a black square with an invisible logo. This asset is
 * colour-type 2 (RGB) with no alpha channel to flatten, and at 1440x810 it is the shape
 * `twitter:card=summary_large_image` actually wants rather than a square that gets cropped.
 */
/* THE OPAQUE SQUARE ICON, matching every other public surface - see src/config/share.ts for the
   full reasoning. Briefly: the wide wd-brand-16x9 card is 801,077 bytes against the 600 KB Meta
   allows for a WhatsApp preview, so it was not being rendered there at all, and this asset is
   already live at 86,123 bytes and inside every limit. twitter:card below is already "summary",
   which is the correct frame for a 1:1 image - so this file needed only the URL changed. */
const DEFAULT_IMAGE = 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png';

// Default keywords for all pages
const DEFAULT_KEYWORDS = 'WhatsApp Business API, WhatsApp CRM, bulk messaging, SMS API, email marketing, voice calls, Razorpay payments, customer engagement, multi-channel CRM, WECARE.DIGITAL, Stack CRM';

export default function SEO({ 
  title, 
  description, 
  keywords = '', 
  canonical,
  noindex = false,
  ogImage = DEFAULT_IMAGE 
}: SEOProps) {
  const fullTitle = buildPageTitle( title );
  const allKeywords = keywords ? `${keywords}, ${DEFAULT_KEYWORDS}` : DEFAULT_KEYWORDS;
  
  return (
    <Head>
      <title>{fullTitle}</title>
      <meta name="description" content={description} />
      <meta name="keywords" content={allKeywords} />
      
      {/* Robots */}
      <meta name="robots" content={noindex ? 'noindex, nofollow' : 'index, follow'} />
      
      {/* Canonical */}
      {canonical && <link rel="canonical" href={`${BASE_URL}${canonical}`} />}
      
      {/* Open Graph */}
      <meta property="og:title" content={fullTitle} />
      <meta property="og:description" content={description} />
      <meta property="og:image" content={ogImage} />
      <meta property="og:type" content="website" />
      <meta property="og:site_name" content={SITE_NAME} />
      {canonical && <meta property="og:url" content={`${BASE_URL}${canonical}`} />}
      
      {/* Twitter */}
      <meta name="twitter:card" content="summary" />
      <meta name="twitter:title" content={fullTitle} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content={ogImage} />
    </Head>
  );
}

// Page-specific SEO configurations
export const PAGE_SEO = {
  dashboard: {
    title: 'Dashboard - Overview & Analytics',
    description: 'View your messaging analytics, contact statistics, payment records, and AWS billing. Monitor WhatsApp, SMS, Email performance in real-time.',
    keywords: 'messaging dashboard, analytics, WhatsApp statistics, SMS reports, email metrics, billing overview'
  },
  contacts: {
    title: 'Contacts - Customer Management',
    description: 'Manage your customer contacts. Import, export, search and organize contacts for WhatsApp, SMS, and Email campaigns.',
    keywords: 'contact management, customer database, import contacts, export contacts, CRM contacts'
  },
  whatsapp: {
    title: 'WhatsApp Messaging - Business API',
    description: 'Send and receive WhatsApp messages using official Business API. Create templates, send bulk messages, and automate responses.',
    keywords: 'WhatsApp messaging, WhatsApp Business API, WhatsApp templates, bulk WhatsApp, WhatsApp automation'
  },
  // Public, indexed metadata. Deliberately vendor-neutral: naming the carrier
  // advertises an implementation detail, dates the page whenever routing
  // changes, and these entries had outlived two migrations - they still said
  sms: {
    title: 'SMS Messaging - Bulk, OTP & Transactional',
    description: 'Send SMS at scale with DLT-compliant templates. Bulk campaigns, OTP delivery, and transactional messages across India and international routes.',
    keywords: 'SMS API, bulk SMS, OTP SMS, transactional SMS, DLT SMS India'
  },
  email: {
    title: 'Email Marketing - Amazon SES',
    description: 'Send emails via Amazon SES. Create email campaigns, transactional emails, and marketing newsletters.',
    keywords: 'email marketing, Amazon SES, bulk email, email campaigns, transactional email'
  },
  voice: {
    title: 'Voice Calls - IVR and Notifications',
    description: 'Place and receive voice calls with IVR and automated voice notifications, plus full call detail records.',
    keywords: 'voice calls API, IVR, voice campaigns, voice notifications, call detail records'
  },
  payments: {
    title: 'Payments - Razorpay Integration',
    description: 'Send payment requests via WhatsApp with Razorpay integration. Track payments, generate payment links.',
    keywords: 'WhatsApp payments, Razorpay integration, payment links, payment collection, UPI payments'
  },
  bulk: {
    title: 'Bulk Messaging - Campaigns',
    description: 'Send bulk messages across WhatsApp, SMS, Email, and Voice. Create campaigns, schedule messages, track delivery.',
    keywords: 'bulk messaging, bulk WhatsApp, bulk SMS, bulk email, message campaigns, scheduled messages'
  },
  templates: {
    title: 'WhatsApp Templates - Message Templates',
    description: 'Create and manage WhatsApp message templates. Promotional, transactional, and utility templates for business messaging.',
    keywords: 'WhatsApp templates, message templates, promotional templates, transactional templates, template management'
  },
  billing: {
    title: 'Billing - Usage and Costs',
    description: 'Track messaging and platform usage and costs across every channel.',
    keywords: 'billing, cost management, usage tracking, messaging costs'
  },
  aiConfig: {
    title: 'AI Configuration - Response Automation',
    description: 'Configure AI-assisted response automation, knowledge sources and auto-reply settings.',
    keywords: 'AI automation, AI responses, chatbot configuration, auto-reply, knowledge base'
  },
  orders: {
    title: 'Orders - Order Management',
    description: 'Manage orders from native commerce, WhatsApp, and manual sources. Track status, payments, and linked submissions.',
    keywords: 'order management, WhatsApp orders, commerce orders, order tracking, payment status'
  },
  documents: {
    title: 'Drop Docs - Document Management',
    description: 'Manage customer-uploaded documents. Review, approve, and organize prescriptions, IDs, and other files.',
    keywords: 'document management, WhatsApp documents, file uploads, document review, drop docs'
  },
  faq: {
    title: 'FAQ Management',
    description: 'Manage frequently asked questions. Create, edit, and organize FAQ entries by category.',
    keywords: 'FAQ management, knowledge base, customer support, help center'
  },
  appointments: {
    title: 'Appointments - Schedule Management',
    description: 'Manage customer appointments. Track scheduling, confirmations, and completions.',
    keywords: 'appointment management, scheduling, calendar, booking'
  },
  rxSlots: {
    title: 'RX Slots - Slot Management',
    description: 'Manage prescription and consultation time slots. Book, block, and track availability.',
    keywords: 'slot management, prescription slots, booking, availability'
  },
  enterprise: {
    title: 'Enterprise Assist - Case Management',
    description: 'Manage enterprise support cases. Track priorities, assignments, and resolutions.',
    keywords: 'case management, enterprise support, ticket system, customer service'
  },
  reviews: {
    title: 'Reviews - Moderation',
    description: 'Moderate customer reviews. Approve, hide, or respond to feedback across channels.',
    keywords: 'review moderation, customer feedback, ratings, review management'
  },
  submitRequest: {
    title: 'Submit Request - Order-Centric Service',
    description: 'Submit a service request linked to an order. Select order, describe issue, review and submit.',
    keywords: 'submit request, service request, order support, customer service'
  },
  trackRequest: {
    title: 'Track Request - Order Status',
    description: 'Track all service activity for an order. View requests, status timeline, payments, and outcomes.',
    keywords: 'track request, order tracking, service status, request history'
  },
  amendRequest: {
    title: 'Amend Request - Modify Submission',
    description: 'Amend or add information to an existing service request linked to an order.',
    keywords: 'amend request, modify request, update submission, order amendment'
  },
};
