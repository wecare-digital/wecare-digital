/** Public entry links open chat with a keyword; backend verifies identity before returning data. */
import { REVIEW_ENTRY_URL } from '../lib/reviewEntry';
export const WHATSAPP_SERVICE_ENTRIES = [
  { slug: 'orders', label: 'Orders', keyword: 'Orders', messageLink: 'https://wa.me/message/2OQZCYBSMU4SE1', flowId: '2167802357142172', state: 'Design draft retained as canonical Flow' },
  { slug: 'submit-request', label: 'Submit Request', keyword: 'Submit Request', messageLink: 'https://wa.me/message/5DRZXKBJTZDQG1', flowId: '1728231914933139', state: 'Design draft retained as canonical Flow' },
  { slug: 'request-amendment', label: 'Request Amendment', keyword: 'Request Amendment', messageLink: 'https://wa.me/message/HD5C4LAUYOOID1', flowId: '959792226650003', state: 'Design draft retained as canonical Flow' },
  { slug: 'drop-docs', label: 'Drop Docs', keyword: 'Drop Docs', messageLink: 'https://wa.me/message/BCYW2SEPI5R4D1', flowId: '1605008471323578', state: 'Design draft retained as canonical Flow' },
  { slug: 'vault', label: 'Vault', keyword: 'Vault', messageLink: 'https://wa.me/message/4J6E277ZRFHLK1', flowId: '1735480734227899', state: 'Design draft retained as canonical Flow' },
  { slug: 'shipments', label: 'Shipments', keyword: 'Shipments', messageLink: 'https://wa.me/message/WGN4NMFLFSJVB1', flowId: '849713848195607', state: 'Design draft retained as canonical Flow' },
  { slug: 'leave-review', label: 'Leave Review', keyword: 'Leave Review', messageLink: REVIEW_ENTRY_URL, flowId: '2352304845587149', state: 'Design draft retained as canonical Flow' },
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
