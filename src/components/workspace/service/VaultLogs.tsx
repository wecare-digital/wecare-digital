import React from 'react';
import * as api from '../../../api/client';
import type { SecureFileLog } from '../../../api/client';
import Spinner from '../../../components/ui/Spinner';
import VaultMessageTimeline from './VaultMessageTimeline';
import { parseVaultJourney, type VaultRegistryJourney } from './VaultJourneyPreview';

function when ( value?: string ): string {
  if ( !value ) return '—';
  const parsed = new Date( value );
  if ( Number.isNaN( parsed.getTime() ) ) return value;
  return parsed.toLocaleString( 'en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata',
  } );
}

function storageLabel ( value: boolean | null | undefined ): string {
  if ( value === true ) return 'Present';
  if ( value === false ) return 'Missing';
  return 'Unknown';
}

export default function VaultLogs () {
  const [ logs, setLogs ] = React.useState<SecureFileLog[]>( [] );
  const [ loading, setLoading ] = React.useState( true );
  const [ error, setError ] = React.useState( '' );
  const [ mobile, setMobile ] = React.useState( '' );
  const [ truncated, setTruncated ] = React.useState( false );
  const [ journey, setJourney ] = React.useState<VaultRegistryJourney | null>( null );
  const [ expandedFileId, setExpandedFileId ] = React.useState( '' );

  const load = React.useCallback( async ( mobileFilter?: string ) => {
    setLoading( true );
    const result = await api.listSecureFileLogs( mobileFilter || undefined );
    if ( result.ok )
    {
      setLogs( result.data.logs || [] );
      setTruncated( !!result.data.truncated );
      setError( '' );
    } else
    {
      setLogs( [] );
      setError( result.failure.message || 'Could not load Vault logs' );
    }
    setLoading( false );
  }, [] );

  React.useEffect( () => { void load(); }, [ load ] );

  React.useEffect( () => {
    let active = true;
    void api.getSystemConfigResult( 'vault_whatsapp_template_journey_v1' ).then( result => {
      if ( active && result.ok ) setJourney( parseVaultJourney( result.data.config ) );
    } ).catch( () => { /* The timeline remains read-only with safe defaults. */ } );
    return () => { active = false; };
  }, [] );

  React.useEffect( () => {
    const refresh = () => {
      if ( document.visibilityState === 'visible' ) void load( mobile || undefined );
    };
    window.addEventListener( 'focus', refresh );
    document.addEventListener( 'visibilitychange', refresh );
    return () => {
      window.removeEventListener( 'focus', refresh );
      document.removeEventListener( 'visibilitychange', refresh );
    };
  }, [ load, mobile ] );

  return (
    <section className="vl-wrap" aria-labelledby="vault-logs-title">
      <div className="vl-head">
        <div>
          <p className="vl-eyebrow">Vault · Audit</p>
          <h1 id="vault-logs-title">Logs</h1>
          <p>
            Review Vault file history and the five-message WhatsApp sequence with attempt times.
            A Meta acceptance is not proof of handset delivery. Missing webhook evidence is marked unverified.
          </p>
        </div>
        <div className="vl-filter">
          <label htmlFor="vault-log-mobile">Filter by mobile</label>
          <div>
            <input
              id="vault-log-mobile"
              value={ mobile }
              onChange={ event => setMobile( event.target.value ) }
              placeholder="8100640044"
              inputMode="tel"
            />
            <button type="button" onClick={ () => { void load( mobile ); } }>Apply</button>
          </div>
        </div>
      </div>

      { error && <div className="vl-alert" role="alert">{ error }</div> }
      { loading && <p className="vl-loading"><Spinner /> Loading Vault logs…</p> }

      { !loading && !error && logs.length === 0 && (
        <p className="vl-empty">No Vault log records found.</p>
      ) }

      { !loading && truncated && (
        <p className="vl-note">Showing the newest { logs.length } log records.</p>
      ) }

      { !loading && logs.length > 0 && (
        <div className="vl-table-wrap">
          <table className="vl-table">
            <thead>
              <tr>
                <th>Created</th>
                <th>File</th>
                <th>Customer</th>
                <th>Uploaded by</th>
                <th>Payment sent by</th>
                <th>Access sent by</th>
                <th>S3 source</th>
                <th>S3 delivery</th>
                <th>Record</th>
                <th>Status</th>
                <th>WhatsApp message log</th>
              </tr>
            </thead>
            <tbody>
              { logs.map( row => (
                <tr key={ row.fileId }>
                  <td data-label="Created">{ when( row.createdAt ) }</td>
                  <td data-label="File">
                    <strong>{ row.displayName || row.fileId }</strong>
                    <small>Private UUID filename · { row.fileId }</small>
                  </td>
                  <td data-label="Customer">
                    <strong>{ row.ownerName || '—' }</strong>
                    <small>{ row.ownerPhoneMasked || '—' }</small>
                  </td>
                  <td data-label="Uploaded by" className="vl-mono">{ row.uploadedBy || 'Legacy / unknown' }</td>
                  <td data-label="Payment sent by">
                    <strong className="vl-mono">{ row.lastPaymentRequestedBy || '—' }</strong>
                    <small>{ when( row.lastPaymentRequestedAt ) }</small>
                  </td>
                  <td data-label="Access sent by">
                    <strong className="vl-mono">{ row.lastAccessSentBy || '—' }</strong>
                    <small>{ when( row.lastAccessSentAt ) }</small>
                  </td>
                  <td data-label="S3 source">
                    <span className={ row.storageOriginalPresent === true ? 'ok' : row.storageOriginalPresent === false ? 'bad' : '' }>
                      { storageLabel( row.storageOriginalPresent ) }
                    </span>
                  </td>
                  <td data-label="S3 delivery">
                    <span className={ row.storageDeliveryPresent === true ? 'ok' : row.storageDeliveryPresent === false ? 'bad' : '' }>
                      { storageLabel( row.storageDeliveryPresent ) }
                    </span>
                  </td>
                  <td data-label="Record">
                    <span className={ row.legacyRecord ? 'legacy' : 'current' }>
                      { row.legacyRecord ? 'Legacy' : 'Current' }
                    </span>
                  </td>
                  <td data-label="Status">
                    <strong>{ row.status || '—' }</strong>
                    { row.revokedAt && <small>Revoked { when( row.revokedAt ) }{ row.revokedBy ? ` by ${ row.revokedBy }` : '' }</small> }
                  </td>
                  <td data-label="WhatsApp message log">
                    <details className="vl-message-details" open={ expandedFileId === row.fileId }>
                      <summary onClick={ event => {
                        event.preventDefault();
                        setExpandedFileId( current => current === row.fileId ? '' : row.fileId );
                      } }>5 stages · timestamps &amp; delivery</summary>
                      { expandedFileId === row.fileId && <VaultMessageTimeline file={ row } journey={ journey } /> }
                    </details>
                  </td>
                </tr>
              ) ) }
            </tbody>
          </table>
        </div>
      ) }

      <style jsx>{`
        .vl-wrap{min-width:0;max-width:100%;padding:4px 0 40px;overflow-x:hidden;overflow-x:clip}
        .vl-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin:0 0 20px}
        .vl-eyebrow{margin:0 0 8px;font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
        h1{margin:0;font-size:clamp(28px,3.2vw,40px);line-height:1.08;letter-spacing:-1.2px;color:var(--text)}
        .vl-head p:not(.vl-eyebrow){max-width:720px;margin:10px 0 0;color:var(--text-muted);line-height:1.5}
        .vl-filter{min-width:300px}
        .vl-filter label{display:block;margin:0 0 7px;font-size:13px;font-weight:700;color:var(--accent)}
        .vl-filter>div{display:flex;gap:8px}
        .vl-filter input{min-width:0;flex:1;min-height:44px;padding:0 12px;border:2px solid var(--border);border-radius:11px;font:inherit}
        .vl-filter button{min-height:44px;padding:0 16px;border:2px solid var(--border);border-radius:11px;background:#fff;color:var(--accent);font-weight:800;cursor:pointer}
        .vl-alert,.vl-empty,.vl-loading,.vl-note{padding:16px;border:1px solid var(--border);border-radius:12px;background:#fff;color:var(--text-muted)}
        .vl-loading{display:flex;align-items:center;gap:8px}
        .vl-table-wrap{overflow:auto;border:1px solid var(--border);border-radius:14px;background:#fff}
        .vl-table{width:100%;border-collapse:collapse;min-width:1340px}
        .vl-message-details{min-width:180px;max-width:350px}
        .vl-message-details>summary{cursor:pointer;color:var(--accent);font-size:12px;font-weight:800;white-space:nowrap;padding:8px 0}
        .vl-message-details[open]{min-width:300px;max-width:380px}
        .vl-message-details>section{margin-top:10px}
        th,td{padding:13px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border);font-size:13px}
        th{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);background:#f8faf9}
        tbody tr:last-child td{border-bottom:0}
        td strong,td small{display:block}
        td small{margin-top:4px;color:var(--text-muted)}
        .vl-mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
        .ok,.bad,.legacy,.current{display:inline-flex;padding:4px 8px;border-radius:999px;font-weight:800;font-size:11px}
        .ok,.current{background:#dcfce7;color:#166534}
        .bad,.legacy{background:#fee2e2;color:#991b1b}
        @media(max-width:800px){
          .vl-head{align-items:stretch;flex-direction:column}
          .vl-filter{min-width:0}
          .vl-filter>div{min-width:0;align-items:stretch}
          .vl-filter input{font-size:16px;min-width:0}
          .vl-filter button{flex:0 0 auto}
          .vl-table-wrap{overflow:visible;border:0;background:transparent}
          .vl-table,.vl-table tbody{display:block;min-width:0;width:100%}
          .vl-table thead{display:none}
          .vl-table tbody{display:grid;gap:12px}
          .vl-table tr{display:block;border:1px solid var(--border);border-radius:14px;background:#fff;overflow:hidden}
          .vl-table td{display:grid;grid-template-columns:minmax(110px,34%) minmax(0,1fr);gap:12px;width:100%;box-sizing:border-box}
          .vl-table td::before{content:attr(data-label);font-size:11px;font-weight:800;text-transform:uppercase;color:var(--text-muted)}
        }
        @media(max-width:399px){
          .vl-filter>div{flex-direction:column}
          .vl-filter button{width:100%}
          .vl-table td{grid-template-columns:1fr;gap:5px;overflow-wrap:anywhere}
        }
      `}</style>
    </section>
  );
}
