/**
 * Enterprise Assist Admin Page — [retired public path]/enterprise
 * Case management: list, filter, detail panel, status/priority updates
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
import { isValidPhone, isValidEmail, normalizePhone } from '../../../../utils/validation';
import * as api from '../../../../api/client';

const PAGE_SIZE = 20;
const STATUS_OPTIONS = [ 'open', 'in_progress', 'waiting', 'resolved', 'closed' ];
const PRIORITY_OPTIONS = [ 'low', 'medium', 'high', 'critical' ];

/* The option lists, hoisted. Same order, same values, same visible text as the rows they
   replaced - including the two '' placeholder rows the filters read as "no filter". */
const STATUS_SELECT_OPTIONS: SelectOption[] = STATUS_OPTIONS.map(
  s => ( { value: s, label: s.replace( /_/g, ' ' ) } )
);
const PRIORITY_SELECT_OPTIONS: SelectOption[] = PRIORITY_OPTIONS.map( p => ( { value: p, label: p } ) );
const STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  ...STATUS_SELECT_OPTIONS,
];
const PRIORITY_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Priorities' },
  ...PRIORITY_SELECT_OPTIONS,
];

/* LAYOUT ONLY. The two in-table controls fill their 100px/130px column; the two filters are
   flex children and need a width, because the trigger shows the selected label while a
   native select sized itself to its widest option. */
const CELL_SELECT_STYLE: React.CSSProperties = { width: '100%' };
const FILTER_STYLE: React.CSSProperties = { width: 170 };

function formatDate ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' } );
}

function statusBadge ( status: string ) {
  const colors: Record<string, { bg: string; fg: string }> = {
    open: { bg: '#dbeafe', fg: '#1e40af' },
    in_progress: { bg: '#fef3c7', fg: '#92400e' },
    waiting: { bg: '#f3e8ff', fg: '#6b21a8' },
    resolved: { bg: '#d1f470', fg: '#1a3a2a' },
    closed: { bg: '#f3f4f6', fg: '#374151' },
  };
  const c = colors[ status ] || { bg: '#f3f4f6', fg: '#374151' };
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 12, fontWeight: 600, background: c.bg, color: c.fg } }>{ status.replace( /_/g, ' ' ) }</span>;
}

function priorityBadge ( priority: string ) {
  const colors: Record<string, { bg: string; fg: string }> = {
    low: { bg: '#f3f4f6', fg: '#374151' },
    medium: { bg: '#fef3c7', fg: '#92400e' },
    high: { bg: '#fed7aa', fg: '#9a3412' },
    critical: { bg: '#fee2e2', fg: '#991b1b' },
  };
  const c = colors[ priority ] || { bg: '#f3f4f6', fg: '#374151' };
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 12, fontWeight: 600, background: c.bg, color: c.fg } }>{ priority }</span>;
}

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const EnterprisePage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ cases, setCases ] = useState<api.EnterpriseCase[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ priorityFilter, setPriorityFilter ] = useState( '' );
  const [ page, setPage ] = useState( 1 );
  const [ selected, setSelected ] = useState<api.EnterpriseCase | null>( null );
  const [ showCreate, setShowCreate ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ createForm, setCreateForm ] = useState( { customerName: '', customerPhone: '', contactEmail: '', accountName: '', subject: '', description: '', priority: 'normal' } );

  const loadData = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listEnterpriseCases( { status: statusFilter || undefined, priority: priorityFilter || undefined } );
      setCases( data.cases || [] );
    } catch { toast.error( 'Failed to load cases' ); }
    setLoading( false );
  }, [ statusFilter, priorityFilter, toast ] );

  useEffect( () => { loadData(); }, [ loadData ] );

  const handleStatusUpdate = async ( id: string, status: string ) => {
    const ok = await api.updateEnterpriseCase( id, { status } );
    if ( ok ) { toast.success( `Case updated to ${status}` ); loadData(); }
    else toast.error( 'Update failed' );
  };

  const handlePriorityUpdate = async ( id: string, priority: string ) => {
    const ok = await api.updateEnterpriseCase( id, { priority } );
    if ( ok ) { toast.success( `Priority set to ${priority}` ); loadData(); }
    else toast.error( 'Update failed' );
  };

  const totalPages = Math.ceil( cases.length / PAGE_SIZE );
  const paged = cases.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  const columns = [
    {
      key: 'caseId', header: 'Case', width: '100px', render: ( c: api.EnterpriseCase ) => (
        <button onClick={ () => setSelected( c ) } style={ { background: 'none', border: 'none', color: '#1a3a2a', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline', padding: 0, fontSize: 13 } }>
          { c.caseId.slice( 0, 8 ) }
        </button>
      )
    },
    {
      key: 'subject', header: 'Subject', render: ( c: api.EnterpriseCase ) => (
        <div><div style={ { fontWeight: 500, fontSize: 14 } }>{ c.subject }</div><div style={ { fontSize: 12, color: '#6b7280' } }>{ c.customerName } · { c.customerPhone }</div></div>
      )
    },
    { key: 'category', header: 'Category', width: '100px', render: ( c: api.EnterpriseCase ) => c.category || '—' },
    {
      key: 'priority', header: 'Priority', width: '100px', render: ( c: api.EnterpriseCase ) => (
        <Select ariaLabel="Priority" value={ c.priority }
          onChange={ v => handlePriorityUpdate( c.caseId, v ) }
          options={ PRIORITY_SELECT_OPTIONS } style={ CELL_SELECT_STYLE } />
      )
    },
    { key: 'assignedTo', header: 'Assigned', width: '100px', render: ( c: api.EnterpriseCase ) => c.assignedTo || '—' },
    {
      key: 'status', header: 'Status', width: '130px', render: ( c: api.EnterpriseCase ) => (
        <Select ariaLabel="Case status" value={ c.status }
          onChange={ v => handleStatusUpdate( c.caseId, v ) }
          options={ STATUS_SELECT_OPTIONS } style={ CELL_SELECT_STYLE } />
      )
    },
    { key: 'createdAt', header: 'Created', width: '120px', render: ( c: api.EnterpriseCase ) => formatDate( c.createdAt ) },
  ];

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.enterprise } />
      <div style={ { padding: '24px 32px', maxWidth: 1400 } }>
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 } }>
          <div>
            <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: 0 } }>Enterprise Assist</h1>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '4px 0 0' } }>{ cases.length } cases</p>
          </div>
          <div style={ { display: 'flex', gap: 8 } }>
            <Button variant="secondary" icon="refresh" onClick={ loadData }>Refresh</Button>
            <Button variant="primary" icon="create" onClick={ () => setShowCreate( true ) }>New Case</Button>
          </div>
        </div>

        <div style={ { display: 'flex', gap: 12, marginBottom: 16 } }>
          <Select ariaLabel="Case status" value={ statusFilter }
            onChange={ v => { setStatusFilter( v ); setPage( 1 ); } }
            options={ STATUS_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <Select ariaLabel="Priority" value={ priorityFilter }
            onChange={ v => { setPriorityFilter( v ); setPage( 1 ); } }
            options={ PRIORITY_FILTER_OPTIONS } style={ FILTER_STYLE } />
        </div>

        { cases.length === 0 && !loading ? (
          <EmptyState icon="default" title="No cases" description="Enterprise assist cases will appear here" />
        ) : (
          <>
            <Table columns={ columns } data={ paged } keyField="caseId" loading={ loading } />
            { totalPages > 1 && <div style={ { marginTop: 16, display: 'flex', justifyContent: 'center' } }><Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } /></div> }
          </>
        ) }
      </div>

      <Modal isOpen={ !!selected } onClose={ () => setSelected( null ) } title={ `Case ${selected?.caseId?.slice( 0, 8 ) || ''}` } size="lg">
        { selected && (
          <div>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 } }>
              <div><span style={ labelStyle }>Customer</span><div style={ { fontWeight: 500 } }>{ selected.customerName || '—' }</div></div>
              <div><span style={ labelStyle }>Phone</span><div>{ selected.customerPhone || '—' }</div></div>
              <div><span style={ labelStyle }>Category</span><div>{ selected.category || '—' }</div></div>
              <div><span style={ labelStyle }>Priority</span><div>{ priorityBadge( selected.priority ) }</div></div>
              <div><span style={ labelStyle }>Status</span><div>{ statusBadge( selected.status ) }</div></div>
              <div><span style={ labelStyle }>Assigned To</span><div>{ selected.assignedTo || '—' }</div></div>
              <div><span style={ labelStyle }>Created</span><div>{ formatDate( selected.createdAt ) }</div></div>
              { selected.resolvedAt && <div><span style={ labelStyle }>Resolved</span><div>{ formatDate( selected.resolvedAt ) }</div></div> }
            </div>
            <div style={ { marginBottom: 12 } }><span style={ labelStyle }>Subject</span><div style={ { fontWeight: 600, fontSize: 16 } }>{ selected.subject }</div></div>
            { selected.description && <div style={ { marginBottom: 12 } }><span style={ labelStyle }>Description</span><div style={ { padding: 12, background: '#f9fafb', borderRadius: 8, fontSize: 14, whiteSpace: 'pre-wrap' } }>{ selected.description }</div></div> }
            { selected.resolution && <div><span style={ labelStyle }>Resolution</span><div style={ { padding: 12, background: '#f0fdf4', borderRadius: 8, fontSize: 14, whiteSpace: 'pre-wrap' } }>{ selected.resolution }</div></div> }
          </div>
        ) }
      </Modal>

      {/* Create Case Modal */ }
      <Modal isOpen={ showCreate } onClose={ () => setShowCreate( false ) } title="New Enterprise Case" size="lg" footer={
        <><Button variant="secondary" onClick={ () => setShowCreate( false ) }>Cancel</Button><Button variant="primary" loading={ creating } onClick={ async () => {
          if ( !createForm.subject.trim() ) { toast.error( 'Subject is required' ); return; }
          if ( createForm.customerPhone && !isValidPhone( createForm.customerPhone ) ) { toast.error( 'Enter a valid phone number' ); return; }
          if ( createForm.contactEmail && !isValidEmail( createForm.contactEmail ) ) { toast.error( 'Enter a valid email address' ); return; }
          setCreating( true );
          const c = await api.createEnterpriseCase( { customerName: createForm.customerName, customerPhone: createForm.customerPhone ? normalizePhone( createForm.customerPhone ) : '', contactEmail: createForm.contactEmail, accountName: createForm.accountName, subject: createForm.subject, description: createForm.description, priority: createForm.priority } as any );
          if ( c ) { toast.success( 'Case created' ); setShowCreate( false ); setCreateForm( { customerName: '', customerPhone: '', contactEmail: '', accountName: '', subject: '', description: '', priority: 'normal' } ); loadData(); }
          else toast.error( 'Failed to create' );
          setCreating( false );
        } }>Create</Button></>
      }>
        <div style={ { display: 'flex', flexDirection: 'column', gap: 14 } }>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <label style={ { fontSize: 14 } }>Contact Name<input type="text" value={ createForm.customerName } onChange={ e => setCreateForm( f => ( { ...f, customerName: e.target.value } ) ) } style={ inputStyle } /></label>
            <label style={ { fontSize: 14 } }>Phone<input type="tel" value={ createForm.customerPhone } onChange={ e => setCreateForm( f => ( { ...f, customerPhone: e.target.value } ) ) } placeholder="+91 9876543210" style={ { ...inputStyle, borderColor: createForm.customerPhone && !isValidPhone( createForm.customerPhone ) ? '#dc2626' : '#e5e7eb' } } />{ createForm.customerPhone && !isValidPhone( createForm.customerPhone ) && <span style={ { fontSize: 11, color: '#dc2626', marginTop: 2 } }>Invalid phone format</span> }</label>
          </div>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <label style={ { fontSize: 14 } }>Email<input type="email" value={ createForm.contactEmail } onChange={ e => setCreateForm( f => ( { ...f, contactEmail: e.target.value } ) ) } placeholder="name@company.com" style={ { ...inputStyle, borderColor: createForm.contactEmail && !isValidEmail( createForm.contactEmail ) ? '#dc2626' : '#e5e7eb' } } />{ createForm.contactEmail && !isValidEmail( createForm.contactEmail ) && <span style={ { fontSize: 11, color: '#dc2626', marginTop: 2 } }>Invalid email format</span> }</label>
            <label style={ { fontSize: 14 } }>Company<input type="text" value={ createForm.accountName } onChange={ e => setCreateForm( f => ( { ...f, accountName: e.target.value } ) ) } style={ inputStyle } /></label>
          </div>
          <label style={ { fontSize: 14 } }>Subject *<input type="text" value={ createForm.subject } onChange={ e => setCreateForm( f => ( { ...f, subject: e.target.value } ) ) } style={ inputStyle } maxLength={ 200 } /></label>
          <label style={ { fontSize: 14 } }>Description<textarea value={ createForm.description } onChange={ e => setCreateForm( f => ( { ...f, description: e.target.value } ) ) } rows={ 3 } style={ { ...inputStyle, resize: 'vertical' } } maxLength={ 2000 } /></label>
          { /* SHAPE (a), design 5.2 - the wrapping <label> is gone and Select owns the pair. */ }
          <Select label="Priority" value={ createForm.priority }
            onChange={ v => setCreateForm( f => ( { ...f, priority: v } ) ) }
            options={ PRIORITY_SELECT_OPTIONS } />
        </div>
      </Modal>
    </MaybeLayout>
  );
};

/* `selectStyle` went with the last native select in this file - it only ever skinned those. */
const labelStyle: React.CSSProperties = { fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 2 };
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 4 };

export default EnterprisePage;
