/**
 * Vault operations — staff-only upload, payment and customer access.
 *
 * New files are stored directly under the exact, edge-gated Vault S3 prefix
 * secure/d/public/valut/ and confirmed before becoming active in SecureFilesTable.
 * No customer-facing Drop Docs upload route or DocumentTable is used.
 *
 * The customer-facing /vault/?file=<id> surface owns download/payment presentation.
 * This component is the staff surface and never exposes raw S3 keys.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
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
import VaultJourneyPreview, { parseVaultJourney, type VaultRegistryJourney } from './VaultJourneyPreview';

/** Staff may edit ONLY the one ₹49 Vault catalogue line's customer-facing name. */
const VAULT_ITEM_DESCRIPTION_DEFAULT = 'Vault Access - Secure document download (24 hours)';
const VAULT_BASE_ITEM_PAISE = 4900;
const VAULT_ITEM_DESCRIPTION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 .,'()&\/-]{11,59}$/;
/** Keep the exact native WhatsApp ORDER_DETAILS item-name limit (12-60).
 * Give staff a specific inline reason instead of a toast about a field below the fold.
 * This mirrors catalog_service_checkout.valid_vault_item_description. */
function vaultItemDescriptionError ( text: string ): string {
    if ( text.length < 12 ) return `Add ${ 12 - text.length } more character(s). Minimum 12; maximum 60.`;
    if ( text.length > 60 ) return 'The WhatsApp payment item name cannot exceed 60 characters.';
    if ( text.trim() !== text ) return 'Remove leading or trailing spaces.';
    if ( text.includes( '  ' ) ) return 'Use only one space between words.';
    if ( text.toLowerCase().includes( 'http' ) ) return 'Links are not allowed in the payment item name.';
    if ( !VAULT_ITEM_DESCRIPTION_PATTERN.test( text ) )
        return "Start with a letter or number. Use only letters, numbers, spaces, . , ' ( ) & / -.";
    return '';
}

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
    // Saving/publishing never sends a WhatsApp request or charges a customer.
    // The fileId whose WhatsApp action is in flight, so one click cannot send twice.
    const [ acting, setActing ] = useState( '' );
    const [ reviewFile, setReviewFile ] = useState<SecureFile | null>( null );
    const [ vaultPricePaise, setVaultPricePaise ] = useState<number | null>( null );
    const [ paymentItemDescription, setPaymentItemDescription ] = useState( VAULT_ITEM_DESCRIPTION_DEFAULT );
    const [ vaultBreakdown, setVaultBreakdown ] = useState<ServicePriceBreakdown | null>( null );
    const [ vaultTemplates, setVaultTemplates ] = useState<ServicePaymentTemplates | null>( null );
    const [ vaultPriceLoading, setVaultPriceLoading ] = useState( false );
    const [ customers, setCustomers ] = useState<api.Contact[]>( [] );
    const [ contactQuery, setContactQuery ] = useState( '' );
    const [ selectedCustomerId, setSelectedCustomerId ] = useState( '' );
    const [ mode, setMode ] = useState<'upload' | 'existing'>( 'upload' );
    const [ journey, setJourney ] = useState<VaultRegistryJourney | null>( null );
    const [ journeyError, setJourneyError ] = useState( '' );
    const [ scheduledAction, setScheduledAction ] = useState<'payment' | 'access' | null>( null );
    const [ scheduledAtLocal, setScheduledAtLocal ] = useState( '' );
    const [ scheduled, setScheduled ] = useState<api.VaultScheduledAction[]>( [] );
    const [ schedulingBusy, setSchedulingBusy ] = useState( false );
    const [ scheduleError, setScheduleError ] = useState( '' );
    // An older all-files request must not overwrite a newly selected customer's files.
    const latestFilesRead = useRef( 0 );
    // Prevent double-clicks during the confirmation modal and network send.
    const sendingAction = useRef( false );

    const clearFileSelection = () => {
        latestFilesRead.current += 1;
        setFiles( [] );
        setReviewFile( null );
        
        setScheduledAction( null );
        setScheduled( [] );
        setScheduleError( '' );
        setTruncated( false );
        setLoadError( '' );
        setLoading( false );
    };

    /** Refetch and replace the table. Used by the filter button and after an upload. */
    const fetchInto = useCallback( async ( mobileFilter?: string ) => {
        const readId = ++latestFilesRead.current;
        const result = await api.listSecureFiles( mobileFilter || undefined );
        // Selection may have changed while this request was in flight.
        if ( readId !== latestFilesRead.current ) return null;
        if ( result.ok )
        {
            setFiles( result.data.files || [] );
            setTruncated( !!result.data.truncated );
            setLoadError( '' );
            setLoading( false );
            return result.data.files || [];
        } else
        {
            // Say why, rather than rendering an empty table that looks like "no files".
            setLoadError( result.failure.message || 'Could not load secure files' );
            setFiles( [] );
            setLoading( false );
            return null;
        }
    }, [] );

    /** Reload with the spinner, for buttons and post-upload refresh. */
    const load = useCallback( ( mobileFilter?: string ) => {
        setLoading( true );
        return fetchInto( mobileFilter );
    }, [ fetchInto ] );

    useEffect( () => {
        let active = true;
        void api.listContacts().then( result => {
            if ( active ) setCustomers( result );
        } ).catch( () => {
            // Manual customer entry stays available even if the CRM is unavailable.
        } );
        return () => { active = false; };
    }, [] );

    useEffect( () => {
        let active = true;
        void api.getSystemConfigResult( 'vault_whatsapp_template_journey_v1' ).then( result => {
            if ( !active ) return;
            if ( !result.ok ) {
                setJourneyError( 'Saved journey registry unavailable; template preview is a reference.' );
                return;
            }
            const parsed = parseVaultJourney( result.data.config );
            setJourney( parsed );
            setJourneyError( parsed ? '' : 'Saved journey mapping is missing or incomplete.' );
        } ).catch( () => {
            if ( active ) setJourneyError( 'Unable to read the saved Vault journey.' );
        } );
        return () => { active = false; };
    }, [] );

    useEffect( () => {
        let active = true;
        const fileId = reviewFile?.fileId;
        setScheduled( [] );
        setScheduleError( '' );
        if ( fileId ) {
            void api.listVaultSchedules( fileId ).then( result => {
                if ( !active ) return;
                if ( result.ok ) setScheduled( result.data.schedules || [] );
                else setScheduleError( result.failure.message || 'Schedules unavailable' );
            } );
        }
        return () => { active = false; };
    }, [ reviewFile?.fileId ] );

    const reloadSchedules = async ( fileId: string ) => {
        const result = await api.listVaultSchedules( fileId );
        if ( result.ok ) {
            setScheduled( result.data.schedules || [] );
            setScheduleError( '' );
        } else {
            setScheduleError( result.failure.message || 'Schedules unavailable' );
        }
    };

    const displayScheduleTime = ( iso: string ) => {
        const parsed = new Date( iso );
        return Number.isNaN( parsed.getTime() ) ? 'Invalid time' : parsed.toLocaleString( 'en-IN', {
            timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short',
        } ) + ' IST';
    };

    const descriptionError = vaultItemDescriptionError( paymentItemDescription );
    const focusInvalidDescription = (): boolean => {
        const error = vaultItemDescriptionError( paymentItemDescription );
        if ( !error ) return false;
        toast.error( error );
        document.getElementById( 'sf-vault-item-description' )?.focus();
        document.getElementById( 'sf-vault-item-description' )?.scrollIntoView(
            { behavior: 'smooth', block: 'center' } );
        return true;
    };

    const matchingCustomers = !reviewFile && !selectedCustomerId && contactQuery.trim().length > 1
        ? customers.filter( customer =>
            ( customer.name || '' ).toLowerCase().includes( contactQuery.trim().toLowerCase() )
            || ( customer.phone || '' ).includes( contactQuery.trim() )
        ).slice( 0, 6 )
        : [];

    const chooseCustomer = ( contact: api.Contact ) => {
        if ( !contact.phone ) return;
        setPaymentItemDescription( VAULT_ITEM_DESCRIPTION_DEFAULT );
        setName( contact.name || '' );
        setMobile( contact.phone );
        setContactQuery( contact.name || contact.phone );
        setSelectedCustomerId( contact.id || contact.contactId );
        setFilterMobile( contact.phone );
        setFile( null );
        
        clearFileSelection();
        setMode( 'existing' );
        void load( contact.phone );
    };

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
        // The same read-sequence guard protects the initial listing and customer filters.
        void fetchInto();
        return () => { latestFilesRead.current += 1; };
    }, [ fetchInto ] );

    /** Meta API acceptance is not handset delivery; 202 means an uncertain send. */
    const reportAction = ( result: api.SecureFileActionResult ) => {
        if ( result.ok && result.status !== 202 ) toast.success( result.message );
        else if ( result.status === 202 || result.status === null ) toast.warning( result.message );
        else toast.error( result.message );
    };

    const preparePayment = ( target: SecureFile ) => {
        setMode( 'existing' );
        setSelectedCustomerId( '' );
        setContactQuery( target.ownerName || '' );
        setReviewFile( target );
        document.getElementById( 'sf-action-panel' )?.scrollIntoView( { behavior: 'smooth', block: 'center' } );
    };

    const handleSendPayment = async ( target: SecureFile ) => {
        if ( sendingAction.current || acting || uploading || schedulingBusy ) return;
        if ( target.status !== 'active' || ![ 'UNPAID', 'EXPIRED' ].includes( accessStateOf( target ) ) ) {
            toast.error( 'This file does not need a new payment request.' );
            return;
        }
        if ( vaultPricePaise === null || !vaultBreakdown ) {
            toast.error( 'Live service price is unavailable. No payment request was sent.' );
            return;
        }
        if ( vaultPricePaise === VAULT_BASE_ITEM_PAISE && focusInvalidDescription() ) return;
        const itemDescription = vaultPricePaise === VAULT_BASE_ITEM_PAISE
            ? paymentItemDescription : undefined;
        sendingAction.current = true;
        let approved = false;
        try {
            approved = await confirm( {
                title: 'Send Review & Pay now?',
                message: `Send a native WhatsApp payment request for ${ target.displayName } to the existing verified owner? Item description: ${ itemDescription || 'server catalogue' }. Amount, quantity and tax are locked. The customer must approve payment.`,
                confirmText: 'Send payment request',
            } );
            if ( !approved ) return;
            setActing( target.fileId );
            const result = await api.requestSecureFilePayment( target.fileId, itemDescription );
            reportAction( result );
            void load( filterMobile || undefined );
        } catch {
            toast.error( 'Payment send could not be confirmed. Check the chat before retrying.' );
        } finally {
            setActing( '' );
            sendingAction.current = false;
        }
    };

    const handleScheduleAction = async ( target: SecureFile ) => {
        const action = scheduledAction;
        if ( !action || sendingAction.current || schedulingBusy || acting || uploading ) return;
        const currentAccess = accessStateOf( target );
        const eligible = action === 'access'
            ? [ 'OPEN', 'READY' ].includes( currentAccess )
            : [ 'UNPAID', 'EXPIRED' ].includes( currentAccess );
        if ( target.status !== 'active' || !eligible ) {
            toast.error( 'File status changed. Refresh before scheduling.' );
            return;
        }
        if ( action === 'payment' && vaultPricePaise === VAULT_BASE_ITEM_PAISE
            && focusInvalidDescription() ) return;
        const itemDescription = action === 'payment' && vaultPricePaise === VAULT_BASE_ITEM_PAISE
            ? paymentItemDescription : undefined;
        const when = new Date( scheduledAtLocal );
        const delta = when.getTime() - Date.now();
        if ( !scheduledAtLocal || Number.isNaN( when.getTime() )
            || delta < 10 * 60 * 1000 || delta > 30 * 24 * 60 * 60 * 1000 ) {
            toast.error( 'Choose a time 10 minutes to 30 days from now.' );
            return;
        }
        sendingAction.current = true;
        setSchedulingBusy( true );
        try {
            const actionName = action === 'payment' ? 'native Review & Pay request' : 'paid Access Vault resend';
            const approved = await confirm( {
                title: `Schedule ${actionName}?`,
                message: `File: ${target.displayName}\nCustomer: ${target.ownerName || 'verified owner'}\n${itemDescription ? 'Item: ' + itemDescription + '\n' : ''}Time: ${displayScheduleTime( when.toISOString() )}\n\nThe send will only run if owner, file, payment and message rules still permit it. A failed or ambiguous send is not retried automatically.`,
                confirmText: 'Confirm schedule',
            } );
            if ( !approved ) return;
            const result = await api.scheduleVaultAction(
                target.fileId, action, when.toISOString(), undefined, itemDescription,
            );
            if ( !result.ok ) {
                toast.error( result.failure.message || 'Schedule was not accepted' );
                return;
            }
            toast.success( 'Scheduled. No message was sent yet.' );
            setScheduledAction( null );
            setScheduledAtLocal( '' );
            await reloadSchedules( target.fileId );
        } catch {
            toast.warning( 'Schedule confirmation was not received. Check the schedule list before retrying.' );
        } finally {
            sendingAction.current = false;
            setSchedulingBusy( false );
        }
    };

    const handleCancelSchedule = async ( target: SecureFile, scheduleId: string ) => {
        if ( sendingAction.current || schedulingBusy || acting ) return;
        const approved = await confirm( {
            title: 'Cancel scheduled message?',
            message: 'Only pending sends can be cancelled. An already claimed send may be in progress.',
            confirmText: 'Cancel schedule',
        } );
        if ( !approved ) return;
        setSchedulingBusy( true );
        try {
            const result = await api.cancelVaultScheduledAction( target.fileId, scheduleId );
            if ( result.ok ) toast.success( 'Scheduled message cancelled.' );
            else toast.error( result.failure.message || 'Could not cancel this schedule.' );
            await reloadSchedules( target.fileId );
        } finally {
            setSchedulingBusy( false );
        }
    };

    const handleSendAccess = async ( target: SecureFile ) => {
        if ( sendingAction.current || acting || uploading ) return;
        sendingAction.current = true;
        let approved = false;
        try {
            approved = await confirm( {
            title: 'Resend Access Vault link?',
            message: `Send the existing paid Vault access link to ${target.ownerName || 'the selected owner'} for ${target.displayName}? No new payment is requested.`,
            confirmText: 'Send access link',
            } );
        } catch {
            toast.error( 'Unable to confirm the send. No WhatsApp request was made.' );
            return;
        } finally {
            if ( !approved ) sendingAction.current = false;
        }
        if ( !approved ) return;
        setActing( target.fileId );
        try
        {
            reportAction( await api.sendSecureFileAccess( target.fileId ) );
            void load( filterMobile || undefined );
        } finally
        {
            setActing( '' );
            sendingAction.current = false;
        }
    };

    const handleStaffDownload = async ( target: SecureFile ) => {
        const url = await api.getVaultStaffDownloadUrl( target.fileId );
        if ( url ) void openExternal( url );
        else toast.error( 'Vault staff preview is unavailable' );
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

    const handleUpload = async () => {
        const customerName = name.trim();
        const customerPhone = mobile.trim();
        if ( !file ) { toast.error( 'Choose a document first' ); return; }
        if ( !customerName ) { toast.error( 'Customer name is required' ); return; }
        if ( !customerPhone ) { toast.error( 'Customer mobile number is required' ); return; }
        // The private upload and publication complete before staff may request payment.
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
            setStep( 'Preparing private Vault upload…' );
            const ticket = await api.initVaultFileUpload( {
                name: customerName,
                mobile: customerPhone,
                originalFilename: file.name,
                contentType,
                sizeBytes: file.size,
            } );
            if ( !ticket.ok )
            {
                toast.error( ticket.failure.message || 'Vault upload could not start. Check that private storage is enabled.' );
                return;
            }

            setStep( 'Uploading directly to Vault S3…' );
            const uploaded = await api.uploadVaultFileBytes(
                ticket.data.uploadUrl, file, ticket.data.contentType || contentType,
            );
            if ( !uploaded )
            {
                toast.error( 'Vault S3 upload failed. No file was activated or charged.' );
                return;
            }

            setStep( 'Confirming Vault file in S3…' );
            const confirmed = await api.confirmVaultFileUpload( ticket.data.fileId );
            if ( !confirmed.ok || confirmed.data.status !== 'active' )
            {
                toast.error( confirmed.ok ? 'Vault storage confirmation did not activate the file.'
                    : confirmed.failure.message || 'Vault file could not be confirmed' );
                return;
            }

            toast.success( `${ticket.data.displayName} saved to Vault. No WhatsApp was sent.` );
            setFile( null );
            
            setName( customerName );
            setMobile( customerPhone );
            setContactQuery( customerName );
            setSelectedCustomerId( '' );
            const refreshed = await load( customerPhone );
            setFilterMobile( customerPhone );
            const publishedFile = ( refreshed || [] ).find( item => item.fileId === ticket.data.fileId ) || null;
            setReviewFile( publishedFile );
            setMode( 'existing' );
            if ( !publishedFile )
                toast.info( 'Vault file is saved. Use Find to refresh the list, then review the direct Review & Pay action.' );
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
                    <p className="sf-eyebrow">WORKSPACE / VAULT</p>
                    <div className="sf-heading-line">
                        <div>
                            <h1 className="sf-title">Secure customer delivery</h1>
                            <p className="sf-lead">One verified customer, one private file, one server-priced Review &amp; Pay request. Invoice and access follow captured payment.</p>
                        </div>
                        <span className="sf-private-indicator">Private · Customer-bound</span>
                    </div>
                    <nav className="sf-top-links" aria-label="Vault action shortcuts">
                        <a href="#sf-add" onClick={ () => setMode( 'upload' ) }>Upload to Vault S3</a>
                        <a href="#sf-action-panel" onClick={ () => setMode( 'existing' ) }>Send · Resend · Schedule</a>
                        <Link href="/workspace/payments?view=timing">Access delay settings (0–5s)</Link>
                    </nav>
                    <ol className="sf-progress" aria-label="Vault workflow">
                        <li><span>1</span> Customer</li>
                        <li><span>2</span> File</li>
                        <li><span>3</span> WhatsApp preview</li>
                        <li><span>4</span> Send</li>
                    </ol>
                </header>

                <section className="sf-workbench" aria-label="Vault customer and file workspace">
                    <div className="sf-compose">
                        <header className="sf-workbench-heading">
                            <div>
                                <h2>Prepare delivery</h2>
                                <p>Customer details, file and WhatsApp message in one place.</p>
                            </div>
                            <span>STEP 1–3</span>
                        </header>
                        <div className="sf-customer-picker">
                            <label className="sf-label" htmlFor="sf-contact-search">Select customer</label>
                            <input className="sf-input" id="sf-contact-search" type="search"
                                placeholder="Search contact name or WhatsApp mobile"
                                value={ contactQuery }
                                onChange={ event => {
                                    setSelectedCustomerId( '' );
                                    setContactQuery( event.target.value );
                                    clearFileSelection();
                                } }
                                disabled={ uploading } autoComplete="off" />
                            { mode === 'existing' && reviewFile ? (
                                <p className="sf-hint">Selected file owner: { reviewFile.ownerName || 'Customer' } · { reviewFile.ownerPhoneMasked || 'masked' }. Ownership is locked to the published file.</p>
                            ) : selectedCustomerId ? (
                                <p className="sf-hint">Customer selected · <button type="button" className="sf-contact-change"
                                    onClick={ () => {
                                        setSelectedCustomerId( '' );
                                        setContactQuery( '' );
                                        setName( '' );
                                        setMobile( '' );
                                        setFilterMobile( '' );
                                        
                                        clearFileSelection();
                                    } }>Change customer</button></p>
                            ) : matchingCustomers.length > 0 ? (
                                <div className="sf-customer-results" role="group" aria-label="Contact search results">
                                    { matchingCustomers.map( contact => (
                                        <button type="button" key={ contact.id || contact.contactId }
                                            onClick={ () => chooseCustomer( contact ) } disabled={ uploading }>
                                            <strong>{ contact.name || 'Customer' }</strong>
                                            <small>{ contact.phone }</small>
                                        </button>
                                    ) ) }
                                </div>
                            ) : <p className="sf-hint">Choose a saved contact or enter the customer details below when uploading.</p> }
                        </div>
                        <div className="sf-identity-fields">
                            <div className="sf-field">
                                <label className="sf-label" htmlFor="sf-name">Customer name</label>
                                <input id="sf-name" className="sf-input" value={ mode === 'existing' && reviewFile ? reviewFile.ownerName || '' : name }
                                    onChange={ event => {
                                        setSelectedCustomerId( '' );
                                        setName( event.target.value );
                                        clearFileSelection();
                                    } }
                                    autoComplete="off" placeholder="Customer full name"
                                    disabled={ uploading || ( mode === 'existing' && !!reviewFile ) } />
                            </div>
                            <div className="sf-field">
                                <label className="sf-label" htmlFor="sf-mobile">WhatsApp mobile</label>
                                <input id="sf-mobile" className="sf-input" value={ mode === 'existing' && reviewFile ? reviewFile.ownerPhoneMasked || '' : mobile }
                                    onChange={ event => {
                                        setSelectedCustomerId( '' );
                                        setMobile( event.target.value );
                                        setFilterMobile( event.target.value );
                                        clearFileSelection();
                                    } }
                                    autoComplete="tel" inputMode="tel" placeholder="+91…"
                                    disabled={ uploading || ( mode === 'existing' && !!reviewFile ) } />
                            </div>
                        </div>
                        <p className="sf-hint sf-ownership-note">
                            { mode === 'existing' && reviewFile
                                ? 'Saved Vault file owner is fixed server-side. Changing the upload form cannot transfer access.'
                                : 'New upload: the entered mobile number is bound to the Vault file by the server, not the uploaded filename.' }
                        </p>
                        <div className="sf-document-mode" role="group" aria-label="Choose a document source">
                            <button type="button" className={ mode === 'upload' ? 'active' : '' }
                                aria-pressed={ mode === 'upload' }
                                onClick={ () => { setMode( 'upload' ); setReviewFile( null ); setScheduledAction( null ); } }>
                                Upload new
                            </button>
                            <button type="button" className={ mode === 'existing' ? 'active' : '' }
                                aria-pressed={ mode === 'existing' }
                                onClick={ () => {
                                    setMode( 'existing' ); setFile( null );
                                    setScheduledAction( null );
                                    void load( filterMobile || mobile || undefined );
                                } }>
                                Reuse existing Vault file
                            </button>
                        </div>
                        { mode === 'upload' ? (
                <section className="sf-upload-area" aria-labelledby="sf-add">
                    <h2 className="sf-h2" id="sf-add">Step 2 · Upload private Vault file</h2>
                    <p className="sf-note">
                        Staff upload goes directly to Vault S3, separate from Drop Docs.
                        The server confirms the bytes before the file can be offered for paid download.
                    </p>

                    <div className="sf-grid">
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

                    </div>

                    <div className="sf-actions">
                        <button className="sf-cta" type="button" onClick={ () => { void handleUpload(); } } disabled={ uploading }>
                            { uploading ? 'Saving to Vault…' : 'Upload to Vault' }
                        </button>
                        <span className="sf-aside">
                            { uploading && step
                                ? step
                                : 'Save only — no WhatsApp message, charge or payment request.' }
                        </span>
                    </div>
                </section>
                        ) : (
                            <section className="sf-existing-picker" aria-labelledby="sf-pick-title">
                                <h3 className="sf-h2" id="sf-pick-title">Reuse a saved Vault file</h3>
                                <p className="sf-note">Reuse a saved file for its existing owner—no second S3 upload. The selected file&apos;s customer cannot be changed.</p>
                                <div className="sf-lookup">
                                    <input className="sf-input" value={ filterMobile } aria-label="Filter by customer mobile"
                                        placeholder="Customer mobile" inputMode="tel"
                                        onChange={ event => {
                                        setSelectedCustomerId( '' );
                                        setContactQuery( '' );
                                        setFilterMobile( event.target.value );
                                    } } />
                                    <button type="button" className="sf-cta sf-cta-quiet" onClick={ () => {
                                        setReviewFile( null );
                                        void load( filterMobile || undefined );
                                    } }>Find</button>
                                </div>
                                { loadError && <p role="alert" className="sf-note">{ loadError }</p> }
                                { loading ? <p className="sf-note"><Spinner /> Loading files…</p> : (
                                    <div className="sf-file-choices" role="group" aria-label="Current Vault files">
                                        { files.length === 0 && <p className="sf-note">No saved Vault file is available for this customer. Use Upload new, then select the server-confirmed file. No payment, invoice or Access Vault message can be created without a verified file.</p> }
                                        { files.slice( 0, 12 ).map( item => (
                                            <button type="button" key={ item.fileId }
                                                className={ reviewFile?.fileId === item.fileId ? 'selected' : '' }
                                                aria-pressed={ reviewFile?.fileId === item.fileId }
                                                onClick={ () => {
                                                    if ( item.fileId !== reviewFile?.fileId )
                                                        setPaymentItemDescription( VAULT_ITEM_DESCRIPTION_DEFAULT );
                                                    setReviewFile( item );
                                                } }>
                                                <span><strong>{ item.displayName }</strong>
                                                    <small>{ item.ownerName || 'Customer' } · { formatBytes( item.sizeBytes ) }</small></span>
                                                <span className="sf-choice-status">{ PURCHASE_LABELS[ accessStateOf( item ) ] }</span>
                                            </button>
                                        ) ) }
                                        { files.length > 12 && <p className="sf-hint">Showing up to 12 files. Filter by mobile to narrow your search.</p> }
                                    </div>
                                ) }
                                { reviewFile && (
                                    <div className="sf-selection-actions">
                                        <strong>{ reviewFile.displayName }</strong>
                                        <small>{ reviewFile.accessWindowStatus || PURCHASE_LABELS[ accessStateOf( reviewFile ) ] }</small>
                                        { accessStateOf( reviewFile ) === 'PAID_UNVERIFIED' &&
                                            <p role="status" className="sf-hint">Paid access needs reconciliation. Do not request payment again.</p> }
                                    </div>
                                ) }
                            </section>
                        ) }

                        <div className="sf-review-actions" id="sf-action-panel">
                            <div className="sf-review-checks" aria-live="polite">
                                <strong>Step 4 · Review &amp; Pay or paid access</strong>
                                <span>{ reviewFile && mode === 'existing' ? 'File selected · saved in Vault' : 'Upload, then select the file' }</span>
                                <span>{ vaultPricePaise !== null && !!vaultBreakdown ? 'Live catalogue quote available · amount locked' : 'Waiting for verified service quote' }</span>
                            </div>
                            { mode === 'existing' && reviewFile?.status === 'active'
                                && ( accessStateOf( reviewFile ) === 'UNPAID' || accessStateOf( reviewFile ) === 'EXPIRED' )
                                && vaultPricePaise === VAULT_BASE_ITEM_PAISE && (
                                <section className="sf-description-editor" aria-label="Vault WhatsApp payment item name">
                                    <div className="sf-description-heading">
                                        <label htmlFor="sf-vault-item-description">₹49 item description · Review &amp; Pay</label>
                                        <output className={ descriptionError ? 'sf-description-count invalid' : 'sf-description-count' }
                                            aria-label={ `${ paymentItemDescription.length } of 60 characters` }>
                                            { paymentItemDescription.length } / 60
                                        </output>
                                    </div>
                                    <input
                                        id="sf-vault-item-description"
                                        className="sf-input sf-description-input"
                                        type="text"
                                        minLength={ 12 }
                                        maxLength={ 60 }
                                        value={ paymentItemDescription }
                                        onChange={ event => setPaymentItemDescription( event.target.value ) }
                                        autoComplete="off"
                                        spellCheck={ false }
                                        aria-invalid={ !!descriptionError }
                                        aria-describedby="sf-vault-item-help sf-vault-item-feedback"
                                    />
                                    <p className="sf-description-help" id="sf-vault-item-help">
                                        12–60 characters. This name appears in the native WhatsApp payment item and
                                        the issued GST invoice. It does not edit template message text, quantity or price.
                                    </p>
                                    <p id="sf-vault-item-feedback" role={ descriptionError ? 'alert' : 'status' }
                                        className={ descriptionError ? 'sf-description-feedback invalid' : 'sf-description-feedback' }>
                                        { descriptionError || 'Valid item name · Ready for Review & Pay.' }
                                    </p>
                                </section>
                            ) }
                            { mode === 'upload' && (
                                <div className="sf-action-empty">
                                    <strong>First, upload the selected file to Vault S3.</strong>
                                    <p>Uploading never sends WhatsApp. After it is saved, select the Vault file to unlock Send now, Schedule and Resend.</p>
                                    <button type="button" className="sf-cta sf-cta-quiet" onClick={ () => {
                                        setMode( 'existing' );
                                        void load( filterMobile || mobile || undefined );
                                    } }>Reuse a file already in Vault</button>
                                </div>
                            ) }
                            { mode === 'existing' && !reviewFile && (
                                <p className="sf-action-empty">Select one of the existing customer-owned Vault files above to activate Send, Schedule or Resend.</p>
                            ) }
                            { mode === 'existing' && reviewFile?.status === 'active' && ( accessStateOf( reviewFile ) === 'UNPAID' || accessStateOf( reviewFile ) === 'EXPIRED' ) && (
                                <div className="sf-delivery-buttons">
                                    <button type="button" className="sf-cta sf-send-cta"
                                        onClick={ () => { void handleSendPayment( reviewFile ); } }
                                        disabled={ !!acting || uploading || schedulingBusy || !vaultBreakdown || vaultPricePaise === null }>
                                        { acting === reviewFile.fileId ? 'Sending…' : reviewFile.lastPaymentRequestedAt ? 'Review payment status / resend' : 'Send Review & Pay now' }
                                    </button>
                                    <button type="button" className="sf-cta sf-cta-quiet"
                                        onClick={ () => setScheduledAction( 'payment' ) }
                                        disabled={ !!acting || schedulingBusy || !vaultBreakdown || vaultPricePaise === null }>
                                        Schedule Review &amp; Pay
                                    </button>
                                    <p className="sf-action-warning">
                                        One owner-bound file and fixed catalogue price. Staff cannot edit the amount.
                                        The customer approves payment on WhatsApp; the receipt and Access Vault link
                                        follow only verified capture. Check uncertain sends before retrying.
                                    </p>
                                </div>
                            ) }
                            { mode === 'existing' && reviewFile?.status === 'active' && ( accessStateOf( reviewFile ) === 'READY' || accessStateOf( reviewFile ) === 'OPEN' ) && (
                                <div className="sf-delivery-buttons">
                                    <button type="button" className="sf-cta sf-send-cta"
                                        disabled={ !!acting || schedulingBusy || uploading }
                                        onClick={ () => { void handleSendAccess( reviewFile ); } }>
                                        { acting ? 'Sending…' : 'Resend Access Vault now' }
                                    </button>
                                    <button type="button" className="sf-cta sf-cta-quiet"
                                        disabled={ !!acting || schedulingBusy || uploading }
                                        onClick={ () => setScheduledAction( 'access' ) }>
                                        Schedule access resend
                                    </button>
                                    <p className="sf-action-warning">
                                        Paid access must still be active at send time. No new payment is requested.
                                    </p>
                                </div>
                            ) }
                            { mode === 'existing' && reviewFile?.status === 'active' && accessStateOf( reviewFile ) === 'PAID_UNVERIFIED' &&
                                <p className="sf-action-warning">Payment requires reconciliation. Sending and scheduling are disabled to prevent a second charge.</p> }
                            { scheduledAction && reviewFile && (
                                <div className="sf-schedule-box">
                                    <h3>Schedule { scheduledAction === 'payment' ? 'Review &amp; Pay' : 'Access Vault resend' }</h3>
                                    <label className="sf-label" htmlFor="sf-scheduled-at">Send date &amp; time · your device timezone</label>
                                    <input type="datetime-local" id="sf-scheduled-at" className="sf-input" step={ 60 }
                                        value={ scheduledAtLocal } onChange={ e => setScheduledAtLocal( e.target.value ) }
                                        disabled={ schedulingBusy } />
                                    <p className="sf-hint">Schedule between 10 minutes and 30 days ahead. The sender runs about every 5 minutes. Each action rechecks file ownership, payment state and delivery rules when due.</p>
                                    <div className="sf-schedule-controls">
                                        <button type="button" className="sf-cta" disabled={ schedulingBusy || !scheduledAtLocal }
                                            onClick={ () => { void handleScheduleAction( reviewFile ); } }>
                                            { schedulingBusy ? 'Scheduling…' : 'Confirm scheduled send' }
                                        </button>
                                        <button type="button" className="sf-cta sf-cta-quiet"
                                            onClick={ () => { setScheduledAction( null ); setScheduledAtLocal( '' ); } }
                                            disabled={ schedulingBusy }>Close</button>
                                    </div>
                                </div>
                            ) }
                            { reviewFile && mode === 'existing' && (
                                <section className="sf-schedules" aria-label="Vault scheduled message history">
                                    <div className="sf-schedules-heading">
                                        <h3>Scheduled &amp; recent actions</h3>
                                        <button type="button" className="sf-act" disabled={ schedulingBusy }
                                            onClick={ () => { void reloadSchedules( reviewFile.fileId ); } }>Refresh</button>
                                    </div>
                                    { scheduleError && <p role="status" className="sf-action-warning">{ scheduleError }</p> }
                                    { scheduled.length === 0 && !scheduleError &&
                                        <p className="sf-hint">No scheduled messages for this file.</p> }
                                    { scheduled.map( record => (
                                        <div className="sf-schedule-record" key={ record.scheduledId }>
                                            <div>
                                                <strong>{ record.action === 'offer' ? 'Retired offer (historical)'
                                                    : record.action === 'payment' ? 'Review & Pay'
                                                        : 'Paid access resend' }</strong>
                                                <small>{ displayScheduleTime( record.scheduledAt ) } · { record.status === 'DISPATCH_UNKNOWN' ? 'Needs delivery review' : record.status }</small>
                                            </div>
                                            { record.status === 'PENDING' && (
                                                <button type="button" className="sf-act" disabled={ schedulingBusy }
                                                    onClick={ () => { void handleCancelSchedule( reviewFile, record.scheduledId ); } }>
                                                    Cancel
                                                </button>
                                            ) }
                                        </div>
                                    ) ) }
                                </section>
                            ) }
                            <Link href="/workspace/communications?view=manage&section=scheduled" className="sf-other-messages">
                                Schedule other approved WhatsApp messages in Communications
                            </Link>
                        </div>
                    </div>
                    <VaultJourneyPreview
                        mode={ mode }
                        customerName={ name }
                        customerPhone={ mobile }
                        draftFile={ file }
                        selectedFile={ reviewFile }
                        pricePaise={ vaultPricePaise }
                        paymentItemDescription={ paymentItemDescription }
                        onPaymentItemDescriptionChange={ setPaymentItemDescription }
                        breakdown={ vaultBreakdown }
                        templates={ vaultTemplates }
                        priceLoading={ vaultPriceLoading }
                        journey={ journey }
                        journeyError={ journeyError }
                        onCopyFileId={ () => { if ( reviewFile ) void handleCopyId( reviewFile ); } }
                        onStaffDownload={ () => { if ( reviewFile ) void handleStaffDownload( reviewFile ); } }
                    />
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
                        <p className="sf-note sf-note-pad" role="status">No current Vault documents for this filter. Upload a private file to Vault S3 before requesting payment; no WhatsApp message, invoice or customer download is generated from an empty Vault. Historical records remain in Logs.</p>
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
                                                    <span className="sf-fileorig">System-generated Vault filename</span>
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
                                                                onClick={ () => preparePayment( row ) }
                                                                disabled={ !!acting }
                                                            >
                                                                { accessStateOf( row ) === 'EXPIRED'
                                                                    ? 'Review renewal payment'
                                                                    : 'Review & Pay for this file' }
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
                                                            onClick={ () => {
                                                                setMode( 'existing' );
                                                                setSelectedCustomerId( '' );
                                                                setContactQuery( row.ownerName || '' );
                                                                setReviewFile( row );
                                                                
                                                                document.getElementById( 'sf-journey-preview' )?.scrollIntoView( { behavior: 'smooth', block: 'start' } );
                                                            } }
                                                        >
                                                            Preview journey
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

            <style jsx>{ `
                .sf-wrap{width:100%;max-width:1320px;padding:16px 24px;box-sizing:border-box;font-family:var(--font-sans);font-size:var(--public-supporting-size);color:var(--public-text)}

                .sf-heading-line{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap}
                .sf-private-indicator{display:inline-flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid var(--public-brand-lime);border-radius:999px;background:var(--public-lime-tint);font-size:var(--public-meta-size);font-weight:700;color:var(--public-brand-green);white-space:nowrap}
                .sf-private-indicator:before{content:'';width:7px;height:7px;border-radius:50%;background:#5eaf73}
                .sf-progress{display:flex;flex-wrap:wrap;list-style:none;padding:0;margin:20px 0 0;gap:9px}
                .sf-progress li{display:inline-flex;align-items:center;gap:7px;padding:6px 11px;background:var(--public-lime-tint);border:1px solid var(--public-hairline);border-radius:999px;color:var(--public-brand-green);font-size:var(--public-meta-size);font-weight:700}
                .sf-progress li span{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#e8f3dd;font-size:11px;color:var(--accent)}
                .sf-progress li:first-child{background:#ecf8d8;border-color:#c7e59c;color:var(--accent)}
                .sf-identity-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:15px}
                .sf-ownership-note{margin:7px 0 0}
                .sf-message-composer{margin-top:20px;padding:16px;border-radius:13px;background:#f7faf5;border:1px solid #d8e7d5}
                .sf-message-heading{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:12px}
                .sf-message-heading strong{color:var(--public-brand-green);font-size:var(--public-supporting-size)}
                .sf-message-heading span{font-weight:700;font-size:11px;color:#59745c}
                .sf-composer-help{font-size:var(--public-meta-size);line-height:1.5;color:var(--public-muted);margin:8px 0 0}
                .sf-composer-help code{font-size:11px}
                .sf-description-editor{min-width:0;display:grid;gap:9px;padding:16px;border-radius:14px;border:1px solid #bcd6b4;background:#f6fbf3}
                .sf-description-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
                .sf-description-heading label{font-weight:750;font-size:14px;line-height:1.35;color:#193d26}
                .sf-description-count{font-size:12px;font-weight:800;white-space:nowrap;font-variant-numeric:tabular-nums;color:#315b38}
                .sf-description-count.invalid{color:#aa3b2c}
                .sf-description-input{min-width:0;font-size:16px}
                .sf-description-input[aria-invalid="true"]{border-color:#b4533c;background:#fffafa}
                .sf-description-help{font-size:12px;line-height:1.5;color:#506756;margin:0}
                .sf-description-feedback{font-size:12px;font-weight:700;line-height:1.4;color:#27613b;margin:0}
                .sf-description-feedback.invalid{color:#aa3b2c}
                .sf-delivery-buttons{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
                .sf-delivery-buttons .sf-cta{min-height:48px;padding:10px 12px;font-family:var(--font-sans);font-size:var(--public-supporting-size);white-space:normal;line-height:1.4}
                .sf-delivery-buttons .sf-send-cta{grid-column:1 / -1;min-height:52px;font-size:var(--public-cta-font-size)!important}
                .sf-action-empty{padding:14px;background:#f6faf3;border:1px dashed #c6dfc1;border-radius:11px;color:#48624c;font-size:13px;line-height:1.5}
                .sf-action-empty strong{font-weight:750;color:#234a2f}
                .sf-action-empty p{margin:6px 0 12px}
                .sf-action-warning{grid-column:1 / -1;margin:0;color:#66766a;font-size:11px;line-height:1.45}
                .sf-schedule-box{padding:16px;border:1px solid #c9dcbf;border-radius:13px;background:#f8fcf5;display:grid;gap:10px}
                .sf-schedule-box h3{margin:0;font-size:15px;color:#214b2b}
                .sf-schedule-box .sf-input{max-width:330px}
                .sf-schedule-controls{display:flex;gap:8px;flex-wrap:wrap}
                .sf-schedule-controls .sf-cta{min-height:43px;font-size:13px;padding:9px 15px}
                .sf-schedules{padding:12px 14px;border-radius:11px;border:1px solid #e1e9dd;background:#fff}
                .sf-schedules-heading{display:flex;align-items:center;justify-content:space-between;gap:8px}
                .sf-schedules-heading h3{font-size:13px;margin:0;font-weight:750;color:#284b32}
                .sf-schedule-record{display:flex;justify-content:space-between;gap:10px;align-items:center;border-top:1px solid #e8efe5;padding:10px 0}
                .sf-schedule-record:first-of-type{margin-top:8px}
                .sf-schedule-record strong{display:block;font-size:12px;color:#243c2c}
                .sf-schedule-record small{display:block;font-size:11px;color:#61746a;line-height:1.6}
                .sf-other-messages{display:inline-flex;align-items:center;min-height:44px;color:var(--accent);font-size:12px;font-weight:750;text-decoration:underline;text-underline-offset:3px}
                .sf-top-links{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 18px}
                .sf-top-links a{display:inline-flex;align-items:center;min-height:42px;box-sizing:border-box;font-size:12px;font-weight:750;padding:7px 13px;border:1px solid #d7e6d3;background:#f8faf5;color:#245334;border-radius:999px;text-decoration:none}
                .sf-top-links a:hover{background:#ecf7e0}
                .sf-top-links a:focus-visible{outline:2px solid #356e38;outline-offset:2px}
                                .sf-review-actions{margin-top:18px;padding-top:14px;border-top:1px solid var(--border);display:grid;gap:12px}
                .sf-review-checks{display:flex;flex-wrap:wrap;gap:6px;align-items:center;color:var(--text-muted)}
                .sf-review-checks strong{width:100%;font-size:13px;color:var(--text)}
                .sf-review-checks span{font-size:11px;padding:5px 8px;border-radius:7px;background:#f4f6f4;border:1px solid #e3e7e1}
                .sf-send-cta{justify-self:stretch;width:100%;font-size:15px!important}
                .sf-send-accepted{margin:0;padding:11px;border-radius:10px;background:#f1f8eb;color:var(--accent);font-size:12px;line-height:1.45}
                .sf-workbench{display:grid;grid-template-columns:minmax(0,1.03fr) minmax(350px,.97fr);align-items:start;gap:18px;margin:0 0 24px}
                .sf-offer-variable{margin-top:16px}
                .sf-offer-textarea{box-sizing:border-box;display:block;width:100%;resize:vertical;min-height:64px}
                .sf-offer-counter{float:right;font-weight:700;color:var(--text-muted)}
                .sf-compose{min-width:0;background:#fff;border:1px solid var(--border);border-radius:16px;padding:20px}
                .sf-workbench-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
                .sf-workbench-heading h2{margin:0 0 6px;font-size:var(--public-card-size);font-weight:var(--public-card-weight);letter-spacing:var(--public-card-tracking);line-height:var(--public-card-leading);color:var(--public-heading)}
                .sf-workbench-heading p{margin:0;color:var(--public-muted);line-height:1.45;font-size:var(--public-supporting-size)}
                .sf-workbench-heading>span{font-size:11px;font-weight:800;color:var(--text-muted)}
                .sf-customer-picker{margin:18px 0 0}
                .sf-customer-results{display:grid;max-height:210px;overflow:auto;border:1px solid var(--border);border-radius:11px;margin-top:9px}
                .sf-customer-results button{display:flex;gap:10px;justify-content:space-between;align-items:center;min-height:48px;text-align:left;border:0;border-top:1px solid var(--public-hairline);background:var(--public-bg);padding:10px 12px;cursor:pointer;color:var(--public-text);font-family:var(--font-sans)}
                .sf-customer-results button:first-child{border-top:0}
                .sf-customer-results button:hover,.sf-customer-results button:focus-visible{background:var(--public-lime-tint);outline-color:var(--public-brand-green)}
                .sf-customer-results button strong{font-size:var(--public-supporting-size)}
                .sf-customer-results button small{color:var(--public-muted);font-size:var(--public-meta-size)}
                .sf-contact-change{border:0;background:transparent;padding:2px 0;color:var(--accent);text-decoration:underline;font:700 12px var(--font-sans);cursor:pointer}
                .sf-document-mode{display:flex;gap:6px;background:var(--public-lime-tint);border:1px solid var(--public-brand-lime);border-radius:12px;padding:5px;margin:20px 0 0}
                .sf-document-mode button{flex:1;min-height:48px;border:0;border-radius:8px;background:transparent;font:700 var(--public-supporting-size)/1.35 var(--font-sans);color:var(--public-brand-green);cursor:pointer}
                .sf-document-mode button.active,.sf-document-mode button:hover{background:var(--public-brand-lime);color:var(--public-brand-green);box-shadow:0 1px 6px rgba(26,58,42,.12)}
                .sf-upload-area,.sf-existing-picker{padding:20px 0 0}
                .sf-upload-area .sf-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
                .sf-upload-area .sf-note,.sf-existing-picker .sf-note{font-size:13px;line-height:1.5}
                .sf-lookup{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;margin:0 0 12px}
                .sf-lookup .sf-cta{font-size:13px;min-height:46px;padding:0 16px}
                .sf-file-choices{display:grid;gap:7px;max-height:360px;overflow:auto}
                .sf-file-choices>button{display:flex;justify-content:space-between;align-items:center;gap:12px;min-width:0;text-align:left;padding:12px;border:1px solid var(--border);border-radius:11px;background:#fff;color:var(--text);cursor:pointer}
                .sf-file-choices>button.selected,.sf-file-choices>button:hover{border-color:var(--public-brand-lime);background:var(--public-lime-tint)}
                .sf-file-choices>button strong{display:block;font-size:var(--public-supporting-size);overflow-wrap:anywhere}
                .sf-file-choices>button small{display:block;margin-top:4px;color:var(--public-muted);font-size:var(--public-meta-size)}
                .sf-choice-status{font-size:11px;max-width:110px;text-align:right;color:var(--text-muted)}
                .sf-selection-actions{display:flex;flex-direction:column;align-items:flex-start;gap:8px;padding-top:14px;margin-top:15px;border-top:1px solid var(--border)}
                .sf-selection-actions>strong{font-size:13px;overflow-wrap:anywhere}
                .sf-selection-actions>small{color:var(--text-muted);font-size:12px}
                .sf-selection-actions .sf-cta{font-size:13px;min-height:44px;padding:0 16px}
                @media(max-width:1080px){.sf-workbench{grid-template-columns:minmax(0,1fr)}}
                @media(max-width:600px){.sf-wrap{padding:12px}.sf-compose{padding:14px}.sf-upload-area .sf-grid,.sf-identity-fields,.sf-delivery-buttons{grid-template-columns:minmax(0,1fr)}.sf-lookup{grid-template-columns:minmax(0,1fr)}.sf-workbench-heading>span{display:none}.sf-progress{gap:5px}.sf-progress li{font-size:10px;padding:5px 7px}.sf-private-indicator{margin-top:4px}.sf-description-editor{padding:13px}.sf-top-links{display:grid;grid-template-columns:1fr 1fr}.sf-top-links a{justify-content:center;text-align:center}.sf-top-links a:last-child{grid-column:1/-1}.sf-schedule-controls{display:grid;grid-template-columns:1fr}.sf-schedule-controls .sf-cta{width:100%}}
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
                  margin:0;max-width:78ch;font-size:15px;font-weight:400;line-height:1.4;
                  letter-spacing:-.125px;color:rgba(0,0,0,.898);
                }

                /* Same panel treatment as .home-close-panel and the /files page. */
                .sf-panel{
                  padding:clamp(18px,2vw,28px);margin:0 0 24px;
                  border:1px solid var(--border);border-radius:14px;background:#fff;
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
                  display:block;margin:0 0 8px;font-size:var(--public-supporting-size);font-weight:650;
                  letter-spacing:-.1px;color:var(--public-brand-green);
                }
                /* 16px minimum: smaller makes iOS Safari zoom the viewport on focus. */
                .sf-input{
                  width:100%;box-sizing:border-box;min-height:48px;padding:0 14px;
                  font-family:var(--font-sans);font-size:var(--public-supporting-size);color:var(--public-text);background:var(--public-bg);
                  border:2px solid rgba(26,58,42,.18);border-radius:12px;
                  transition:border-color .2s;
                }
                .sf-input:focus{outline:none;border-color:var(--public-brand-lime);box-shadow:0 0 0 2px var(--public-lime-tint)}
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
                  .sf-storage-card{grid-template-columns:1fr}
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
