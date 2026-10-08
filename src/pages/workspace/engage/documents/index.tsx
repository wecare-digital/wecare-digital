/**
 * Drop Docs — Document Management — [retired public path]/documents
 *
 * Full document management system:
 * - List all documents from all sources (WhatsApp, manual, web, flow)
 * - Filter by source, type, status, date
 * - Preview/download from S3
 * - Approve/reject/request reupload actions
 * - Link to order/customer
 * - Document history/audit trail in detail panel
 * - WhatsApp-uploaded documents auto-reflect here
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
const STATUS_OPTIONS = [ 'uploaded', 'under_review', 'approved', 'rejected', 'reupload_requested' ];
const SOURCE_OPTIONS = [ 'whatsapp', 'flow', 'upload', 'manual' ];
const TYPE_OPTIONS = [ 'prescription', 'id_proof', 'address_proof', 'invoice', 'photo', 'other' ];

/* The option lists, hoisted. Same order, same values, same visible text as the rows they
   replaced, including the three '' placeholder rows the filters read as "no filter". */
const STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  ...STATUS_OPTIONS.map( s => ( { value: s, label: s.replace( /_/g, ' ' ) } ) ),
];
const SOURCE_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Sources' },
  ...SOURCE_OPTIONS.map( s => ( { value: s, label: s } ) ),
];
const TYPE_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Types' },
  ...TYPE_OPTIONS.map( s => ( { value: s, label: s.replace( /_/g, ' ' ) } ) ),
];
const TYPE_SELECT_OPTIONS: SelectOption[] = TYPE_OPTIONS.map(
  t => ( { value: t, label: t.replace( /_/g, ' ' ) } )
);

/* LAYOUT ONLY - the three filters are flex children, and a native select sized itself to
   its widest option while the trigger shows the selected one. */
const FILTER_STYLE: React.CSSProperties = { width: 170 };

function fmtDate ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' } );
}

function fmtSize ( bytes?: number ): string {
  if ( !bytes ) return '—';
  if ( bytes < 1024 ) return `${bytes} B`;
  if ( bytes < 1048576 ) return `${( bytes / 1024 ).toFixed( 1 )} KB`;
  return `${( bytes / 1048576 ).toFixed( 1 )} MB`;
}

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  uploaded: { bg: '#dbeafe', fg: '#1e40af' },
  under_review: { bg: '#e0e7ff', fg: '#3730a3' },
  approved: { bg: '#d1f470', fg: '#1a3a2a' },
  rejected: { bg: '#fee2e2', fg: '#991b1b' },
  reupload_requested: { bg: '#f3e8ff', fg: '#6b21a8' },
};

const SOURCE_ICONS: Record<string, string> = { whatsapp: '💬', flow: '🔄', upload: '📤', manual: '✏️' };

function StatusBadge ( { status }: { status: string } ) {
  const c = STATUS_COLORS[ status ] || { bg: '#f3f4f6', fg: '#374151' };
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 12, fontWeight: 600, background: c.bg, color: c.fg } }>{ status.replace( /_/g, ' ' ) }</span>;
}

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const DocumentsPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ docs, setDocs ] = useState<api.Document[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ sourceFilter, setSourceFilter ] = useState( '' );
  const [ typeFilter, setTypeFilter ] = useState( '' );
  const [ page, setPage ] = useState( 1 );
  const [ selected, setSelected ] = useState<api.Document | null>( null );
  const [ actionLoading, setActionLoading ] = useState( false );
  const [ remarks, setRemarks ] = useState( '' );
  const [ showCreate, setShowCreate ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ createForm, setCreateForm ] = useState( { customerName: '', customerPhone: '', orderId: '', type: 'other', fileName: '', notes: '' } );

  const loadData = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listDocuments( {
        status: statusFilter || undefined,
        source: sourceFilter || undefined,
        type: typeFilter || undefined,
      } );
      setDocs( data.documents || [] );
    } catch { toast.error( 'Failed to load documents' ); }
    setLoading( false );
  }, [ statusFilter, sourceFilter, typeFilter, toast ] );

  useEffect( () => { loadData(); }, [ loadData ] );

  const handleStatusAction = async ( doc: api.Document, newStatus: string, actionRemarks?: string ) => {
    setActionLoading( true );
    const ok = await api.updateDocument( doc.documentId, {
      status: newStatus,
      notes: actionRemarks || remarks || undefined,
    } as any );
    if ( ok )
    {
      toast.success( `Document ${newStatus.replace( /_/g, ' ' )}` );
      loadData();
      if ( selected?.documentId === doc.documentId )
      {
        setSelected( { ...doc, status: newStatus } );
      }
    } else toast.error( 'Action failed' );
    setActionLoading( false );
    setRemarks( '' );
  };

  const handleDownload = async ( doc: api.Document ) => {
    const url = await api.getDocumentDownloadUrl( doc.documentId );
    if ( url ) window.open( url, '_blank' );
    else toast.error( 'Download not available' );
  };

  const totalPages = Math.ceil( docs.length / PAGE_SIZE );
  const paged = docs.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  // Stats
  const stats = {
    total: docs.length,
    uploaded: docs.filter( d => d.status === 'uploaded' ).length,
    underReview: docs.filter( d => d.status === 'under_review' ).length,
    approved: docs.filter( d => d.status === 'approved' ).length,
    rejected: docs.filter( d => d.status === 'rejected' ).length,
  };

  const columns = [
    {
      key: 'source', header: 'Src', width: '40px', render: ( d: api.Document ) => (
        <span title={ d.source } style={ { fontSize: 16 } }>{ SOURCE_ICONS[ d.source ] || '📄' }</span>
      )
    },
    {
      key: 'fileName', header: 'Document', render: ( d: api.Document ) => (
        <button onClick={ () => { setSelected( d ); setRemarks( '' ); } } style={ { background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left' } }>
          <div style={ { fontWeight: 500, fontSize: 14, color: '#1a3a2a', textDecoration: 'underline' } }>{ d.fileName || 'Untitled' }</div>
          <div style={ { fontSize: 12, color: '#6b7280' } }>{ d.type } · { fmtSize( d.fileSize ) }</div>
        </button>
      )
    },
    {
      key: 'customer', header: 'Customer', width: '140px', render: ( d: api.Document ) => (
        <div><div style={ { fontWeight: 500, fontSize: 13 } }>{ d.customerName || '—' }</div><div style={ { fontSize: 12, color: '#6b7280' } }>{ d.customerPhone }</div></div>
      )
    },
    {
      key: 'orderId', header: 'Order', width: '100px', render: ( d: api.Document ) => d.orderId ? (
        <span style={ { fontSize: 12, fontFamily: 'monospace', color: '#1a3a2a' } }>{ d.orderId.split( '-' ).pop() }</span>
      ) : <span style={ { color: '#9ca3af' } }>—</span>
    },
    { key: 'status', header: 'Status', width: '140px', render: ( d: api.Document ) => <StatusBadge status={ d.status } /> },
    { key: 'createdAt', header: 'Uploaded', width: '130px', render: ( d: api.Document ) => fmtDate( d.createdAt ) },
    {
      key: 'actions', header: '', width: '120px', render: ( d: api.Document ) => (
        <div style={ { display: 'flex', gap: 4 } }>
          { d.status !== 'approved' && <button onClick={ () => handleStatusAction( d, 'approved' ) } title="Approve" style={ actionBtnStyle }>✅</button> }
          { d.status !== 'rejected' && <button onClick={ () => handleStatusAction( d, 'rejected' ) } title="Reject" style={ actionBtnStyle }>❌</button> }
          { d.status !== 'reupload_requested' && <button onClick={ () => handleStatusAction( d, 'reupload_requested' ) } title="Request Reupload" style={ actionBtnStyle }>🔄</button> }
          <button onClick={ () => handleDownload( d ) } title="Download" style={ actionBtnStyle }>⬇️</button>
        </div>
      )
    },
  ];

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.documents } />
      <div style={ { padding: '24px 32px', maxWidth: 1400 } }>
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 } }>
          <div>
            <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: 0 } }>Drop Docs</h1>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '4px 0 0' } }>Document management — all sources</p>
          </div>
          <div style={ { display: 'flex', gap: 8 } }>
            <Button variant="secondary" icon="refresh" onClick={ loadData }>Refresh</Button>
            <Button variant="primary" icon="create" onClick={ () => setShowCreate( true ) }>Add Document</Button>
          </div>
        </div>

        {/* Stats */ }
        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 20 } }>
          { [
            { label: 'Total', value: stats.total, bg: '#f9fafb' },
            { label: 'Uploaded', value: stats.uploaded, bg: '#dbeafe' },
            { label: 'Under Review', value: stats.underReview, bg: '#e0e7ff' },
            { label: 'Approved', value: stats.approved, bg: '#d1fae5' },
            { label: 'Rejected', value: stats.rejected, bg: '#fee2e2' },
          ].map( s => (
            <div key={ s.label } style={ { padding: '12px 16px', background: s.bg, borderRadius: 10, border: '2px solid #f3f4f6' } }>
              <div style={ { fontSize: 22, fontWeight: 700, color: '#1a3a2a' } }>{ s.value }</div>
              <div style={ { fontSize: 12, color: '#6b7280' } }>{ s.label }</div>
            </div>
          ) ) }
        </div>

        {/* Filters */ }
        <div style={ { display: 'flex', gap: 12, marginBottom: 16 } }>
          <Select ariaLabel="Document status" value={ statusFilter }
            onChange={ v => { setStatusFilter( v ); setPage( 1 ); } }
            options={ STATUS_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <Select ariaLabel="Source" value={ sourceFilter }
            onChange={ v => { setSourceFilter( v ); setPage( 1 ); } }
            options={ SOURCE_FILTER_OPTIONS } style={ FILTER_STYLE } />
          <Select ariaLabel="Document type" value={ typeFilter }
            onChange={ v => { setTypeFilter( v ); setPage( 1 ); } }
            options={ TYPE_FILTER_OPTIONS } style={ FILTER_STYLE } />
        </div>

        { docs.length === 0 && !loading ? (
          <EmptyState icon="default" title="No documents" description="Documents from WhatsApp, web uploads, and manual entries will appear here" />
        ) : (
          <>
            <Table columns={ columns } data={ paged } keyField="documentId" loading={ loading } />
            { totalPages > 1 && <div style={ { marginTop: 16, display: 'flex', justifyContent: 'center' } }><Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } /></div> }
          </>
        ) }
      </div>

      {/* Detail Modal */ }
      <Modal isOpen={ !!selected } onClose={ () => setSelected( null ) } title="Document Details" size="lg">
        { selected && (
          <div>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 } }>
              <div><span style={ labelStyle }>File Name</span><div style={ { fontWeight: 500 } }>{ selected.fileName || 'Untitled' }</div></div>
              <div><span style={ labelStyle }>Type</span><div>{ selected.type }</div></div>
              <div><span style={ labelStyle }>Source</span><div>{ SOURCE_ICONS[ selected.source ] || '📄' } { selected.source }</div></div>
              <div><span style={ labelStyle }>Size</span><div>{ fmtSize( selected.fileSize ) }</div></div>
              <div><span style={ labelStyle }>Status</span><div><StatusBadge status={ selected.status } /></div></div>
              <div><span style={ labelStyle }>Uploaded</span><div>{ fmtDate( selected.createdAt ) }</div></div>
              <div><span style={ labelStyle }>Customer</span><div>{ selected.customerName || '—' } ({ selected.customerPhone || '—' })</div></div>
              { selected.orderId && <div><span style={ labelStyle }>Order ID</span><div style={ { fontFamily: 'monospace', fontSize: 13 } }>{ selected.orderId }</div></div> }
              { selected.mimeType && <div><span style={ labelStyle }>MIME Type</span><div style={ { fontSize: 13 } }>{ selected.mimeType }</div></div> }
              { selected.reviewedBy && <div><span style={ labelStyle }>Reviewed By</span><div>{ selected.reviewedBy } · { fmtDate( selected.reviewedAt ) }</div></div> }
            </div>
            { selected.notes && (
              <div style={ { marginBottom: 16 } }>
                <span style={ labelStyle }>Remarks</span>
                <div style={ { padding: 12, background: '#f9fafb', borderRadius: 8, fontSize: 14 } }>{ selected.notes }</div>
              </div>
            ) }

            {/* Action Remarks */ }
            <div style={ { marginBottom: 16 } }>
              <label style={ { fontSize: 14, fontWeight: 500 } }>
                Action Remarks (optional)
                <textarea value={ remarks } onChange={ e => setRemarks( e.target.value ) } rows={ 2 } placeholder="Add remarks for this action..." style={ { ...inputStyle, resize: 'vertical' } } />
              </label>
            </div>

            <div style={ { display: 'flex', gap: 8, justifyContent: 'flex-end' } }>
              <Button variant="secondary" onClick={ () => handleDownload( selected ) }>Download</Button>
              <Button variant="primary" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'approved', remarks ) }>Approve</Button>
              <Button variant="danger" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'rejected', remarks ) }>Reject</Button>
              <Button variant="secondary" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'reupload_requested', remarks ) }>Request Reupload</Button>
            </div>
          </div>
        ) }
      </Modal>

      {/* Create Document Modal */ }
      <Modal isOpen={ showCreate } onClose={ () => setShowCreate( false ) } title="Add Document (Manual)" size="md" footer={
        <><Button variant="secondary" onClick={ () => setShowCreate( false ) }>Cancel</Button><Button variant="primary" loading={ creating } onClick={ async () => {
          if ( !createForm.customerPhone && !createForm.customerName ) { toast.error( 'Customer name or phone is required' ); return; }
          setCreating( true );
          const doc = await api.createDocument( { customerName: createForm.customerName, customerPhone: createForm.customerPhone, orderId: createForm.orderId || undefined, type: createForm.type, fileName: createForm.fileName, notes: createForm.notes } as any );
          if ( doc ) { toast.success( 'Document record created' ); setShowCreate( false ); setCreateForm( { customerName: '', customerPhone: '', orderId: '', type: 'other', fileName: '', notes: '' } ); loadData(); }
          else toast.error( 'Failed to create' );
          setCreating( false );
        } }>Create</Button></>
      }>
        <div style={ { display: 'flex', flexDirection: 'column', gap: 14 } }>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <label style={ { fontSize: 14 } }>Customer Name<input type="text" value={ createForm.customerName } onChange={ e => setCreateForm( f => ( { ...f, customerName: e.target.value } ) ) } style={ inputStyle } /></label>
            <label style={ { fontSize: 14 } }>Phone<input type="tel" value={ createForm.customerPhone } onChange={ e => setCreateForm( f => ( { ...f, customerPhone: e.target.value } ) ) } placeholder="+91..." style={ inputStyle } /></label>
          </div>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            { /* SHAPE (a), design 5.2 - the wrapping <label> is gone and Select owns the pair. */ }
            <Select label="Document Type" value={ createForm.type }
              onChange={ v => setCreateForm( f => ( { ...f, type: v } ) ) }
              options={ TYPE_SELECT_OPTIONS } />
            <label style={ { fontSize: 14 } }>Order ID (optional)<input type="text" value={ createForm.orderId } onChange={ e => setCreateForm( f => ( { ...f, orderId: e.target.value } ) ) } placeholder="WD-ORD-..." style={ inputStyle } /></label>
          </div>
          <label style={ { fontSize: 14 } }>File Name<input type="text" value={ createForm.fileName } onChange={ e => setCreateForm( f => ( { ...f, fileName: e.target.value } ) ) } placeholder="e.g. prescription_jan2026.pdf" style={ inputStyle } /></label>
          <label style={ { fontSize: 14 } }>Notes<textarea value={ createForm.notes } onChange={ e => setCreateForm( f => ( { ...f, notes: e.target.value } ) ) } rows={ 2 } placeholder="Any remarks about this document..." style={ { ...inputStyle, resize: 'vertical' } } /></label>
          <div style={ { padding: 12, background: '#fef3c7', borderRadius: 8, fontSize: 13, color: '#92400e' } }>
            This creates a document record. To attach the actual file, the customer can send it via WhatsApp or you can update the storage key later.
          </div>
        </div>
      </Modal>
    </MaybeLayout>
  );
};

/* `selectStyle` went with the last native select in this file - it only ever skinned those. */
const labelStyle: React.CSSProperties = { fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 2 };
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 4 };
const actionBtnStyle: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, padding: '2px 4px' };

export default DocumentsPage;
