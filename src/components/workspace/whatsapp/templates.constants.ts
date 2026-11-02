/**
 * Static option tables, colour maps, inline style objects, and the page props type
 * for the WhatsApp Template Management screen.
 *
 * Extracted VERBATIM from templates.tsx as part of a pure structural refactor (no
 * behaviour change). These are build-time constants with no component state; the
 * component imports them so its render output, effect timing, and memoization are
 * unchanged.
 */

import type React from 'react';
import { type SelectOption } from '../../../components/ui/Select';

export interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

export const WABA_OPTIONS = [
  { id: 'waba-e47d916f3c7a47e1a34a19653893dd4b', name: 'WECARE.DIGITAL' },
  { id: 'waba-dbe343f210204752b74c80a0a59631a6', name: 'Manish Agarwal' },
];

export const WABA_SELECT_OPTIONS: SelectOption[] = WABA_OPTIONS.map( ( w ) => ( { value: w.id, label: w.name } ) );
export const TEMPLATE_CATEGORY_OPTIONS: SelectOption[] = [
  { value: 'UTILITY', label: 'Utility' },
  { value: 'MARKETING', label: 'Marketing' },
  { value: 'AUTHENTICATION', label: 'Authentication' },
];
export const TEMPLATE_LANGUAGE_OPTIONS: SelectOption[] = [
  { value: 'en_US', label: 'English (US)' },
  { value: 'en_GB', label: 'English (UK)' },
  { value: 'hi', label: 'Hindi' },
  { value: 'es', label: 'Spanish' },
];
export const HEADER_TYPE_OPTIONS: SelectOption[] = [
  { value: 'none', label: 'No Header' },
  { value: 'text', label: 'Text' },
  { value: 'image', label: 'Image' },
  { value: 'video', label: 'Video' },
  { value: 'document', label: 'Document' },
  { value: 'location', label: 'Location (map pin)' },
];
export const BUTTON_TYPE_OPTIONS: SelectOption[] = [
  { value: 'URL', label: 'URL' },
  { value: 'PHONE_NUMBER', label: 'Phone' },
  { value: 'QUICK_REPLY', label: 'Quick Reply' },
];
/** The carousel card's own order, which differs from the body button list above it. */
export const CARD_BUTTON_TYPE_OPTIONS: SelectOption[] = [
  { value: 'QUICK_REPLY', label: 'Quick Reply' },
  { value: 'URL', label: 'URL' },
  { value: 'PHONE_NUMBER', label: 'Phone' },
];
export const CAROUSEL_CATEGORY_OPTIONS: SelectOption[] = [
  { value: 'MARKETING', label: 'Marketing' },
  { value: 'UTILITY', label: 'Utility' },
];
export const CAROUSEL_LANGUAGE_OPTIONS: SelectOption[] = [
  { value: 'en_US', label: 'English (US)' },
  { value: 'en_GB', label: 'English (UK)' },
  { value: 'hi', label: 'Hindi' },
  { value: 'bn', label: 'Bengali' },
  { value: 'ta', label: 'Tamil' },
  { value: 'te', label: 'Telugu' },
  { value: 'gu', label: 'Gujarati' },
  { value: 'mr', label: 'Marathi' },
];
/* Layout only, and these numbers are not new: they are the sizes the dropped `.waba-select`
   and `.button-row select` rules carried. A styled-jsx class cannot be forwarded to a child
   component - its scope hash never reaches that component's DOM - and `className` on a Select
   lands on the wrapper, so the class goes and the layout half of it comes back here. */
export const WABA_SELECT_STYLE: React.CSSProperties = { minWidth: 200 };
export const EMBEDDED_WABA_SELECT_STYLE: React.CSSProperties = { flex: 1, minWidth: 150 };
export const BUTTON_TYPE_SELECT_STYLE: React.CSSProperties = { width: 120 };

export const CATEGORY_COLORS: Record<string, string> = {
  MARKETING: 'var(--text)',
  UTILITY: '#4a4a4a',
  AUTHENTICATION: '#6b6b6b',
};

export const STATUS_COLORS: Record<string, string> = {
  APPROVED: 'var(--text)',
  PENDING: '#6b6b6b',
  REJECTED: 'var(--accent)',
};

export const TEMPLATE_OPERATION_PATHS: Record<string, string> = {
  wecare_order_status_v3: 'Payments · Order status',
  wecare_default_invoice_image_template: 'Payments · Send invoice',
  wecare_leave_review: 'Inbox · Send template',
  wecare_whatapp_native_pay_template: 'Payments · Request payment',
  wecare_default_download: 'Inbox · Send template · Vault file ID',
  wecare_location_share_pin: 'Inbox · Send template · Location',
  wecare_otp: 'Customer verification · Automatic',
  wecare_vault_request_ready: 'Retired · historical Vault offer only; use Pay & Flow → Vault',
};
