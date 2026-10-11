/**
 * One status/payment badge for the whole Service Operations surface.
 *
 * WHY THIS EXISTS. The Phase 1 audit found ~9 hand-rolled badge implementations across the
 * workspace (service/track, service/amend, engage/orders, reviews, documents, flow-responses,
 * flow-hub, forms/responses, secure-files, contact-360) — each with its own colour map and its
 * own spelling of the same statuses. This is the single component they fold into. The payment
 * vocabulary mirrors the server ladder in amplify/functions/shared/lambda_utils/payment_status.py
 * (pending < authorized < failed < captured < refunded) plus the richer display states the
 * product brief distinguishes (verified-paid, blocked, reconciliation-required, etc.).
 */
import React from 'react';

export type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'muted';

const TONE: Record<BadgeTone, { bg: string; fg: string; border: string }> = {
  neutral: { bg: '#f1f5f9', fg: '#334155', border: '#e2e8f0' },
  info:    { bg: '#eff6ff', fg: '#1e40af', border: '#bfdbfe' },
  success: { bg: '#ecfdf5', fg: '#065f46', border: '#a7f3d0' },
  warning: { bg: '#fffbeb', fg: '#92400e', border: '#fde68a' },
  danger:  { bg: '#fef2f2', fg: '#991b1b', border: '#fecaca' },
  muted:   { bg: '#f8fafc', fg: '#64748b', border: '#e2e8f0' },
};

/** Normalise an arbitrary server string to a comparison key. */
const key = ( s: string ): string => ( s || '' ).trim().toLowerCase().replace( /[\s-]+/g, '_' );

/** Payment status -> tone + human label. Covers the server ladder and the display-only states. */
const PAYMENT: Record<string, { tone: BadgeTone; label: string }> = {
  prepared:                 { tone: 'neutral', label: 'Prepared' },
  pending:                  { tone: 'warning', label: 'Pending' },
  payment_request_sent:     { tone: 'info',    label: 'Request sent' },
  sent:                     { tone: 'info',    label: 'Request sent' },
  authorized:               { tone: 'info',    label: 'Authorized' },
  provider_captured:        { tone: 'info',    label: 'Provider captured' },
  captured:                 { tone: 'success', label: 'Captured' },
  verified_paid:            { tone: 'success', label: 'Verified paid' },
  paid:                     { tone: 'success', label: 'Paid' },
  paid_but_blocked:         { tone: 'warning', label: 'Paid · blocked' },
  blocked:                  { tone: 'warning', label: 'Blocked' },
  failed:                   { tone: 'danger',  label: 'Failed' },
  expired:                  { tone: 'muted',   label: 'Expired' },
  refunded:                 { tone: 'muted',   label: 'Refunded' },
  reconciliation_required:  { tone: 'danger',  label: 'Reconcile' },
};

/** Request/record status -> tone + label. */
const STATUS: Record<string, { tone: BadgeTone; label: string }> = {
  new:          { tone: 'info',    label: 'New' },
  open:         { tone: 'info',    label: 'Open' },
  pending:      { tone: 'warning', label: 'Pending' },
  in_progress:  { tone: 'info',    label: 'In progress' },
  processing:   { tone: 'info',    label: 'Processing' },
  active:       { tone: 'info',    label: 'Active' },
  assigned:     { tone: 'info',    label: 'Assigned' },
  resolved:     { tone: 'success', label: 'Resolved' },
  completed:    { tone: 'success', label: 'Completed' },
  approved:     { tone: 'success', label: 'Approved' },
  closed:       { tone: 'muted',   label: 'Closed' },
  rejected:     { tone: 'danger',  label: 'Rejected' },
  cancelled:    { tone: 'muted',   label: 'Cancelled' },
  expired:      { tone: 'muted',   label: 'Expired' },
  failed:       { tone: 'danger',  label: 'Failed' },
  hidden:       { tone: 'muted',   label: 'Hidden' },
  flagged:      { tone: 'warning', label: 'Flagged' },
};

export interface StatusBadgeProps {
  /** The raw status string from the server. */
  value: string;
  /** Which vocabulary to read. 'payment' uses the money ladder; 'status' the request ladder. */
  kind?: 'status' | 'payment';
  /** Optional explicit label override. */
  label?: string;
  title?: string;
}

const StatusBadge: React.FC<StatusBadgeProps> = ( { value, kind = 'status', label, title } ) => {
  const table = kind === 'payment' ? PAYMENT : STATUS;
  const match = table[key( value )];
  const tone = match?.tone ?? 'neutral';
  // Unknown status is shown verbatim (title-cased) rather than hidden — an unrecognised state
  // the staff can still read beats a silent blank.
  const text = label ?? match?.label ?? ( value ? value.replace( /[_-]+/g, ' ' ).replace( /\b\w/g, c => c.toUpperCase() ) : '—' );
  const c = TONE[tone];
  return (
    <span
      title={title ?? value}
      style={{
        display: 'inline-block', padding: '2px 10px', borderRadius: 999,
        fontSize: 11, fontWeight: 600, lineHeight: 1.6, whiteSpace: 'nowrap',
        background: c.bg, color: c.fg, border: `1px solid ${c.border}`,
      }}
    >
      {text}
    </span>
  );
};

/** Convenience wrapper for the money ladder. */
export const PaymentBadge: React.FC<Omit<StatusBadgeProps, 'kind'>> = ( props ) => (
  <StatusBadge {...props} kind="payment" />
);

export default StatusBadge;
