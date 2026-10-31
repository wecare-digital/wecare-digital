/** Public entry links open chat with a keyword; backend verifies identity before returning data. */
import { REVIEW_ENTRY_URL, REVIEW_FLOW_ID } from '../lib/reviewEntry';
import { canonicalFlowId } from '../lib/canonicalFlows';

export const WHATSAPP_SERVICE_ENTRIES = [
  { slug: 'orders', label: 'Orders', keyword: 'Orders', messageLink: 'https://wa.me/message/2OQZCYBSMU4SE1', flowId: '', state: 'Canonical customer order numbers; paginated' },
  { slug: 'submit-request', label: 'Submit Request', keyword: 'Submit Request', messageLink: 'https://wa.me/message/5DRZXKBJTZDQG1', flowId: canonicalFlowId( 'submit_request' ) || '', state: 'Published on Meta; canonical Submit Request flow' },
  { slug: 'request-amendment', label: 'Request Amendment', keyword: 'Request Amendment', messageLink: 'https://wa.me/message/HD5C4LAUYOOID1', flowId: canonicalFlowId( 'amend_request' ) || '', state: 'Published on Meta; canonical Request Amendment flow' },
  { slug: 'drop-docs', label: 'Drop Docs', keyword: 'Drop Docs', messageLink: 'https://wa.me/message/BCYW2SEPI5R4D1', flowId: canonicalFlowId( 'drop_docs' ) || '', state: 'Published on Meta; payment-gated Drop Docs flow' },
  { slug: 'vault', label: 'Vault', keyword: 'Vault', messageLink: 'https://wa.me/message/4J6E277ZRFHLK1', flowId: '', state: 'Secure file selection and delivery; no extra Flow' },
  // Request Pickup uses the dedicated pickup Meta short link. The canonical Flow is published,
  // payment-gated in FlowRegistry, and its completion path remains guarded until the published
  // payload is pickup-specific.
  { slug: 'request-pickup', label: 'Request Pickup', keyword: 'Request Pickup', messageLink: 'https://wa.me/message/NRWQFXOPGL7OO1', flowId: canonicalFlowId( 'request_pickup' ) || '', state: 'Published on Meta; payment-gated; completion wiring guarded' },
  { slug: 'shipments-track', label: 'Track', keyword: 'Shipment Track', messageLink: 'https://wa.me/message/WGN4NMFLFSJVB1', flowId: canonicalFlowId( 'shipments' ) || '', state: 'Published on Meta; canonical shipment tracking flow' },
  { slug: 'leave-review', label: 'Leave Review', keyword: 'Leave Review', messageLink: REVIEW_ENTRY_URL, flowId: REVIEW_FLOW_ID, state: 'Published on Meta; direct review Meta short link' },
  // This explicit WhatsApp keyword entry retains its dedicated Meta short link.
  // Public Subscribe bell/Header use an authenticated Orders invitation instead;
  // keep this link byte-equal to SUBSCRIBE_CTA_HREF for other chat entry integrations.
  { slug: 'subscribe', label: 'Subscribe', keyword: 'Subscribe', messageLink: 'https://wa.me/message/WUDPTMYSO6XII1', flowId: canonicalFlowId( 'subscribe' ) || '', state: 'Published on Meta; direct Subscribe Meta short link' },
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
