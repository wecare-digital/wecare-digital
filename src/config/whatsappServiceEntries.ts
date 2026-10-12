/** Public entry links open chat with a keyword; backend verifies identity before returning data. */
import { REVIEW_ENTRY_URL } from '../lib/reviewEntry';
export const WHATSAPP_SERVICE_ENTRIES = [
  { slug: 'orders', label: 'Orders', keyword: 'Orders', messageLink: 'https://wa.me/message/2OQZCYBSMU4SE1', flowId: '', state: 'Canonical customer order numbers; paginated' },
  { slug: 'submit-request', label: 'Submit Request', keyword: 'Submit Request', messageLink: 'https://wa.me/message/5DRZXKBJTZDQG1', flowId: '1107164111921876', state: 'Published; opens after verified payment' },
  { slug: 'request-amendment', label: 'Request Amendment', keyword: 'Request Amendment', messageLink: 'https://wa.me/message/HD5C4LAUYOOID1', flowId: '3678132465672138', state: 'Existing draft; publication pending' },
  { slug: 'drop-docs', label: 'Drop Docs', keyword: 'Drop Docs', messageLink: 'https://wa.me/message/BCYW2SEPI5R4D1', flowId: '1211063631104445', state: 'Existing draft; publication pending' },
  { slug: 'vault', label: 'Vault', keyword: 'Vault', messageLink: 'https://wa.me/message/4J6E277ZRFHLK1', flowId: '', state: 'Secure file selection and delivery; no extra Flow' },
  // Request Pickup, added 2026-10-10 with the fifth Wix service variant. It shares the dedicated
  // pickup Meta short link that the /shipments "Request pickup" CTA already uses
  // (src/content/shipments.ts ctaHref2), so both pickup entry points open the same conversation.
  { slug: 'request-pickup', label: 'Request Pickup', keyword: 'Request Pickup', messageLink: 'https://wa.me/message/NRWQFXOPGL7OO1', flowId: '', state: 'Public page live; shares the pickup Meta short link with /shipments CTA 2' },
  { slug: 'shipments', label: 'Shipments', keyword: 'Shipments', messageLink: 'https://wa.me/message/WGN4NMFLFSJVB1', flowId: '', state: 'Verified order history; carrier booking is separate' },
  { slug: 'leave-review', label: 'Leave Review', keyword: 'Leave Review', messageLink: REVIEW_ENTRY_URL, flowId: '1578178897413815', state: 'Published' },
  // The dedicated Subscribe Meta short link, the same one the blog surfaces use
  // (post/[slug].tsx, BlogFooterCTA.tsx). It must stay EQUAL to SUBSCRIBE_CTA_HREF in
  // src/content/subscribe.ts and SUBSCRIBE_HREF in src/components/PublicShare.tsx —
  // ProductPage renders the CTA as whatsappServiceLink(slug) || ctaHref, so a mismatch would
  // show the entry link, not the content one.
  { slug: 'subscribe', label: 'Subscribe', keyword: 'Subscribe', messageLink: 'https://wa.me/message/WUDPTMYSO6XII1', flowId: '', state: 'Dedicated Subscribe Meta short link; shared with the blog surfaces' },
  { slug: 'anew', label: 'Anew', keyword: 'Start a conversation', messageLink: 'https://wa.me/message/F2D7PVR5Q45MP1', flowId: '', state: 'Public Anew conversation entry' },
  // No Meta short link exists for this entry; the empty messageLink makes whatsappServiceLink
  // fall back to the keyword deep link (wa.me/919330994400?text=Customer%20ID), which opens
  // WhatsApp on any device with "Customer ID" pre-filled. Swap in a wa.me/message/… short link
  // here when Meta issues one.
  { slug: 'customer-id', label: 'Customer ID', keyword: 'Customer ID', messageLink: '', flowId: '', state: 'Stored public customer UUID; keyword deep link, no Meta short link yet' },
] as const;

export const whatsappKeywordLink = ( keyword: string ): string =>
  `https://wa.me/919330994400?text=${encodeURIComponent( keyword )}`;

export const whatsappServiceLink = ( slug: string ): string | undefined => {
  const entry = WHATSAPP_SERVICE_ENTRIES.find( row => row.slug === slug );
  if ( !entry ) return undefined;
  return entry.messageLink || whatsappKeywordLink( entry.keyword );
};
