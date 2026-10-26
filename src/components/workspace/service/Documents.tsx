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
import MaybeLayout from '../../../components/MaybeLayout';
import SEO, { PAGE_SEO } from '../../../components/SEO';
import Table from '../../../components/ui/Table';
import Modal from '../../../components/ui/Modal';
import Button from '../../../components/ui/Button';
import Pagination from '../../../components/ui/Pagination';
import EmptyState from '../../../components/ui/EmptyState';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import type { ApiFailure } from '../../../api/client';
import { openExternal } from '../../../lib/capacitor';
import ServiceDataState from '../../../components/service/ServiceDataState';

const PAGE_SIZE = 20;
const STATUS_OPTIONS = [ 'awaiting_upload', 'uploaded', 'under_review', 'approved', 'rejected', 'reupload_requested' ];
const SOURCE_OPTIONS = [ 'flow', 'manual', 'web' ];
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
const TYPE_SELECT_OPTIONS: SelectOption[] = [
  { value: '', label: 'Select document type' },
  ...TYPE_OPTIONS.map( t => ( { value: t, label: t.replace( /_/g, ' ' ) } ) ),
];

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
  awaiting_upload: { bg: '#fef3c7', fg: '#92400e' },
  uploaded: { bg: '#dbeafe', fg: '#1e40af' },
  under_review: { bg: '#e0e7ff', fg: '#3730a3' },
  approved: { bg: 'var(--lime)', fg: 'var(--accent)' },
  rejected: { bg: '#fee2e2', fg: '#991b1b' },
  reupload_requested: { bg: '#f3e8ff', fg: '#6b21a8' },
};

const SOURCE_ICONS: Record<string, string> = { whatsapp: '💬', flow: '🔄', upload: '📤', manual: '✏️' };

function StatusBadge ( { status }: { status: string } ) {
  const c = STATUS_COLORS[ status ] || { bg: '#f3f4f6', fg: '#374151' };
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 'var(--text-xs)', fontWeight: 600, background: c.bg, color: c.fg } }>{ status.replace( /_/g, ' ' ) }</span>;
}

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const DocumentsPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ docs, setDocs ] = useState<api.Document[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ failure, setFailure ] = useState<ApiFailure | null>( null );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ sourceFilter, setSourceFilter ] = useState( '' );
  const [ typeFilter, setTypeFilter ] = useState( '' );
  const [ page, setPage ] = useState( 1 );
  const [ selected, setSelected ] = useState<api.Document | null>( null );
  const [ actionLoading, setActionLoading ] = useState( false );
  const [ remarks, setRemarks ] = useState( '' );
  const [ showCreate, setShowCreate ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ contactQuery, setContactQuery ] = useState( '' );
  const [ contactResults, setContactResults ] = useState<api.Contact[]>( [] );
  const [ contactSearching, setContactSearching ] = useState( false );
  const [ customerOrders, setCustomerOrders ] = useState<api.Order[]>( [] );
  const [ ordersLoading, setOrdersLoading ] = useState( false );
  const [ createFile, setCreateFile ] = useState<File | null>( null );
  const [ createForm, setCreateForm ] = useState( {
    contactId: '', customerName: '', customerPhone: '', orderId: '',
    type: '', typeLabel: '', fileName: '', notes: '',
  } );

  const loadData = useCallback( async () => {
    setLoading( true );
    // A failed load must show an error, not an empty "No documents" table.
    const { data, failures } = await api.collectApiFailures( () => api.listDocuments( {
      status: statusFilter || undefined,
      source: sourceFilter || undefined,
      type: typeFilter || undefined,
    } ) );
    const rows = data.documents || [];
    setDocs( rows );
    setFailure( rows.length === 0 && failures.length ? failures[ 0 ] : null );
    setLoading( false );
  }, [ statusFilter, sourceFilter, typeFilter, toast ] );

  useEffect( () => { loadData(); }, [ loadData ] );

  useEffect( () => {
    if ( !showCreate )
    {
      setContactResults( [] );
      return;
    }
    const q = contactQuery.trim();
    if ( q.length < 2 )
    {
      setContactResults( [] );
      return;
    }
    const timer = window.setTimeout( () => {
      setContactSearching( true );
      void api.searchContactsResult( q, 8 ).then( result => {
        setContactResults( result.ok ? result.data : [] );
      } ).finally( () => setContactSearching( false ) );
    }, 250 );
    return () => window.clearTimeout( timer );
  }, [ contactQuery, showCreate ] );

  useEffect( () => {
    if ( !showCreate || !createForm.customerPhone )
    {
      setCustomerOrders( [] );
      return;
    }
    let cancelled = false;
    setOrdersLoading( true );
    void api.listOrders( { phone: createForm.customerPhone, limit: 50 } )
      .then( result => { if ( !cancelled ) setCustomerOrders( result.orders || [] ); } )
      .finally( () => { if ( !cancelled ) setOrdersLoading( false ); } );
    return () => { cancelled = true; };
  }, [ createForm.customerPhone, showCreate ] );

  const resetCreate = () => {
    setCreateForm( {
      contactId: '', customerName: '', customerPhone: '', orderId: '',
      type: '', typeLabel: '', fileName: '', notes: '',
    } );
    setContactQuery( '' );
    setContactResults( [] );
    setCustomerOrders( [] );
    setCreateFile( null );
  };

  const selectContact = ( contact: api.Contact ) => {
    setCreateForm( form => ( {
      ...form,
      contactId: contact.contactId || contact.id,
      customerName: contact.name || [ contact.firstName, contact.lastName ].filter( Boolean ).join( ' ' ),
      customerPhone: contact.phone || '',
      orderId: '',
    } ) );
    setContactQuery( contact.name || contact.phone || '' );
    setContactResults( [] );
  };

  const handleCreateDocument = async () => {
    if ( !createForm.customerPhone && !createForm.contactId )
    {
      toast.error( 'Select a customer or enter their mobile number' );
      return;
    }
    if ( !createForm.type )
    {
      toast.error( 'Select a document type' );
      return;
    }
    if ( createForm.type === 'other' && !createForm.typeLabel.trim() )
    {
      toast.error( 'Enter the document type/name' );
      return;
    }
    if ( !createFile )
    {
      toast.error( 'Choose a file to upload' );
      return;
    }

    setCreating( true );
    try
    {
      const mimeType = createFile.type || 'application/octet-stream';
      const ticket = await api.initDocumentUpload( {
        contactId: createForm.contactId || undefined,
        customerName: createForm.customerName || undefined,
        customerPhone: createForm.customerPhone || undefined,
        orderId: createForm.orderId || undefined,
        type: createForm.type,
        typeLabel: createForm.type === 'other' ? createForm.typeLabel.trim() : undefined,
        fileName: createFile.name,
        mimeType,
        fileSize: createFile.size,
        notes: createForm.notes || undefined,
      } );
      if ( !ticket.ok )
      {
        toast.error( ticket.failure.message || 'Could not start the upload' );
        return;
      }

      const uploaded = await api.uploadDocumentBytes(
        ticket.data.uploadUrl, createFile, ticket.data.contentType || mimeType );
      if ( !uploaded )
      {
        toast.error( 'File upload failed. Please try again.' );
        return;
      }

      const confirmed = await api.confirmDocumentUpload( ticket.data.documentId );
      if ( !confirmed.ok )
      {
        toast.error( confirmed.failure.message || 'The upload could not be confirmed' );
        return;
      }

      toast.success( 'Document uploaded' );
      setShowCreate( false );
      resetCreate();
      void loadData();
    } finally
    {
      setCreating( false );
    }
  };

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
    // openExternal opens the S3 download URL in the in-app browser inside the native WebView
    // shell (where a bare _blank target has no tab to open into) and uses the standard web
    // open otherwise.
    if ( url ) void openExternal( url );
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
        <span title={ d.source } style={ { fontSize: 'var(--text-base)' } }>{ SOURCE_ICONS[ d.source ] || '📄' }</span>
      )
    },
    {
      key: 'fileName', header: 'Document', render: ( d: api.Document ) => (
        <button onClick={ () => { setSelected( d ); setRemarks( '' ); } } style={ { background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left' } }>
          <div style={ { fontWeight: 500, fontSize: 'var(--text-md)', color: 'var(--accent)', textDecoration: 'underline' } }>{ d.fileName || 'Untitled' }</div>
          <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ d.type } · { fmtSize( d.fileSize ) }</div>
        </button>
      )
    },
    {
      key: 'customer', header: 'Customer', width: '140px', render: ( d: api.Document ) => (
        <div><div style={ { fontWeight: 500, fontSize: 'var(--text-sm)' } }>{ d.customerName || '—' }</div><div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ d.customerPhone }</div></div>
      )
    },
    {
      key: 'orderId', header: 'Order', width: '100px', render: ( d: api.Document ) => d.orderId ? (
        <span style={ { fontSize: 'var(--text-xs)', fontFamily: 'monospace', color: 'var(--accent)' } }>{ d.orderId.split( '-' ).pop() }</span>
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
            <h1 style={ { fontSize: 'var(--text-3xl)', fontWeight: 700, color: 'var(--accent)', margin: 0 } }>Drop Docs</h1>
            <p style={ { fontSize: 'var(--text-md)', color: 'var(--text-muted)', margin: '4px 0 0' } }>Document management — all sources</p>
          </div>
          <div style={ { display: 'flex', gap: 8 } }>
            <Button variant="secondary" icon="refresh" onClick={ loadData }>Refresh</Button>
            <Button variant="primary" icon="create" onClick={ () => setShowCreate( true ) }>Add Document</Button>
          </div>
        </div>

        {/* Stats */ }
        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 20 } }>
          { [
            { label: 'Total', value: stats.total, bg: 'var(--bg-secondary)' },
            { label: 'Uploaded', value: stats.uploaded, bg: '#dbeafe' },
            { label: 'Under Review', value: stats.underReview, bg: '#e0e7ff' },
            { label: 'Approved', value: stats.approved, bg: '#d1fae5' },
            { label: 'Rejected', value: stats.rejected, bg: '#fee2e2' },
          ].map( s => (
            <div key={ s.label } style={ { padding: '12px 16px', background: s.bg, borderRadius: 10, border: '2px solid #f3f4f6' } }>
              <div style={ { fontSize: 22, fontWeight: 700, color: 'var(--accent)' } }>{ s.value }</div>
              <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ s.label }</div>
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

        <ServiceDataState
          loading={ loading }
          failure={ failure }
          empty={ docs.length === 0 }
          emptyLabel="No documents"
          emptyIcon="default"
          onRetry={ loadData }
        >
          <Table columns={ columns } data={ paged } keyField="documentId" loading={ loading } />
          { totalPages > 1 && <div style={ { marginTop: 16, display: 'flex', justifyContent: 'center' } }><Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } /></div> }
        </ServiceDataState>
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
              { selected.orderId && <div><span style={ labelStyle }>Order ID</span><div style={ { fontFamily: 'monospace', fontSize: 'var(--text-sm)' } }>{ selected.orderId }</div></div> }
              { selected.mimeType && <div><span style={ labelStyle }>MIME Type</span><div style={ { fontSize: 'var(--text-sm)' } }>{ selected.mimeType }</div></div> }
              { selected.reviewedBy && <div><span style={ labelStyle }>Reviewed By</span><div>{ selected.reviewedBy } · { fmtDate( selected.reviewedAt ) }</div></div> }
            </div>
            { selected.notes && (
              <div style={ { marginBottom: 16 } }>
                <span style={ labelStyle }>Remarks</span>
                <div style={ { padding: 12, background: 'var(--bg-secondary)', borderRadius: 8, fontSize: 'var(--text-md)' } }>{ selected.notes }</div>
              </div>
            ) }

            {/* Action Remarks */ }
            <div style={ { marginBottom: 16 } }>
              <label style={ { fontSize: 'var(--text-md)', fontWeight: 500 } }>
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
      <Modal
        isOpen={ showCreate }
        onClose={ () => { if ( !creating ) { setShowCreate( false ); resetCreate(); } } }
        title="Add Document"
        size="md"
        footer={
          <>
            <Button variant="secondary" onClick={ () => { setShowCreate( false ); resetCreate(); } } disabled={ creating }>Cancel</Button>
            <Button variant="primary" loading={ creating } onClick={ handleCreateDocument }>Upload document</Button>
          </>
        }
      >
        <div style={ { display: 'flex', flexDirection: 'column', gap: 14 } }>
          <div>
            <label style={ { fontSize: 'var(--text-md)' } }>
              Find customer
              <input
                type="search"
                value={ contactQuery }
                onChange={ e => setContactQuery( e.target.value ) }
                placeholder="Search name or mobile"
                style={ inputStyle }
                disabled={ creating }
              />
            </label>
            { contactSearching && <div style={ helperStyle }>Searching contacts…</div> }
            { contactResults.length > 0 && (
              <div style={ resultListStyle }>
                { contactResults.map( contact => (
                  <button
                    key={ contact.contactId || contact.id }
                    type="button"
                    onClick={ () => selectContact( contact ) }
                    style={ resultButtonStyle }
                  >
                    <strong>{ contact.name || [ contact.firstName, contact.lastName ].filter( Boolean ).join( ' ' ) || 'Unnamed contact' }</strong>
                    <span style={ { color: 'var(--text-muted)' } }>{ contact.phone || 'No phone' }</span>
                  </button>
                ) ) }
              </div>
            ) }
          </div>

          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <label style={ { fontSize: 'var(--text-md)' } }>
              Customer Name
              <input
                type="text"
                value={ createForm.customerName }
                onChange={ e => setCreateForm( form => ( { ...form, customerName: e.target.value, contactId: '' } ) ) }
                style={ inputStyle }
                disabled={ creating }
              />
            </label>
            <label style={ { fontSize: 'var(--text-md)' } }>
              Phone
              <input
                type="tel"
                value={ createForm.customerPhone }
                onChange={ e => setCreateForm( form => ( { ...form, customerPhone: e.target.value, contactId: '', orderId: '' } ) ) }
                placeholder="+91..."
                style={ inputStyle }
                disabled={ creating }
              />
            </label>
          </div>

          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
            <Select
              label="Document Type"
              value={ createForm.type }
              onChange={ value => setCreateForm( form => ( { ...form, type: value, typeLabel: value === 'other' ? form.typeLabel : '' } ) ) }
              options={ TYPE_SELECT_OPTIONS }
              disabled={ creating }
            />
            <Select
              label="Order (optional)"
              value={ createForm.orderId }
              onChange={ value => setCreateForm( form => ( { ...form, orderId: value } ) ) }
              options={ [
                { value: '', label: ordersLoading ? 'Loading orders…' : 'No order / standalone document' },
                ...customerOrders.map( order => ( {
                  value: order.orderId,
                  label: `${order.orderNumber || order.shortId || order.orderId} · ${order.paymentStatus || 'payment unknown'}`,
                } ) ),
              ] }
              disabled={ creating || ordersLoading || !createForm.customerPhone }
            />
          </div>

          { createForm.type === 'other' && (
            <label style={ { fontSize: 'var(--text-md)' } }>
              Document type/name
              <input
                type="text"
                value={ createForm.typeLabel }
                onChange={ e => setCreateForm( form => ( { ...form, typeLabel: e.target.value } ) ) }
                placeholder="e.g. Trade licence, PAN card, agreement"
                style={ inputStyle }
                disabled={ creating }
              />
            </label>
          ) }

          <label style={ { fontSize: 'var(--text-md)' } }>
            Choose file
            <input
              type="file"
              onChange={ e => {
                const next = e.target.files?.[ 0 ] || null;
                setCreateFile( next );
                setCreateForm( form => ( { ...form, fileName: next?.name || '' } ) );
              } }
              style={ inputStyle }
              disabled={ creating }
            />
          </label>
          { createFile && (
            <div style={ helperStyle }>
              { createFile.name } · { fmtSize( createFile.size ) } · { createFile.type || 'unknown type' }
            </div>
          ) }

          <label style={ { fontSize: 'var(--text-md)' } }>
            Notes
            <textarea
              value={ createForm.notes }
              onChange={ e => setCreateForm( form => ( { ...form, notes: e.target.value } ) ) }
              rows={ 2 }
              placeholder="Any remarks about this document..."
              style={ { ...inputStyle, resize: 'vertical' } }
              disabled={ creating }
            />
          </label>

          <div style={ { padding: 12, background: '#ecfccb', borderRadius: 8, fontSize: 'var(--text-sm)', color: '#365314' } }>
            The file is uploaded into private Drop Docs storage and linked to the selected customer and, when chosen, their order.
          </div>
        </div>
      </Modal>
    </MaybeLayout>
  );
};

/* `selectStyle` went with the last native select in this file - it only ever skinned those. */
const labelStyle: React.CSSProperties = { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', display: 'block', marginBottom: 2 };
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', fontSize: 'var(--text-md)', marginTop: 4 };
const actionBtnStyle: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', fontSize: 'var(--text-base)', padding: '2px 4px' };
const helperStyle: React.CSSProperties = { fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginTop: 6 };
const resultListStyle: React.CSSProperties = { marginTop: 6, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', maxHeight: 220, overflowY: 'auto' };
const resultButtonStyle: React.CSSProperties = { width: '100%', display: 'flex', justifyContent: 'space-between', gap: 12, padding: '9px 12px', border: 0, borderBottom: '1px solid var(--border)', background: 'var(--bg-primary)', cursor: 'pointer', textAlign: 'left' };

export default DocumentsPage;
