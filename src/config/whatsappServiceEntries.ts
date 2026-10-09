/** Public entry links open chat with a keyword; backend verifies identity before returning data. */
import { REVIEW_ENTRY_URL } from '../lib/reviewEntry';
export const WHATSAPP_SERVICE_ENTRIES = [
  { slug: 'submit-request', label: 'Submit Request', keyword: 'Submit Request', flowId: '1107164111921876', state: 'Published; opens after verified payment' },
  { slug: 'request-amendment', label: 'Request Amendment', keyword: 'Request Amendment', flowId: '3678132465672138', state: 'Existing draft; publication pending' },
  { slug: 'drop-docs', label: 'Drop Docs', keyword: 'Drop Docs', flowId: '1211063631104445', state: 'Existing draft; publication pending' },
  { slug: 'vault', label: 'Vault', keyword: 'Vault', flowId: '', state: 'Secure file selection and delivery; no extra Flow' },
  { slug: 'shipments', label: 'Shipments', keyword: 'Shipments', flowId: '', state: 'Verified order history; carrier booking is separate' },
  { slug: 'leave-review', label: 'Leave Review', keyword: 'Leave Review', flowId: '1578178897413815', state: 'Published' },
  { slug: 'orders', label: 'Orders', keyword: 'Orders', flowId: '', state: 'Canonical customer order numbers; paginated' },
  { slug: 'customer-id', label: 'Customer ID', keyword: 'Customer ID', flowId: '', state: 'Stored public customer UUID' },
] as const;

export const whatsappKeywordLink = ( keyword: string ): string =>
  `https://wa.me/919330994400?text=${encodeURIComponent( keyword )}`;

export const whatsappServiceLink = ( slug: string ): string | undefined => {
  if ( slug === 'leave-review' ) return REVIEW_ENTRY_URL;
  const entry = WHATSAPP_SERVICE_ENTRIES.find( row => row.slug === slug );
  return entry ? whatsappKeywordLink( entry.keyword ) : undefined;
};
