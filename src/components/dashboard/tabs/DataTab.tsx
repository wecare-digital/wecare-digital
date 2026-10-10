/**
 * Factory Reset Tab — single Deep Clean tool.
 *
 * Lists every DynamoDB table, S3 folder and SQS queue the backend knows about, with live
 * record counts. Only the ones the SERVER marks `selectable` can be chosen; everything else
 * renders disabled with the server's reason next to it.
 *
 * WHAT CHANGED AND WHY IT IS NOT COSMETIC. This header used to say the backend
 * auto-discovered every table and that you could "select any/all of them", and that was
 * accurate: `system-cleanup` merged every `stack-wecare-digital-*` table into the registry,
 * so Contacts, Invoices, Payments and AuditLogs were all one "Select All" away from being
 * emptied. The server now refuses all of those, and this tab stops offering them — not as
 * the guard, but so an operator is not handed a choice that is going to be declined.
 *
 * THE SERVER IS THE AUTHORITY. Every protection here is duplicated server-side and refused
 * there: an allow-list, an independent keyword deny list, Admin + MFA, and a single-use
 * confirmation token bound to the exact selection. A direct API call that skips this screen
 * entirely is refused for want of that token. Nothing below is load-bearing for safety, and
 * nothing below should be relied on as if it were.
 */
import React, { useState, useCallback, useEffect } from 'react';
import * as api from '../../../api/client';
import Button from '../../../components/ui/Button';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import type { DashboardData } from '../../../types/dashboard';
import { PUBLIC_ROOT } from '../../../lib/media-paths';

interface DataTabProps {
  data: DashboardData;
  onRefresh: () => void;
}

// Minimal fallback shown only if the backend preview endpoint is unreachable.
const CLEANUP_FALLBACK: api.CleanupResource[] = [
  { id: 'whatsapp_inbox', label: 'WhatsApp Inbox (Inbound)', category: 'Messages', type: 'dynamodb', table: 'WhatsAppInboundTable', count: -1 },
  { id: 'whatsapp_outbox', label: 'WhatsApp Outbox (Outbound)', category: 'Messages', type: 'dynamodb', table: 'WhatsAppOutboundTable', count: -1 },
  { id: 'contacts', label: 'Contacts', category: 'Contacts', type: 'dynamodb', table: 'ContactsTable', count: -1 },
  { id: 'voice_cdr', label: 'Voice CDR Records', category: 'Voice', type: 'dynamodb', table: 'VoiceCDRTable', count: -1 },
  // Rooted via PUBLIC_ROOT to match what the backend actually deletes: system-cleanup
  // builds these with media_paths.public(...), which yields `o/stack/...`. These rows
  // read `stack/...` until 2026-09-29 — one level above the data, and shown precisely
  // when the live preview is unreachable, so there was nothing to cross-check against.
  { id: 's3_whatsapp_media', label: 'S3: WhatsApp Media', category: 'S3 Storage', type: 's3', prefix: `${PUBLIC_ROOT}stack/whatsapp-media/`, count: -1 },
  { id: 's3_voice_recordings', label: 'S3: Voice Recordings', category: 'S3 Storage', type: 's3', prefix: `${PUBLIC_ROOT}stack/voice/`, count: -1 },
];

const DataTab: React.FC<DataTabProps> = ( { data, onRefresh } ) => {
  const toast = useToastContext();
  const confirm = useConfirm();

  const [ cleanupResources, setCleanupResources ] = useState<api.CleanupResource[]>( [] );
  const [ cleanupSelected, setCleanupSelected ] = useState<Set<string>>( new Set() );
  const [ cleanupLoading, setCleanupLoading ] = useState( false );
  const [ cleanupRunning, setCleanupRunning ] = useState( false );
  const [ cleanupResults, setCleanupResults ] = useState<api.CleanupResult[] | null>( null );
  const [ cleanupSummary, setCleanupSummary ] = useState<{ deleted: number; protected: number; skipped: number } | null>( null );
  const [ confirmToken, setConfirmToken ] = useState( '' );
  const [ confirmWarning, setConfirmWarning ] = useState<string | undefined>( undefined );

  const loadCleanupPreview = useCallback( async () => {
    setCleanupLoading( true );
    setCleanupResults( null );
    setCleanupSummary( null );
    try
    {
      const resources = await api.getCleanupPreview();
      setCleanupResources( resources && resources.length > 0 ? resources : CLEANUP_FALLBACK );
      // The token belongs to THIS preview and to the exact id set the server counted, so it
      // is read in the same breath as the rows. Clearing the selection matters too: a
      // selection made against the previous preview is no longer the set the new token
      // authorises, and the server would refuse it 409.
      const confirmation = api.lastCleanupConfirmation();
      setConfirmToken( confirmation.token );
      setConfirmWarning( confirmation.warning );
      setCleanupSelected( new Set() );
    } catch
    {
      setCleanupResources( CLEANUP_FALLBACK );
      setConfirmToken( '' );
      setConfirmWarning( undefined );
    } finally
    {
      setCleanupLoading( false );
    }
  }, [] );

  // Load live counts as soon as the tab opens (real-time view).
  useEffect( () => { loadCleanupPreview(); }, [ loadCleanupPreview ] );

  /**
   * Whether this row may be selected at all.
   *
   * `protected !== true` rather than `selectable === true`: a response from a backend that
   * predates these fields carries neither, and treating "absent" as protected would render
   * the whole tab inert against an older deployment. The authority is the server, which
   * refuses a protected id whatever arrives — this only stops the UI offering an action it
   * knows will be declined.
   */
  const isSelectable = ( r: api.CleanupResource ) => r.protected !== true;
  const selectableResources = cleanupResources.filter( isSelectable );

  const toggleCleanupItem = ( id: string ) => {
    const resource = cleanupResources.find( r => r.id === id );
    if ( resource && !isSelectable( resource ) ) return;
    setCleanupSelected( prev => {
      const next = new Set( prev );
      if ( next.has( id ) ) next.delete( id ); else next.add( id );
      return next;
    } );
  };

  const toggleCleanupCategory = ( category: string ) => {
    // Only the selectable rows in the category. A category box that swept protected ids
    // into the selection would be the "Select All over protected data" this guard exists to
    // remove, one category at a time.
    const items = selectableResources.filter( r => r.category === category );
    if ( items.length === 0 ) return;
    const allSelected = items.every( r => cleanupSelected.has( r.id ) );
    setCleanupSelected( prev => {
      const next = new Set( prev );
      items.forEach( r => { if ( allSelected ) next.delete( r.id ); else next.add( r.id ); } );
      return next;
    } );
  };

  const selectAllCleanup = () => {
    if ( cleanupSelected.size === selectableResources.length && selectableResources.length > 0 )
    {
      setCleanupSelected( new Set() );
    } else
    {
      setCleanupSelected( new Set( selectableResources.map( r => r.id ) ) );
    }
  };

  const totalRecords = cleanupResources.reduce( ( sum, r ) => sum + ( r.count > 0 ? r.count : 0 ), 0 );
  // Protected rows are excluded from the selection and therefore from this total, so the
  // figure in the confirmation dialog is what would actually be deleted rather than what was
  // ticked.
  const selectedRecords = selectableResources
    .filter( r => cleanupSelected.has( r.id ) )
    .reduce( ( sum, r ) => sum + ( r.count > 0 ? r.count : 0 ), 0 );
  const protectedCount = cleanupResources.length - selectableResources.length;

  const executeSystemCleanup = async () => {
    const ok = await confirm( {
      title: 'Deep Clean — Permanent Delete',
      message: (
        <div>
          <p style={ { color: '#0f2a1d', fontWeight: 500, marginBottom: 8 } }>
            Permanently delete { cleanupSelected.size } resource{ cleanupSelected.size !== 1 ? 's' : '' }
            { selectedRecords > 0 ? ` (~${selectedRecords.toLocaleString()} records)` : '' }?
          </p>
          <p>This wipes the selected DynamoDB tables and S3 folders. This action cannot be undone.</p>
        </div>
      ),
      confirmInput: 'CONFIRM DELETE',
      confirmText: 'Permanently Delete',
      danger: true,
    } );
    if ( !ok ) return;
    setCleanupRunning( true );
    // Filtered again at the point of sending, not just at the point of ticking. The two
    // guards answer different questions: the checkbox stops an operator choosing a
    // protected row, this stops a stale selection carrying one into the request after a
    // refresh changed what is protected.
    const selected = Array.from( cleanupSelected ).filter( id => {
      const resource = cleanupResources.find( r => r.id === id );
      return !resource || isSelectable( resource );
    } );
    try
    {
      const response = await api.executeCleanup( selected, confirmToken );
      if ( response.results && response.results.length > 0 )
      {
        setCleanupSelected( new Set() );
        // Refresh FIRST, then publish the results.
        //
        // `loadCleanupPreview` opens with `setCleanupResults( null )` — correct for a manual
        // refresh, and it was silently wiping the result list on every run, because the old
        // order set the results and then awaited the refresh. So the panel this tab renders
        // for `cleanupResults` never appeared after a cleanup, and the per-row outcome was
        // only ever visible in a toast total. The reordering is what makes the server's
        // protected/skipped counts reachable at all.
        await loadCleanupPreview();
        setCleanupResults( response.results );
        setCleanupSummary( {
          deleted: response.totalDeleted || 0,
          protected: response.protected || 0,
          skipped: response.skipped || 0,
        } );
        onRefresh();
        const deleted = response.totalDeleted || 0;
        const kept = response.protected || 0;
        toast.success( `Deep clean complete — ${deleted.toLocaleString()} records deleted`
          + ( kept > 0 ? `, ${kept} protected and kept` : '' ) );
      }
    } catch
    {
      setCleanupResults( selected.map( id => ( {
        id,
        label: cleanupResources.find( r => r.id === id )?.label || id,
        deleted: 0,
        error: 'Cleanup endpoint not available',
      } ) ) );
      toast.error( 'Cleanup endpoint not available' );
    } finally
    {
      setCleanupRunning( false );
    }
  };

  const categories = Array.from( new Set( cleanupResources.map( r => r.category ) ) );

  return (
    <div className="data-tab">
      <h3>Factory Reset · Deep Clean</h3>

      <div className="delete-panel">
        <div className="warning">
          Select any clearable cache or analytics table to permanently delete. Counts are live.
          Customer, financial and message history is protected by the server and cannot be selected here.
        </div>

        { confirmWarning && <div className="warning">{ confirmWarning }</div> }

        <div className="cleanup-header">
          <label className="cleanup-select-all">
            <input
              type="checkbox"
              checked={ cleanupSelected.size === selectableResources.length && selectableResources.length > 0 }
              onChange={ selectAllCleanup }
            />
            Select All
          </label>
          <span className="cleanup-count">
            { cleanupSelected.size } of { selectableResources.length } selected
            { selectedRecords > 0 ? ` · ~${selectedRecords.toLocaleString()} records` : '' }
            { protectedCount > 0 ? ` · ${protectedCount} protected` : '' }
          </span>
        </div>

        { cleanupLoading && <p className="cleanup-loading">Loading live resource counts…</p> }

        { !cleanupLoading && cleanupResources.length > 0 && (
          <>
            { categories.map( category => {
              const items = cleanupResources.filter( r => r.category === category );
              // The tri-state box reasons over the SELECTABLE rows only. A category of
              // nothing but protected rows is neither checked nor indeterminate — an
              // indeterminate dash there would offer a choice that does not exist.
              const catSelectable = items.filter( isSelectable );
              const allCatSelected = catSelectable.length > 0
                && catSelectable.every( r => cleanupSelected.has( r.id ) );
              const someCatSelected = catSelectable.some( r => cleanupSelected.has( r.id ) );
              return (
                <div key={ category } className="cleanup-category">
                  <label className="cleanup-category-label">
                    <input
                      type="checkbox"
                      checked={ allCatSelected }
                      disabled={ catSelectable.length === 0 }
                      ref={ el => { if ( el ) el.indeterminate = someCatSelected && !allCatSelected; } }
                      onChange={ () => toggleCleanupCategory( category ) }
                    />
                    { category }
                  </label>
                  { items.map( res => {
                    const selectable = isSelectable( res );
                    return (
                      <label
                        key={ res.id }
                        className={ `cleanup-item${selectable ? '' : ' cleanup-item-protected'}` }
                        aria-disabled={ selectable ? undefined : true }
                      >
                        <input
                          type="checkbox"
                          checked={ selectable && cleanupSelected.has( res.id ) }
                          disabled={ !selectable }
                          onChange={ () => toggleCleanupItem( res.id ) }
                        />
                        <span className="cleanup-item-label">{ res.label }</span>
                        { !selectable && (
                          // The reason travels with its own row rather than being a colour
                          // change, so it is readable by a screen reader and by anyone who
                          // cannot tell the two greys apart.
                          <span className="cleanup-item-reason">
                            { res.protectedReason || 'Protected by the server' }
                          </span>
                        ) }
                        <span className={ `cleanup-item-count ${res.count > 0 ? 'has-data' : ''}` }>
                          { res.count === -1 ? '—' : res.count.toLocaleString() }
                        </span>
                      </label>
                    );
                  } ) }
                </div>
              );
            } ) }
          </>
        ) }

        { cleanupResults && (
          <div className="cleanup-results">
            <p className="cleanup-results-title">Deep Clean Complete</p>
            { cleanupSummary && (
              // The SERVER's counts, not a client-side sum. `protected` and `skipped` are
              // the two numbers a client cannot compute, and they are the ones that say
              // whether the sweep left anything behind on purpose.
              <p className="cleanup-results-summary">
                { cleanupSummary.deleted.toLocaleString() } deleted
                { cleanupSummary.protected > 0 ? ` · ${cleanupSummary.protected} protected and kept` : '' }
                { cleanupSummary.skipped > 0 ? ` · ${cleanupSummary.skipped} skipped` : '' }
              </p>
            ) }
            { cleanupResults.map( r => (
              <div key={ r.id } className="cleanup-result-row">
                <span>{ r.label }</span>
                { /* Three outcomes, three renderings. A protected row is a CORRECT result
                     and must not read as a failure — folding it into the error style is how
                     a sweep that properly refused looks broken, and how someone then
                     "fixes" the refusal. */ }
                { r.error ? (
                  <span className="cleanup-result-error">Error: { r.error }</span>
                ) : r.protected ? (
                  <span className="cleanup-result-kept">
                    Kept — { r.protectedReason || 'protected by the server' }
                  </span>
                ) : (
                  <span className="cleanup-result-success">
                    { `${r.deleted} deleted${r.refused ? `, ${r.refused} kept (has payments — archive instead)` : ''}${r.elapsed ? ` (${r.elapsed}s)` : ''}` }
                  </span>
                ) }
              </div>
            ) ) }
          </div>
        ) }

        <div className="delete-actions">
          <Button variant="secondary" onClick={ loadCleanupPreview } disabled={ cleanupLoading }>Refresh Counts</Button>
          <Button
            variant="danger"
            onClick={ executeSystemCleanup }
            // No token means the server will refuse the POST, so the button is disabled
            // rather than offering a click that cannot succeed.
            disabled={ cleanupRunning || cleanupSelected.size === 0 || !confirmToken }
            loading={ cleanupRunning }
          >
            Deep Clean { cleanupSelected.size } Resource{ cleanupSelected.size !== 1 ? 's' : '' }
          </Button>
        </div>

        <div className="stats-grid" style={ { marginTop: '1rem' } }>
          <div className="stat-card"><div className="stat-value">{ selectableResources.length }</div><div className="stat-label">Clearable</div></div>
          <div className="stat-card"><div className="stat-value">{ protectedCount }</div><div className="stat-label">Protected</div></div>
          <div className="stat-card"><div className="stat-value">{ totalRecords.toLocaleString() }</div><div className="stat-label">Total Records</div></div>
          <div className="stat-card"><div className="stat-value">{ data.contacts.length }</div><div className="stat-label">Contacts</div></div>
        </div>
      </div>
    </div>
  );
};

export default DataTab;
