/**
 * Appointments Admin Page — [retired public path]/appointments
 * AppointmentTable: status management, filters, detail panel
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
import DateField from '../../../../components/ui/DateField';
import TimeField from '../../../../components/ui/TimeField';
import { useToastContext } from '../../../../contexts/ToastContext';
import { isValidPhone, isNotPastDate, getTodayISO, normalizePhone } from '../../../../utils/validation';
import * as api from '../../../../api/client';

const PAGE_SIZE = 20;
const STATUS_OPTIONS = [ 'scheduled', 'confirmed', 'in_progress', 'completed', 'cancelled', 'no_show' ];
const TYPE_OPTIONS = [ 'consultation', 'follow_up', 'procedure', 'checkup', 'other' ];

/* The option lists, hoisted. Same order, same values, same visible text as the rows they
   replaced, including the two '' placeholder rows the filters read as "no filter". */
const STATUS_SELECT_OPTIONS: SelectOption[] = STATUS_OPTIONS.map(
  s => ( { value: s, label: s.replace( /_/g, ' ' ) } )
);
const TYPE_SELECT_OPTIONS: SelectOption[] = TYPE_OPTIONS.map( t => ( { value: t, label: t } ) );
const STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  ...STATUS_SELECT_OPTIONS,
];
const TYPE_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Types' },
  ...TYPE_OPTIONS.map( s => ( { value: s, label: s.replace( /_/g, ' ' ) } ) ),
];

/* LAYOUT ONLY. The in-table control fills its 130px column; the two filters are flex
   children and need a width, because the trigger shows the selected label while a native
   select sized itself to its widest option. */
const CELL_SELECT_STYLE: React.CSSProperties = { width: '100%' };
const FILTER_STYLE: React.CSSProperties = { width: 170 };
/* The 14px the wrapping <label> set on the create-modal date/time pair, carried on the field
   wrapper so the label text and the control keep the type size they render at today. */
const FIELD_STYLE: React.CSSProperties = { fontSize: 14 };

function formatDate ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' } );
}

function statusBadge ( status: string ) {
  const colors: Record<string, { bg: string; fg: string }> = {
    scheduled: { bg: '#dbeafe', fg: '#1e40af' },
    confirmed: { bg: '#d1f470', fg: '#1a3a2a' },
    in_progress: { bg: '#fef3c7', fg: '#92400e' },
    completed: { bg: '#d1fae5', fg: '#065f46' },
    cancelled: { bg: '#fee2e2', fg: '#991b1b' },
    no_show: { bg: '#f3e8ff', fg: '#6b21a8' },
  };
  const c = colors[ status ] || { bg: '#f3f4f6', fg: '#374151' };
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 12, fontWeight: 600, background: c.bg, color: c.fg } }>{ status.replace( /_/g, ' ' ) }</span>;
}

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const AppointmentsPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ items, setItems ] = useState<api.Appointment[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ typeFilter, setTypeFilter ] = useState( '' );
  const [ page, setPage ] = useState( 1 );
  const [ selected, setSelected ] = useState<api.Appointment | null>( null );
  const [ showCreate, setShowCreate ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ createForm, setCreateForm ] = useState( { customerName: '', customerPhone: '', type: 'consultation', slotDate: '', slotTime: '', location: '', duration: 30, notes: '' } );

  const loadData = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listAppointments( { status: statusFilter || undefined, type: typeFilter || undefined } );
      setItems( data.appointments || [] );
    } catch { toast.error( 'Failed to load appointments' ); }
    setLoading( false );
  }, [ statusFilter, typeFilter, toast ] );

  useEffect( () => { loadData(); }, [ loadData ] );

  const handleStatusUpdate = async ( id: string, status: string ) => {
    const ok = await api.updateAppointment( id, { status } );
    if ( ok ) { toast.success( `Updated to ${status}` ); loadData(); }
    else toast.error( 'Update failed' );
  };

  const totalPages = Math.ceil( items.length / PAGE_SIZE );
  const paged = items.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  const columns = [
    {
      key: 'appointmentId', header: 'ID', width: '100px', render: ( a: api.Appointment ) => (
        <button onClick={ () => setSelected( a ) } style={ { background: 'none', border: 'none', color: '#1a3a2a', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline', padding: 0, fontSize: 13 } }>
          { a.appointmentId.slice( 0, 8 ) }
        </button>
      )
    },
    { key: 'scheduledAt', header: 'Scheduled', width: '150px', render: ( a: api.Appointment ) => formatDate( a.scheduledAt ) },
    {
      key: 'customerName', header: 'Customer', render: ( a: api.Appointment ) => (
        <div><div style={ { fontWeight: 500 } }>{ a.customerName || '—' }</div><div style={ { fontSize: 12, color: '#6b7280' } }>{ a.customerPhone }</div></div>
      )
    },
    { key: 'type', header: 'Type', width: '110px', render: ( a: api.Appointment ) => a.type },
    { key: 'provider', header: 'Provider', width: '120px', render: ( a: api.Appointment ) => a.provider || '—' },
    { key: 'duration', header: 'Duration', width: '80px', render: ( a: api.Appointment ) => a.duration ? `${a.duration}m` : '—' },
    {
      key: 'status', header: 'Status', width: '130px', render: ( a: api.Appointment ) => (
        <Select ariaLabel="Appointment status" value={ a.status }
          onChange={ v => handleStatusUpdate( a.appointmentId, v ) }
          options={ STATUS_SELECT_OPTIONS } style={ CELL_SELECT_STYLE } />
      )
    },
  ];

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.appointments } />
      <div style={ { padding: '24px 32px', maxWidth: 1400 } }>
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 } }>
          <div>
            <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: 0 } }>Appointments</h1>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '4px 0 0' } }>{ items.length } appointments</p>
          </div>
          <div style={ { display: 'flex', gap: 8 } }>
            <Button variant="secondary" icon="refresh" onClick={ loadData }>Refresh</Button>
            <Button variant="primary" icon="create" onClick={ () => setShowCreate( true ) }>New Appointment</Button>
          </div>
        </div>

        <div style={ { display: 'flex', gap: 12, marginBottom: 16 } }>
          <Select ariaLabel="Appointment status" value={ statusFilter }
            onChange={ v => { setStatusFilter( v ); setPage( 1 ); } }
            options={ STATUS_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <Select ariaLabel="Appointment type" value={ typeFilter }
            onChange={ v => { setTypeFilter( v ); setPage( 1 ); } }
            options={ TYPE_FILTER_OPTIONS } style={ FILTER_STYLE } />
        </div>

        { items.length === 0 && !loading ? (
          <EmptyState icon="default" title="No appointments" description="Appointments will appear here when created" />
        ) : (
          <>
            <Table columns={ columns } data={ paged } keyField="appointmentId" loading={ loading } />
            { totalPages > 1 && <div style={ { marginTop: 16, display: 'flex', justifyContent: 'center' } }><Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } /></div> }
          </>
        ) }
      </div>

      <Modal isOpen={ !!selected } onClose={ () => setSelected( null ) } title={ `Appointment ${selected?.appointmentId?.slice( 0, 8 ) || ''}` } size="md">
        { selected && (
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <div><span style={ labelStyle }>Customer</span><div style={ { fontWeight: 500 } }>{ selected.customerName || '—' }</div></div>
            <div><span style={ labelStyle }>Phone</span><div>{ selected.customerPhone || '—' }</div></div>
            <div><span style={ labelStyle }>Type</span><div>{ selected.type }</div></div>
            <div><span style={ labelStyle }>Provider</span><div>{ selected.provider || '—' }</div></div>
            <div><span style={ labelStyle }>Scheduled</span><div>{ formatDate( selected.scheduledAt ) }</div></div>
            <div><span style={ labelStyle }>Duration</span><div>{ selected.duration ? `${selected.duration} min` : '—' }</div></div>
            <div><span style={ labelStyle }>Status</span><div>{ statusBadge( selected.status ) }</div></div>
            <div><span style={ labelStyle }>Location</span><div>{ selected.location || '—' }</div></div>
            { selected.notes && <div style={ { gridColumn: '1 / -1' } }><span style={ labelStyle }>Notes</span><div style={ { padding: 8, background: '#f9fafb', borderRadius: 6, fontSize: 14 } }>{ selected.notes }</div></div> }
          </div>
        ) }
      </Modal>

      {/* Create Appointment Modal */ }
      <Modal isOpen={ showCreate } onClose={ () => setShowCreate( false ) } title="New Appointment" size="md" footer={
        <><Button variant="secondary" onClick={ () => setShowCreate( false ) }>Cancel</Button><Button variant="primary" loading={ creating } onClick={ async () => {
          if ( !createForm.customerPhone ) { toast.error( 'Phone is required' ); return; }
          if ( !isValidPhone( createForm.customerPhone ) ) { toast.error( 'Enter a valid phone number (e.g. +91 9876543210)' ); return; }
          if ( !createForm.slotDate ) { toast.error( 'Date is required' ); return; }
          if ( !isNotPastDate( createForm.slotDate ) ) { toast.error( 'Date cannot be in the past' ); return; }
          setCreating( true );
          const apt = await api.createAppointment( { customerName: createForm.customerName, customerPhone: normalizePhone( createForm.customerPhone ), type: createForm.type, slotDate: createForm.slotDate, slotTime: createForm.slotTime, location: createForm.location, duration: createForm.duration, notes: createForm.notes, status: 'scheduled' } as any );
          if ( apt ) { toast.success( 'Appointment created' ); setShowCreate( false ); setCreateForm( { customerName: '', customerPhone: '', type: 'consultation', slotDate: '', slotTime: '', location: '', duration: 30, notes: '' } ); loadData(); }
          else toast.error( 'Failed to create' );
          setCreating( false );
        } }>Create</Button></>
      }>
        <div style={ { display: 'flex', flexDirection: 'column', gap: 14 } }>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <label style={ { fontSize: 14 } }>Customer Name<input type="text" value={ createForm.customerName } onChange={ e => setCreateForm( f => ( { ...f, customerName: e.target.value } ) ) } style={ inputStyle } /></label>
            <label style={ { fontSize: 14 } }>Phone *<input type="tel" value={ createForm.customerPhone } onChange={ e => setCreateForm( f => ( { ...f, customerPhone: e.target.value } ) ) } placeholder="+91 9876543210" style={ { ...inputStyle, borderColor: createForm.customerPhone && !isValidPhone( createForm.customerPhone ) ? '#dc2626' : '#e5e7eb' } } />{ createForm.customerPhone && !isValidPhone( createForm.customerPhone ) && <span style={ { fontSize: 11, color: '#dc2626', marginTop: 2 } }>Invalid phone format</span> }</label>
          </div>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            { /* SHAPE (a), design 5.2 - the wrapping <label> is gone and Select owns the pair. */ }
            <Select label="Type" value={ createForm.type }
              onChange={ v => setCreateForm( f => ( { ...f, type: v } ) ) }
              options={ TYPE_SELECT_OPTIONS } />
            <label style={ { fontSize: 14 } }>Location<input type="text" value={ createForm.location } onChange={ e => setCreateForm( f => ( { ...f, location: e.target.value } ) ) } style={ inputStyle } /></label>
          </div>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 } }>
            { /* SHAPE (a) for both: the wrapping <label> is gone and each component owns its
                 label/control pair. `min={ getTodayISO() }` is a first-class DateField prop and
                 is now enforced in TWO places the native input never enforced it - the calendar
                 grid disables an out-of-range day, and the type-in parse refuses one - which is
                 why the past-date message below can only ever appear for a value that was
                 already in state when the page loaded.
                 THE PAST-DATE ERROR STYLING IS UNCHANGED, DELIBERATELY. It stays `invalid`
                 driving a `border-color` and NOT a `border` shorthand: `border-color` is outside
                 form-controls.css's !important set precisely so a validity colour still wins,
                 and a shorthand would set the colour too and silently erase it. */ }
            <div style={ { fontSize: 14 } }>
              <DateField label="Date *" value={ createForm.slotDate } min={ getTodayISO() }
                invalid={ !!createForm.slotDate && !isNotPastDate( createForm.slotDate ) }
                onChange={ v => setCreateForm( f => ( { ...f, slotDate: v } ) ) } />
              { createForm.slotDate && !isNotPastDate( createForm.slotDate ) && <span style={ { fontSize: 11, color: '#dc2626', marginTop: 2 } }>Cannot be in the past</span> }
            </div>
            <TimeField label="Time" value={ createForm.slotTime }
              onChange={ v => setCreateForm( f => ( { ...f, slotTime: v } ) ) }
              style={ FIELD_STYLE } />
            <label style={ { fontSize: 14 } }>Duration (min)<input type="number" value={ createForm.duration } min={ 5 } max={ 480 } onChange={ e => setCreateForm( f => ( { ...f, duration: Number( e.target.value ) } ) ) } style={ inputStyle } /></label>
          </div>
          <label style={ { fontSize: 14 } }>Notes<textarea value={ createForm.notes } onChange={ e => setCreateForm( f => ( { ...f, notes: e.target.value } ) ) } rows={ 2 } style={ { ...inputStyle, resize: 'vertical' } } /></label>
        </div>
      </Modal>
    </MaybeLayout>
  );
};

/* `selectStyle` went with the last native select in this file - it only ever skinned those.
   THE PAST-DATE ERROR IS STILL A BORDER-COLOUR AND NOTHING ELSE, which is the one thing this
   file's date control was not allowed to lose. It used to be an inline `borderColor` on the
   native input; it is now DateField's `invalid` prop, which resolves to
   `.ui-date-input[aria-invalid="true"] { border-color: var(--danger) }` in form-controls.css.
   Same property, same single property - still not a `border` shorthand, because a shorthand
   sets the colour too and would erase the error it is meant to show. The message <span>'s own
   11px / #dc2626 styling is byte-for-byte what it was. */
const labelStyle: React.CSSProperties = { fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 2 };
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 4 };

export default AppointmentsPage;
