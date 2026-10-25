/**
 * Per-day WhatsApp Flow funnel, read from /wa-business/flow-funnel.
 *
 * Shared by Flow Hub analytics and the F001 control surface so both show the same counters.
 * The counters hold no customer data. A failed read says why it failed instead of showing
 * zeros, because "nobody opened the Flow" and "the counters could not be read" lead staff to
 * different actions.
 */
import React, { useEffect, useState } from 'react';
import * as api from '../../../api/client';

/** Staff-readable label for every stage lambda_utils.flow_funnel records. */
export const FUNNEL_STAGE_LABELS: Record<string, string> = {
  launch_attempted: 'Launch requested (keyword or staff send)',
  launch_blocked: 'Launch refused by a control',
  launch_redirected: 'Website link sent instead (WABA 2)',
  launch_sent: 'Flow message handed to WhatsApp',
  launch_failed: 'Flow message failed to send',
  init_received: 'Flow opened (INIT received)',
  init_success: 'Opened with saved details',
  init_rejected: 'Open refused (expired or unknown link)',
  init_failed: 'Open failed (server error)',
  review_rejected: 'Save refused (expired or finished link)',
  validation_failed: 'Customer asked to correct a field',
  stale_write_refused: 'Save refused: profile changed elsewhere',
  save_refused: 'Save refused: identity or contact problem',
  save_success: 'Profile saved',
  completion_history_failed: 'Saved, but history write failed',
  complete_returned: 'COMPLETE shown to the customer',
  error_notification: 'WhatsApp client error reports',
};

interface Props {
  flowCode: string;
  days?: number;
  /** Show one column per day as well as the totals. */
  showDays?: boolean;
}

export default function FlowFunnel ( { flowCode, days = 7, showDays = false }: Props ) {
  const [ report, setReport ] = useState<api.FlowFunnelReport | null>( null );
  const [ failure, setFailure ] = useState( '' );
  const [ loading, setLoading ] = useState( true );
  const [ reloadKey, setReloadKey ] = useState( 0 );

  // State is set only after the request resolves, and a response for a flow code the
  // component no longer shows is dropped.
  useEffect( () => {
    if ( !flowCode ) return undefined;
    let cancelled = false;
    ( async () => {
      const result = await api.getFlowFunnel( flowCode, days );
      if ( cancelled ) return;
      setReport( result.ok ? result.data : null );
      setFailure( result.ok ? '' : ( result.failure.message || 'Funnel counters could not be read.' ) );
      setLoading( false );
    } )();
    return () => { cancelled = true; };
  }, [ flowCode, days, reloadKey ] );

  const refresh = () => {
    setLoading( true );
    setReloadKey( key => key + 1 );
  };

  if ( !flowCode ) return null;
  const totals = report?.totals || {};
  const anyActivity = Object.values( totals ).some( value => value > 0 );
  return (
    <div aria-label={ `Funnel for ${flowCode}` }>
      <div style={ { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 } }>
        <strong style={ { fontSize: 13 } }>Funnel, last { days } days (UTC)</strong>
        <button type="button" onClick={ refresh } disabled={ loading }
          style={ { minHeight: 32, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 6, background: '#fff', cursor: 'pointer' } }>
          { loading ? 'Loading…' : 'Refresh' }
        </button>
      </div>
      { failure && <p role="alert" style={ { fontSize: 13 } }>Funnel unavailable: { failure }</p> }
      { report && !anyActivity && <p role="status" style={ { fontSize: 13, color: 'var(--text-muted)' } }>No activity recorded in this window.</p> }
      { report && anyActivity && (
        <div style={ { overflowX: 'auto' } }>
          <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 12 } }>
            <thead>
              <tr>
                <th scope="col" style={ { textAlign: 'left', padding: 6, borderBottom: '1px solid var(--border)' } }>Stage</th>
                <th scope="col" style={ { textAlign: 'right', padding: 6, borderBottom: '1px solid var(--border)' } }>Total</th>
                { showDays && report.days.map( day => (
                  <th key={ day.day } scope="col" style={ { textAlign: 'right', padding: 6, borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' } }>{ day.day.slice( 5 ) }</th>
                ) ) }
              </tr>
            </thead>
            <tbody>
              { report.stages.map( stage => (
                <tr key={ stage }>
                  <th scope="row" style={ { textAlign: 'left', padding: 6, borderBottom: '1px solid var(--border)', fontWeight: 500 } }>
                    { FUNNEL_STAGE_LABELS[ stage ] || stage }
                  </th>
                  <td style={ { textAlign: 'right', padding: 6, borderBottom: '1px solid var(--border)', fontVariantNumeric: 'tabular-nums' } }>{ totals[ stage ] || 0 }</td>
                  { showDays && report.days.map( day => (
                    <td key={ day.day } style={ { textAlign: 'right', padding: 6, borderBottom: '1px solid var(--border)', fontVariantNumeric: 'tabular-nums' } }>{ day.counts[ stage ] || 0 }</td>
                  ) ) }
                </tr>
              ) ) }
            </tbody>
          </table>
        </div>
      ) }
    </div>
  );
}
