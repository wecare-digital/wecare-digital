/**
 * One short toast vocabulary for authenticated WhatsApp invitations on /orders.
 *
 * Only Subscribe and Leave Review currently send actual WhatsApp messages.
 * Contribute uses the same authenticated handoff but remains blocked until
 * its template is configured. Reuse the generic failure copy without ever
 * claiming that a message was sent or delivered.
 * Keep this separate from Workspace ToastContext.
 *
 * "Sent to WhatsApp." means Meta accepted the send request, not that delivery
 * or Flow completion is confirmed. Never automatically retry an ambiguous send.
 */
export type CustomerMenuNoticeStatus = 'pending' | 'accepted' | 'awaiting-template' | 'failed';

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
  'awaiting-template': {
    message: "Couldn't confirm. Check WhatsApp.",
    error: true,
  }
  failed: {
    message: "Couldn't confirm. Check WhatsApp.",
    error: true,
  },
};

export function customerMenuNotice ( status: CustomerMenuNoticeStatus ): CustomerMenuNotice {
  return NOTICES[ status ];
}
