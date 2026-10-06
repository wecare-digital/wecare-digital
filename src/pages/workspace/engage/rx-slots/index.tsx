/**
 * RX Slots Admin Page — [retired public path]/rx-slots
 * Slot management: list, filter, create, status updates
 */
import React, { useState, useEffect, useCallback } from 'react';
import MaybeLayout from '../../../../components/MaybeLayout';
import SEO, { PAGE_SEO } from '../../../../components/SEO';
import Table from '../../../../components/ui/Table';
import Modal from '../../../../components/ui/Modal';
import Button from '../../../../components/ui/Button';
import Pagination from '../../../../components/ui/Pagination';
import EmptyState from '../../../../components/ui/EmptyState';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';

const PAGE_SIZE = 20;
const STATUS_OPTIONS = [ 'available', 'booked', 'blocked', 'completed' ];

/* Hoisted option rows. Same order, same values, same visible text, with the filter's ''
   placeholder row kept first. */
const STATUS_SELECT_OPTIONS: SelectOption[] = STATUS_OPTIONS.map( s => ( { value: s, label: s } ) );
const STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  ...STATUS_SELECT_OPTIONS,
];

/* LAYOUT ONLY. The in-table control fills its 120px column; the filter is a flex child
   beside a date input, and a native select sized itself to its widest option. */
const CELL_SELECT_STYLE: React.CSSProperties = { width: '100%' };
const FILTER_STYLE: React.CSSProperties = { width: 170 };

function statusBadge ( status: string ) {
  const colors: Record<string, { bg: string; fg: string }> = {
    available: { bg: '#d1f470', fg: '#1a3a2a' },
    booked: { bg: '#dbeafe', fg: '#1e40af' },
    blocked: { bg: '#fee2e2', fg: '#991b1b' },
    completed: { bg: '#d1fae5', fg: '#065f46' },
  };
  const c = colors[ status ] || { bg: '#f3f4f6', fg: '#374151' };
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 12, fontWeight: 600, background: c.bg, color: c.fg } }>{ status }</span>;
}

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const RxSlotsPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ slots, setSlots ] = useState<api.RxSlot[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ dateFilter, setDateFilter ] = useState( '' );
  const [ page, setPage ] = useState( 1 );
  const [ selected, setSelected ] = useState<api.RxSlot | null>( null );
  const [ showCreate, setShowCreate ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ form, setForm ] = useState( { date: '', time: '', duration: 30, provider: '', notes: '' } );

  const loadData = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listRxSlots( { status: statusFilter || undefined, date: dateFilter || undefined } );
      setSlots( data.slots || [] );
    } catch { toast.error( 'Failed to load slots' ); }
    setLoading( false );
  }, [ statusFilter, dateFilter, toast ] );

  useEffect( () => { loadData(); }, [ loadData ] );

  const handleStatusUpdate = async ( id: string, status: string ) => {
    const ok = await api.updateRxSlot( id, { status } );
    if ( ok ) { toast.success( `Slot updated to ${status}` ); loadData(); }
    else toast.error( 'Update failed' );
  };

  const handleCreate = async () => {
    if ( !form.date || !form.time ) { toast.error( 'Date and time are required' ); return; }
    setCreating( true );
    const slot = await api.createRxSlot( { date: form.date, time: form.time, duration: form.duration, provider: form.provider, notes: form.notes, status: 'available' } );
    if ( slot ) { toast.success( 'Slot created' ); setShowCreate( false ); setForm( { date: '', time: '', duration: 30, provider: '', notes: '' } ); loadData(); }
    else toast.error( 'Failed to create slot' );
    setCreating( false );
  };

  const totalPages = Math.ceil( slots.length / PAGE_SIZE );
  const paged = slots.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  const columns = [
    {
      key: 'slotId', header: 'ID', width: '90px', render: ( s: api.RxSlot ) => (
        <button onClick={ () => setSelected( s ) } style={ { background: 'none', border: 'none', color: '#1a3a2a', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline', padding: 0, fontSize: 13 } }>
          { s.slotId.slice( 0, 8 ) }
        </button>
      )
    },
    { key: 'date', header: 'Date', width: '110px' },
    { key: 'time', header: 'Time', width: '80px' },
    { key: 'duration', header: 'Duration', width: '80px', render: ( s: api.RxSlot ) => s.duration ? `${s.duration}m` : '—' },
    { key: 'provider', header: 'Provider', width: '120px', render: ( s: api.RxSlot ) => s.provider || '—' },
    {
      key: 'patientName', header: 'Patient', render: ( s: api.RxSlot ) => (
        <div><div style={ { fontWeight: 500 } }>{ s.patientName || '—' }</div><div style={ { fontSize: 12, color: '#6b7280' } }>{ s.patientPhone }</div></div>
      )
    },
    {
      key: 'status', header: 'Status', width: '120px', render: ( s: api.RxSlot ) => (
        <Select ariaLabel="Slot status" value={ s.status }
          onChange={ v => handleStatusUpdate( s.slotId, v ) }
          options={ STATUS_SELECT_OPTIONS } style={ CELL_SELECT_STYLE } />
      )
    },
  ];

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.rxSlots } />
      <div style={ { padding: '24px 32px', maxWidth: 1400 } }>
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 } }>
          <div>
            <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: 0 } }>RX Slots</h1>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '4px 0 0' } }>{ slots.length } slots</p>
          </div>
          <div style={ { display: 'flex', gap: 8 } }>
            <Button variant="secondary" icon="refresh" onClick={ loadData }>Refresh</Button>
            <Button variant="primary" icon="create" onClick={ () => setShowCreate( true ) }>Add Slot</Button>
          </div>
        </div>

        <div style={ { display: 'flex', gap: 12, marginBottom: 16 } }>
          <Select ariaLabel="Slot status" value={ statusFilter }
            onChange={ v => { setStatusFilter( v ); setPage( 1 ); } }
            options={ STATUS_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <input type="date" value={ dateFilter } onChange={ e => { setDateFilter( e.target.value ); setPage( 1 ); } } style={ selectStyle } />
        </div>

        { slots.length === 0 && !loading ? (
          <EmptyState icon="default" title="No slots" description="Create slots for scheduling" action={ { label: 'Add Slot', onClick: () => setShowCreate( true ) } } />
        ) : (
          <>
            <Table columns={ columns } data={ paged } keyField="slotId" loading={ loading } />
            { totalPages > 1 && <div style={ { marginTop: 16, display: 'flex', justifyContent: 'center' } }><Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } /></div> }
          </>
        ) }
      </div>

      {/* Detail */ }
      <Modal isOpen={ !!selected } onClose={ () => setSelected( null ) } title={ `Slot ${selected?.slotId?.slice( 0, 8 ) || ''}` } size="md">
        { selected && (
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <div><span style={ labelStyle }>Date</span><div>{ selected.date }</div></div>
            <div><span style={ labelStyle }>Time</span><div>{ selected.time }</div></div>
            <div><span style={ labelStyle }>Duration</span><div>{ selected.duration ? `${selected.duration} min` : '—' }</div></div>
            <div><span style={ labelStyle }>Provider</span><div>{ selected.provider || '—' }</div></div>
            <div><span style={ labelStyle }>Status</span><div>{ statusBadge( selected.status ) }</div></div>
            <div><span style={ labelStyle }>Patient</span><div>{ selected.patientName || '—' } { selected.patientPhone ? `(${selected.patientPhone})` : '' }</div></div>
            { selected.notes && <div style={ { gridColumn: '1 / -1' } }><span style={ labelStyle }>Notes</span><div style={ { padding: 8, background: '#f9fafb', borderRadius: 6, fontSize: 14 } }>{ selected.notes }</div></div> }
          </div>
        ) }
      </Modal>

      {/* Create */ }
      <Modal isOpen={ showCreate } onClose={ () => setShowCreate( false ) } title="Add Slot" size="md" footer={
        <><Button variant="secondary" onClick={ () => setShowCreate( false ) }>Cancel</Button><Button variant="primary" loading={ creating } onClick={ handleCreate }>Create</Button></>
      }>
        <div style={ { display: 'flex', flexDirection: 'column', gap: 14 } }>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <label style={ { fontSize: 14 } }>Date *<input type="date" value={ form.date } onChange={ e => setForm( f => ( { ...f, date: e.target.value } ) ) } style={ inputStyle } /></label>
            <label style={ { fontSize: 14 } }>Time *<input type="time" value={ form.time } onChange={ e => setForm( f => ( { ...f, time: e.target.value } ) ) } style={ inputStyle } /></label>
          </div>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <label style={ { fontSize: 14 } }>Duration (min)<input type="number" value={ form.duration } onChange={ e => setForm( f => ( { ...f, duration: Number( e.target.value ) } ) ) } style={ inputStyle } /></label>
            <label style={ { fontSize: 14 } }>Provider<input type="text" value={ form.provider } onChange={ e => setForm( f => ( { ...f, provider: e.target.value } ) ) } style={ inputStyle } /></label>
          </div>
          <label style={ { fontSize: 14 } }>Notes<textarea value={ form.notes } onChange={ e => setForm( f => ( { ...f, notes: e.target.value } ) ) } rows={ 2 } style={ { ...inputStyle, resize: 'vertical' } } /></label>
        </div>
      </Modal>
    </MaybeLayout>
  );
};

const selectStyle: React.CSSProperties = { padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14 };
const labelStyle: React.CSSProperties = { fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 2 };
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 4 };

export default RxSlotsPage;
