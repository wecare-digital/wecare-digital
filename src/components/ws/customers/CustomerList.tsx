/**
 * CustomerList — the fresh, mobile-first customer list for /ws/customers (FEAT-003).
 *
 * Loads the active customer set with api.listContacts and renders it as tappable rows (>=44px).
 * It carries the two LIST-level actions the user called out:
 *   - Bulk delete: a selection mode with checkbox rows and one confirm-gated bulk action
 *     (api.bulkDeleteContacts, which reports { deleted, failed }).
 *   - Per-row actions: each row opens CustomerActionsSheet (delete single / delete identity /
 *     delete a field / delete messages / block-archive), all confirm-gated and honouring the
 *     server ApiResult.
 * An "Manage data" control opens the reused CustomerManageData modal for the identity / merge /
 * archive review surface rather than reimplementing merge logic.
 *
 * On a confirmed soft-delete or archive the row is dropped from local state ONLY after the server
 * confirmed it; a refusal shows the server reason and leaves the row in place (handled in the
 * sheet / bulk handler). React 19: icons typed React.JSX.Element.
 */
import React from 'react';
import type { Contact } from '../../../api/client';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import CustomerManageData from '../../workspace/customers/ManageData';
import CustomerActionsSheet from './CustomerActionsSheet';

const SearchGlyph = (): React.JSX.Element => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
  </svg>
);

const DotsGlyph = (): React.JSX.Element => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="5" r="1.4" /><circle cx="12" cy="12" r="1.4" /><circle cx="12" cy="19" r="1.4" />
  </svg>
);

function initialsOf ( contact: Contact ): string {
  const source = ( contact.name || contact.phone || '?' ).trim();
  const parts = source.split( /\s+/ ).filter( Boolean );
  if ( parts.length >= 2 ) return ( parts[ 0 ][ 0 ] + parts[ 1 ][ 0 ] ).toUpperCase();
  return source.slice( 0, 2 ).toUpperCase();
}

const CustomerList: React.FC = () => {
  const toast = useToastContext();
  const confirm = useConfirm();

  const [ contacts, setContacts ] = React.useState<Contact[]>( [] );
  const [ loading, setLoading ] = React.useState( true );
  const [ error, setError ] = React.useState( '' );
  const [ query, setQuery ] = React.useState( '' );

  const [ selectMode, setSelectMode ] = React.useState( false );
  const [ selected, setSelected ] = React.useState<Set<string>>( new Set() );
  const [ bulkBusy, setBulkBusy ] = React.useState( false );

  const [ sheetFor, setSheetFor ] = React.useState<Contact | null>( null );
  const [ manageOpen, setManageOpen ] = React.useState( false );

  const load = React.useCallback( async () => {
    setLoading( true );
    setError( '' );
    try {
      // listContactsResult tells an empty table apart from a failed read; a failed read must not
      // render as "no customers".
      const result = await api.listContactsResult();
      if ( result.ok ) {
        setContacts( result.data );
      } else {
        setError( result.failure.message || 'Customers could not be loaded.' );
      }
    } catch {
      setError( 'Customers could not be loaded.' );
    } finally {
      setLoading( false );
    }
  }, [] );

  React.useEffect( () => { void load(); }, [ load ] );

  const filtered = React.useMemo( () => {
    const q = query.trim().toLowerCase();
    if ( !q ) return contacts;
    return contacts.filter( c =>
      ( c.name || '' ).toLowerCase().includes( q )
      || ( c.phone || '' ).toLowerCase().includes( q )
      || ( c.email || '' ).toLowerCase().includes( q ) );
  }, [ contacts, query ] );

  const dropRow = React.useCallback( ( contactId: string ) => {
    setContacts( prev => prev.filter( c => c.contactId !== contactId ) );
    setSelected( prev => { const next = new Set( prev ); next.delete( contactId ); return next; } );
  }, [] );

  const toggleSelect = ( id: string ) => {
    setSelected( prev => {
      const next = new Set( prev );
      if ( next.has( id ) ) next.delete( id ); else next.add( id );
      return next;
    } );
  };

  const exitSelect = () => { setSelectMode( false ); setSelected( new Set() ); };

  const bulkDelete = async () => {
    if ( bulkBusy || selected.size === 0 ) return;
    const ids = Array.from( selected );
    const locked = contacts.filter( c => ids.includes( c.contactId ) && c.locked ).length;
    if ( locked ) {
      toast.warning( `${locked} selected customer${ locked > 1 ? 's are' : ' is' } protected by a retention lock. Unlock before deleting.` );
      return;
    }
    const ok = await confirm( {
      title: `Delete ${ ids.length } customer${ ids.length > 1 ? 's' : '' }?`,
      message: `Delete ${ ids.length } selected customer${ ids.length > 1 ? 's' : '' } from active records? This is a soft delete; phones stay reserved and payment/order history is never erased. Any customer the server refuses (legal lock or linked payments) is kept and reported.`,
      confirmText: 'Delete selected',
      danger: true,
    } );
    if ( !ok ) return;
    setBulkBusy( true );
    try {
      // bulkDeleteContacts reports { deleted, failed }; a refused row counts as failed and is
      // kept. We re-read the authoritative list rather than guessing which rows went.
      const { deleted, failed } = await api.bulkDeleteContacts( ids );
      if ( deleted > 0 ) {
        toast.success( `Deleted ${ deleted } customer${ deleted > 1 ? 's' : '' }.${ failed > 0 ? ` ${ failed } kept (refused or failed).` : '' }` );
      } else {
        toast.error( `No customers deleted. ${ failed } kept (refused by the server or failed).` );
      }
      exitSelect();
      await load();
    } catch {
      toast.error( 'Bulk delete failed. No deletions were confirmed.' );
    } finally {
      setBulkBusy( false );
    }
  };

  return (
    <section className="cl">
      <header className="cl-head">
        <div className="cl-titlerow">
          <h1 className="cl-title">Customers</h1>
          <div className="cl-head-actions">
            <button type="button" className="cl-ghost" onClick={ () => setManageOpen( true ) }>
              Manage data
            </button>
            { selectMode ? (
              <button type="button" className="cl-ghost" onClick={ exitSelect }>Done</button>
            ) : (
              <button type="button" className="cl-ghost" onClick={ () => setSelectMode( true ) } disabled={ loading || contacts.length === 0 }>
                Select
              </button>
            ) }
          </div>
        </div>

        <label className="cl-search">
          <span className="cl-search-icon"><SearchGlyph /></span>
          <input
            type="search"
            className="cl-search-input"
            placeholder="Search name, phone or email"
            value={ query }
            onChange={ e => setQuery( e.target.value ) }
            aria-label="Search customers"
          />
        </label>
      </header>

      { loading ? (
        <p className="cl-note">Loading customers…</p>
      ) : error ? (
        <div className="cl-error" role="alert">
          <p>{ error }</p>
          <button type="button" className="cl-ghost" onClick={ () => void load() }>Retry</button>
        </div>
      ) : filtered.length === 0 ? (
        <p className="cl-note">{ query ? 'No customers match your search.' : 'No customers yet.' }</p>
      ) : (
        <ul className="cl-list" data-wc-no-translate="true">
          { filtered.map( c => {
            const isSel = selected.has( c.contactId );
            return (
              <li key={ c.contactId } className={ `cl-row ${ isSel ? 'sel' : '' }` }>
                { selectMode && (
                  <label className="cl-check">
                    <input
                      type="checkbox"
                      checked={ isSel }
                      onChange={ () => toggleSelect( c.contactId ) }
                      aria-label={ `Select ${ c.name || c.phone }` }
                    />
                  </label>
                ) }

                <button
                  type="button"
                  className="cl-rowmain"
                  onClick={ () => selectMode ? toggleSelect( c.contactId ) : setSheetFor( c ) }
                >
                  <span className="cl-avatar" aria-hidden="true">{ initialsOf( c ) }</span>
                  <span className="cl-meta">
                    <span className="cl-name">
                      { c.name || 'Unnamed customer' }
                      { c.locked && <span className="cl-badge">Locked</span> }
                    </span>
                    <span className="cl-sub">{ c.phone || 'No phone' }{ c.email ? ` · ${ c.email }` : '' }</span>
                  </span>
                </button>

                { !selectMode && (
                  <button
                    type="button"
                    className="cl-more"
                    onClick={ () => setSheetFor( c ) }
                    aria-label={ `Actions for ${ c.name || c.phone }` }
                  >
                    <DotsGlyph />
                  </button>
                ) }
              </li>
            );
          } ) }
        </ul>
      ) }

      { selectMode && selected.size > 0 && (
        <div className="cl-bulkbar" role="region" aria-label="Bulk actions">
          <span className="cl-bulkcount">{ selected.size } selected</span>
          <button type="button" className="cl-bulk-danger" disabled={ bulkBusy } onClick={ bulkDelete }>
            { bulkBusy ? 'Deleting…' : 'Delete selected' }
          </button>
        </div>
      ) }

      { sheetFor && (
        <CustomerActionsSheet
          contact={ sheetFor }
          onClose={ () => setSheetFor( null ) }
          onRemoved={ dropRow }
          onArchived={ dropRow }
          onChanged={ load }
        />
      ) }

      { manageOpen && (
        <CustomerManageData
          contacts={ contacts }
          onClose={ () => setManageOpen( false ) }
          onOpenCustomer={ ( id ) => {
            const found = contacts.find( c => c.contactId === id );
            setManageOpen( false );
            if ( found ) setSheetFor( found );
          } }
          onChanged={ load }
        />
      ) }

      <style jsx>{ `
        .cl{ width:100%; min-width:0; display:grid; gap:14px; }
        .cl-head{ display:grid; gap:12px; }
        .cl-titlerow{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
        .cl-title{ margin:0; font-size:24px; font-weight:700; letter-spacing:-0.5px; color:var(--text,#1a1a1a); }
        .cl-head-actions{ margin-left:auto; display:flex; gap:8px; }
        .cl-ghost{
          min-height:var(--tap-min,44px); padding:8px 14px; box-sizing:border-box;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-lg,12px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a);
          font:inherit; font-weight:600; font-size:14px; cursor:pointer;
        }
        .cl-ghost:hover:not(:disabled){ background:var(--bg-hover,#f5f5f5); }
        .cl-ghost:disabled{ opacity:0.5; cursor:not-allowed; }
        .cl-ghost:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }

        .cl-search{
          display:flex; align-items:center; gap:8px;
          min-height:var(--tap-min,44px); padding:0 14px; box-sizing:border-box;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-full,9999px);
          background:var(--surface,#fff);
        }
        .cl-search-icon{ display:inline-flex; color:var(--text-muted,#6b7280); flex:0 0 auto; }
        .cl-search-input{
          flex:1 1 auto; min-width:0; border:0; outline:none; background:transparent;
          font:inherit; font-size:16px; color:var(--text,#1a1a1a);
        }

        .cl-note{ margin:0; font-size:14px; color:var(--text-muted,#6b7280); }
        .cl-error{ display:grid; gap:10px; justify-items:start; padding:12px; border:1px solid var(--danger,#dc2626); border-radius:var(--radius-lg,12px); background:var(--danger-bg,#fef2f2); }
        .cl-error p{ margin:0; font-size:14px; color:var(--danger,#dc2626); }

        .cl-list{ list-style:none; margin:0; padding:0; display:grid; gap:8px; }
        .cl-row{
          display:flex; align-items:center; gap:4px; min-width:0;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-xl,14px);
          background:var(--surface,#fff); overflow:hidden;
        }
        .cl-row.sel{ border-color:var(--accent,#1a3a2a); background:var(--lime-tint,rgba(209,244,112,0.22)); }
        .cl-check{
          flex:0 0 auto; display:inline-flex; align-items:center; justify-content:center;
          min-width:var(--tap-min,44px); min-height:var(--tap-min,44px); padding-left:6px;
        }
        .cl-check input{ width:20px; height:20px; }
        .cl-rowmain{
          flex:1 1 auto; min-width:0; display:flex; align-items:center; gap:12px;
          padding:10px 12px; min-height:var(--tap-min,44px);
          border:0; background:transparent; text-align:left; cursor:pointer; font:inherit;
        }
        .cl-rowmain:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:-2px; }
        .cl-avatar{
          flex:0 0 auto; width:40px; height:40px; border-radius:var(--radius-full,9999px);
          display:inline-flex; align-items:center; justify-content:center;
          background:var(--lime,#d1f470); color:var(--accent,#1a3a2a);
          font-weight:700; font-size:13px;
        }
        .cl-meta{ min-width:0; display:grid; gap:2px; }
        .cl-name{
          font-weight:700; font-size:15px; color:var(--text,#1a1a1a);
          display:flex; align-items:center; gap:8px; min-width:0;
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }
        .cl-badge{
          flex:0 0 auto; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.4px;
          padding:2px 6px; border-radius:var(--radius-full,9999px);
          background:var(--danger-bg,#fef2f2); color:var(--danger,#dc2626);
        }
        .cl-sub{
          font-size:13px; color:var(--text-muted,#6b7280);
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }
        .cl-more{
          flex:0 0 auto; width:var(--tap-min,44px); height:var(--tap-min,44px);
          display:inline-flex; align-items:center; justify-content:center;
          border:0; background:transparent; color:var(--text-muted,#6b7280); cursor:pointer;
        }
        .cl-more:hover{ color:var(--accent,#1a3a2a); }
        .cl-more:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:-2px; }

        .cl-bulkbar{
          position:sticky; bottom:0; z-index:5;
          display:flex; align-items:center; gap:12px;
          padding:12px; margin-top:4px;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-xl,14px);
          background:var(--surface,#fff);
          box-shadow:0 -2px 12px rgba(0,0,0,0.06);
        }
        .cl-bulkcount{ font-size:14px; font-weight:600; color:var(--text,#1a1a1a); }
        .cl-bulk-danger{
          margin-left:auto; min-height:var(--tap-min,44px); padding:10px 18px; box-sizing:border-box;
          border:0; border-radius:var(--radius-lg,12px);
          background:var(--danger,#dc2626); color:#fff;
          font:inherit; font-weight:700; font-size:14px; cursor:pointer;
        }
        .cl-bulk-danger:disabled{ opacity:0.6; cursor:not-allowed; }
        .cl-bulk-danger:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }
      ` }</style>
    </section>
  );
};

export default CustomerList;
