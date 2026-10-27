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
import React, { useState, useEffect, useCallback, useRef } from 'react';
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


function fmtOrderLabel ( order: api.Order ): string {
  const id = order.orderNumber || order.shortId || order.orderId;
  const when = fmtDate( order.createdAt );
  const payment = order.paymentStatus || 'payment unknown';
  const amount = ( order.paymentAmount ?? order.totalAmount );
  return [ id, when, amount !== undefined ? `₹${amount}` : '', payment, order.source || '' ].filter( Boolean ).join( ' · ' );
}

function fileExtension ( name?: string ): string {
  const value = String( name || '' );
  const match = value.match( /\.[a-z0-9]{1,10}$/i );
  return match ? match[ 0 ].toLowerCase() : '';
}

/* {{1}} of the ₹49 Vault message (wecare_valut_49), cleaned the way the server cleans it: one
   line, at most 60 characters, no * _ ~ marks (the body wraps {{1}} in *bold*). So the preview
   below is the text the customer receives. */
function vaultMessageName ( raw?: string ): string {
  return String( raw || '' )
    .replace( /[\u0000-\u001f\u007f]/g, ' ' )
    .replace( /[*~]/g, '' )
    .replace( /_/g, ' ' )
    .split( /\s+/ ).filter( Boolean ).join( ' ' )
    .slice( 0, 60 ).trim();
}

/* The published Vault file's own record, read from Secure files when a published document opens.
   `unknown` covers "not read yet" and "no mobile to read it by". */
type VaultFileView =
  | { status: 'unknown' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; file: api.SecureFile | null };

/* Same fallback as Secure files for a list served by an older backend. */
function vaultAccessState ( file: api.SecureFile ): api.SecureFileAccessState {
  if ( file.accessState ) return file.accessState;
  return file.vaultPaymentStatus === 'PAID' ? 'READY' : 'UNPAID';
}

const VAULT_ACCESS_LABELS: Record<api.SecureFileAccessState, string> = {
  UNPAID: 'Not paid yet',
  OPEN: 'Paid · access window open',
  READY: 'Paid · window opens on first download',
  EXPIRED: 'Paid · window used, ₹49 renewal needed',
  PAID_UNVERIFIED: 'Paid · needs reconciling, do not charge again',
};

function vaultStateText ( view: VaultFileView ): string {
  if ( view.status === 'loading' ) return 'Checking payment…';
  if ( view.status === 'error' ) return view.message;
  if ( view.status !== 'ready' ) return '';
  if ( !view.file ) return 'Not found in this customer’s Vault';
  if ( view.file.status !== 'active' ) return `Vault file ${ view.file.status }`;
  const state = vaultAccessState( view.file );
  return state === 'OPEN' && view.file.accessWindowStatus
    ? `Paid · ${ view.file.accessWindowStatus }`
    : VAULT_ACCESS_LABELS[ state ];
}

/* Which WhatsApp action fits the Vault file now: the ₹49 message while unpaid or used up, the
   Access Vault link while paid, neither while a payment needs reconciling or the file is gone.
   An unread state offers both; the server refuses the one that does not fit. */
function vaultActionsFor ( view: VaultFileView ): { ask: boolean; resend: boolean; renewal: boolean } {
  if ( view.status !== 'ready' ) return { ask: true, resend: true, renewal: false };
  if ( !view.file || view.file.status !== 'active' ) return { ask: false, resend: false, renewal: false };
  const state = vaultAccessState( view.file );
  return {
    ask: state === 'UNPAID' || state === 'EXPIRED',
    resend: state === 'OPEN' || state === 'READY',
    renewal: state === 'EXPIRED',
  };
}

/* The Vault name to start from: the published one, else what Publish would derive (staff's
   label, then the customer's own file name; fileName is the generated reference). */
function defaultVaultName ( doc: api.Document ): string {
  return vaultMessageName( doc.vaultDisplayName || doc.documentTypeLabel || doc.originalFileName
    || doc.fileName || '' );
}

function referenceAgeSeconds ( doc: api.Document ): number {
  const base = doc.referenceIssuedAt || doc.createdAt || 0;
  if ( !base ) return Number.POSITIVE_INFINITY;
  const ms = base < 1e12 ? base * 1000 : base;
  return Math.max( 0, Math.floor( ( Date.now() - ms ) / 1000 ) );
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
  // What staff typed for {{1}} of the Vault message, for the open document.
  const [ vaultName, setVaultName ] = useState( '' );
  // The open document's Vault file (paid or not, window, revoked), and a guard so a slow read
  // for a document staff already closed cannot overwrite the one they opened next.
  const [ vaultFile, setVaultFile ] = useState<VaultFileView>( { status: 'unknown' } );
  const vaultFileSeq = useRef( 0 );
  const [ actionLoading, setActionLoading ] = useState( false );
  const [ remarks, setRemarks ] = useState( '' );
  const [ showCreate, setShowCreate ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ contactQuery, setContactQuery ] = useState( '' );
  const [ contactResults, setContactResults ] = useState<api.Contact[]>( [] );
  const [ contactSearching, setContactSearching ] = useState( false );
  const contactSearchSeq = useRef( 0 );
  const [ customerOrders, setCustomerOrders ] = useState<api.Order[]>( [] );
  const [ ordersLoading, setOrdersLoading ] = useState( false );
  const [ createFile, setCreateFile ] = useState<File | null>( null );
  const [ replacementFile, setReplacementFile ] = useState<File | null>( null );
  const [ createForm, setCreateForm ] = useState( {
    contactId: '', customerName: '', customerPhone: '', orderId: '',
    type: '', typeLabel: '', notes: '',
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
      contactSearchSeq.current += 1;
      setContactResults( [] );
      setContactSearching( false );
      return;
    }

    const q = contactQuery.trim();
    const digits = q.replace( /\D/g, '' );
    const looksNumeric = q.length > 0 && /^[+0-9() .-]+$/.test( q );
    // Do not full-scan ContactsTable for each digit typed. Number searches become useful
    // only once enough digits exist to distinguish a customer; name searches can start at 2.
    const ready = looksNumeric ? ( q.startsWith( '+' ) || q.startsWith( '00' ) ? digits.length >= 7 : digits.length >= 10 ) : q.length >= 2;
    if ( !ready )
    {
      contactSearchSeq.current += 1;
      setContactResults( [] );
      setContactSearching( false );
      return;
    }

    const timer = window.setTimeout( () => {
      const seq = ++contactSearchSeq.current;
      setContactSearching( true );
      void api.searchContactsResult( q, 8 ).then( result => {
        if ( seq !== contactSearchSeq.current ) return;
        setContactResults( result.ok ? result.data : [] );
      } ).finally( () => {
        if ( seq === contactSearchSeq.current ) setContactSearching( false );
      } );
    }, looksNumeric ? 120 : 220 );

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
      type: '', typeLabel: '', notes: '',
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

  const createCustomerReady = Boolean( createForm.contactId || createForm.customerPhone.trim() );
  const createTypeReady = Boolean( createForm.type
    && ( createForm.type !== 'other' || createForm.typeLabel.trim() ) );
  const createReady = createCustomerReady && createTypeReady && Boolean( createFile );

  const closeCreate = () => {
    if ( creating ) return;
    setShowCreate( false );
    resetCreate();
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


  const handleRevalidateReference = async ( doc: api.Document ) => {
    setActionLoading( true );
    try
    {
      const result = await api.revalidateDocumentReference( doc.documentId );
      if ( !result.ok )
      {
        toast.error( result.failure.message || 'Reference cannot be revalidated yet' );
        return;
      }
      const updated = {
        ...doc,
        documentRef: result.data.documentRef,
        fileName: result.data.fileName,
        referenceIssuedAt: result.data.referenceIssuedAt,
      };
      setSelected( updated );
      toast.success( `New reference issued: ${result.data.documentRef}` );
      void loadData();
    } finally
    {
      setActionLoading( false );
    }
  };


  /* Read the published file's state from Secure files (one customer's files, by mobile). */
  const loadVaultFile = async ( doc: api.Document | null ) => {
    const seq = ++vaultFileSeq.current;
    if ( !doc?.vaultFileId || !doc.customerPhone )
    {
      setVaultFile( { status: 'unknown' } );
      return;
    }
    setVaultFile( { status: 'loading' } );
    const result = await api.listSecureFiles( doc.customerPhone );
    if ( seq !== vaultFileSeq.current ) return;
    if ( !result.ok )
    {
      setVaultFile( { status: 'error', message: result.failure.message || 'Could not read the Vault payment state.' } );
      return;
    }
    setVaultFile( {
      status: 'ready',
      file: ( result.data.files || [] ).find( row => row.fileId === doc.vaultFileId ) || null,
    } );
  };

  /* 202 means "may have been sent", which is not a success. Same rule as Secure files. */
  const reportVaultAction = ( result: api.SecureFileActionResult ) => {
    if ( result.ok && result.status !== 202 ) toast.success( result.message );
    else if ( result.status === 202 || result.status === null ) toast.warning( result.message );
    else toast.error( result.message );
  };

  const openDocument = ( doc: api.Document ) => {
    setSelected( doc );
    setReplacementFile( null );
    setRemarks( '' );
    setVaultName( defaultVaultName( doc ) );
    void loadVaultFile( doc );
  };

  /* Publish (or, when already published, rename) with the {{1}} staff typed. Returns the
     updated document, or null after reporting why it failed. */
  const publishVault = async ( doc: api.Document ): Promise<api.Document | null> => {
    const name = vaultMessageName( vaultName );
    const published = await api.publishDocumentToVault( doc.documentId, name || undefined );
    if ( !published.ok )
    {
      toast.error( published.failure.message || 'Could not publish this document to Vault' );
      return null;
    }
    const next = {
      ...doc,
      vaultFileId: published.data.fileId,
      vaultPublishedAt: doc.vaultPublishedAt || Date.now() / 1000,
      vaultDisplayName: published.data.displayName || name || doc.vaultDisplayName,
    };
    setSelected( next );
    setVaultName( vaultMessageName( next.vaultDisplayName ) );
    if ( published.data.created ) toast.success( `Published to Vault as “${ next.vaultDisplayName || 'Document' }”` );
    else if ( published.data.renamed ) toast.success( `Vault name saved: “${ next.vaultDisplayName }”` );
    void loadVaultFile( next );
    return next;
  };

  const handlePublishToVault = async ( doc: api.Document ) => {
    if ( actionLoading ) return;
    setActionLoading( true );
    try
    {
      if ( await publishVault( doc ) ) void loadData();
    } finally
    {
      setActionLoading( false );
    }
  };

  const handleSendVaultOffer = async ( doc: api.Document ) => {
    if ( actionLoading || !doc.vaultFileId ) return;
    setActionLoading( true );
    try
    {
      // A name edited but not saved would otherwise go out as the old one: save it first, so
      // the message says exactly what the preview shows.
      let target: api.Document | null = doc;
      const name = vaultMessageName( vaultName );
      if ( name && name !== ( doc.vaultDisplayName || '' ) ) target = await publishVault( doc );
      if ( !target?.vaultFileId ) return;
      reportVaultAction( await api.requestSecureFilePayment( target.vaultFileId ) );
      // A refusal such as "already paid" means the state moved; re-read it so the right action shows.
      void loadVaultFile( target );
      void loadData();
    } finally
    {
      setActionLoading( false );
    }
  };

  /* A paid file: send the Access Vault link again. Never charges and never opens a window. */
  const handleSendVaultAccess = async ( doc: api.Document ) => {
    if ( actionLoading || !doc.vaultFileId ) return;
    setActionLoading( true );
    try
    {
      reportVaultAction( await api.sendSecureFileAccess( doc.vaultFileId ) );
      void loadVaultFile( doc );
    } finally
    {
      setActionLoading( false );
    }
  };

  const handleReplacementUpload = async ( doc: api.Document ) => {
    if ( actionLoading || !replacementFile ) return;
    setActionLoading( true );
    try
    {
      const mimeType = replacementFile.type || 'application/octet-stream';
      const ticket = await api.initDocumentReplacement( doc.documentId, {
        fileName: replacementFile.name,
        mimeType,
        fileSize: replacementFile.size,
      } );
      if ( !ticket.ok )
      {
        toast.error( ticket.failure.message || 'Could not start replacement upload' );
        return;
      }
      const uploaded = await api.uploadDocumentBytes(
        ticket.data.uploadUrl, replacementFile, ticket.data.contentType || mimeType );
      if ( !uploaded )
      {
        toast.error( 'Replacement upload failed. The current document was not changed.' );
        return;
      }
      const confirmed = await api.confirmDocumentReplacement( doc.documentId );
      if ( !confirmed.ok )
      {
        toast.error( confirmed.failure.message || 'Replacement could not be confirmed' );
        return;
      }
      setReplacementFile( null );
      setSelected( confirmed.data );
      setVaultName( defaultVaultName( confirmed.data ) );
      void loadVaultFile( confirmed.data );
      toast.success( `Replacement uploaded · new reference ${confirmed.data.documentRef || ''}`.trim() );
      void loadData();
    } finally
    {
      setActionLoading( false );
    }
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
        <button onClick={ () => openDocument( d ) } style={ { background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left' } }>
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
      key: 'orderId', header: 'Order', width: '120px', render: ( d: api.Document ) => d.orderId ? (
        <span title={ d.orderId } style={ { fontSize: 'var(--text-xs)', fontFamily: 'monospace', color: 'var(--accent)' } }>{ d.orderNumber || d.orderId.split( '-' ).pop() }</span>
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
      <Modal isOpen={ !!selected } onClose={ () => { setSelected( null ); setReplacementFile( null ); void loadVaultFile( null ); } } title="Document Details" size="lg">
        { selected && (
          <div>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 } }>
              <div><span style={ labelStyle }>File Name</span><div style={ { fontWeight: 500 } }>{ selected.fileName || 'Untitled' }</div></div>
              <div><span style={ labelStyle }>Type</span><div>{ selected.type }{ selected.documentTypeLabel ? ` · ${ selected.documentTypeLabel }` : '' }</div></div>
              <div><span style={ labelStyle }>Source</span><div>{ SOURCE_ICONS[ selected.source ] || '📄' } { selected.source }</div></div>
              <div><span style={ labelStyle }>Size</span><div>{ fmtSize( selected.fileSize ) }</div></div>
              <div><span style={ labelStyle }>Status</span><div><StatusBadge status={ selected.status } /></div></div>
              <div><span style={ labelStyle }>Uploaded</span><div>{ fmtDate( selected.createdAt ) }</div></div>
              <div><span style={ labelStyle }>Customer</span><div>{ selected.customerName || '—' } ({ selected.customerPhone || '—' })</div></div>
              { selected.orderId && (
                <div>
                  <span style={ labelStyle }>Order</span>
                  { selected.orderNumber && <div style={ { fontWeight: 500, fontFamily: 'monospace' } }>{ selected.orderNumber }</div> }
                  <div style={ { fontFamily: 'monospace', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', overflowWrap: 'anywhere' } }>{ selected.orderId }</div>
                </div>
              ) }
              { selected.documentRef && <div><span style={ labelStyle }>Reference</span><div style={ { fontFamily: 'monospace', fontSize: 'var(--text-sm)' } }>{ selected.documentRef }</div></div> }
              { selected.vaultFileId && (
                <div>
                  <span style={ labelStyle }>Vault</span>
                  <div style={ { fontSize: 'var(--text-sm)' } }>Published{ selected.vaultDisplayName ? ` as “${ selected.vaultDisplayName }”` : '' }</div>
                  { vaultStateText( vaultFile ) && (
                    <div role="status" style={ { fontSize: 'var(--text-sm)', fontWeight: 500 } }>{ vaultStateText( vaultFile ) }</div>
                  ) }
                  <div style={ { fontFamily: 'monospace', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', overflowWrap: 'anywhere' } }>{ selected.vaultFileId }</div>
                </div>
              ) }
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

            {/* The ₹49 Vault message. Shown for a document that is, or can be, in the Vault. */ }
            { ( selected.vaultFileId || ( selected.storageKey && [ 'uploaded', 'approved' ].includes( selected.status ) ) ) && (
              <div style={ vaultBoxStyle }>
                <label style={ { fontSize: 'var(--text-md)', fontWeight: 500 } }>
                  Vault message name <span style={ { fontWeight: 400, color: 'var(--text-muted)' } }>({ '{{1}}' } in wecare_valut_49)</span>
                  <input
                    type="text"
                    value={ vaultName }
                    maxLength={ 60 }
                    onChange={ e => setVaultName( e.target.value ) }
                    placeholder="e.g. Trade licence, PAN card, Medical report"
                    style={ inputStyle }
                    disabled={ actionLoading }
                  />
                </label>
                <div style={ helperStyle }>
                  The customer gets: “Your <strong>{ vaultMessageName( vaultName ) || defaultVaultName( selected ) || 'document' }</strong> copy is ready!
                  Pay <strong>₹49</strong> for instant and secure access to download it.” with an <strong>Unlock Vault</strong> button.
                </div>
              </div>
            ) }
            { !selected.vaultFileId && selected.storageKey && ![ 'uploaded', 'approved' ].includes( selected.status ) && (
              <div style={ { ...helperStyle, marginTop: 0, marginBottom: 16 } }>
                Approve this document to publish it to the customer&apos;s Vault.
              </div>
            ) }

            { selected.status === 'reupload_requested' && (
              <div style={ { ...vaultBoxStyle, borderColor: '#a855f7' } }>
                <label style={ { fontSize: 'var(--text-md)', fontWeight: 500 } }>
                  Replacement file
                  <input
                    type="file"
                    onChange={ e => setReplacementFile( e.target.files?.[ 0 ] || null ) }
                    style={ inputStyle }
                    disabled={ actionLoading }
                  />
                </label>
                <div style={ helperStyle }>
                  The current file stays unchanged until the replacement is fully uploaded and confirmed.
                  Confirming the replacement rotates the document reference; the next Vault publish uses a new
                  Vault file ID so an older paid entitlement cannot unlock the new bytes.
                </div>
                <div style={ { marginTop: 10 } }>
                  <Button
                    variant="primary"
                    loading={ actionLoading }
                    disabled={ !replacementFile || !!selected.vaultFileId }
                    onClick={ () => handleReplacementUpload( selected ) }
                  >
                    Upload replacement
                  </Button>
                  { selected.vaultFileId && (
                    <div style={ { ...helperStyle, color: '#991b1b' } }>
                      Revoke the published Vault file first, then upload the replacement.
                    </div>
                  ) }
                </div>
              </div>
            ) }

            <div style={ { display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' } }>
              <Button variant="secondary" onClick={ () => handleDownload( selected ) }>Download</Button>
              <Button
                variant="secondary"
                loading={ actionLoading }
                disabled={ referenceAgeSeconds( selected ) < 24 * 3600 }
                onClick={ () => handleRevalidateReference( selected ) }
              >
                { referenceAgeSeconds( selected ) < 24 * 3600 ? 'Reference valid <24h' : 'Revalidate reference' }
              </Button>
              { selected.vaultFileId ? (
                <Button
                  variant="secondary"
                  loading={ actionLoading }
                  disabled={ !vaultMessageName( vaultName ) || vaultMessageName( vaultName ) === ( selected.vaultDisplayName || '' ) }
                  onClick={ () => handlePublishToVault( selected ) }
                >
                  Save Vault name
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  loading={ actionLoading }
                  disabled={ !selected.storageKey || ![ 'uploaded', 'approved' ].includes( selected.status ) }
                  onClick={ () => handlePublishToVault( selected ) }
                >
                  Publish to Vault
                </Button>
              ) }
              { selected.vaultFileId && vaultActionsFor( vaultFile ).ask && (
                <Button
                  variant="primary"
                  loading={ actionLoading }
                  disabled={ vaultFile.status === 'loading' }
                  onClick={ () => handleSendVaultOffer( selected ) }
                >
                  { vaultActionsFor( vaultFile ).renewal ? 'Send ₹49 renewal message' : 'Send ₹49 Vault message' }
                </Button>
              ) }
              { selected.vaultFileId && vaultActionsFor( vaultFile ).resend && (
                <Button
                  variant="secondary"
                  loading={ actionLoading }
                  disabled={ vaultFile.status === 'loading' }
                  onClick={ () => handleSendVaultAccess( selected ) }
                >
                  Resend Access Vault
                </Button>
              ) }
              <Button variant="primary" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'approved', remarks ) }>Approve</Button>
              <Button variant="danger" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'rejected', remarks ) }>Reject</Button>
              <Button variant="secondary" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'reupload_requested', remarks ) }>Request Reupload</Button>
            </div>
          </div>
        ) }
      </Modal>

      {/* Create Document Modal
          Task modal: no accidental overlay/Escape/top-right dismissal. Cancel is explicit. */ }
      <Modal
        isOpen={ showCreate }
        onClose={ closeCreate }
        title="Upload to Drop Docs"
        size="lg"
        closeOnOverlay={ false }
        closeOnEsc={ false }
        showCloseButton={ false }
        footer={
          <>
            <Button variant="secondary" onClick={ closeCreate } disabled={ creating }>Cancel</Button>
            <Button
              variant="primary"
              loading={ creating }
              disabled={ creating || !createReady }
              onClick={ handleCreateDocument }
            >
              Upload document
            </Button>
          </>
        }
      >
        <div style={ { display: 'flex', flexDirection: 'column', gap: 18 } }>
          <div style={ uploadIntroStyle }>
            Add a document to the customer’s private Drop Docs record. Publishing or charging for Vault happens later, from the document record.
          </div>

          <section style={ sectionStyle }>
            <div style={ sectionHeadingStyle }>
              <strong>1. Customer</strong>
              <span style={ sectionHintStyle }>Required</span>
            </div>

            { createForm.contactId ? (
              <div style={ selectedCustomerStyle }>
                <div style={ { minWidth: 0 } }>
                  <div style={ { fontWeight: 650 } }>{ createForm.customerName || 'Customer' }</div>
                  <div style={ helperStyle }>{ createForm.customerPhone || 'Customer record selected' }</div>
                </div>
                <Button
                  variant="secondary"
                  onClick={ () => {
                    setCreateForm( form => ( {
                      ...form,
                      contactId: '', customerName: '', customerPhone: '', orderId: '',
                    } ) );
                    setContactQuery( '' );
                    setCustomerOrders( [] );
                  } }
                  disabled={ creating }
                >
                  Change
                </Button>
              </div>
            ) : (
              <div>
                <label style={ fieldLabelStyle }>
                  Search customer
                  <input
                    type="text"
                    value={ contactQuery }
                    onChange={ e => setContactQuery( e.target.value ) }
                    placeholder="Name or mobile number"
                    autoComplete="off"
                    style={ inputStyle }
                    disabled={ creating }
                  />
                </label>
                { contactSearching && <div style={ helperStyle }>Searching contacts…</div> }
                { !contactSearching && /^[+0-9() .-]+$/.test( contactQuery.trim() ) && contactQuery.replace( /\D/g, '' ).length > 0 && (
                  ( contactQuery.trim().startsWith( '+' ) || contactQuery.trim().startsWith( '00' ) )
                    ? contactQuery.replace( /\D/g, '' ).length < 7
                    : contactQuery.replace( /\D/g, '' ).length < 10
                ) && (
                  <div style={ helperStyle }>
                    { contactQuery.trim().startsWith( '+' ) || contactQuery.trim().startsWith( '00' )
                      ? 'Enter more of the international number to search.'
                      : 'Enter the full 10-digit mobile number to search.' }
                  </div>
                ) }
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
                { !contactSearching && contactQuery.trim() && contactResults.length === 0 && (
                  <div style={ manualCustomerStyle }>
                    <div style={ { fontWeight: 600 } }>Customer not listed?</div>
                    <div style={ helperStyle }>You can enter a mobile number directly. Name is optional.</div>
                    <div style={ { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 10, marginTop: 10 } }>
                      <label style={ fieldLabelStyle }>
                        Mobile
                        <input
                          type="tel"
                          value={ createForm.customerPhone }
                          onChange={ e => setCreateForm( form => ( { ...form, customerPhone: e.target.value, contactId: '', orderId: '' } ) ) }
                          placeholder="+91…"
                          style={ inputStyle }
                          disabled={ creating }
                        />
                      </label>
                      <label style={ fieldLabelStyle }>
                        Name <span style={ sectionHintStyle }>(optional)</span>
                        <input
                          type="text"
                          value={ createForm.customerName }
                          onChange={ e => setCreateForm( form => ( { ...form, customerName: e.target.value, contactId: '' } ) ) }
                          placeholder="Customer name"
                          style={ inputStyle }
                          disabled={ creating }
                        />
                      </label>
                    </div>
                  </div>
                ) }
              </div>
            ) }
          </section>

          <section style={ sectionStyle }>
            <div style={ sectionHeadingStyle }>
              <strong>2. Document</strong>
              <span style={ sectionHintStyle }>Required</span>
            </div>

            <div style={ { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12 } }>
              <Select
                label="Document type"
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
                  { value: '', label: ordersLoading ? 'Loading orders…' : 'No linked order' },
                  ...customerOrders.map( order => ( {
                    value: order.orderId,
                    label: fmtOrderLabel( order ),
                  } ) ),
                ] }
                disabled={ creating || ordersLoading || !createForm.customerPhone }
              />
            </div>

            { createForm.type === 'other' && (
              <label style={ fieldLabelStyle }>
                Document name
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

            <label style={ fieldLabelStyle }>
              File
              <input
                type="file"
                onChange={ e => setCreateFile( e.target.files?.[ 0 ] || null ) }
                style={ inputStyle }
                disabled={ creating }
              />
            </label>
            { createFile && (
              <div style={ fileSummaryStyle }>
                <div style={ { fontWeight: 600, overflowWrap: 'anywhere' } }>{ createFile.name }</div>
                <div style={ helperStyle }>{ fmtSize( createFile.size ) } · { createFile.type || 'File' }</div>
                <div style={ helperStyle }>Private upload. A six-digit WECARE reference is generated automatically.</div>
              </div>
            ) }
          </section>

          <section style={ sectionStyle }>
            <div style={ sectionHeadingStyle }>
              <strong>3. Note</strong>
              <span style={ sectionHintStyle }>Optional</span>
            </div>
            <textarea
              aria-label="Internal note"
              value={ createForm.notes }
              onChange={ e => setCreateForm( form => ( { ...form, notes: e.target.value } ) ) }
              rows={ 2 }
              placeholder="Internal note about this upload"
              style={ { ...inputStyle, resize: 'vertical', marginTop: 0 } }
              disabled={ creating }
            />
          </section>

          <div style={ uploadFooterNoteStyle }>
            <strong>Next:</strong> review the uploaded document. If the customer should receive a downloadable copy, use <strong>Publish to Vault</strong> from that document later.
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
const fieldLabelStyle: React.CSSProperties = { fontSize: 'var(--text-md)', display: 'block' };
const sectionStyle: React.CSSProperties = { display: 'grid', gap: 12, padding: 14, border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg-primary)' };
const sectionHeadingStyle: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 };
const sectionHintStyle: React.CSSProperties = { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontWeight: 500 };
const selectedCustomerStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 14px', borderRadius: 10, background: 'var(--bg-secondary)', border: '1px solid var(--border)' };
const manualCustomerStyle: React.CSSProperties = { marginTop: 10, padding: 12, border: '1px dashed var(--border)', borderRadius: 10, background: 'var(--bg-secondary)' };
const fileSummaryStyle: React.CSSProperties = { padding: '10px 12px', borderRadius: 10, background: 'var(--bg-secondary)', border: '1px solid var(--border)' };
const uploadIntroStyle: React.CSSProperties = { fontSize: 'var(--text-sm)', lineHeight: 1.5, color: 'var(--text-muted)' };
const uploadFooterNoteStyle: React.CSSProperties = { padding: 12, borderRadius: 10, background: 'var(--bg-secondary)', border: '1px solid var(--border)', fontSize: 'var(--text-sm)', lineHeight: 1.5 };
const vaultBoxStyle: React.CSSProperties = { marginBottom: 16, padding: 12, borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-secondary)' };
const resultListStyle: React.CSSProperties = { marginTop: 6, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', maxHeight: 220, overflowY: 'auto' };
const resultButtonStyle: React.CSSProperties = { width: '100%', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', alignItems: 'center', gap: 12, padding: '10px 12px', border: 0, borderBottom: '1px solid var(--border)', background: 'var(--bg-primary)', cursor: 'pointer', textAlign: 'left' };

export default DocumentsPage;
