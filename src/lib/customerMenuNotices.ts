/**
 * One short toast vocabulary for authenticated WhatsApp invitations on /orders.
 *
 * Subscribe, Leave Review and Referral send WhatsApp invitations. Contribute can initiate
 * an authenticated native ORDER_DETAILS/Review & Pay request, but only its
 * exact verified PAYMENT_REQUEST_SENT outcome counts as accepted. 409 release
 * refusals and uncertain results always use the generic inline failure copy.
 * Never claim that a message was sent or delivered without server acceptance.
 * Keep this separate from Workspace ToastContext.
 *
 * "Sent to WhatsApp." means Meta accepted the send request, not that delivery
 * or Flow completion is confirmed. Never automatically retry an ambiguous send.
 */
import { publicActionText } from './publicActionNotices';

export type CustomerMenuNoticeStatus = 'pending' | 'accepted' | 'blocked' | 'failed';

export type CustomerMenuNotice = Readonly<{
  message: string;
  error: boolean;
}>;

const NOTICES: Readonly<Record<CustomerMenuNoticeStatus, CustomerMenuNotice>> = {
  pending: {
    message: publicActionText( 'processing' ),
    error: false,
  },
  accepted: {
    message: publicActionText( 'whatsappAccepted' ),
    error: false,
  },
  blocked: {
    message: publicActionText( 'whatsappFailed' ),
    error: true,
  },
  failed: {
    message: publicActionText( 'whatsappFailed' ),
    error: true,
  },
};

export function customerMenuNotice ( status: CustomerMenuNoticeStatus ): CustomerMenuNotice {
  return NOTICES[ status ];
}
