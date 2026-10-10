/** Public entry links open chat with a keyword; backend verifies identity before returning data. */
import { REVIEW_ENTRY_URL } from '../lib/reviewEntry';
export const WHATSAPP_SERVICE_ENTRIES = [
  { slug: 'orders', label: 'Orders', keyword: 'Orders', messageLink: 'https://wa.me/message/2OQZCYBSMU4SE1', flowId: '', state: 'Canonical customer order numbers; paginated' },
  { slug: 'submit-request', label: 'Submit Request', keyword: 'Submit Request', messageLink: 'https://wa.me/message/5DRZXKBJTZDQG1', flowId: '1107164111921876', state: 'Published; opens after verified payment' },
  { slug: 'request-amendment', label: 'Request Amendment', keyword: 'Request Amendment', messageLink: 'https://wa.me/message/HD5C4LAUYOOID1', flowId: '3678132465672138', state: 'Existing draft; publication pending' },
  { slug: 'drop-docs', label: 'Drop Docs', keyword: 'Drop Docs', messageLink: 'https://wa.me/message/BCYW2SEPI5R4D1', flowId: '1211063631104445', state: 'Existing draft; publication pending' },
  { slug: 'vault', label: 'Vault', keyword: 'Vault', messageLink: 'https://wa.me/message/4J6E277ZRFHLK1', flowId: '', state: 'Secure file selection and delivery; no extra Flow' },
  // Request Pickup, added 2026-10-10 with the fifth Wix service variant. `messageLink` is empty on
  // purpose: Meta has issued no short link for it yet, and an empty value makes
  // whatsappServiceLink fall back to the keyword deep link, which works today.
  { slug: 'request-pickup', label: 'Request Pickup', keyword: 'Request Pickup', messageLink: '', flowId: '', state: 'Public page live; keyword deep link only, no Meta short link or Flow yet' },
  { slug: 'shipments', label: 'Shipments', keyword: 'Shipments', messageLink: 'https://wa.me/message/WGN4NMFLFSJVB1', flowId: '', state: 'Verified order history; carrier booking is separate' },
  { slug: 'leave-review', label: 'Leave Review', keyword: 'Leave Review', messageLink: REVIEW_ENTRY_URL, flowId: '1578178897413815', state: 'Published' },
  { slug: 'subscribe', label: 'Subscribe', keyword: 'Subscribe', messageLink: 'https://wa.me/message/WUDPTMYSO6XII1', flowId: '', state: 'Meta message link; legacy Subscribe flows remain retired' },
  { slug: 'customer-id', label: 'Customer ID', keyword: 'Customer ID', messageLink: '', flowId: '', state: 'Stored public customer UUID' },
] as const;

export const whatsappKeywordLink = ( keyword: string ): string =>
  `https://wa.me/919330994400?text=${encodeURIComponent( keyword )}`;

export const whatsappServiceLink = ( slug: string ): string | undefined => {
  const entry = WHATSAPP_SERVICE_ENTRIES.find( row => row.slug === slug );
  if ( !entry ) return undefined;
  return entry.messageLink || whatsappKeywordLink( entry.keyword );
};
