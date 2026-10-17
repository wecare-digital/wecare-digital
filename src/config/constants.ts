/**
 * Application Constants - WECARE.DIGITAL
 * Centralized configuration for all hardcoded values
 * 
 * These values can be overridden by environment variables:
 * - NEXT_PUBLIC_API_BASE
 * - NEXT_PUBLIC_PAYMENT_PHONE_ID
 * - NEXT_PUBLIC_PAYMENT_PHONE_DISPLAY
 * - NEXT_PUBLIC_PAYMENT_PHONE_NAME
 * - NEXT_PUBLIC_DEFAULT_GSTIN
 */

// AWS Account Configuration
// AWS_ACCOUNT_ID is used for ARN display in admin dashboards only.
// It should NOT be used for authentication or API calls.
export const AWS_ACCOUNT_ID = process.env.NEXT_PUBLIC_AWS_ACCOUNT_ID || '';
export const AWS_REGION = process.env.NEXT_PUBLIC_AWS_REGION || 'us-east-1';

// API Configuration
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

// Payment Phone Configuration (default active phone for payments)
export const PAYMENT_CONFIG = {
  phoneNumberId: process.env.NEXT_PUBLIC_PAYMENT_PHONE_ID || 'phone-number-id-waba-t-direct-1055232054343117',
  phoneDisplay: process.env.NEXT_PUBLIC_PAYMENT_PHONE_DISPLAY || '+91 99033 00044',
  phoneName: process.env.NEXT_PUBLIC_PAYMENT_PHONE_NAME || 'Manish Agarwal',
};

// Default GSTIN for invoices — loaded from env, no hardcoded fallback
export const DEFAULT_GSTIN = process.env.NEXT_PUBLIC_DEFAULT_GSTIN || '';

// WhatsApp Phone Numbers
// Payment config names must match EXACTLY what's configured on the WABA in Meta Business Manager
export const WHATSAPP_PHONES = {
  primary: {
    id: 'phone-number-id-waba1-direct-1016149501586345',
    display: '+91 93309 94400',
    name: 'WECARE.DIGITAL',
    username: 'wecare.digital',  // Fixed WhatsApp business username (reserved with Meta)
    wabaId: '2094615664435155',
    metaPhoneId: '1016149501586345',
    hasPayment: true,
    paymentConfigName: 'WECAREDIGITAL',
    paymentConfigs: [ 'WECAREDIGITAL', 'WECAREUPI' ],
    paymentProtected: false,
    pendingRegistration: true,  // Blocked by Meta rate limit — registration pending
  },
  secondary: {
    id: 'phone-number-id-waba-t-direct-1055232054343117',
    display: '+91 99033 00044',
    name: 'Manish Agarwal',
    username: 'manishagarwal',  // Fixed WhatsApp business username (reserved with Meta)
    wabaId: '2513394156072604',
    metaPhoneId: '1055232054343117',
    hasPayment: true,
    paymentConfigName: 'WECAREDIGITAL',
    paymentConfigs: [ 'WECAREDIGITAL', 'WECAREUPI' ],
    paymentProtected: true,
    directApi: true,
  },
};

// GST Rate Options
export const GST_RATES = [
  { value: 0, label: '0%' },
  { value: 3, label: '3%' },
  { value: 5, label: '5%' },
  { value: 12, label: '12%' },
  { value: 18, label: '18%' },
  { value: 28, label: '28%' },
];

// Convenience Fee Configuration
// Fee is charged on the cart/collection subtotal, then GST is applied to the
// fee itself: total = (subtotal x percent%) x (1 + gstPercent/100).
// The public checkout is AWS-owned. Server-side checkout/order code must use
// the same values when composing the final payable amount; do not duplicate
// these rates anywhere else.
//
// 2.5% ON OWNER INSTRUCTION, AND THE THREE COPIES NOW AGREE. They did not: this file
// said 2.2%, outbound-whatsapp/handler.py defaulted to 0.022 and
// payments/invoice-engine/handler.py hardcoded 0.02 - so the fee a customer was quoted
// depended on which surface composed the order. All three are 2.5% / 18% in this commit.
// If this value moves again, those two move with it; no test pins the rate, so nothing
// else will tell you.
export const CONVENIENCE_FEE = {
  percent: 2.5,
  gstPercent: 18.0,
};

// WhatsApp Payment Configuration Details
// The Razorpay MID (acc_...) stays backend-only and is deliberately absent here.
// MCC and purpose code are non-sensitive category codes.
export const PAYMENT_DETAILS = {
  // Verified against Graph API /{waba}/payment_configurations 2026-08-23:
  // MCC 7392 (Management, consulting and public relations services) on all
  // four configs across both WABAs. Was previously 4722 (travel agencies),
  // which did not match Meta and could cause payment rejections.
  mcc: '7392',
  purposeCode: '03',
  // Payee address of the WECAREUPI configuration. This is NOT a credential:
  // it is the `pa=` parameter of every UPI deep link and QR we hand to a payer,
  // so it is public by construction. It lives here because [retired public path]/link builds
  // that deep link client-side and cannot invent a payee.
  //
  // It must stay identical to _WECARE_UPI_VPA in
  // amplify/functions/messaging/whatsapp-business-api/handler.py, which is the
  // authoritative copy (overridable there via RAZORPAY_UPI_ID). Two earlier
  // VPAs are retired and must never reappear (one @kotak address once hardcoded
  // in the pay-link page, one bank-suffixed address once noted on the architecture
  // page). A stale VPA does not error - it silently collects money elsewhere.
  upiVpa: 'wecaredigitalbh511413.rzp@rxairtel',
};

// The only payment configuration names that exist on Meta. Both WABAs expose
// this identical pair; anything else is rejected with error 136026. Keep in step
// with VALID_PAYMENT_CONFIGS in
// amplify/functions/messaging/outbound-whatsapp/handler.py.
export const PAYMENT_CONFIG_NAMES = {
  gateway: 'WECAREDIGITAL',
  upi: 'WECAREUPI',
} as const;

export const DEFAULT_PAYMENT_CONFIG = PAYMENT_CONFIG_NAMES.gateway;

// All payment-enabled phones (convenience helper)
export const PAYMENT_PHONES = Object.values( WHATSAPP_PHONES ).filter( p => p.hasPayment );

// Message TTL (30 days in seconds)
export const MESSAGE_TTL_SECONDS = 30 * 24 * 60 * 60;

// Pagination defaults
export const PAGINATION = {
  defaultPageSize: 20,
  maxPageSize: 100,
};

// Retry configuration for API calls
export const RETRY_CONFIG = {
  maxRetries: 1,
  baseDelayMs: 500,
  maxDelayMs: 3000,
};
