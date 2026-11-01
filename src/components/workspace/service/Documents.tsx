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
import { useConfirm } from '../../../contexts/ConfirmContext';
import * as api from '../../../api/client';
import type { ApiFailure } from '../../../api/client';
import { openExternal } from '../../../lib/capacitor';
import { fetchServicePrices, rupeesFromPaise, type ServicePaymentTemplates, type ServicePriceBreakdown } from '../../../lib/servicePricing';
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

const DROP_DOCS_META_ACCEPT = [
  '.jpeg', '.png',
  '.mp4', '.3gp',
  '.aac', '.amr', '.mp3', '.m4a', '.ogg',
  '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
].join( ',' );

type MetaFileRule = { supported: boolean; bytes: number; label: string; kind: string; reason?: string };

function dropDocsMetaLimit ( file: Pick<File, 'type' | 'name'> ): MetaFileRule {
  const mime = ( file.type || '' ).toLowerCase();
  const name = ( file.name || '' ).toLowerCase();
  const ext = name.includes( '.' ) ? name.slice( name.lastIndexOf( '.' ) ) : '';

  if ( ( mime === 'image/jpeg' && ext === '.jpeg' ) || ( mime === 'image/png' && ext === '.png' ) )
    return { supported: true, bytes: 5 * 1024 * 1024, label: '5 MB', kind: 'Image' };

  if ( ( mime === 'video/mp4' && ext === '.mp4' ) || ( mime === 'video/3gpp' && ext === '.3gp' ) )
    return { supported: true, bytes: 16 * 1024 * 1024, label: '16 MB', kind: 'Video' };

  const audioPairs: Record<string, string> = {
    '.aac': 'audio/aac', '.amr': 'audio/amr', '.mp3': 'audio/mpeg',
    '.m4a': 'audio/mp4', '.ogg': 'audio/ogg',
  };
  if ( audioPairs[ ext ] === mime )
    return { supported: true, bytes: 16 * 1024 * 1024, label: '16 MB', kind: 'Audio' };

  const documentPairs: Record<string, string> = {
    '.txt': 'text/plain',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.pdf': 'application/pdf',
  };
  if ( documentPairs[ ext ] === mime )
    return { supported: true, bytes: 100 * 1024 * 1024, label: '100 MB', kind: 'Document' };

  return {
    supported: false,
    bytes: 0,
    label: '',
    kind: 'File',
    reason: 'WhatsApp supports JPEG/PNG images, MP4/3GP video, AAC/AMR/MP3/M4A/OGG audio, and PDF/TXT/Word/Excel/PowerPoint documents here. File extension and MIME type must match.',
  };
}

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
  EXPIRED: 'Paid · access expired · no renewal',
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
  const confirm = useConfirm();
  const [ docs, setDocs ] = useState<api.Document[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ failure, setFailure ] = useState<ApiFailure | null>( null );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ sourceFilter, setSourceFilter ] = useState( '' );
  const [ typeFilter, setTypeFilter ] = useState( '' );
  const [ recordFilter, setRecordFilter ] = useState<'active' | 'archived' | 'all'>( 'active' );
  const [ page, setPage ] = useState( 1 );
  const [ selected, setSelected ] = useState<api.Document | null>( null );
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
  const [ dropDocsPricePaise, setDropDocsPricePaise ] = useState<number | null>( null );
  const [ dropDocsBreakdown, setDropDocsBreakdown ] = useState<ServicePriceBreakdown | null>( null );
  const [ dropDocsTemplates, setDropDocsTemplates ] = useState<ServicePaymentTemplates | null>( null );
  const [ replacementFile, setReplacementFile ] = useState<File | null>( null );
  const [ createForm, setCreateForm ] = useState( {
    contactId: '', customerName: '', customerPhone: '', orderId: '',
    type: '', notes: '',
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
    let cancelled = false;
    void fetchServicePrices().then( prices => {
      if ( cancelled ) return;
      const dropDocs = prices[ 'drop-docs' ];
      setDropDocsPricePaise( dropDocs?.available ? dropDocs.paise : null );
      setDropDocsBreakdown( dropDocs?.available ? dropDocs.breakdown || null : null );
      setDropDocsTemplates( dropDocs?.available ? dropDocs.templates || null : null );
    } );
    return () => { cancelled = true; };
  }, [] );

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
      type: '', notes: '',
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
  const createTypeReady = Boolean( createForm.type );
  const createFileRule = createFile ? dropDocsMetaLimit( createFile ) : null;
  const createFileReady = Boolean( createFile && createFileRule?.supported && createFile.size <= createFileRule.bytes );
  const createReady = createCustomerReady && createTypeReady && createFileReady;

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
    if ( !createFile )
    {
      toast.error( 'Choose a file to upload' );
      return;
    }
    const metaRule = dropDocsMetaLimit( createFile );
    if ( !metaRule.supported )
    {
      toast.error( metaRule.reason || 'This file type is not supported by WhatsApp.' );
      return;
    }
    if ( createFile.size > metaRule.bytes )
    {
      toast.error( `${ metaRule.kind } limit is ${ metaRule.label } on WhatsApp. Selected file: ${ fmtSize( createFile.size ) }.` );
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

      toast.success( 'Document saved to Drop Docs. No Vault upload or payment was initiated.' );

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

  const openDocument = ( doc: api.Document ) => {
    setSelected( doc );
    setReplacementFile( null );
    setRemarks( '' );
    void loadVaultFile( doc );
  };

  const handleArchive = async ( doc: api.Document ) => {
    if ( actionLoading ) return;
    const ok = await confirm( {
      title: `Archive "${doc.fileName || 'document'}"?`,
      message: 'This removes it from the active list but keeps the private file, audit history, and any Vault/payment evidence. You can restore it later.',
      confirmText: 'Archive',
      danger: true,
    } );
    if ( !ok ) return;
    setActionLoading( true );
    try
    {
      if ( await api.archiveDocument( doc.documentId ) )
      {
        toast.success( 'Document archived' );
        if ( selected?.documentId === doc.documentId ) setSelected( null );
        void loadData();
      }
      else toast.error( 'Could not archive this document' );
    } finally
    {
      setActionLoading( false );
    }
  };

  const handleRestore = async ( doc: api.Document ) => {
    if ( actionLoading ) return;
    setActionLoading( true );
    try
    {
      if ( await api.restoreArchivedDocument( doc.documentId ) )
      {
        toast.success( 'Document restored to Active' );
        void loadData();
      }
      else toast.error( 'Could not restore this document' );
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
      void loadVaultFile( confirmed.data );
      toast.success( `Replacement uploaded · new reference ${confirmed.data.documentRef || ''}`.trim() );
      void loadData();
    } finally
    {
      setActionLoading( false );
    }
  };

  const activeDocs = docs.filter( d => !d.archivedAt );
  const archivedDocs = docs.filter( d => !!d.archivedAt );
  const visibleDocs = recordFilter === 'all' ? docs : recordFilter === 'archived' ? archivedDocs : activeDocs;
  const totalPages = Math.max( 1, Math.ceil( visibleDocs.length / PAGE_SIZE ) );
  const paged = visibleDocs.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  const stats = {
    active: activeDocs.length,
    archived: archivedDocs.length,
    inVault: activeDocs.filter( d => !!d.vaultFileId ).length,
  };

  const columns = [
    {
      key: 'fileName', header: 'Document', render: ( d: api.Document ) => (
        <button onClick={ () => openDocument( d ) } style={ documentLinkStyle }>
          <div style={ { fontWeight: 650, fontSize: 'var(--text-md)' } }>{ d.fileName || 'Untitled' }</div>
          <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>
            { d.documentTypeLabel || d.type } · { fmtSize( d.fileSize ) } · { fmtDate( d.createdAt ) }
          </div>
        </button>
      )
    },
    {
      key: 'customer', header: 'Customer', width: '170px', render: ( d: api.Document ) => (
        <div><div style={ { fontWeight: 600, fontSize: 'var(--text-sm)' } }>{ d.customerName || '—' }</div><div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ d.customerPhone }</div></div>
      )
    },
    {
      key: 'workflow', header: 'Review', width: '135px', render: ( d: api.Document ) => <StatusBadge status={ d.status } />
    },
    {
      key: 'delivery', header: 'Historic Vault link', width: '190px', render: ( d: api.Document ) => (
        <div>
          <div style={ { fontWeight: 600, fontSize: 'var(--text-sm)' } }>
            { d.vaultFileId ? 'Historically linked' : 'Separate from Vault' }
          </div>
          <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>
            { d.vaultFileId ? 'Read-only: existing payment/access history' : 'Customer upload only; no Vault payment' }
          </div>
        </div>
      )
    },
    {
      key: 'record', header: 'Record', width: '110px', render: ( d: api.Document ) => (
        <span style={ d.archivedAt ? archivedPillStyle : activePillStyle }>{ d.archivedAt ? 'Archived' : 'Active' }</span>
      )
    },
    {
      key: 'actions', header: 'Next action', width: '280px', render: ( d: api.Document ) => (
        <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
          { d.archivedAt ? (
            <button className="dd-action dd-action-primary" onClick={ () => { void handleRestore( d ); } } disabled={ actionLoading }>Restore</button>
          ) : (
            <>
              { d.vaultFileId && (
                <button className="dd-action dd-action-primary" onClick={ () => openDocument( d ) }>Open Vault status</button>
              ) }
              <button className="dd-action" onClick={ () => { void handleDownload( d ); } }>Download</button>
              <button className="dd-action dd-action-muted" onClick={ () => { void handleArchive( d ); } } disabled={ actionLoading }>Archive</button>
            </>
          ) }
        </div>
      )
    },
  ];

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.documents } />
      <div style={ pageStyle }>
        <div style={ pageHeaderStyle }>
          <div>
            <div style={ eyebrowStyle }>Service · Documents</div>
            <h1 style={ pageTitleStyle }>Drop Docs</h1>
            <p style={ pageLeadStyle }>Manage customer-submitted documents here. Staff Vault uploads and payments are separate under Pay & Flow → Vault.</p>
          </div>
          <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap' } }>
            <Button variant="secondary" icon="refresh" onClick={ loadData }>Refresh</Button>
            <Button variant="primary" icon="create" onClick={ () => setShowCreate( true ) }>Upload document</Button>
          </div>
        </div>

        <div className="dd-summary" style={ summaryStripStyle }>
          <div><strong>{ stats.active }</strong><span>Active</span></div>
          <div><strong>{ stats.inVault }</strong><span>Legacy Vault links</span></div>
          <div><strong>{ stats.archived }</strong><span>Archived</span></div>
        </div>

        <section className="dd-journey" aria-label="Drop Docs WhatsApp journey">
          <div className="dd-journey-head">
            <div>
              <strong>Drop Docs WhatsApp journey</strong>
              <span>What the customer receives, in order</span>
            </div>
            <span className="dd-journey-note">Payment/status/receipt are shared platform defaults; only the paid Drop Docs delivery step is service-specific.</span>
          </div>
          <div className="dd-journey-grid">
            <div><span>1</span><strong>Review &amp; Pay</strong><small>{ dropDocsTemplates?.nativePay || 'Native payment template' }</small></div>
            <div><span>2</span><strong>Order status</strong><small>{ dropDocsTemplates ? `${dropDocsTemplates.orderStatus} · ${dropDocsTemplates.orderStatusStates.join(' → ')}` : 'Shared order-status template' }</small></div>
            <div><span>3</span><strong>Drop Docs Flow</strong><small>{ dropDocsTemplates?.delivery || 'Paid Drop Docs Flow template' }</small></div>
            <div><span>4</span><strong>Receipt</strong><small>{ dropDocsTemplates?.receipt || 'Shared invoice template' }</small></div>
          </div>
        </section>

        <section className="dd-review-preview" aria-label="Drop Docs Review and Pay preview">
          <div className="dd-review-preview-head">
            <div>
              <strong>Review &amp; Pay preview</strong>
              <span>Drop Docs · { dropDocsTemplates?.nativePay || 'native Review & Pay' } · same server pricing as WhatsApp</span>
            </div>
            <img
              src="https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png"
              alt=""
            />
          </div>
          <div className="dd-review-item">
            <strong>Drop Docs × 1</strong>
            <span>{ dropDocsPricePaise === null ? 'Live price unavailable' : `₹${rupeesFromPaise( dropDocsPricePaise )}` }</span>
          </div>
          <div className="dd-review-lines">
            <div><span>Items</span><strong>{ dropDocsPricePaise === null ? '—' : `₹${rupeesFromPaise( dropDocsPricePaise )}` }</strong></div>
            <div><span>GST (18%)</span><strong>{ dropDocsBreakdown ? `₹${rupeesFromPaise( dropDocsBreakdown.supplyGstPaise )}` : '—' }</strong></div>
            <div><span>Delight</span><strong>{ dropDocsBreakdown ? `−₹${rupeesFromPaise( dropDocsBreakdown.delightPaise )}` : '—' }</strong></div>
            <div><span>Express</span><strong>{ dropDocsBreakdown ? `₹${rupeesFromPaise( dropDocsBreakdown.expressPaise )}` : '—' }</strong></div>
            <div><span>Convenience Fee</span><strong>{ dropDocsBreakdown ? `₹${rupeesFromPaise( dropDocsBreakdown.convenienceFeePaise )}` : '—' }</strong></div>
            <div><span>GST on Convenience Fee (18%)</span><strong>{ dropDocsBreakdown ? `₹${rupeesFromPaise( dropDocsBreakdown.convenienceGstPaise )}` : '—' }</strong></div>
            <div className="dd-review-total"><span>Amount Payable</span><strong>{ dropDocsBreakdown ? `₹${rupeesFromPaise( dropDocsBreakdown.totalPayablePaise )}` : '—' }</strong></div>
          </div>
        </section>

        <div style={ toolbarStyle }>
          <div style={ segmentedStyle } aria-label="Record visibility">
            { ( [ [ 'active', 'Active' ], [ 'archived', 'Archived' ], [ 'all', 'All' ] ] as const ).map( ( [ value, label ] ) => (
              <button
                key={ value }
                type="button"
                onClick={ () => { setRecordFilter( value ); setPage( 1 ); } }
                style={ recordFilter === value ? segmentActiveStyle : segmentStyle }
              >
                { label }
              </button>
            ) ) }
          </div>
          <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap' } }>
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
        </div>

        <ServiceDataState
          loading={ loading }
          failure={ failure }
          empty={ visibleDocs.length === 0 }
          emptyLabel={ recordFilter === 'archived' ? 'No archived documents' : 'No documents here' }
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
              <div><span style={ labelStyle }>Review status</span><div><StatusBadge status={ selected.status } /></div></div>
              <div><span style={ labelStyle }>Record</span><div><span style={ selected.archivedAt ? archivedPillStyle : activePillStyle }>{ selected.archivedAt ? 'Archived' : 'Active' }</span></div></div>
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

            { selected.vaultFileId && (
              <div style={ vaultBoxStyle }>
                <div style={ { fontSize: 'var(--text-md)', fontWeight: 650 } }>Historical Vault linkage</div>
                <div style={ helperStyle }>
                  This older document was previously linked to a Vault file. Its existing payment
                  history remains read-only here. New staff Vault uploads and sends are managed
                  separately under Pay & Flow → Vault.
                </div>
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
                  Confirming the replacement rotates the Drop Docs document reference. Any older Vault
                  file and paid entitlement remain independent and are not replaced here.
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
                      Legacy Vault-linked documents cannot be replaced from this screen. Manage the existing Vault entitlement separately.
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
              { selected.archivedAt ? (
                <Button variant="primary" loading={ actionLoading } onClick={ () => { void handleRestore( selected ); } }>Restore</Button>
              ) : (
                <>
                  <Button variant="primary" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'approved', remarks ) }>Approve</Button>
                  <Button variant="danger" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'rejected', remarks ) }>Reject</Button>
                  <Button variant="secondary" loading={ actionLoading } onClick={ () => handleStatusAction( selected, 'reupload_requested', remarks ) }>Request Reupload</Button>
                  <Button variant="secondary" loading={ actionLoading } onClick={ () => { void handleArchive( selected ); } }>Archive</Button>
                </>
              ) }
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
              onClick={ () => { void handleCreateDocument(); } }
            >
              Save to Drop Docs
            </Button>
          </>
        }
      >
        <div className="dd-upload-form" style={ { display: 'flex', flexDirection: 'column', gap: 14 } }>
          <div style={ uploadIntroStyle }>
            Customer Drop Docs upload only. Files are stored in private Drop Docs storage and do not create a Vault file, payment request, or WhatsApp message.
          </div>

          <section style={ sectionStyle }>
            <div style={ sectionHeadingStyle }>
              <strong>Customer</strong>
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
                    style={ uploadInputStyle }
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
                    <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10, marginTop: 10 } }>
                      <label style={ fieldLabelStyle }>
                        Mobile
                        <input
                          type="tel"
                          value={ createForm.customerPhone }
                          onChange={ e => setCreateForm( form => ( { ...form, customerPhone: e.target.value, contactId: '', orderId: '' } ) ) }
                          placeholder="+91…"
                          style={ uploadInputStyle }
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
                          style={ uploadInputStyle }
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
              <strong>Document</strong>
              <span style={ sectionHintStyle }>Required</span>
            </div>

            <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 } }>
              <Select
                label="Document type"
                value={ createForm.type }
                onChange={ value => setCreateForm( form => ( { ...form, type: value } ) ) }
                options={ TYPE_SELECT_OPTIONS }
                style={ uploadSelectStyle }
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
                style={ uploadSelectStyle }
                disabled={ creating || ordersLoading || !createForm.customerPhone }
              />
            </div>

            <label style={ fieldLabelStyle }>
              File
              <input
                type="file"
                accept={ DROP_DOCS_META_ACCEPT }
                onChange={ e => {
                  const next = e.target.files?.[ 0 ] || null;
                  setCreateFile( next );
                  if ( !next ) return;
                  const rule = dropDocsMetaLimit( next );
                  if ( !rule.supported )
                  {
                    toast.error( rule.reason || 'This file type is not supported by WhatsApp.' );
                    e.target.value = '';
                    setCreateFile( null );
                    return;
                  }
                  if ( next.size > rule.bytes )
                  {
                    toast.error( `${ rule.kind } limit is ${ rule.label } on WhatsApp. Selected file: ${ fmtSize( next.size ) }.` );
                    e.target.value = '';
                    setCreateFile( null );
                  }
                  else
                  {
                    toast.success( `${ rule.kind } selected · WhatsApp limit ${ rule.label }.` );
                  }
                } }
                className="dd-auth-file"
                disabled={ creating }
              />
            </label>
            { createFile && (
              <div style={ fileSummaryStyle }>
                <div style={ { fontWeight: 650, overflowWrap: 'anywhere' } }>{ createFile.name }</div>
                <div style={ { ...helperStyle, color: createFileRule && createFile.size > createFileRule.bytes ? '#991b1b' : 'var(--text-muted)' } }>
                  { fmtSize( createFile.size ) } · { createFile.type || 'File' } · WhatsApp { createFileRule?.kind || 'file' } limit { createFileRule?.label || 'unsupported' }
                </div>
                <div style={ helperStyle }>Uploads directly to private storage. A WECARE reference and filename are generated automatically.</div>
              </div>
            ) }
          </section>

          <section style={ sectionStyle }>
            <div style={ sectionHeadingStyle }>
              <strong>Note</strong>
              <span style={ sectionHintStyle }>Optional</span>
            </div>
            <textarea
              aria-label="Internal note"
              value={ createForm.notes }
              onChange={ e => setCreateForm( form => ( { ...form, notes: e.target.value } ) ) }
              rows={ 2 }
              placeholder="Internal note about this upload"
              style={ { ...uploadInputStyle, resize: 'vertical', minHeight: 84, paddingTop: 12, marginTop: 0 } }
              disabled={ creating }
            />
          </section>

          <div style={ uploadFooterNoteStyle }>
            Drop Docs is the customer-document service. To upload a separate staff Vault file,
            use Workspace → Pay & Flow → Vault.
          </div>
        </div>
      </Modal>
      <style jsx global>{`
        .dd-summary > div{background:var(--bg-primary);padding:14px 16px;display:grid;gap:3px}
        .dd-review-preview{margin:0 0 16px;padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--bg-primary)}
        .dd-review-preview-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px}
        .dd-review-preview-head>div{display:grid;gap:3px}
        .dd-review-preview-head span{font-size:var(--text-xs);color:var(--text-muted)}
        .dd-review-preview-head img{width:52px;height:52px;object-fit:cover;border-radius:10px;background:#fff}
        .dd-review-item{display:flex;justify-content:space-between;gap:12px;padding:12px;border-radius:10px;background:var(--lime-tint)}
        .dd-review-lines{display:grid;margin-top:10px;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
        .dd-review-lines>div{display:flex;justify-content:space-between;gap:12px;padding:9px 0;font-size:var(--text-sm)}
        .dd-review-lines>div+div{border-top:1px solid rgba(26,58,42,.07)}
        .dd-review-total{font-size:var(--text-md)!important;color:var(--accent)}
        .dd-journey{margin:0 0 16px;padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--bg-primary)}
        .dd-journey-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-bottom:12px}
        .dd-journey-head>div{display:grid;gap:3px}
        .dd-journey-head span,.dd-journey-note{font-size:var(--text-xs);color:var(--text-muted)}
        .dd-journey-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}
        .dd-journey-grid>div{display:grid;grid-template-columns:28px 1fr;grid-template-areas:"n t" "n s";column-gap:8px;align-items:center;padding:10px 12px;border:1px solid var(--border);border-radius:9px;background:var(--bg-secondary)}
        .dd-journey-grid>div>span{grid-area:n;width:26px;height:26px;border-radius:999px;display:grid;place-items:center;background:var(--accent);color:#fff;font-size:var(--text-xs);font-weight:700}
        .dd-journey-grid strong{grid-area:t;font-size:var(--text-sm)}
        .dd-journey-grid small{grid-area:s;color:var(--text-muted);overflow-wrap:anywhere}
        .dd-summary strong{font-size:22px;color:var(--accent)}
        .dd-summary span{font-size:var(--text-xs);color:var(--text-muted)}
        .dd-action{
          min-height:34px;
          border:1px solid var(--border);
          background:var(--bg-primary);
          color:var(--accent);
          border-radius:8px;
          padding:6px 10px;
          font-size:var(--text-sm);
          font-weight:600;
          cursor:pointer;
        }
        .dd-action:hover{background:var(--bg-secondary)}
        .dd-action:disabled{opacity:.55;cursor:not-allowed}
        .dd-action-primary{background:var(--accent);color:#fff;border-color:var(--accent)}
        .dd-action-primary:hover{filter:brightness(.96);background:var(--accent)}
        .dd-action-muted{color:var(--text-muted)}
        .dd-action-danger{color:#991b1b}
        .dd-upload-form input:focus,.dd-upload-form textarea:focus{outline:0!important;box-shadow:inset 0 -2px 0 rgba(26,58,42,.34),0 0 0 2px rgba(209,244,112,.22)!important}
        .dd-auth-file{display:block;width:100%;min-height:54px;margin-top:7px;padding:6px 8px;border:0;border-radius:12px;background:#fff;color:var(--text);font:600 15px/1.3 inherit;box-shadow:inset 0 0 0 1px rgba(26,58,42,.08)}
        .dd-auth-file::file-selector-button{min-height:40px;margin-right:12px;padding:0 14px;border:0;border-radius:9px;background:var(--lime-tint);color:var(--accent);font:650 15px/1 inherit;cursor:pointer}
        .dd-auth-file:hover::file-selector-button{background:var(--lime)}
        .dd-variable-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
        .dd-variable-grid>div{display:grid;gap:4px;padding:10px 12px;border-radius:12px;background:#fff;box-shadow:inset 0 0 0 1px rgba(26,58,42,.07)}
        .dd-variable-grid span{font-size:var(--text-xs);color:var(--text-muted);font-weight:600}
        .dd-variable-grid strong{font-size:var(--text-sm);color:var(--accent);overflow-wrap:anywhere}
        @media(max-width:720px){.dd-variable-grid{grid-template-columns:1fr}}
      `}</style>
    </MaybeLayout>
  );
};

/* `selectStyle` went with the last native select in this file - it only ever skinned those. */
const labelStyle: React.CSSProperties = { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', display: 'block', marginBottom: 2 };
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', fontSize: 'var(--text-md)', marginTop: 4 };
const uploadInputStyle: React.CSSProperties = { display: 'block', width: '100%', minHeight: 48, padding: '0 12px', borderRadius: 12, border: 0, background: '#fff', boxShadow: 'inset 0 0 0 1px rgba(26,58,42,.08)', color: 'var(--text)', fontSize: 16, marginTop: 7, outline: 0 };
const uploadSelectStyle: React.CSSProperties = { width: '100%', minHeight: 48, borderRadius: 12, border: 0, background: '#fff', boxShadow: 'inset 0 0 0 1px rgba(26,58,42,.08)' };
const actionBtnStyle: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', fontSize: 'var(--text-base)', padding: '2px 4px' };
const helperStyle: React.CSSProperties = { fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginTop: 6 };
const fieldLabelStyle: React.CSSProperties = { fontSize: 'var(--text-md)', display: 'block' };
const sectionStyle: React.CSSProperties = { display: 'grid', gap: 12, padding: 18, border: 0, borderRadius: 14, background: '#fcfdfa', boxShadow: '0 8px 24px rgba(16,32,24,.06)' };
const sectionHeadingStyle: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 };
const sectionHintStyle: React.CSSProperties = { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontWeight: 500 };
const selectedCustomerStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 14px', minHeight: 58, borderRadius: 12, background: '#fff', border: 0, boxShadow: 'inset 0 0 0 1px rgba(26,58,42,.08)' };
const manualCustomerStyle: React.CSSProperties = { marginTop: 10, padding: 14, border: 0, borderRadius: 12, background: '#fff', boxShadow: 'inset 0 0 0 1px rgba(26,58,42,.08)' };
const fileSummaryStyle: React.CSSProperties = { padding: '10px 12px', borderRadius: 12, background: '#fff', border: 0, boxShadow: 'inset 0 0 0 1px rgba(26,58,42,.08)' };
const uploadIntroStyle: React.CSSProperties = { fontSize: 15, lineHeight: 1.5, color: 'var(--text-muted)', padding: '0 2px' };
const uploadFooterNoteStyle: React.CSSProperties = { padding: '11px 14px', borderRadius: 12, background: 'var(--lime-tint)', color: 'var(--accent)', border: 0, fontSize: 'var(--text-sm)', lineHeight: 1.5 };
const pageStyle: React.CSSProperties = { padding: '28px 32px', maxWidth: 1480 };
const pageHeaderStyle: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 24, marginBottom: 22 };
const eyebrowStyle: React.CSSProperties = { fontSize: 'var(--text-xs)', fontWeight: 650, color: 'var(--text-muted)', letterSpacing: '.04em', textTransform: 'uppercase', marginBottom: 6 };
const pageTitleStyle: React.CSSProperties = { fontSize: 'var(--text-3xl)', lineHeight: 1.1, fontWeight: 720, color: 'var(--accent)', margin: 0, letterSpacing: '-.02em' };
const pageLeadStyle: React.CSSProperties = { maxWidth: 720, fontSize: 'var(--text-md)', lineHeight: 1.5, color: 'var(--text-muted)', margin: '7px 0 0' };
const summaryStripStyle: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 1, overflow: 'hidden', border: '1px solid var(--border)', borderRadius: 12, background: 'var(--border)', marginBottom: 16 };
const toolbarStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 14 };
const segmentedStyle: React.CSSProperties = { display: 'inline-flex', padding: 3, gap: 2, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 10 };
const segmentStyle: React.CSSProperties = { border: 0, background: 'transparent', color: 'var(--text-muted)', padding: '7px 12px', borderRadius: 7, cursor: 'pointer', fontWeight: 600 };
const segmentActiveStyle: React.CSSProperties = { ...segmentStyle, background: 'var(--bg-primary)', color: 'var(--accent)', boxShadow: '0 1px 2px rgba(0,0,0,.08)' };
const documentLinkStyle: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left', color: 'var(--accent)' };
const activePillStyle: React.CSSProperties = { display: 'inline-flex', padding: '4px 8px', borderRadius: 999, background: '#dcfce7', color: '#166534', fontSize: 'var(--text-xs)', fontWeight: 650 };
const archivedPillStyle: React.CSSProperties = { display: 'inline-flex', padding: '4px 8px', borderRadius: 999, background: '#f3f4f6', color: '#6b7280', fontSize: 'var(--text-xs)', fontWeight: 650 };
const vaultBoxStyle: React.CSSProperties = { marginBottom: 16, padding: 12, borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-secondary)' };
const resultListStyle: React.CSSProperties = { marginTop: 6, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', maxHeight: 220, overflowY: 'auto' };
const resultButtonStyle: React.CSSProperties = { width: '100%', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', alignItems: 'center', gap: 12, padding: '10px 12px', border: 0, borderBottom: '1px solid var(--border)', background: 'var(--bg-primary)', cursor: 'pointer', textAlign: 'left' };

export default DocumentsPage;
