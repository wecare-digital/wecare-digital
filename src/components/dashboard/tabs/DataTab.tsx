/**
 * Factory Reset Tab — single Deep Clean tool.
 * Lists EVERY DynamoDB table and S3 folder (auto-discovered by the backend) with live
 * record counts, lets you select any/all of them, and permanently deletes on confirm.
 * SystemConfig is always preserved.
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

  const loadCleanupPreview = useCallback( async () => {
    setCleanupLoading( true );
    setCleanupResults( null );
    try
    {
      const resources = await api.getCleanupPreview();
      setCleanupResources( resources && resources.length > 0 ? resources : CLEANUP_FALLBACK );
    } catch
    {
      setCleanupResources( CLEANUP_FALLBACK );
    } finally
    {
      setCleanupLoading( false );
    }
  }, [] );

  // Load live counts as soon as the tab opens (real-time view).
  useEffect( () => { loadCleanupPreview(); }, [ loadCleanupPreview ] );

  const toggleCleanupItem = ( id: string ) => {
    setCleanupSelected( prev => {
      const next = new Set( prev );
      if ( next.has( id ) ) next.delete( id ); else next.add( id );
      return next;
    } );
  };

  const toggleCleanupCategory = ( category: string ) => {
    const items = cleanupResources.filter( r => r.category === category );
    const allSelected = items.every( r => cleanupSelected.has( r.id ) );
    setCleanupSelected( prev => {
      const next = new Set( prev );
      items.forEach( r => { if ( allSelected ) next.delete( r.id ); else next.add( r.id ); } );
      return next;
    } );
  };

  const selectAllCleanup = () => {
    if ( cleanupSelected.size === cleanupResources.length )
    {
      setCleanupSelected( new Set() );
    } else
    {
      setCleanupSelected( new Set( cleanupResources.map( r => r.id ) ) );
    }
  };

  const totalRecords = cleanupResources.reduce( ( sum, r ) => sum + ( r.count > 0 ? r.count : 0 ), 0 );
  const selectedRecords = cleanupResources
    .filter( r => cleanupSelected.has( r.id ) )
    .reduce( ( sum, r ) => sum + ( r.count > 0 ? r.count : 0 ), 0 );

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
    const selected = Array.from( cleanupSelected );
    try
    {
      const response = await api.executeCleanup( selected );
      if ( response.results && response.results.length > 0 )
      {
        setCleanupResults( response.results );
        setCleanupSelected( new Set() );
        await loadCleanupPreview();
        onRefresh();
        const deleted = response.results.reduce( ( s, r ) => s + ( r.deleted || 0 ), 0 );
        toast.success( `Deep clean complete — ${deleted.toLocaleString()} records deleted` );
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
          Select any tables and S3 folders to permanently delete. Counts are live. SystemConfig is always preserved.
        </div>

        <div className="cleanup-header">
          <label className="cleanup-select-all">
            <input
              type="checkbox"
              checked={ cleanupSelected.size === cleanupResources.length && cleanupResources.length > 0 }
              onChange={ selectAllCleanup }
            />
            Select All
          </label>
          <span className="cleanup-count">
            { cleanupSelected.size } of { cleanupResources.length } selected
            { selectedRecords > 0 ? ` · ~${selectedRecords.toLocaleString()} records` : '' }
          </span>
        </div>

        { cleanupLoading && <p className="cleanup-loading">Loading live resource counts…</p> }

        { !cleanupLoading && cleanupResources.length > 0 && (
          <>
            { categories.map( category => {
              const items = cleanupResources.filter( r => r.category === category );
              const allCatSelected = items.every( r => cleanupSelected.has( r.id ) );
              const someCatSelected = items.some( r => cleanupSelected.has( r.id ) );
              return (
                <div key={ category } className="cleanup-category">
                  <label className="cleanup-category-label">
                    <input
                      type="checkbox"
                      checked={ allCatSelected }
                      ref={ el => { if ( el ) el.indeterminate = someCatSelected && !allCatSelected; } }
                      onChange={ () => toggleCleanupCategory( category ) }
                    />
                    { category }
                  </label>
                  { items.map( res => (
                    <label key={ res.id } className="cleanup-item">
                      <input type="checkbox" checked={ cleanupSelected.has( res.id ) } onChange={ () => toggleCleanupItem( res.id ) } />
                      <span className="cleanup-item-label">{ res.label }</span>
                      <span className={ `cleanup-item-count ${res.count > 0 ? 'has-data' : ''}` }>
                        { res.count === -1 ? '—' : res.count.toLocaleString() }
                      </span>
                    </label>
                  ) ) }
                </div>
              );
            } ) }
          </>
        ) }

        { cleanupResults && (
          <div className="cleanup-results">
            <p className="cleanup-results-title">Deep Clean Complete</p>
            { cleanupResults.map( r => (
              <div key={ r.id } className="cleanup-result-row">
                <span>{ r.label }</span>
                <span className={ r.error ? 'cleanup-result-error' : 'cleanup-result-success' }>
                  { r.error
                    ? `Error: ${r.error}`
                    : `${r.deleted} deleted${r.refused ? `, ${r.refused} kept (has payments — archive instead)` : ''}${r.elapsed ? ` (${r.elapsed}s)` : ''}` }
                </span>
              </div>
            ) ) }
          </div>
        ) }

        <div className="delete-actions">
          <Button variant="secondary" onClick={ loadCleanupPreview } disabled={ cleanupLoading }>Refresh Counts</Button>
          <Button
            variant="danger"
            onClick={ executeSystemCleanup }
            disabled={ cleanupRunning || cleanupSelected.size === 0 }
            loading={ cleanupRunning }
          >
            Deep Clean { cleanupSelected.size } Resource{ cleanupSelected.size !== 1 ? 's' : '' }
          </Button>
        </div>

        <div className="stats-grid" style={ { marginTop: '1rem' } }>
          <div className="stat-card"><div className="stat-value">{ cleanupResources.length }</div><div className="stat-label">Resources</div></div>
          <div className="stat-card"><div className="stat-value">{ totalRecords.toLocaleString() }</div><div className="stat-label">Total Records</div></div>
          <div className="stat-card"><div className="stat-value">{ data.contacts.length }</div><div className="stat-label">Contacts</div></div>
        </div>
      </div>
    </div>
  );
};

export default DataTab;
