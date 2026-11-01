/**
 * Staff-only read-only view of authenticated website Subscribe / Leave Review / Referral sends
 * and their Flow replies. Uses the SAME canonical MessagesTable as Unified Inbox.
 *
 * Meta acceptance is stored as pending. Only signed delivery webhooks may advance
 * sent/delivered/read/failed. Completed F001/F002/F008 responses are the existing
 * FlowSubmission -> flow_response projection, never an inferred send success.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import * as api from '../../../api/client';
import FlowResponseDetails from '../../FlowResponseDetails';

const TEMPLATE_NAMES = new Set( [ 'service_details', 'wecare_leave_review', 'wecare_referal_update' ] );
const FLOW_CODES = new Set( [
  'WD-F001-SUBSCRIBE-PROFILE', 'WD-F002-LEAVE-REVIEW', 'WD-F008-REFERRAL', 'WD_IDEA', 'WD_REV',
] );

function kind ( message: api.Message ): 'send' | 'response' | null {
  if ( message.direction === 'OUTBOUND' && message.messageType === 'template'
    && TEMPLATE_NAMES.has( message.templateName || '' ) ) return 'send';
  if ( message.messageType === 'flow_response'
    && ( FLOW_CODES.has( message.flowCode || '' )
      || message.flowType === 'customer_idea' ) ) return 'response';
  return null;
}

function title ( message: api.Message ): string {
  if ( message.templateName === 'service_details'
    || message.flowCode === 'WD-F001-SUBSCRIBE-PROFILE' ) return 'Subscribe';
  if ( message.templateName === 'wecare_referal_update'
    || message.flowCode === 'WD-F008-REFERRAL'
    || message.flowType === 'referral' ) return 'Referral';
  if ( message.templateName === 'wecare_leave_review'
    || message.flowType === 'customer_idea'
    || message.flowCode === 'WD-F002-LEAVE-REVIEW'
    || message.flowCode === 'WD_IDEA'
    || message.flowCode === 'WD_REV' ) return 'Leave Review';
  return 'WhatsApp service';
}

export default function WhatsAppServiceLogs (): React.ReactElement {
  const [ messages, setMessages ] = useState<api.Message[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ error, setError ] = useState( '' );

  const reload = useCallback( async () => {
    setLoading( true );
    setError( '' );
    try {
      const { data, failures } = await api.collectApiFailures( () => Promise.all( [
        api.listMessages( undefined, 'WHATSAPP', 2000 ),
      ] ) );
      if ( failures.length ) {
        setError( 'WhatsApp logs could not be loaded. Try Refresh or open Inbox.' );
        return;
      }
      setMessages( ( data[ 0 ] || [] ).filter( message => kind( message ) !== null ) );
    } catch {
      setError( 'WhatsApp logs could not be loaded. Try Refresh or open Inbox.' );
    } finally {
      setLoading( false );
    }
  }, [] );

  useEffect( () => { void reload(); }, [ reload ] );

  const ordered = useMemo( () => [ ...messages ].sort( ( a, b ) =>
    new Date( b.timestamp ).getTime() - new Date( a.timestamp ).getTime() ), [ messages ] );
  const sends = ordered.filter( item => kind( item ) === 'send' ).length;
  const responses = ordered.filter( item => kind( item ) === 'response' ).length;

  return (
    <section className="sl-root" aria-label="WhatsApp service delivery and response logs">
      <div className="sl-head">
        <div>
          <h2>WhatsApp Logs</h2>
          <p>Subscribe, Leave Review and Referral sends, delivery updates and submitted Flow answers.</p>
        </div>
        <div className="sl-actions">
          <button type="button" onClick={ () => void reload() } disabled={ loading }>
            { loading ? 'Loading…' : 'Refresh' }
          </button>
          <Link href="/workspace/engage/inbox?channel=whatsapp">Open full Inbox</Link>
        </div>
      </div>
      <p className="sl-summary" aria-live="polite">
        { sends } template sends · { responses } Flow responses
      </p>
      { error && <p role="alert" className="sl-error">{ error }</p> }
      { !loading && !error && ordered.length === 0 && (
        <p role="status" className="sl-empty">
          No matching sends or responses in the latest 2,000 WhatsApp messages.
        </p>
      ) }
      { ordered.length > 0 && (
        <div className="sl-scroll" tabIndex={ 0 } aria-label="WhatsApp service log table">
          <table>
            <thead><tr>
              <th scope="col">Time</th>
              <th scope="col">Action</th>
              <th scope="col">Record</th>
              <th scope="col">Status</th>
              <th scope="col">Details</th>
            </tr></thead>
            <tbody>
              { ordered.map( message => {
                const isResponse = kind( message ) === 'response';
                return (
                  <tr key={ message.id || message.messageId }>
                    <td>{ new Date( message.timestamp ).toLocaleString() }</td>
                    <td>{ title( message ) }</td>
                    <td>{ isResponse ? 'Flow response' : 'Template send' }</td>
                    <td>{ isResponse ? 'Submitted' : ( message.status || 'pending' ) }</td>
                    <td>
                      { isResponse ? (
                        <details>
                          <summary>View answers</summary>
                          <FlowResponseDetails flowAnswers={ message.flowAnswers }
                            flowAttachments={ message.flowAttachments } />
                        </details>
                      ) : (
                        <details>
                          <summary>Message details</summary>
                          <p>Template: { message.templateName }</p>
                          <p>Provider message ID: <code>{ message.whatsappMessageId || 'Not available' }</code></p>
                          { message.errorCode && <p>Delivery error code: { message.errorCode }</p> }
                        </details>
                      ) }
                    </td>
                  </tr>
                );
              } ) }
            </tbody>
          </table>
        </div>
      ) }
      <p className="sl-foot">
        Pending means accepted by Meta, not delivered. Delivery statuses come from the WhatsApp
        webhook; completed answers come from signed Flow replies. Send attempts and failures
        are separately recorded in Audit Logs. This view covers the most recent 2,000
        WhatsApp messages; use Inbox for the full conversation.
      </p>
      <style jsx>{`
        .sl-root{min-width:0;color:var(--text)}
        .sl-head{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;flex-wrap:wrap}
        .sl-head h2{font:800 24px/1.2 var(--font-sans);margin:0 0 8px}
        .sl-head p,.sl-foot{color:var(--text-muted);line-height:1.5;margin:0}
        .sl-actions{display:flex;flex-wrap:wrap;align-items:center;gap:12px}
        .sl-actions button,.sl-actions a{font:700 14px/1.3 var(--font-sans);padding:10px 14px;
          border-radius:9px;border:1px solid var(--border);color:var(--accent);background:var(--surface);
          text-decoration:none;cursor:pointer}
        .sl-actions button:disabled{opacity:.6;cursor:wait}
        .sl-actions :is(button,a):focus-visible{outline:2px solid var(--accent);outline-offset:2px}
        .sl-summary{font-weight:700;margin:22px 0 12px}
        .sl-empty,.sl-error{padding:14px 0;line-height:1.5}
        .sl-scroll{width:100%;overflow-x:auto;border:1px solid var(--border);border-radius:12px}
        .sl-scroll:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
        table{width:100%;border-collapse:collapse;min-width:680px;font-size:14px}
        th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid var(--border)}
        th{font-weight:800;color:var(--accent);background:var(--surface)}
        td code{overflow-wrap:anywhere}
        details{max-width:520px}
        summary{cursor:pointer;text-decoration:underline;text-underline-offset:2px;font-weight:600}
        details p{overflow-wrap:anywhere}
        .sl-foot{margin:18px 0 0;font-size:13px}
        @media(max-width:767px){.sl-head h2{font-size:21px}}
      `}</style>
    </section>
  );
}
