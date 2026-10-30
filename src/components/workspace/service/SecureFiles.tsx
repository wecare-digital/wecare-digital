/**
 * Vault operations — staff upload, publish, payment and customer access.
 *
 * Vault has one supported intake path: a staff upload is first saved as a private
 * DocumentTable/S3 document, confirmed from S3, then explicitly published into
 * SecureFilesTable. The retired /secure-files/upload-init and /confirm routes are not
 * used here.
 *
 * The customer-facing /vault/?file=<id> surface owns download/payment presentation.
 * This component is the staff surface and never exposes raw S3 keys.
 */

import React, { useCallback, useEffect, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Spinner from '../../../components/ui/Spinner';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import * as api from '../../../api/client';
import type { SecureFile, SecureFileAccessState } from '../../../api/client';
import { openExternal } from '../../../lib/capacitor';
import { fetchServicePrices, rupeesFromPaise, type ServicePaymentTemplates, type ServicePriceBreakdown } from '../../../lib/servicePricing';
import { resolveWaMime, validateWaMediaSize, WA_ACCEPT_STRING } from '../../../lib/wa-media';

function formatBytes ( bytes: number ): string {
    if ( !bytes ) return '0 B';
    const units = [ 'B', 'KB', 'MB', 'GB' ];
    const exponent = Math.min( Math.floor( Math.log( bytes ) / Math.log( 1024 ) ), units.length - 1 );
    return `${( bytes / Math.pow( 1024, exponent ) ).toFixed( exponent === 0 ? 0 : 1 )} ${units[ exponent ]}`;
}

/** The backend's access state, or a fallback for a list served by an older backend. */
function accessStateOf ( row: SecureFile ): SecureFileAccessState {
    if ( row.accessState ) return row.accessState;
    return row.vaultPaymentStatus === 'PAID' ? 'READY' : 'UNPAID';
}

const PURCHASE_LABELS: Record<SecureFileAccessState, string> = {
    UNPAID: 'Awaiting purchase',
    OPEN: 'Paid · Window open',
    READY: 'Paid · Access ready',
    EXPIRED: 'Paid · Window used, renewal needed',
    PAID_UNVERIFIED: 'Paid · Needs reconciling, do not charge',
};

/** Status pill colours. Lime is reserved for actions, so status uses its own set. */
const STATUS_COLOURS: Record<string, { bg: string; fg: string; border: string }> = {
    active: { bg: '#dcfce7', fg: '#166534', border: '#16a34a' },
    pending: { bg: '#fef3c7', fg: '#92400e', border: '#d97706' },
    revoked: { bg: '#fee2e2', fg: '#991b1b', border: '#ef4444' },
};

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

export default function SecureFilesPage ( { signOut, user, embedded }: PageProps ) {
    const toast = useToastContext();
    const confirm = useConfirm();

    const [ name, setName ] = useState( '' );
    const [ mobile, setMobile ] = useState( '' );
    const [ file, setFile ] = useState<File | null>( null );
    const [ uploading, setUploading ] = useState( false );
    const [ step, setStep ] = useState( '' );

    const [ files, setFiles ] = useState<SecureFile[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ loadError, setLoadError ] = useState( '' );
    const [ filterMobile, setFilterMobile ] = useState( '' );
    const [ truncated, setTruncated ] = useState( false );
    // On by default: an unpaid document is only useful once its owner receives native Review & Pay.
    const [ requestAfterUpload, setRequestAfterUpload ] = useState( true );
    // The fileId whose WhatsApp action is in flight, so one click cannot send twice.
    const [ acting, setActing ] = useState( '' );
    const [ reviewFile, setReviewFile ] = useState<SecureFile | null>( null );
    const [ vaultPricePaise, setVaultPricePaise ] = useState<number | null>( null );
    const [ vaultBreakdown, setVaultBreakdown ] = useState<ServicePriceBreakdown | null>( null );
    const [ vaultTemplates, setVaultTemplates ] = useState<ServicePaymentTemplates | null>( null );
    const [ vaultPriceLoading, setVaultPriceLoading ] = useState( false );

    /** Refetch and replace the table. Used by the filter button and after an upload. */
    const fetchInto = useCallback( async ( mobileFilter?: string ) => {
        const result = await api.listSecureFiles( mobileFilter || undefined );
        if ( result.ok )
        {
            setFiles( result.data.files || [] );
            setTruncated( !!result.data.truncated );
            setLoadError( '' );
        } else
        {
            // Say why, rather than rendering an empty table that looks like "no files".
            setLoadError( result.failure.message || 'Could not load secure files' );
            setFiles( [] );
        }
        setLoading( false );
    }, [] );

    /** Reload with the spinner, for buttons and post-upload refresh. */
    const load = useCallback( ( mobileFilter?: string ) => {
        setLoading( true );
        return fetchInto( mobileFilter );
    }, [ fetchInto ] );

    useEffect( () => {
        let cancelled = false;
        setVaultPriceLoading( true );
        void fetchServicePrices().then( prices => {
            if ( cancelled ) return;
            const vault = prices.vault;
            setVaultPricePaise( vault?.available ? vault.paise : null );
            setVaultBreakdown( vault?.available ? vault.breakdown || null : null );
            setVaultTemplates( vault?.available ? vault.templates || null : null );
            setVaultPriceLoading( false );
        } );
        return () => { cancelled = true; };
    }, [] );

    useEffect( () => {
        if ( !reviewFile ) return;
        const onKey = ( event: KeyboardEvent ) => {
            if ( event.key === 'Escape' ) setReviewFile( null );
        };
        window.addEventListener( 'keydown', onKey );
        return () => window.removeEventListener( 'keydown', onKey );
    }, [ reviewFile ] );

    useEffect( () => {
        // Settled from the promise callback rather than the effect body: `loading`
        // already starts true, and calling a state-setting helper directly here trips
        // react-hooks/set-state-in-effect even when every write is after an await.
        let cancelled = false;
        api.listSecureFiles().then( result => {
            if ( cancelled ) return;
            if ( result.ok )
            {
                setFiles( result.data.files || [] );
                setTruncated( !!result.data.truncated );
                setLoadError( '' );
            } else
            {
                setLoadError( result.failure.message || 'Could not load secure files' );
                setFiles( [] );
            }
            setLoading( false );
        } );
        return () => { cancelled = true; };
    }, [] );

    /** Report a WhatsApp action. 202 means "may have been sent", which is not a success. */
    const reportAction = ( result: api.SecureFileActionResult ) => {
        if ( result.ok && result.status !== 202 ) toast.success( result.message );
        else if ( result.status === 202 || result.status === null ) toast.warning( result.message );
        else toast.error( result.message );
    };

    const handleRequestPayment = async ( target: SecureFile ) => {
        if ( acting ) return;
        setActing( target.fileId );
        try
        {
            reportAction( await api.requestSecureFilePayment( target.fileId ) );
            load( filterMobile || undefined );
        } finally
        {
            setActing( '' );
        }
    };

    const handleSendAccess = async ( target: SecureFile ) => {
        if ( acting ) return;
        setActing( target.fileId );
        try
        {
            reportAction( await api.sendSecureFileAccess( target.fileId ) );
        } finally
        {
            setActing( '' );
        }
    };

    const handleStaffDownload = async ( target: SecureFile ) => {
        if ( !target.sourceDocumentId )
        {
            toast.error( 'The source Drop Docs record is not available for this Vault file.' );
            return;
        }
        const url = await api.getDocumentDownloadUrl( target.sourceDocumentId );
        if ( url ) void openExternal( url );
        else toast.error( 'Download not available' );
    };

    const handleCustomerVaultLink = ( target: SecureFile ) => {
        void openExternal( `https://wecare.digital/vault/?file=${encodeURIComponent( target.fileId )}` );
    };

    /** The file ID is what the Vault template's button carries; copying beats retyping it. */
    const handleCopyId = async ( target: SecureFile ) => {
        try
        {
            if ( !navigator.clipboard?.writeText ) throw new Error( 'clipboard unavailable' );
            await navigator.clipboard.writeText( target.fileId );
            toast.success( 'File ID copied' );
        } catch
        {
            // WebViews and insecure contexts often have no clipboard API: show it instead.
            toast.info( `File ID: ${ target.fileId }` );
        }
    };

    const resetForm = () => {
        setName( '' );
        setMobile( '' );
        setFile( null );
    };

    const handleUpload = async () => {
        const customerName = name.trim();
        const customerPhone = mobile.trim();
        if ( !file ) { toast.error( 'Choose a document first' ); return; }
        if ( !customerName ) { toast.error( 'Customer name is required' ); return; }
        if ( !customerPhone ) { toast.error( 'Customer mobile number is required' ); return; }

        const contentType = resolveWaMime( file );
        const validation = validateWaMediaSize( file, contentType );
        if ( !validation.ok )
        {
            toast.error( validation.message || 'This file cannot be uploaded to Vault.' );
            return;
        }

        setUploading( true );
        try
        {
            setStep( 'Creating private document record…' );
            const ticket = await api.initDocumentUpload( {
                customerName,
                customerPhone,
                // Vault no longer asks staff to classify the file. Keep the Documents API's
                // neutral internal type until that older contract is retired server-side.
                type: 'other',
                fileName: file.name,
                mimeType: contentType,
                fileSize: file.size,
                notes: 'Uploaded from Workspace Vault',
            } );
            if ( !ticket.ok )
            {
                toast.error( ticket.failure.message || 'Could not start the document upload' );
                return;
            }

            setStep( 'Uploading private document…' );
            const uploaded = await api.uploadDocumentBytes(
                ticket.data.uploadUrl,
                file,
                ticket.data.contentType || contentType,
            );
            if ( !uploaded )
            {
                toast.error( 'File upload failed. The Vault file was not published.' );
                return;
            }

            setStep( 'Confirming stored bytes…' );
            const confirmed = await api.confirmDocumentUpload( ticket.data.documentId );
            if ( !confirmed.ok )
            {
                toast.error( confirmed.failure.message || 'The uploaded document could not be confirmed' );
                return;
            }

            setStep( 'Publishing to Vault…' );
            const published = await api.publishDocumentToVault( confirmed.data.documentId );
            if ( !published.ok )
            {
                toast.warning( 'Document saved privately, but Vault publishing failed. Nothing was charged.' );
                return;
            }

            toast.success( `${ published.data.displayName || ticket.data.fileName } published to Vault` );
            if ( requestAfterUpload )
            {
                setStep( 'Sending Review & Pay on WhatsApp…' );
                reportAction( await api.requestSecureFilePayment( published.data.fileId ) );
            }

            resetForm();
            await load( customerPhone );
            setFilterMobile( customerPhone );
        } catch ( err: unknown )
        {
            toast.error( err instanceof Error ? err.message : 'Upload failed' );
        } finally
        {
            setUploading( false );
            setStep( '' );
        }
    };

    const handleRevoke = async ( target: SecureFile ) => {
        const ok = await confirm( {
            title: `Revoke "${target.displayName}"?`,
            message: 'The customer will no longer be able to download it. '
                + 'The record is kept so the history of who was charged survives.',
            confirmText: 'Revoke',
            danger: true,
        } );
        if ( !ok ) return;

        const result = await api.revokeSecureFile( target.fileId );
        if ( result.ok )
        {
            toast.success( 'File revoked' );
            load( filterMobile || undefined );
        } else
        {
            toast.error( result.failure.message || 'Could not revoke the file' );
        }
    };

    const body = (
        <>
            <div className="sf-wrap">
                <header className="sf-head">
                    <p className="sf-eyebrow">Service · Vault</p>
                    <h1 className="sf-title">Vault</h1>
                    <p className="sf-lead">
                        Upload a customer document into the private Documents store, publish it to Vault,
                        then manage Review &amp; Pay and Access Vault from one place.
                    </p>
                </header>

                <section className="sf-journey" aria-label="Vault customer journey">
                    <div><span>1</span><strong>Review &amp; Pay</strong><small>{ vaultTemplates?.nativePay || 'Native payment template' }</small></div>
                    <div><span>2</span><strong>Order status</strong><small>{ vaultTemplates ? `${vaultTemplates.orderStatus} · ${vaultTemplates.orderStatusStates.join( ' → ' )}` : 'Shared order-status template' }</small></div>
                    <div><span>3</span><strong>Access Vault</strong><small>{ vaultTemplates?.delivery || 'Vault delivery template' } · {'{{1}}'} = Vault file ID</small></div>
                    <div><span>4</span><strong>Receipt</strong><small>{ vaultTemplates?.receipt || 'Shared invoice template' }</small></div>
                </section>

                <section className="sf-panel" aria-labelledby="sf-add">
                    <h2 className="sf-h2" id="sf-add">Upload document</h2>
                    <p className="sf-note">
                        The file is saved privately as a Document first, verified in S3, then published to Vault.
                        Direct Vault upload is retired.
                    </p>

                    <div className="sf-grid">
                        <div className="sf-field">
                            <label className="sf-label" htmlFor="sf-name">Customer name</label>
                            <input
                                id="sf-name"
                                className="sf-input"
                                value={ name }
                                onChange={ e => setName( e.target.value ) }
                                placeholder="Ramesh Kumar"
                                autoComplete="off"
                                disabled={ uploading }
                            />
                        </div>

                        <div className="sf-field">
                            <label className="sf-label" htmlFor="sf-mobile">Customer mobile</label>
                            <input
                                id="sf-mobile"
                                className="sf-input"
                                value={ mobile }
                                onChange={ e => setMobile( e.target.value ) }
                                placeholder="8100640044"
                                inputMode="tel"
                                autoComplete="tel"
                                disabled={ uploading }
                            />
                            <p className="sf-hint">
                                This verified number owns the Vault file and receives the WhatsApp sign-in/payment messages.
                            </p>
                        </div>

                        <div className="sf-field">
                            <label className="sf-label" htmlFor="sf-file">Document</label>
                            <input
                                id="sf-file"
                                className="sf-input sf-input-file"
                                type="file"
                                accept={ WA_ACCEPT_STRING }
                                onChange={ e => setFile( e.target.files?.[ 0 ] || null ) }
                                disabled={ uploading }
                            />
                            <p className="sf-hint">
                                { file
                                    ? `${ formatBytes( file.size ) } · ${ resolveWaMime( file ) }`
                                    : 'PDF, Word, Excel, PowerPoint, text, JPEG/PNG, supported audio or video.' }
                            </p>
                        </div>

                        <div className="sf-field sf-field-wide">
                            <label className="sf-check" htmlFor="sf-request">
                                <input
                                    id="sf-request"
                                    type="checkbox"
                                    checked={ requestAfterUpload }
                                    onChange={ e => setRequestAfterUpload( e.target.checked ) }
                                    disabled={ uploading }
                                />
                                <span>Send Review &amp; Pay on WhatsApp after publishing</span>
                            </label>
                            <p className="sf-hint">
                                Turn this off to publish the file without asking the customer to pay yet.
                                Vault itself has no Meta Flow.
                            </p>
                        </div>
                    </div>

                    <div className="sf-actions">
                        <button className="sf-cta" type="button" onClick={ () => { void handleUpload(); } } disabled={ uploading }>
                            { uploading ? 'Working…' : 'Upload & publish' }
                        </button>
                        <span className="sf-aside">
                            { uploading && step
                                ? step
                                : 'One supported path: Documents → private S3 → confirm → Vault.' }
                        </span>
                    </div>
                </section>

                {/* ── registered files ──────────────────────────────────────────── */ }
                <section className="sf-panel" aria-labelledby="sf-list">
                    <div className="sf-listhead">
                        <div>
                            <h2 className="sf-h2" id="sf-list">Current Vault documents</h2>
                            <p className="sf-note">
                                { loading ? 'Loading…' : `${files.length} file${files.length === 1 ? '' : 's'}` }
                            </p>
                        </div>
                        <div className="sf-filter">
                            <div className="sf-field">
                                <label className="sf-label" htmlFor="sf-filter">Filter by mobile</label>
                                <input
                                    id="sf-filter"
                                    className="sf-input"
                                    value={ filterMobile }
                                    onChange={ e => setFilterMobile( e.target.value ) }
                                    placeholder="8100640044"
                                    inputMode="tel"
                                />
                            </div>
                            <button
                                className="sf-cta sf-cta-quiet"
                                onClick={ () => load( filterMobile || undefined ) }
                            >
                                Apply
                            </button>
                        </div>
                    </div>

                    { loadError && (
                        <div className="sf-alert" role="alert">{ loadError }</div>
                    ) }

                    { loading && (
                        <p className="sf-note sf-note-pad">
                            <Spinner /> Loading files…
                        </p>
                    ) }

                    { !loading && !loadError && files.length === 0 && (
                        <p className="sf-note sf-note-pad">No current Vault documents yet. Historical records are in Logs.</p>
                    ) }

                    { !loading && truncated && (
                        <p className="sf-note sf-note-pad" role="status">
                            Showing the newest { files.length } files. Filter by mobile to see one customer&apos;s files.
                        </p>
                    ) }

                    { !loading && files.length > 0 && (
                        <div className="sf-tablewrap">
                            <table className="sf-table">
                                <thead>
                                    <tr>
                                        { [ 'File', 'Customer', 'Mobile', 'Uploaded by', 'Size', 'Downloads', 'Vault purchase', 'Access window', 'Status', '' ].map( heading => (
                                            <th key={ heading } scope="col">{ heading }</th>
                                        ) ) }
                                    </tr>
                                </thead>
                                <tbody>
                                    { files.map( row => {
                                        const colour = STATUS_COLOURS[ row.status ] || STATUS_COLOURS.pending;
                                        return (
                                            <tr key={ row.fileId }>
                                                <td>
                                                    <span className="sf-filename">{ row.displayName }</span>
                                                    <span className="sf-fileorig">{ row.originalFilename || 'Vault document' }</span>
                                                </td>
                                                <td>{ row.ownerName || '—' }</td>
                                                {/* masked at the API; the full number never reaches the browser */ }
                                                <td className="sf-mono">{ row.ownerPhoneMasked || '—' }</td>
                                                <td className="sf-mono">{ row.uploadedBy || '—' }</td>
                                                <td>{ formatBytes( row.sizeBytes ) }</td>
                                                <td>{ row.downloadCount ?? 0 }</td>
                                                <td>
                                                    <span className="sf-filename">{ PURCHASE_LABELS[ accessStateOf( row ) ] }</span>
                                                    { row.vaultOrderNumber && <span className="sf-fileorig">{ row.vaultOrderNumber }</span> }
                                                    { row.vaultRequestNumber && <span className="sf-fileorig">{ row.vaultRequestNumber }</span> }
                                                </td>
                                                <td>
                                                    {/* "Active · ends in Xh" / "Expired" / "Awaiting purchase" — same predicate the
                                                        backend gates downloads on, so screen and backend never disagree. */}
                                                    <span className={ `sf-window ${ row.accessWindowOpen ? 'sf-window-open' : ( ( row.accessWindowCount ?? 0 ) > 0 ? 'sf-window-expired' : 'sf-window-none' ) }` }>
                                                        { row.accessWindowStatus || 'Awaiting purchase' }
                                                    </span>
                                                    { ( row.accessWindowCount ?? 0 ) > 1 && (
                                                        <span className="sf-fileorig">{ row.accessWindowCount } windows</span>
                                                    ) }
                                                </td>
                                                <td>
                                                    <span
                                                        className="sf-status"
                                                        style={ {
                                                            background: colour.bg,
                                                            color: colour.fg,
                                                            borderColor: colour.border,
                                                        } }
                                                    >
                                                        { row.status }
                                                    </span>
                                                </td>
                                                <td>
                                                    <div className="sf-rowactions">
                                                        { row.status === 'active' && ( accessStateOf( row ) === 'UNPAID' || accessStateOf( row ) === 'EXPIRED' ) && (
                                                            <button
                                                                className="sf-act"
                                                                onClick={ () => { void handleRequestPayment( row ); } }
                                                                disabled={ !!acting }
                                                                aria-busy={ acting === row.fileId }
                                                            >
                                                                { acting === row.fileId
                                                                    ? 'Sending…'
                                                                    : accessStateOf( row ) === 'EXPIRED'
                                                                        ? 'Send renewal payment'
                                                                        : 'Send Review & Pay' }
                                                            </button>
                                                        ) }
                                                        { row.status === 'active' && ( accessStateOf( row ) === 'OPEN' || accessStateOf( row ) === 'READY' ) && (
                                                            <button
                                                                className="sf-act"
                                                                onClick={ () => { void handleSendAccess( row ); } }
                                                                disabled={ !!acting }
                                                                aria-busy={ acting === row.fileId }
                                                            >
                                                                { acting === row.fileId ? 'Sending…' : 'Send Access Vault' }
                                                            </button>
                                                        ) }
                                                        <button
                                                            className="sf-act"
                                                            onClick={ () => setReviewFile( row ) }
                                                        >
                                                            Review &amp; Pay
                                                        </button>
                                                        { row.sourceDocumentId && (
                                                            <button
                                                                className="sf-act"
                                                                onClick={ () => { void handleStaffDownload( row ); } }
                                                            >
                                                                Download
                                                            </button>
                                                        ) }
                                                        <button
                                                            className="sf-act"
                                                            onClick={ () => handleCustomerVaultLink( row ) }
                                                        >
                                                            Customer Vault link
                                                        </button>
                                                        <button
                                                            className="sf-act sf-act-quiet"
                                                            onClick={ () => { void handleCopyId( row ); } }
                                                            aria-label={ `Copy the file ID of ${ row.displayName }` }
                                                        >
                                                            Copy ID
                                                        </button>
                                                        { row.status !== 'revoked' && (
                                                            <button
                                                                className="sf-revoke"
                                                                onClick={ () => handleRevoke( row ) }
                                                            >
                                                                Revoke
                                                            </button>
                                                        ) }
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    } ) }
                                </tbody>
                            </table>
                        </div>
                    ) }
                </section>
            </div>

            { reviewFile && (
                <div
                    className="sf-review-backdrop"
                    role="presentation"
                    onMouseDown={ event => {
                        if ( event.currentTarget === event.target ) setReviewFile( null );
                    } }
                >
                    <aside
                        className="sf-review-drawer"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="sf-review-title"
                    >
                        <div className="sf-review-head">
                            <div>
                                <p className="sf-review-eyebrow">Customer preview</p>
                                <h2 id="sf-review-title">Review &amp; Pay</h2>
                                <p>{ vaultTemplates?.nativePay || 'Native Review & Pay' } · exact file · live catalog price</p>
                            </div>
                            <button
                                type="button"
                                className="sf-review-close"
                                onClick={ () => setReviewFile( null ) }
                                aria-label="Close Review and Pay preview"
                            >
                                ×
                            </button>
                        </div>

                        <div className="sf-review-item">
                            <img
                                src="https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png"
                                alt=""
                                className="sf-review-thumb"
                            />
                            <div className="sf-review-itemcopy">
                                <strong>Vault</strong>
                                <span>{ reviewFile.displayName }</span>
                                <small>{ formatBytes( reviewFile.sizeBytes ) } · Quantity 1</small>
                            </div>
                        </div>

                        <div className="sf-review-breakdown">
                            <div><span>Items</span><strong>{ vaultPricePaise === null ? '—' : `₹${rupeesFromPaise( vaultPricePaise )}` }</strong></div>
                            <div><span>GST (18%)</span><strong>{ vaultBreakdown ? `₹${rupeesFromPaise( vaultBreakdown.supplyGstPaise )}` : '—' }</strong></div>
                            <div><span>Delight</span><strong>{ vaultBreakdown ? `−₹${rupeesFromPaise( vaultBreakdown.delightPaise )}` : '—' }</strong></div>
                            <div><span>Express</span><strong>{ vaultBreakdown ? `₹${rupeesFromPaise( vaultBreakdown.expressPaise )}` : '—' }</strong></div>
                            <div><span>Convenience Fee</span><strong>{ vaultBreakdown ? `₹${rupeesFromPaise( vaultBreakdown.convenienceFeePaise )}` : '—' }</strong></div>
                            <div><span>GST on Convenience Fee (18%)</span><strong>{ vaultBreakdown ? `₹${rupeesFromPaise( vaultBreakdown.convenienceGstPaise )}` : '—' }</strong></div>
                            <div className="sf-review-total"><span>Amount Payable</span><strong>{ vaultBreakdown ? `₹${rupeesFromPaise( vaultBreakdown.totalPayablePaise )}` : '—' }</strong></div>
                        </div>

                        <div className="sf-review-meta">
                            <div><span>Payment state</span><strong>{ PURCHASE_LABELS[ accessStateOf( reviewFile ) ] }</strong></div>
                            <div><span>Customer</span><strong>{ reviewFile.ownerName || '—' }</strong></div>
                            <div><span>Mobile</span><strong>{ reviewFile.ownerPhoneMasked || '—' }</strong></div>
                            <div><span>Access template</span><strong className="sf-mono">{ vaultTemplates?.delivery || 'wecare_default_download' }</strong></div>
                            <div>
                                <span>Template variable {'{{1}}'}</span>
                                <div className="sf-variable-value">
                                    <strong className="sf-mono">{ reviewFile.fileId }</strong>
                                    <button
                                        type="button"
                                        className="sf-copy-variable"
                                        onClick={ () => { void handleCopyId( reviewFile ); } }
                                    >
                                        Copy {'{{1}}'}
                                    </button>
                                </div>
                            </div>
                        </div>

                        <p className="sf-review-note">
                            { vaultPriceLoading
                                ? 'Reading the live Vault price from ProductsTable…'
                                : vaultPricePaise === null
                                    ? 'Live Vault price is unavailable. Do not send a payment request until pricing recovers.'
                                    : vaultBreakdown === null
                                        ? 'Live payment breakdown is unavailable. Do not send a payment request until pricing recovers.'
                                        : 'Review & Pay is sent first. After payment, Access Vault uses wecare_default_download; its URL variable {{1}} is filled automatically from this exact Vault file ID. Staff do not type or override it.' }
                        </p>
                    </aside>
                </div>
            ) }

            <style jsx>{ `
                .sf-wrap{width:100%;max-width:1180px;padding:24px;box-sizing:border-box}
                .sf-review-backdrop{
                  position:fixed;inset:0;z-index:var(--z-drawer,1300);
                  background:rgba(15,23,42,.26);display:flex;justify-content:flex-end;
                }
                .sf-review-drawer{
                  width:min(440px,100%);height:100vh;height:100dvh;overflow:auto;background:#fff;
                  padding:
                    max(24px,env(safe-area-inset-top,0px))
                    max(24px,env(safe-area-inset-right,0px))
                    max(24px,env(safe-area-inset-bottom,0px))
                    max(24px,env(safe-area-inset-left,0px));
                  box-sizing:border-box;box-shadow:-18px 0 48px rgba(15,23,42,.18);
                  border-left:1px solid rgba(26,58,42,.10);
                  overscroll-behavior:contain;
                }
                .sf-review-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;margin-bottom:22px}
                .sf-review-head h2{margin:2px 0 4px;font-size:28px;line-height:1.1;color:var(--accent)}
                .sf-review-head p{margin:0;color:var(--text-muted);font-size:var(--text-sm)}
                .sf-review-eyebrow{text-transform:uppercase;letter-spacing:.08em;font-weight:700!important;font-size:var(--text-xs)!important;color:var(--accent)!important}
                .sf-review-close{
                  width:38px;height:38px;border:0;border-radius:10px;background:var(--lime-tint,#f4fbdc);
                  color:var(--accent);font-size:26px;line-height:1;cursor:pointer;
                }
                .sf-review-item{
                  display:flex;gap:14px;align-items:center;padding:14px;border-radius:14px;
                  background:rgba(209,244,112,.20);border:1px solid rgba(26,58,42,.08);
                }
                .sf-review-thumb{width:58px;height:58px;object-fit:cover;border-radius:12px;background:#fff}
                .sf-review-itemcopy{display:grid;gap:4px;min-width:0}
                .sf-review-itemcopy strong{font-size:17px;color:var(--accent)}
                .sf-review-itemcopy span{font-size:var(--text-sm);overflow-wrap:anywhere}
                .sf-review-itemcopy small{color:var(--text-muted)}
                .sf-review-breakdown{display:grid;gap:0;margin:22px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
                .sf-review-breakdown>div{display:flex;justify-content:space-between;gap:16px;padding:11px 0;font-size:var(--text-sm)}
                .sf-review-breakdown>div+div{border-top:1px solid rgba(26,58,42,.07)}
                .sf-review-total{font-size:17px!important;color:var(--accent)}
                .sf-review-meta{display:grid;gap:10px}
                .sf-review-meta>div{display:grid;grid-template-columns:110px 1fr;gap:12px;font-size:var(--text-sm)}
                .sf-review-meta span{color:var(--text-muted)}
                .sf-review-meta strong{overflow-wrap:anywhere}
                .sf-variable-value{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}
                .sf-copy-variable{
                  flex:0 0 auto;min-height:32px;padding:0 10px;border:1px solid var(--border);
                  border-radius:8px;background:#fff;color:var(--accent);font:700 12px/1 var(--font-sans);
                  cursor:pointer;
                }
                .sf-copy-variable:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
                .sf-review-note{
                  margin:20px 0 0;padding:12px 14px;border-radius:12px;background:#f8faf9;
                  color:var(--text-muted);font-size:var(--text-sm);line-height:1.5;
                }

                .sf-head{margin:0 0 28px}
                .sf-journey{
                  display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
                  gap:8px;margin:0 0 20px;
                }
                .sf-journey>div{
                  display:grid;grid-template-columns:30px 1fr;grid-template-areas:"n t" "n s";
                  column-gap:9px;align-items:center;padding:12px 14px;
                  border:1px solid var(--border);border-radius:12px;background:#fff;
                }
                .sf-journey span{
                  grid-area:n;width:28px;height:28px;border-radius:999px;display:grid;place-items:center;
                  background:var(--accent);color:#fff;font-size:var(--text-xs);font-weight:700;
                }
                .sf-journey strong{grid-area:t;font-size:var(--text-sm);color:var(--text)}
                .sf-journey small{grid-area:s;font-size:var(--text-xs);color:var(--text-muted)}
                .sf-eyebrow{
                  margin:0 0 14px;font-size:var(--text-xs);font-weight:700;
                  letter-spacing:.08em;text-transform:uppercase;color:var(--accent);
                }
                /* The site's section-heading rung, identical to .home-close-title. */
                .sf-title{
                  margin:0 0 16px;font-size:clamp(28px,3.2vw,40px);font-weight:700;
                  line-height:1.08;letter-spacing:-1.2px;color:rgba(0,0,0,.95);
                }
                /* The one body level. */
                .sf-lead{
                  margin:0;max-width:62ch;font-size:20px;font-weight:400;line-height:1.4;
                  letter-spacing:-.125px;color:rgba(0,0,0,.898);
                }

                /* Same panel treatment as .home-close-panel and the /files page. */
                .sf-panel{
                  padding:clamp(24px,3vw,40px);margin:0 0 24px;
                  border:2px solid var(--lime);border-radius:14px;
                  background:rgba(209,244,112,.22);
                }
                .sf-h2{
                  margin:0 0 6px;font-size:22px;font-weight:700;
                  letter-spacing:-.4px;color:rgba(0,0,0,.95);
                }
                .sf-note{margin:0 0 20px;font-size:var(--text-md);color:rgba(26,58,42,.72)}
                .sf-note-pad{display:flex;align-items:center;gap:8px;padding:12px 0;margin:0}

                .sf-grid{
                  display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
                  gap:20px;margin:0 0 20px;
                }
                .sf-field{min-width:0}
                .sf-field-wide{grid-column:1/-1}
                .sf-label{
                  display:block;margin:0 0 8px;font-size:var(--text-md);font-weight:600;
                  letter-spacing:-.1px;color:var(--accent);
                }
                /* 16px minimum: smaller makes iOS Safari zoom the viewport on focus. */
                .sf-input{
                  width:100%;box-sizing:border-box;min-height:48px;padding:0 14px;
                  font-size:var(--text-base);color:rgba(0,0,0,.95);background:#fff;
                  border:2px solid rgba(26,58,42,.18);border-radius:12px;
                  transition:border-color .2s;
                }
                .sf-input:focus{outline:none;border-color:var(--accent)}
                .sf-input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
                .sf-input:disabled{opacity:.6}
                .sf-input-file{padding:11px 12px;min-height:48px}
                .sf-hint{margin:8px 0 0;font-size:var(--text-sm);line-height:1.45;color:rgba(26,58,42,.72)}

                .sf-actions{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
                .sf-aside{font-size:var(--text-md);color:rgba(26,58,42,.72)}

                /* The home page CTA: 52px, 50px pill, lime inverting to white. */
                .sf-cta{
                  display:inline-flex;align-items:center;justify-content:center;
                  min-height:52px;padding:0 28px;
                  border:2px solid var(--lime);border-radius:50px;background:var(--lime);
                  color:var(--accent);font-size:var(--h4);font-weight:600;cursor:pointer;
                  transition:background-color .2s,transform .2s,box-shadow .2s;
                }
                .sf-cta:hover:not(:disabled){
                  background:#fff;transform:translateY(-2px);
                  box-shadow:0 4px 12px rgba(26,58,42,.12);
                }
                .sf-cta:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
                .sf-cta:disabled{opacity:.55;cursor:default}
                /* Secondary: same geometry, white by default, so it reads as the lesser
                   of the two without introducing a third shape. */
                .sf-cta-quiet{
                  min-height:48px;padding:0 22px;font-size:var(--text-md);
                  background:#fff;border-color:rgba(26,58,42,.18);
                }
                .sf-cta-quiet:hover:not(:disabled){background:var(--lime);border-color:var(--lime)}

                .sf-listhead{
                  display:flex;justify-content:space-between;align-items:flex-end;
                  gap:20px;flex-wrap:wrap;margin:0 0 8px;
                }
                .sf-filter{display:flex;align-items:flex-end;gap:10px}
                .sf-filter .sf-input{width:190px}

                .sf-alert{
                  margin:0 0 16px;padding:12px 16px;border-radius:12px;
                  border:2px solid #ef4444;background:#fee2e2;color:#7f1d1d;
                  font-size:var(--text-md);line-height:1.45;
                }

                /* White table on the tinted panel, so rows stay legible. */
                .sf-tablewrap{
                  overflow-x:auto;background:#fff;
                  border:2px solid rgba(26,58,42,.12);border-radius:12px;
                }
                .sf-table{width:100%;border-collapse:collapse}
                .sf-table th{
                  padding:12px 14px;text-align:left;font-size:var(--text-xs);font-weight:700;
                  letter-spacing:.06em;text-transform:uppercase;color:rgba(26,58,42,.6);
                  border-bottom:2px solid rgba(26,58,42,.12);white-space:nowrap;
                }
                .sf-table td{
                  padding:12px 14px;font-size:var(--text-md);color:rgba(0,0,0,.9);
                  border-bottom:1px solid rgba(26,58,42,.08);vertical-align:top;
                }
                .sf-table tr:last-child td{border-bottom:0}
                .sf-filename{display:block;font-weight:600;letter-spacing:-.2px}
                .sf-fileorig{
                  display:block;margin-top:3px;font-size:var(--text-sm);color:rgba(26,58,42,.6);
                }
                .sf-mono{font-family:var(--font-mono,ui-monospace,monospace)}

                .sf-status{
                  display:inline-block;padding:3px 10px;border-radius:50px;
                  border:1px solid;font-size:var(--text-xs);font-weight:600;text-transform:capitalize;
                }

                .sf-label-opt{font-weight:400;color:#64748b}
                .sf-muted{color:#cbd5e1}
                .sf-tagpill{
                  display:inline-block;padding:2px 10px;border-radius:50px;
                  background:#f1f5f9;color:#334155;border:1px solid #e2e8f0;
                  font-size:var(--text-xs);font-weight:600;
                }
                .sf-window{
                  display:inline-block;padding:2px 10px;border-radius:50px;
                  border:1px solid;font-size:var(--text-xs);font-weight:600;white-space:nowrap;
                }
                .sf-window-open{background:#ecfdf5;color:#065f46;border-color:#a7f3d0}
                .sf-window-expired{background:#fef2f2;color:#991b1b;border-color:#fecaca}
                .sf-window-none{background:#f8fafc;color:#64748b;border-color:#e2e8f0}

                .sf-revoke{
                  border:2px solid rgba(26,58,42,.18);border-radius:50px;
                  background:#fff;color:var(--accent);padding:6px 16px;
                  font-size:var(--text-md);font-weight:600;cursor:pointer;transition:background-color .2s;
                }
                .sf-revoke:hover{background:#fee2e2;border-color:#ef4444;color:#991b1b}
                .sf-revoke:focus-visible{outline:3px solid var(--accent);outline-offset:2px}

                .sf-rowactions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
                /* Same pill geometry as .sf-revoke; lime is the action colour on this page. */
                .sf-act{
                  min-height:var(--tap-min,44px);border:2px solid var(--lime);border-radius:50px;
                  background:var(--lime);color:var(--accent);padding:6px 16px;white-space:nowrap;
                  font-size:var(--text-md);font-weight:600;cursor:pointer;transition:background-color .2s;
                }
                .sf-act:hover:not(:disabled){background:#fff}
                .sf-act:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
                .sf-act:disabled{opacity:.55;cursor:default}
                .sf-act-quiet{background:#fff;border-color:rgba(26,58,42,.18)}
                .sf-act-quiet:hover:not(:disabled){background:var(--lime);border-color:var(--lime)}
                .sf-revoke{min-height:var(--tap-min,44px)}

                .sf-check{
                  display:flex;align-items:center;gap:10px;min-height:var(--tap-min,44px);
                  font-size:var(--text-md);font-weight:600;color:var(--accent);cursor:pointer;
                }
                .sf-check input{width:20px;height:20px;accent-color:var(--accent);flex:0 0 auto}

                @media(max-width:760px){
                  .sf-wrap{padding:16px}
                  .sf-head{margin-bottom:20px}
                  .sf-lead{font-size:17px}
                  .sf-panel{padding:18px 16px;border-radius:16px}
                  .sf-grid{grid-template-columns:1fr;gap:16px}
                  .sf-actions{align-items:stretch;flex-direction:column}
                  .sf-cta,.sf-cta-quiet{width:100%}
                  .sf-listhead{align-items:stretch}
                  .sf-filter{width:100%;align-items:stretch;flex-direction:column}
                  .sf-filter .sf-input{width:100%;font-size:16px}
                  .sf-input{font-size:16px}
                  .sf-tablewrap{overflow:visible;border:0;background:transparent}
                  .sf-table,.sf-table tbody{display:block;width:100%}
                  .sf-table thead{display:none}
                  .sf-table tbody{display:grid;gap:12px}
                  .sf-table tr{display:block;border:1px solid rgba(26,58,42,.12);border-radius:14px;background:#fff;overflow:hidden}
                  .sf-table td{display:grid;grid-template-columns:minmax(96px,34%) minmax(0,1fr);gap:12px;width:100%;box-sizing:border-box;padding:11px 12px;border-bottom:1px solid rgba(26,58,42,.08);overflow-wrap:anywhere}
                  .sf-table td::before{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:rgba(26,58,42,.58)}
                  .sf-table td:nth-child(1)::before{content:'File'}
                  .sf-table td:nth-child(2)::before{content:'Customer'}
                  .sf-table td:nth-child(3)::before{content:'Mobile'}
                  .sf-table td:nth-child(4)::before{content:'Uploaded by'}
                  .sf-table td:nth-child(5)::before{content:'Size'}
                  .sf-table td:nth-child(6)::before{content:'Downloads'}
                  .sf-table td:nth-child(7)::before{content:'Purchase'}
                  .sf-table td:nth-child(8)::before{content:'Access'}
                  .sf-table td:nth-child(9)::before{content:'Status'}
                  .sf-table td:nth-child(10)::before{content:'Actions'}
                  .sf-table tr:last-child td:last-child{border-bottom:0}
                  .sf-rowactions{display:grid;grid-template-columns:1fr;align-items:stretch}
                  .sf-act,.sf-revoke{width:100%;white-space:normal}
                  .sf-review-drawer{width:100%;padding:20px 16px max(20px,env(safe-area-inset-bottom));border-left:0}
                  .sf-review-meta>div{grid-template-columns:1fr;gap:3px}
                }
                @media(max-width:380px){
                  .sf-table td{grid-template-columns:1fr;gap:5px}
                }
                @media(prefers-reduced-motion:reduce){
                  .sf-cta,.sf-input,.sf-revoke,.sf-act{transition:none}
                  .sf-cta:hover:not(:disabled){transform:none}
                }
            ` }</style>
        </>
    );

    if ( embedded ) return body;
    return (
        <Layout onSignOut={ signOut } user={ user }>
            <SEO title="Vault" description="Upload, publish and manage customer Vault access" />
            { body }
        </Layout>
    );
}
