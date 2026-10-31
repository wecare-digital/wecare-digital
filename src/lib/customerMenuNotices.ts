/**
 * One short toast vocabulary for authenticated WhatsApp invitations on /orders.
 *
 * Only Subscribe and Leave Review currently trigger an actual send. Other order
 * menu entries must not display "Sent to WhatsApp." without a confirmed API
 * acknowledgment. Keep this separate from Workspace ToastContext.
 *
 * "Sent to WhatsApp." means Meta accepted the send request, not that delivery
 * or Flow completion is confirmed. Never automatically retry an ambiguous send.
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
