/**
 * Customer-initiated WhatsApp menu notices shown on /orders.
 *
 * Keep this separate from the authenticated Workspace ToastContext: /orders is a
 * public/customer route with a local, accessible inline notice rail.
 *
 * "accepted" means Meta accepted the invitation for delivery, NOT that the
 * customer received it or completed the Flow. An ambiguous failure must never
 * trigger an automatic retry; the customer may already have received it.
 */
import type { CustomerMenuAction } from './customerMenuActions';

export type CustomerMenuNoticeStatus = 'pending' | 'accepted' | 'failed';

export type CustomerMenuNotice = Readonly<{
  message: string;
  error: boolean;
}>;

const NOTICES: Readonly<Record<CustomerMenuAction,
  Readonly<Record<CustomerMenuNoticeStatus, CustomerMenuNotice>>>> = {
  subscribe: {
    pending: {
      message: 'Requesting your profile update invitation on WhatsApp…',
      error: false,
    },
    accepted: {
      message: 'WhatsApp accepted your profile update invitation. Delivery is not yet confirmed.',
      error: false,
    },
    failed: {
      message: 'We could not confirm the profile update invitation. Check WhatsApp before trying again.',
      error: true,
    },
  },
  'leave-review': {
    pending: {
      message: 'Requesting your Leave Review invitation on WhatsApp…',
      error: false,
    },
    accepted: {
      message: 'WhatsApp accepted your Leave Review invitation. Delivery is not yet confirmed.',
      error: false,
    },
    failed: {
      message: 'We could not confirm the Leave Review invitation. Check WhatsApp before trying again.',
      error: true,
    },
  },
};

export function customerMenuNotice (
  action: CustomerMenuAction, status: CustomerMenuNoticeStatus,
): CustomerMenuNotice {
  return NOTICES[ action ][ status ];
}
