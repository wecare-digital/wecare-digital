import React, { useEffect, useState } from 'react';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';

/**
 * Consent-as-EVIDENCE for one customer. Replaces the boolean/percentage anti-pattern.
 *
 * This surface reads the append-only consent ledger and shows, per channel, the current state
 * (including OPTED_OUT as first-class) WITH its history depth and the evidence behind the latest
 * record — who said so, when, through which source, for what purpose, with what reference. Staff
 * record a NEW piece of evidence (which appends, never overwrites); there is deliberately no
 * casual boolean toggle, because consent is proof, not a switch.
 */

const CHANNELS: api.ConsentChannel[] = [ 'WHATSAPP', 'SMS', 'EMAIL', 'RCS', 'VOICE', 'PUSH' ];
const STATES: api.ConsentState[] = [ 'OPTED_IN', 'OPTED_OUT', 'PENDING' ];
const PURPOSES: api.ConsentPurpose[] = [ 'MARKETING', 'TRANSACTIONAL', 'SERVICE' ];
// Sources a human on our side may legitimately record. An import-only source (CSV/address book)
// is never offered here, because this surface records consent a customer actually gave.
const SOURCES = [ 'DASHBOARD', 'WEB_FORM', 'FLOW_SUBMISSION', 'WHATSAPP_REPLY', 'DOUBLE_OPT_IN', 'CHECKOUT_VERIFIED', 'CUSTOMER_REQUEST' ];

const STATE_COLOR: Record<api.ConsentState, string> = {
  OPTED_IN: '#15803d',
  OPTED_OUT: '#b91c1c',
  PENDING: '#b45309',
};

const STATE_LABEL: Record<api.ConsentState, string> = {
  OPTED_IN: 'Opted in',
  OPTED_OUT: 'Opted out',
  PENDING: 'Pending',
};

function fmtWhen ( at?: number ): string {
  if ( !at ) return '';
  const ms = at < 1e12 ? at * 1000 : at;
  return new Date( ms ).toLocaleString( 'en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' } );
}

interface Props { contactId: string; }

const ConsentPanel: React.FC<Props> = ( { contactId } ) => {
  const toast = useToastContext();
  const confirm = useConfirm();
  const [ view, setView ] = useState<api.ConsentView | null>( null );
  const [ loading, setLoading ] = useState( false );
  const [ error, setError ] = useState<string | null>( null );
  const [ saving, setSaving ] = useState( false );

  const [ channel, setChannel ] = useState<api.ConsentChannel>( 'WHATSAPP' );
  const [ state, setState ] = useState<api.ConsentState>( 'OPTED_IN' );
  const [ source, setSource ] = useState( 'DASHBOARD' );
  const [ purpose, setPurpose ] = useState<api.ConsentPurpose>( 'MARKETING' );
  const [ reference, setReference ] = useState( '' );

  const load = React.useCallback( async () => {
    if ( !contactId ) return;
    setLoading( true );
    setError( null );
    const result = await api.getConsent( contactId );
    if ( result.ok ) setView( result.data );
    else setError( result.failure.message || 'Could not load consent evidence' );
    setLoading( false );
  }, [ contactId ] );

  useEffect( () => { load(); }, [ load ] );

  const record = async () => {
    const ok = await confirm( {
      title: 'Record consent evidence',
      message: `Append a ${STATE_LABEL[ state ]} record for ${channel} (${purpose.toLowerCase()}). `
        + `This is added to the customer's consent history and does not overwrite prior evidence.`,
      confirmText: 'Record evidence',
    } );
    if ( !ok ) return;
    setSaving( true );
    const result = await api.appendConsent( contactId, {
      channel, state, source, purpose,
      reference: reference.trim() || undefined,
    } );
    if ( result.ok ) {
      setView( result.data );
      setReference( '' );
      toast.success( 'Consent evidence recorded.' );
    } else {
      toast.error( result.failure.message || 'Could not record consent evidence' );
    }
    setSaving( false );
  };

  return (
    <div className="consent-panel">
      <div className="cp-head">
        <h4>Consent &amp; permissions</h4>
        <p>Evidence-based. Each channel shows its current state and the proof behind it. Recording appends to history — it never flips a boolean.</p>
      </div>

      { loading && <p className="cp-muted">Loading consent evidence…</p> }
      { error && <p className="cp-error">{ error }</p> }

      { view && (
        <ul className="cp-channels">
          { CHANNELS.map( ch => {
            const summary = view.summary[ ch ];
            const current: api.ConsentState = summary?.state || 'PENDING';
            return (
              <li key={ ch } className="cp-channel">
                <div className="cp-channel-head">
                  <strong>{ ch }</strong>
                  <span className="cp-state" style={ { color: STATE_COLOR[ current ] } }>{ STATE_LABEL[ current ] }</span>
                </div>
                { summary ? (
                  <p className="cp-evidence">
                    { summary.source } · { summary.purpose.toLowerCase() } · { fmtWhen( summary.at ) }
                    { summary.reference ? ` · ref: ${summary.reference}` : '' }
                    <span className="cp-history"> · { summary.history } record{ summary.history === 1 ? '' : 's' }</span>
                  </p>
                ) : (
                  <p className="cp-muted">No consent evidence recorded — this channel is not sendable.</p>
                ) }
              </li>
            );
          } ) }
        </ul>
      ) }

      <div className="cp-record">
        <strong>Record new evidence</strong>
        <div className="cp-form">
          <label>Channel<select value={ channel } onChange={ e => setChannel( e.target.value as api.ConsentChannel ) }>{ CHANNELS.map( c => <option key={ c } value={ c }>{ c }</option> ) }</select></label>
          <label>State<select value={ state } onChange={ e => setState( e.target.value as api.ConsentState ) }>{ STATES.map( s => <option key={ s } value={ s }>{ STATE_LABEL[ s ] }</option> ) }</select></label>
          <label>Purpose<select value={ purpose } onChange={ e => setPurpose( e.target.value as api.ConsentPurpose ) }>{ PURPOSES.map( p => <option key={ p } value={ p }>{ p }</option> ) }</select></label>
          <label>Source<select value={ source } onChange={ e => setSource( e.target.value ) }>{ SOURCES.map( s => <option key={ s } value={ s }>{ s }</option> ) }</select></label>
          <label className="cp-ref">Evidence reference<input type="text" value={ reference } placeholder="form id, message id, ticket…" onChange={ e => setReference( e.target.value ) } /></label>
        </div>
        <button type="button" className="cp-btn" onClick={ record } disabled={ saving || !contactId }>{ saving ? 'Recording…' : 'Record evidence' }</button>
      </div>

      <style jsx>{`
        .consent-panel{margin-top:20px;border-top:2px solid var(--border,#f3f4f6);padding-top:16px}
        .cp-head h4{margin:0;font-size:var(--text-md);font-weight:700;color:var(--text,#111)}
        .cp-head p{margin:4px 0 12px;font-size:var(--text-xs);color:var(--text-muted,#6b7280);line-height:1.5}
        .cp-muted{font-size:var(--text-xs);color:var(--text-muted,#9ca3af)}
        .cp-error{font-size:var(--text-xs);color:#b91c1c}
        .cp-channels{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
        .cp-channel{border:1px solid var(--border,#e5e7eb);border-radius:10px;padding:10px 12px}
        .cp-channel-head{display:flex;justify-content:space-between;align-items:center}
        .cp-state{font-size:var(--text-xs);font-weight:800;text-transform:uppercase;letter-spacing:.05em}
        .cp-evidence{margin:4px 0 0;font-size:var(--text-xs);color:var(--text-muted,#6b7280);overflow-wrap:anywhere}
        .cp-history{color:var(--text-muted,#9ca3af)}
        .cp-record{margin-top:16px;border:1px solid var(--border,#e5e7eb);border-radius:12px;padding:12px}
        .cp-record>strong{font-size:var(--text-xs);text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted,#6b7280)}
        .cp-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}
        .cp-form label{display:flex;flex-direction:column;gap:3px;font-size:var(--text-xs);color:var(--text-muted,#6b7280)}
        .cp-form select,.cp-form input{min-height:40px;border:1px solid var(--border,#d1d5db);border-radius:8px;padding:0 8px;font-size:var(--text-sm);background:#fff;color:var(--text,#111)}
        .cp-ref{grid-column:1/-1}
        .cp-btn{min-height:44px;border:1px solid var(--accent,#1a3a2a);border-radius:10px;background:var(--accent,#1a3a2a);color:#fff;font-size:var(--text-sm);font-weight:700;padding:0 18px;cursor:pointer}
        .cp-btn:disabled{opacity:.5;cursor:not-allowed}
        @media(forced-colors:active){.cp-channel,.cp-record,.cp-form select,.cp-form input{border-color:CanvasText}}
      `}</style>
    </div>
  );
};

export default ConsentPanel;
