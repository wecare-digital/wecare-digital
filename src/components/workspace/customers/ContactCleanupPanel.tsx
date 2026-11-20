import React, { useState } from 'react';
import * as api from '../../../api/client';
import type { ContactCleanupKeep, ContactCleanupScanResult } from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import { useUserRole } from '../../../hooks/useUserRole';

export const CLEANUP_POLICY_NOTE =
  'Cleanup only archives, and archive is reversible. Permanent delete is a separate Admin + MFA action '
  + 'below. It needs an approved case and is refused for contacts with payment history.';

/**
 * Turn the keep textarea (one identifier per line) into exact identifier lists.
 * A line that looks like a phone number is a phone, "CC.xxxx" is a BSUID, anything else is a
 * contact id. Names are never selectors.
 */
export function parseKeepList ( text: string ): ContactCleanupKeep {
  const keep: Required<ContactCleanupKeep> = { keepContactIds: [], keepPhones: [], keepBsuids: [] };
  for ( const raw of text.split( /\r?\n/ ) ) {
    const line = raw.trim();
    if ( !line ) continue;
    if ( /^\+?[\d\s-]{7,}$/.test( line ) ) keep.keepPhones.push( line.replace( /\D/g, '' ) );
    else if ( /^[A-Za-z]{2}\.[A-Za-z0-9]+/.test( line ) ) keep.keepBsuids.push( line );
    else keep.keepContactIds.push( line );
  }
  return keep;
}

const COUNT_LABELS: Array<[ string, string ]> = [
  [ 'eligible', 'Junk candidates' ],
  [ 'FINANCIAL_RETENTION', 'Keep: paid messages, invoices, payment links' ],
  [ 'LEGAL_OR_IDENTITY_LOCK', 'Keep: locked' ],
  [ 'OPERATOR_HOLD', 'Keep: operator hold' ],
  [ 'REVIEW_REQUIRED', 'Review required' ],
];

interface Props {
  onChanged?: () => void | Promise<void>;
}

const ContactCleanupPanel: React.FC<Props> = ( { onChanged } ) => {
  const toast = useToastContext();
  const confirm = useConfirm();
  const { role } = useUserRole();
  const canArchive = role === 'Admin';
  const [ keepText, setKeepText ] = useState( '' );
  const [ reason, setReason ] = useState( '' );
  const [ scan, setScan ] = useState<ContactCleanupScanResult | null>( null );
  const [ keepUsed, setKeepUsed ] = useState<ContactCleanupKeep>( {} );
  const [ selected, setSelected ] = useState<Set<string>>( new Set() );
  const [ scanning, setScanning ] = useState( false );
  const [ archiving, setArchiving ] = useState( false );
  const [ error, setError ] = useState<string | null>( null );
  const [ delId, setDelId ] = useState( '' );
  const [ delCase, setDelCase ] = useState( '' );
  const [ delManifest, setDelManifest ] = useState( '' );
  const [ delToken, setDelToken ] = useState( '' );
  const [ delTyped, setDelTyped ] = useState( '' );
  const [ deleting, setDeleting ] = useState( false );
  const canDelete = !!delId.trim() && !!delCase.trim() && !!delManifest.trim() && !!delToken.trim()
    && delTyped.trim() === 'DELETE';

  const runPermanentDelete = async () => {
    if ( !canDelete ) return;
    const ok = await confirm( {
      title: 'Permanently delete this contact?',
      message: 'The contact is erased and its phone and identity keys are freed so the same number can be '
        + 'added again. Payment, invoice and Razorpay records are kept. This cannot be undone.',
      confirmText: 'Delete permanently',
      danger: true,
    } );
    if ( !ok ) return;
    setDeleting( true );
    const result = await api.deleteContactPermanently( delId.trim(), {
      caseId: delCase.trim(), manifestSha256: delManifest.trim(), approvalToken: delToken.trim(),
    } );
    setDeleting( false );
    if ( result.ok ) {
      toast.success( result.data.erasureComplete
        ? 'Contact deleted. The same phone number can be added again.'
        : 'Deletion is pending. Check the audit record before retrying.' );
      setDelId( '' ); setDelCase( '' ); setDelManifest( '' ); setDelToken( '' ); setDelTyped( '' );
      await onChanged?.();
      return;
    }
    const code = result.failure.code || '';
    toast.error( code === 'ERASURE_ADMIN_MFA_REQUIRED'
      ? 'Permanent delete needs an Admin with MFA enrolled. Enrol MFA and sign in again.'
      : ( result.failure.message || 'Permanent delete refused' ) );
  };

  const incomplete = !!scan && scan.status !== 'OK';
  const candidates = incomplete ? [] : ( scan?.eligible || [] );
  // The server token is bound to the exact page of ids, so the whole page is archived together.
  const allSelected = candidates.length > 0 && selected.size === candidates.length;

  const runScan = async () => {
    setScanning( true );
    setError( null );
    setScan( null );
    setSelected( new Set() );
    const keep = parseKeepList( keepText );
    const result = await api.scanContactCleanup( keep );
    setScanning( false );
    if ( !result.ok ) {
      setError( result.failure.message || 'Scan failed' );
      return;
    }
    setKeepUsed( keep );
    setScan( result.data );
    if ( result.data.status === 'OK' ) {
      setSelected( new Set( result.data.eligible.map( c => c.contactId ) ) );
    } else {
      setError( 'The scan could not read every record, so nothing can be archived. '
        + ( result.data.problems || [] ).join( '; ' ) );
    }
  };

  const toggle = ( id: string ) => {
    setSelected( prev => {
      const next = new Set( prev );
      if ( next.has( id ) ) next.delete( id ); else next.add( id );
      return next;
    } );
  };

  const runArchive = async () => {
    if ( !scan || !scan.confirmationToken || incomplete ) return;
    const ids = candidates.map( c => c.contactId );
    // The confirmation token covers the whole scanned page, so partial selection is refused here
    // rather than sent to a request the server would reject.
    if ( selected.size !== ids.length ) {
      toast.error( 'Archive applies to the whole scanned page. Add contacts to the keep list and scan again to exclude them.' );
      return;
    }
    if ( !reason.trim() ) {
      toast.error( 'Enter a reason for the archive' );
      return;
    }
    const ok = await confirm( {
      title: 'Archive junk contacts?',
      message: `Archive ${ids.length} contacts with no paid messages, invoices or payment links? `
        + 'Archive is reversible: Restore brings a contact back. Nothing is deleted.',
      confirmText: 'Archive contacts',
      danger: true,
    } );
    if ( !ok ) return;
    setArchiving( true );
    const result = await api.archiveCleanupCandidates( {
      confirmationToken: scan.confirmationToken,
      contactIds: ids,
      reason: reason.trim(),
      keep: keepUsed,
    } );
    setArchiving( false );
    if ( result.ok ) {
      const { archived, refused } = result.data;
      toast.success( `Archived ${archived} contacts${refused ? `, ${refused} refused` : ''}. Use Restore to bring a contact back.` );
      setScan( null );
      setSelected( new Set() );
      await onChanged?.();
      return;
    }
    const refusedMap = result.failure.details?.refused as Record<string, string> | undefined;
    const why = refusedMap
      ? ' ' + Object.values( refusedMap ).slice( 0, 3 ).join( '; ' )
      : '';
    toast.error( ( result.failure.message || 'Archive refused' ) + why );
    // Evidence changed or the token was used. Force a fresh scan.
    setScan( null );
    setSelected( new Set() );
  };

  return (
    <section className="review-section cleanup" aria-labelledby="cleanup-title">
      <h3 id="cleanup-title">Clean up contacts</h3>
      <p>
        Finds junk contacts with no paid messages, invoices, payment links, lock or operator hold.
        Contacts with any of those are kept. Cleanup archives; it never deletes.
      </p>
      <p className="cleanup-note" role="note">{ CLEANUP_POLICY_NOTE }</p>

      <label className="cleanup-label" htmlFor="cleanup-keep">Always keep (optional, one contact id, phone or BSUID per line)</label>
      <textarea id="cleanup-keep" className="cleanup-text" rows={ 3 } value={ keepText }
        onChange={ e => setKeepText( e.target.value ) } disabled={ scanning || archiving } />
      <div className="cleanup-actions">
        <button type="button" className="action" onClick={ () => void runScan() } disabled={ scanning || archiving || !canArchive } title={ canArchive ? undefined : 'Scanning requires the Admin role' }>
          { scanning ? 'Scanning…' : 'Scan contacts' }
        </button>
      </div>

      { error && <p className="cleanup-error" role="alert">{ error }</p> }

      { scan && (
        <>
          <div className="cleanup-counts">
            { COUNT_LABELS.map( ( [ key, label ] ) => (
              <div key={ key }><strong>{ key === 'eligible' && incomplete ? 0 : ( scan.counts[ key ] || 0 ) }</strong><small>{ label }</small></div>
            ) ) }
          </div>

          { candidates.length > 0 && (
            <>
              <h4>Junk candidates ({ candidates.length }{ scan.eligibleNextOffset !== null ? ', more after archiving this page' : '' })</h4>
              <label className="cleanup-check">
                <input type="checkbox" checked={ allSelected }
                  onChange={ () => setSelected( allSelected ? new Set() : new Set( candidates.map( c => c.contactId ) ) ) } />
                Select all
              </label>
              <ul className="cleanup-list">
                { candidates.map( c => (
                  <li key={ c.contactId }>
                    <label className="cleanup-check">
                      <input type="checkbox" checked={ selected.has( c.contactId ) } onChange={ () => toggle( c.contactId ) } />
                      <span>{ c.maskedPhone || 'No phone' } · { c.messageTotal } messages</span>
                    </label>
                  </li>
                ) ) }
              </ul>

              <label className="cleanup-label" htmlFor="cleanup-reason">Reason (required)</label>
              <input id="cleanup-reason" className="cleanup-text" type="text" maxLength={ 400 } value={ reason }
                onChange={ e => setReason( e.target.value ) } disabled={ archiving } />
              { canArchive ? (
                <div className="cleanup-actions">
                  <button type="button" className="action" onClick={ () => void runArchive() }
                    disabled={ archiving || !reason.trim() || !scan.confirmationToken || selected.size !== candidates.length }>
                    { archiving ? 'Archiving…' : `Archive ${selected.size} contacts` }
                  </button>
                </div>
              ) : (
                <p className="cleanup-note">Archiving junk contacts requires the Admin role.</p>
              ) }
            </>
          ) }

          { !incomplete && candidates.length === 0 && <p className="empty">No junk candidates found.</p> }

          { scan.kept.length > 0 && (
            <details className="cleanup-kept">
              <summary>Kept contacts ({ scan.keptTotal })</summary>
              <ul className="cleanup-list">
                { scan.kept.map( ( k, i ) => (
                  <li key={ `${k.label}-${i}` }>
                    <strong>{ k.label }</strong> <small>{ k.maskedPhone }</small>
                    <small> { k.keepReasons.join( ', ' ) }</small>
                  </li>
                ) ) }
              </ul>
              { scan.keptNextOffset !== null && <small className="more">Showing first { scan.kept.length } of { scan.keptTotal }.</small> }
            </details>
          ) }

          { scan.ttlGap?.note && <p className="cleanup-note">{ scan.ttlGap.note }</p> }
        </>
      ) }

      <h4>Delete a contact permanently</h4>
      <p className="cleanup-note" role="note">
        Admin with MFA only. Frees the phone and identity keys so the same number can be added again.
        Payment, invoice and Razorpay records are kept, and a contact with payment history cannot be deleted (archive it instead).
      </p>
      { canArchive ? (
        <>
          <label className="cleanup-label" htmlFor="del-id">Contact id</label>
          <input id="del-id" className="cleanup-text" type="text" value={ delId } onChange={ e => setDelId( e.target.value ) } disabled={ deleting } />
          <label className="cleanup-label" htmlFor="del-case">Approved case id</label>
          <input id="del-case" className="cleanup-text" type="text" value={ delCase } onChange={ e => setDelCase( e.target.value ) } disabled={ deleting } />
          <label className="cleanup-label" htmlFor="del-manifest">Reviewed manifest SHA-256</label>
          <input id="del-manifest" className="cleanup-text" type="text" value={ delManifest } onChange={ e => setDelManifest( e.target.value ) } disabled={ deleting } />
          <label className="cleanup-label" htmlFor="del-token">Approval token</label>
          <input id="del-token" className="cleanup-text" type="password" autoComplete="off" value={ delToken } onChange={ e => setDelToken( e.target.value ) } disabled={ deleting } />
          <label className="cleanup-label" htmlFor="del-typed">Type DELETE to confirm</label>
          <input id="del-typed" className="cleanup-text" type="text" value={ delTyped } onChange={ e => setDelTyped( e.target.value ) } disabled={ deleting } />
          <div className="cleanup-actions">
            <button type="button" className="action" onClick={ () => void runPermanentDelete() } disabled={ deleting || !canDelete }>
              { deleting ? 'Deleting…' : 'Delete permanently' }
            </button>
          </div>
        </>
      ) : (
        <p className="cleanup-note">Permanent delete requires the Admin role with MFA enrolled.</p>
      ) }

      <style jsx>{`
        .cleanup-note{padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:var(--bg-secondary);font-size:var(--text-xs)}
        .cleanup-error{padding:10px 12px;border:1px solid var(--danger, #b91c1c);border-radius:10px;color:var(--danger, #b91c1c);font-size:var(--text-sm)}
        .cleanup-label{display:block;margin-top:12px;font-size:var(--text-xs);color:var(--text-muted)}
        .cleanup-text{width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border:1px solid var(--border);border-radius:10px;font:inherit;font-size:var(--text-sm)}
        .cleanup-actions{margin-top:10px;display:flex;gap:8px}
        .action{min-height:44px;padding:7px 14px;border:1px solid var(--border);border-radius:10px;background:#fff;color:var(--text);font:inherit;font-size:var(--text-xs);font-weight:700;cursor:pointer}
        .action:disabled{opacity:.55;cursor:default}
        .action:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
        .cleanup-counts{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-top:14px}
        .cleanup-counts div{border:1px solid var(--border);border-radius:12px;padding:10px;display:flex;flex-direction:column}
        .cleanup-counts strong{font-size:22px}.cleanup-counts small{color:var(--text-muted);font-size:var(--text-xs)}
        .cleanup-list{margin:8px 0;padding:0;list-style:none;max-height:260px;overflow:auto;border:1px solid var(--border);border-radius:12px}
        .cleanup-list li{padding:8px 12px;border-top:1px solid var(--border-light);font-size:var(--text-sm)}.cleanup-list li:first-child{border-top:0}
        .cleanup-check{display:flex;align-items:center;gap:8px;min-height:32px;font-size:var(--text-sm)}
        .cleanup-kept{margin-top:14px}.cleanup-kept summary{cursor:pointer;font-size:var(--text-sm);font-weight:700}
      `}</style>
    </section>
  );
};

export default ContactCleanupPanel;
