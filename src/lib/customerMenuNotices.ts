/**
 * One short notification vocabulary for customer-initiated WhatsApp sends on Orders.
 *
 * Only actual provider send attempts may display these messages. At present, only
 * Subscribe and Leave Review initiate a WhatsApp template from the public Orders
 * page. Other menu items navigate to /orders/ and must never imply a send.
 *
 * 'accepted' means the WhatsApp sender accepted the request. It does not prove
 * handset delivery, a completed Flow, or submitted customer feedback.
 * An ambiguous failure is never automatically retried.
 */
export type CustomerMenuNoticeStatus = 'pending' | 'accepted' | 'failed';

export type CustomerMenuNotice = Readonly<{
  message: string;
  error: boolean;
}>;

const NOTICES: Readonly<Record<CustomerMenuNoticeStatus, CustomerMenuNotice>> = {
  pending: {
    message: 'Processing…',
    error: false,
  },
  accepted: {
    message: 'Sent to WhatsApp.',
    error: false,
  },
  failed: {
    message: "Couldn't confirm. Check WhatsApp.",
    error: true,
  },
};

export function customerMenuNotice ( status: CustomerMenuNoticeStatus ): CustomerMenuNotice {
  return NOTICES[ status ];
}
