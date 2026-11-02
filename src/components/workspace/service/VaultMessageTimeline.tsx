/**
 * Read-only message and hand-off ledger. Never infer handset delivery from Meta
 * acceptance or from a paid entitlement. Only authenticated, file-scoped audit fields
 * supplied by SecureFiles API may appear here. The current four stages are
 * trigger-gated; historical offers remain in the backend audit but are not sent.
 */
import React from 'react';
import * as api from '../../../api/client';
import type { SecureFile, VaultMessageDeliveryLog, VaultMessageDeliveryEvidence } from '../../../api/client';
import type { VaultRegistryJourney } from './VaultJourneyPreview';
import styles from './VaultMessageTimeline.module.css';

export interface VaultMessageStep {
  index: number;
  title: string;
  template: string;
  templateId?: string;
  gap: string;
  event: string;
  state: 'accepted' | 'unknown' | 'failed' | 'waiting';
  stateLabel: string;
  delivery: string;
  at: string;
  detail: string;
  subEvents?: { label: string; status: string; timestamp: string }[];
}

const TITLE = [ 'Review & Pay', 'Order updates ×2', 'Paid invoice', 'Access Vault' ];
const FALLBACK = [
  'wecare_whatapp_native_pay_template',
  'wecare_order_status_v3',
  'wecare_default_invoice_image_template',
  'wecare_default_download',
];

function timeLabel ( value?: string | number | null ): string {
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

function providerStatus ( result: VaultMessageDeliveryEvidence | undefined ):
  { state: VaultMessageStep['state']; label: string; delivery: string } | null {
  if ( !result || result.status === 'NOT_TRACKED' ) return null;
  const at = result.observedAt ? timeLabel( result.observedAt ) : 'time unavailable';
  switch ( result.status ) {
    case 'READ': return { state: 'accepted', label: 'Read', delivery: 'Read receipt recorded · ' + at };
    case 'DELIVERED': return { state: 'accepted', label: 'Delivered', delivery: 'Delivered webhook recorded · ' + at };
    case 'SENT': return { state: 'accepted', label: 'Sent', delivery: 'Sent webhook recorded · ' + at };
    case 'ACCEPTED': return {
      state: 'accepted', label: 'Meta accepted',
      delivery: ( result.source === 'SEND_LOG' ? 'Provider acceptance in send log · ' : 'Meta acceptance recorded · ' )
        + at + ' · handset not verified',
    };
    case 'FAILED': return {
      state: 'failed',
      label: result.source === 'SEND_LOG' ? 'Send refused' : 'Delivery failed',
      delivery: ( result.source === 'SEND_LOG' ? 'Sender refusal recorded · ' : 'Failure webhook recorded · ' ) + at,
    };
    case 'UNAVAILABLE': return { state: 'unknown', label: 'Status unavailable', delivery: 'Provider status lookup unavailable; do not retry automatically' };
    default: return { state: 'unknown', label: 'Needs reconciliation', delivery: 'Provider status has not been confirmed' };
  }
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
  log?: VaultMessageDeliveryLog | null,
): VaultMessageStep[] {
  const paid = file?.vaultPaymentStatus === 'PAID'
    || file?.accessState === 'READY' || file?.accessState === 'OPEN'
    || file?.accessState === 'EXPIRED';
  const payment = String( file?.lastPaymentRequestOutcome || '' );
  const access = String( file?.lastAccessSendOutcome || '' );
  const nativePayProof = providerStatus( log?.evidence.nativePay );
  const processingProof = providerStatus( log?.evidence.processing );
  const completedProof = providerStatus( log?.evidence.completed );
  const invoiceProof = providerStatus( log?.evidence.invoice );
  // Automatic paid delivery and staff-requested resends are different sends.
  // Display both independently; neither status proves the other was delivered.
  const automaticAccessProof = providerStatus( log?.evidence.autoAccess );
  const accessProof = providerStatus( log?.evidence.access );
  const accessEvents = [
    { label: 'Automatic access', data: log?.evidence.autoAccess, proof: automaticAccessProof },
    { label: 'Staff resend', data: log?.evidence.access, proof: accessProof },
  ].map( entry => ({
    label: entry.label,
    status: entry.proof?.label || 'Not verified',
    timestamp: timeLabel( entry.data?.observedAt || undefined ),
  }) );
  const orderEvents = [
    { label: 'Processing', data: log?.evidence.processing, proof: processingProof },
    { label: 'Completed', data: log?.evidence.completed, proof: completedProof },
  ].map( entry => ({
    label: entry.label,
    status: entry.proof?.label || 'Not verified',
    timestamp: timeLabel( entry.data?.observedAt || undefined ),
  }) );
  const payState = outcomeState( payment, 'PAYMENT_REQUEST_SENT' );
  const accessState = automaticAccessProof?.state || accessProof?.state || outcomeState( access, 'VAULT_LINK_SENT' );
  const stage = ( i: number ) => {
    const roles = [ 'native_payment', 'order_status', 'receipt', 'access' ];
    const record = journey?.steps.find( step => step.role === roles[ i ] );
    // Historical journey metadata may still mention removed status delays.
    // Only the access link has a configurable wait in the sending runtime.
    const gaps = [
      'Customer-approved · no timer',
      '1s Processing → Completed · Vault only',
      'No added wait · paid capture required',
      'Access delay · Pay & Flow settings',
    ];
    return {
      template: record?.templateName || FALLBACK[ i ],
      templateId: record?.templateId || '',
      gap: gaps[ i ],
    };
  };
  return [
    {
      index: 1, title: TITLE[ 0 ], ...stage( 0 ),
      event: 'Staff or customer requests a native Review & Pay; customer approves the payment',
      state: nativePayProof?.state || ( paid ? 'accepted' : payState ),
      stateLabel: nativePayProof?.label || ( paid ? 'Payment captured · WA unverified' : payState === 'waiting' ? 'Ready for customer payment' : stateText( payState ) ),
      delivery: nativePayProof?.delivery || 'Native payment message delivery not linked to this file audit',
      at: timeLabel( log?.evidence.nativePay?.observedAt || file?.lastPaymentRequestedAt ),
      detail: paid ? 'Payment evidence recorded; this does not itself prove WhatsApp delivery'
        : payment ? 'Staff request outcome: ' + payment : 'No automatic charge; the customer must approve this exact-file request',
    },
    {
      index: 2, title: TITLE[ 1 ], ...stage( 1 ),
      event: 'Processing → completed (two separate messages)',
      state: completedProof?.state || processingProof?.state || 'waiting',
      stateLabel: completedProof ? 'Completed · ' + completedProof.label
        : processingProof ? 'Processing · ' + processingProof.label
          : paid ? 'Order updates not verified' : 'Waiting for captured payment',
      delivery: completedProof?.delivery || processingProof?.delivery || 'No verified order-update webhook linked to this paid file',
      at: timeLabel( log?.evidence.completed?.observedAt || log?.evidence.processing?.observedAt ),
      detail: 'Payment captured → Processing; fixed 1s after accepted Processing → Completed for Vault only, and 0s before the paid invoice. Both sends have different provider message IDs.',
      subEvents: orderEvents,
    },
    {
      index: 3, title: TITLE[ 2 ], ...stage( 2 ),
      event: 'Verified paid invoice image',
      state: invoiceProof?.state || 'waiting',
      stateLabel: invoiceProof?.label || ( paid ? 'Invoice delivery not verified' : 'Waiting for paid invoice' ),
      delivery: invoiceProof?.delivery || 'No confirmed invoice send status linked to this paid file',
      at: timeLabel( log?.evidence.invoice?.observedAt ),
      detail: 'The invoice image is sent after payment confirmation. A paid entitlement alone never proves handset receipt.',
    },
    {
      index: 4, title: TITLE[ 3 ], ...stage( 3 ),
      event: 'Paid entitlement + invoice required',
      state: accessState,
      stateLabel: automaticAccessProof
        ? 'Auto access · ' + automaticAccessProof.label
        : accessProof ? 'Staff resend · ' + accessProof.label
          : access ? stateText( accessState ) : paid ? 'Paid access · delivery unverified' : 'Waiting for paid access',
      delivery: automaticAccessProof?.delivery || accessProof?.delivery || 'Handset delivery/read not independently linked',
      at: timeLabel( log?.evidence.autoAccess?.observedAt || file?.lastAccessSentAt ),
      detail: access ? 'Last staff resend: ' + access + ( file?.lastAccessSentBy ? ' · by ' + file.lastAccessSentBy : '' )
        : paid ? 'Paid entitlement exists; automatic and manual send events are tracked separately'
          : 'No authorized Access Vault send yet',
      subEvents: accessEvents,
    },
  ];
}

export default function VaultMessageTimeline ( {
  file, journey, compact = false,
}: { file: SecureFile | null; journey: VaultRegistryJourney | null; compact?: boolean } ) {
  const [ log, setLog ] = React.useState<VaultMessageDeliveryLog | null>( null );
  const [ loading, setLoading ] = React.useState( false );
  const [ logError, setLogError ] = React.useState( '' );
  const refresh = React.useCallback( async () => {
    if ( !file?.fileId ) return;
    setLoading( true );
    const result = await api.readVaultMessageDeliveryLog( file.fileId );
    if ( result.ok ) {
      setLog( result.data );
      setLogError( '' );
    } else {
      setLog( null );
      setLogError( 'Delivery evidence unavailable. No status has been inferred.' );
    }
    setLoading( false );
  }, [ file ] );
  React.useEffect( () => {
    // Load on selecting one file; staff can refresh to see webhook updates.
    let active = true;
    if ( file?.fileId ) void api.readVaultMessageDeliveryLog( file.fileId ).then( result => {
      if ( active ) {
        setLog( result.ok ? result.data : null );
        setLogError( result.ok ? '' : 'Delivery evidence unavailable.' );
      }
    } );
    return () => { active = false; };
  }, [ file?.fileId ] );
  const scopedLog = log?.fileId === file?.fileId ? log : null;
  const steps = vaultMessageSteps( file, journey, scopedLog );
  return (
    <section className={ styles.ledger } aria-label="Four-stage Vault payment and access status">
      <div className={ styles.legend }>
        <strong>Message order &amp; delivery log</strong>
        <span className={ styles.refreshGroup }>
          <small>IST · Recorded evidence only</small>
          { file?.fileId && <button type="button" className={ styles.refresh }
            disabled={ loading } onClick={ () => { void refresh(); } }>
            { loading ? 'Checking…' : 'Refresh status' }
          </button> }
        </span>
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
                  { stage.subEvents && <div className={ styles.subEvents } aria-label="Order update individual message statuses">
                    { stage.subEvents.map( event => <div key={ event.label }>
                      <strong>{ event.label }</strong>
                      <span>{ event.status }</span>
                      <time>{ event.timestamp }</time>
                    </div> ) }
                  </div> }
                  <p className={ styles.note }>{ stage.detail }</p>
                  <p className={ styles.delivery }>{ stage.delivery }</p>
                  <code className={ styles.template }>{ stage.template }{ stage.templateId ? ' · Meta ID ' + stage.templateId : '' }</code>
                </>
              ) }
            </div>
          </li>
        ) ) }
      </ol>
      { logError && <p className={ styles.disclaimer } role="status">{ logError }</p> }
      <p className={ styles.disclaimer }>
        Timing separates send attempts; it does not guarantee device delivery order.
        “Meta accepted” does not mean delivered or read. Unknown sends must be reconciled,
        never automatically retried.
      </p>
    </section>
  );
}
