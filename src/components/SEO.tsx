/**
 * SEO Component - WECARE.DIGITAL
 *
 * Head tags for the authenticated Workspace screens and the noindex /get/ utility page. Public,
 * indexable pages use components/PageMeta.tsx instead; nothing that should rank renders this.
 *
 * DEFAULT IS noindex, nofollow. It used to be "index, follow", and because a component's <Head>
 * is processed after _app.tsx's, every Workspace screen that omitted the prop replaced the
 * authenticated branch's noindex with an index signal once it rendered. Default to deny; a page
 * that genuinely should be indexed belongs on PageMeta, not here.
 */

import Head from 'next/head';
import { buildPageTitle } from '../lib/page-title';

interface SEOProps {
  title: string;
  description: string;
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

// NO meta keywords: Google Search does not use the tag and .kiro/steering/00-common.md says not to
// add it. The `keywords` prop and the WhatsApp-heavy default list went with it on 2026-10-25.

export default function SEO({ 
  title, 
  description, 
  canonical,
  noindex = true,
  ogImage = DEFAULT_IMAGE 
}: SEOProps) {
  const fullTitle = buildPageTitle( title );
  
  return (
    <Head>
      <title>{fullTitle}</title>
      <meta name="description" content={description} />
      
      {/* Robots */}
      <meta name="robots" content={noindex ? 'noindex, nofollow' : 'index, follow'} />
      
      {/* Canonical. Keyed like PageMeta's so it REPLACES _app.tsx's computed one. */}
      {canonical && <link rel="canonical" key="canonical" href={`${BASE_URL}${canonical}`} />}
      
      {/* Open Graph. THE KEYS ARE LOAD-BEARING: next/head never de-duplicates by `property`, so
          on /get/ - the one public route that renders this component - every unkeyed og: tag
          here was emitted BESIDE _app.tsx's keyed copy (two og:title, og:description, og:image,
          og:type and og:site_name, measured on the export). Same keys as _app.tsx and PageMeta. */}
      <meta property="og:title" key="og:title" content={fullTitle} />
      <meta property="og:description" key="og:description" content={description} />
      <meta property="og:image" key="og:image" content={ogImage} />
      <meta property="og:type" key="og:type" content="website" />
      <meta property="og:site_name" key="og:site_name" content={SITE_NAME} />
      {canonical && <meta property="og:url" key="og:url" content={`${BASE_URL}${canonical}`} />}
      
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
  },
  contacts: {
    title: 'Contacts - Customer Management',
    description: 'Manage your customer contacts. Import, export, search and organize contacts for WhatsApp, SMS, and Email campaigns.',
  },
  whatsapp: {
    title: 'WhatsApp Messaging - Business API',
    description: 'Send and receive WhatsApp messages using official Business API. Create templates, send bulk messages, and automate responses.',
  },
  // Public, indexed metadata. Deliberately vendor-neutral: naming the carrier
  // advertises an implementation detail, dates the page whenever routing
  // changes, and these entries had outlived two migrations - they still said
  sms: {
    title: 'SMS Messaging - Bulk, OTP & Transactional',
    description: 'Send SMS at scale with DLT-compliant templates. Bulk campaigns, OTP delivery, and transactional messages across India and international routes.',
  },
  email: {
    title: 'Email Marketing - Amazon SES',
    description: 'Send emails via Amazon SES. Create email campaigns, transactional emails, and marketing newsletters.',
  },
  voice: {
    title: 'Voice Calls - IVR and Notifications',
    description: 'Place and receive voice calls with IVR and automated voice notifications, plus full call detail records.',
  },
  payments: {
    title: 'Payments - Razorpay Integration',
    description: 'Send payment requests via WhatsApp with Razorpay integration. Track payments, generate payment links.',
  },
  bulk: {
    title: 'Bulk Messaging - Campaigns',
    description: 'Send bulk messages across WhatsApp, SMS, Email, and Voice. Create campaigns, schedule messages, track delivery.',
  },
  templates: {
    title: 'WhatsApp Templates - Message Templates',
    description: 'Create and manage WhatsApp message templates. Promotional, transactional, and utility templates for business messaging.',
  },
  billing: {
    title: 'Billing - Usage and Costs',
    description: 'Track messaging and platform usage and costs across every channel.',
  },
  aiConfig: {
    title: 'AI Configuration - Response Automation',
    description: 'Configure AI-assisted response automation, knowledge sources and auto-reply settings.',
  },
  orders: {
    title: 'Orders - Order Management',
    description: 'Manage orders from native commerce, WhatsApp, and manual sources. Track status, payments, and linked submissions.',
  },
  documents: {
    title: 'Drop Docs - Document Management',
    description: 'Manage customer-uploaded documents. Review, approve, and organize prescriptions, IDs, and other files.',
  },
  faq: {
    title: 'FAQ Management',
    description: 'Manage frequently asked questions. Create, edit, and organize FAQ entries by category.',
  },
  appointments: {
    title: 'Appointments - Schedule Management',
    description: 'Manage customer appointments. Track scheduling, confirmations, and completions.',
  },
  sehatAppointments: {
    title: 'Sehat Appointments - Booking Management',
    description: 'Manage Sehat appointment availability and bookings with qualified professionals.',
  },
  enterprise: {
    title: 'Enterprise Assist - Case Management',
    description: 'Manage enterprise support cases. Track priorities, assignments, and resolutions.',
  },
  reviews: {
    title: 'Reviews - Moderation',
    description: 'Moderate customer reviews. Approve, hide, or respond to feedback across channels.',
  },
  submitRequest: {
    title: 'Submit Request - Order-Centric Service',
    description: 'Submit a service request linked to an order. Select order, describe issue, review and submit.',
  },
  trackRequest: {
    title: 'Track Request - Order Status',
    description: 'Track all service activity for an order. View requests, status timeline, payments, and outcomes.',
  },
  amendRequest: {
    title: 'Amend Request - Modify Submission',
    description: 'Amend or add information to an existing service request linked to an order.',
  },
};
