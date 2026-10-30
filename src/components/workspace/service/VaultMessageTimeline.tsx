/**
 * Read-only message and hand-off ledger. Never infer handset delivery from Meta
 * acceptance or from a paid entitlement. Only authenticated, file-scoped audit fields
 * supplied by SecureFiles API may appear here. The five templates are NOT five automatic
 * sends: customer tap and verified capture are required between stages.
 */
import React from 'react';
import type { SecureFile } from '../../../api/client';
import type { VaultRegistryJourney } from './VaultJourneyPreview';
import styles from './VaultMessageTimeline.module.css';

export interface VaultMessageStep {
  index: number;
  title: string;
  template: string;
  gap: string;
  event: string;
  state: 'accepted' | 'unknown' | 'failed' | 'waiting';
  stateLabel: string;
  delivery: string;
  at: string;
  detail: string;
}

const TITLE = [ 'Unlock Vault offer', 'Review & Pay', 'Order updates ×2', 'Paid invoice', 'Access Vault' ];
const FALLBACK = [
  'wecare_vault_request_ready',
  'wecare_whatapp_native_pay_template',
  'wecare_order_status_v3',
  'wecare_default_invoice_image_template',
  'wecare_default_download',
];

function timeLabel ( value?: string | number ): string {
  if ( value === undefined || value === null || value === '' ) return 'No verified time recorded';
  const asNumber = typeof value === 'number' ? value : Number( value );
  const d = Number.isFinite( asNumber ) && String( value ).trim() !== ''
    ? new Date( asNumber * ( asNumber < 10_000_000_000 ? 1000 : 1 ) )
    : new Date( value );
  if ( Number.isNaN( d.getTime() ) ) return 'Time unavailable';
  return d.toLocaleString( 'en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: true,
  } ) + ' IST';
}

function outcomeState ( outcome: string, success: string ): VaultMessageStep['state'] {
  if ( outcome === success ) return 'accepted';
  if ( /UNCONFIRMED|UNKNOWN|RECENT|PENDING|SENDING/.test( outcome ) ) return 'unknown';
  if ( outcome ) return 'failed';
  return 'waiting';
}

function stateText ( state: VaultMessageStep['state'] ): string {
  if ( state === 'accepted' ) return 'Meta accepted';
  if ( state === 'unknown' ) return 'Needs reconciliation';
  if ( state === 'failed' ) return 'Not confirmed sent';
  return 'Awaiting trigger';
}

export function vaultMessageSteps (
  file: SecureFile | null,
  journey: VaultRegistryJourney | null,
): VaultMessageStep[] {
  const paid = file?.vaultPaymentStatus === 'PAID'
    || file?.accessState === 'READY' || file?.accessState === 'OPEN'
    || file?.accessState === 'EXPIRED';
  const offer = String( file?.lastOfferOutcome || '' );
  const payment = String( file?.lastPaymentRequestOutcome || '' );
  const access = String( file?.lastAccessSendOutcome || '' );
  const offerState = outcomeState( offer, 'VAULT_OFFER_SENT' );
  const payState = outcomeState( payment, 'PAYMENT_REQUEST_SENT' );
  const accessState = outcomeState( access, 'VAULT_LINK_SENT' );
  const stage = ( i: number, gapDefault: string ) => {
    const record = journey?.steps[ i ];
    return {
      template: record?.templateName || FALLBACK[ i ],
      gap: record?.defaultDelaySeconds !== undefined
        ? ( record.defaultDelaySeconds > 0 ? record.defaultDelaySeconds + 's spacing' : 'Trigger-based' )
        : gapDefault,
    };
  };
  return [
    {
      index: 1, title: TITLE[ 0 ], ...stage( 0, 'Staff-triggered' ),
      event: 'Staff explicitly confirms send',
      state: offerState, stateLabel: stateText( offerState ),
      delivery: 'Handset delivery/read not independently linked',
      at: timeLabel( file?.lastOfferRequestedAt ),
      detail: offer
        ? 'Last result: ' + offer + ( file?.lastOfferRequestedBy ? ' · by ' + file.lastOfferRequestedBy : '' )
        : 'No staff offer attempt in this file audit. Uploaded documents do not send messages.',
    },
    {
      index: 2, title: TITLE[ 1 ], ...stage( 1, 'Customer-triggered' ),
      event: 'Only after customer taps Unlock Vault',
      state: paid ? 'accepted' : payState,
      stateLabel: paid ? 'Payment captured' : payState === 'waiting' ? 'Customer action required' : stateText( payState ),
      delivery: 'Native payment message delivery not linked to this file audit',
      at: timeLabel( file?.lastPaymentRequestedAt ),
      detail: paid ? 'Payment evidence recorded; this does not prove WhatsApp delivery'
        : payment ? 'Staff request outcome: ' + payment : 'Customer-triggered checkout is not a scheduled blast',
    },
    {
      index: 3, title: TITLE[ 2 ], ...stage( 2, 'After verified capture' ),
      event: 'Processing → completed (two separate messages)',
      state: 'waiting', stateLabel: paid ? 'Delivery status not linked' : 'Waiting for captured payment',
      delivery: 'No per-update sent/delivered/read evidence in this file view',
      at: 'No stage-specific timestamp recorded',
      detail: 'Order status is advanced only after provider acceptance of the prior transition. Full evidence lives in the order and invoice audit.',
    },
    {
      index: 4, title: TITLE[ 3 ], ...stage( 3, 'After order update' ),
      event: 'Verified paid invoice image',
      state: 'waiting', stateLabel: paid ? 'Invoice delivery not linked' : 'Waiting for paid invoice',
      delivery: 'Invoice WhatsApp status is not a property of the Vault file',
      at: 'No stage-specific timestamp recorded',
      detail: 'A paid entitlement does not prove that an invoice message reached the handset.',
    },
    {
      index: 5, title: TITLE[ 4 ], ...stage( 4, 'After invoice acceptance' ),
      event: 'Paid entitlement + invoice required',
      state: accessState, stateLabel: access ? stateText( accessState ) : paid ? 'Paid access available' : 'Waiting for paid access',
      delivery: 'Handset delivery/read not independently linked',
      at: timeLabel( file?.lastAccessSentAt ),
      detail: access ? 'Last staff resend: ' + access + ( file?.lastAccessSentBy ? ' · by ' + file.lastAccessSentBy : '' )
        : paid ? 'Paid access exists; automatic Access Vault message has no staff-resend audit timestamp here'
          : 'No authorized Access Vault send yet',
    },
  ];
}

export default function VaultMessageTimeline ( {
  file, journey, compact = false,
}: { file: SecureFile | null; journey: VaultRegistryJourney | null; compact?: boolean } ) {
  const steps = vaultMessageSteps( file, journey );
  return (
    <section className={ styles.ledger } aria-label="Five-stage Vault message status and timing">
      <div className={ styles.legend }>
        <strong>Message order &amp; delivery log</strong>
        <small>IST · Stored attempts only</small>
      </div>
      <ol className={ styles.timeline }>
        { steps.map( stage => (
          <li className={ styles.step } key={ stage.index }>
            <span className={ styles.bubble } aria-hidden="true">{ stage.index }</span>
            <div className={ styles.main }>
              <div className={ styles.head }>
                <strong>{ stage.title }</strong>
                <span className={ styles.gap }>{ stage.gap }</span>
              </div>
              <div className={ styles.details }>
                <span className={ styles.status + ' ' + styles[ stage.state ] }>{ stage.stateLabel }</span>
                <time className={ styles.time }>{ stage.at }</time>
              </div>
              { !compact && (
                <>
                  <p className={ styles.trigger }>{ stage.event }</p>
                  <p className={ styles.note }>{ stage.detail }</p>
                  <p className={ styles.delivery }>{ stage.delivery }</p>
                  <code className={ styles.template }>{ stage.template }</code>
                </>
              ) }
            </div>
          </li>
        ) ) }
      </ol>
      <p className={ styles.disclaimer }>
        Timing separates send attempts; it does not guarantee device delivery order.
        “Meta accepted” does not mean delivered or read. Unknown sends must be reconciled,
        never automatically retried.
      </p>
    </section>
  );
}
