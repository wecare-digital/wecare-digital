/**
 * Reversible inbox presentation filter, not a message erasure or payment classifier.
 *
 * A staff-requested "Today + retained" view can hide older non-retained messages
 * without mutating MessagesTable, WhatsApp history, receipts or S3 media.
 * FINANCIAL matches are intentionally broad: false positives merely keep more
 * history visible. Uncertain records are ALWAYS accessible via "Show all".
 */
export interface CleanInboxMessage {
  contactId?: string;
  senderPhone?: string;
  receivingPhone?: string;
  timestamp?: string | number;
  content?: string;
  transcription?: string;
  messageType?: string;
  paymentReferenceId?: string;
  paymentOrderId?: string;
  paymentDueRef?: string;
  paymentId?: string;
  invoiceId?: string;
  orderId?: string;
  paymentPurpose?: string;
}

const FINANCIAL_FIELDS: ( keyof CleanInboxMessage )[] = [
  'paymentReferenceId', 'paymentOrderId', 'paymentDueRef',
  'paymentId', 'invoiceId', 'orderId', 'paymentPurpose',
];

const FINANCIAL_WORDS = /razorpay|payment|paid|refund|receipt|invoice|transaction|upi|chargeback|dispute|pay now|payment link|order id|₹|\binr\b/i;

export function inboxConversationKey ( m: CleanInboxMessage ): string {
  return m.contactId || m.senderPhone || m.receivingPhone || 'unknown';
}

export function mayContainPaymentEvidence ( m: CleanInboxMessage ): boolean {
  if ( FINANCIAL_FIELDS.some( field => Boolean( m[ field ] ) ) ) return true;
  return FINANCIAL_WORDS.test( [
    m.content || '', m.transcription || '', m.messageType || '',
  ].join( ' ' ) );
}

export function filterInboxCleanView<T extends CleanInboxMessage> (
  messages: readonly T[],
  todayStartMs: number,
  retainedConversationIds: ReadonlySet<string>,
): T[] {
  // Preserve complete context for flagged financial conversations, rather than
  // hiding some of their older messages behind a date boundary.
  const financialConversations = new Set(
    messages.filter( mayContainPaymentEvidence ).map( inboxConversationKey )
  );
  return messages.filter( m => {
    const key = inboxConversationKey( m );
    if ( key === 'unknown' || retainedConversationIds.has( key )
      || financialConversations.has( key ) ) return true;
    const timestamp = new Date( m.timestamp ?? '' ).getTime();
    return !Number.isFinite( timestamp ) || timestamp >= todayStartMs;
  } );
}
