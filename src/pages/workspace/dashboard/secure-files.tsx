/**
 * Secure Files — upload and register a file to one customer.
 *
 * One form does three things, because they are one intention: naming a customer,
 * registering a file to them, and creating the login that lets them fetch it.
 * Entering a mobile number here CREATES a Cognito customer if none exists, and that
 * number is the one that receives the WhatsApp OTP - so a typo does not fail loudly,
 * it silently registers the file to someone who will never ask for it. The form says
 * so next to the field.
 *
 * Upload is three calls, not one: register, PUT to S3, confirm. The confirm step
 * re-checks the object really landed, so an upload that dies half way leaves a
 * `pending` row rather than an `active` file a customer could be charged for and not
 * receive.
 *
 * The S3 key is deliberately absent from this page. Objects are stored as
 * `wecare-digital-<uuid>-<uuid>`, and the readable name lives only in the table, so
 * everything here is keyed on `fileId`. Owner numbers arrive already masked to the
 * last four digits; the full number is never sent to the browser.
 *
 * Design
 * ------
 * Carries the home page's language, matching the customer-facing /files page: the
 * #d1f470 lime with #1a3a2a on it, 14px-radius panels with 2px borders, the 52px
 * 50px-radius pill CTA, and the site heading rung
 * clamp(28px,3.2vw,40px)/700/1.08/-1.2px. This is deliberately NOT the other
 * dashboard pages' var(--surface)/var(--border) treatment - the two secure-file
 * screens are a pair and should read as one feature, since an operator moves between
 * this page and the customer's view of the same file. It still sits inside the
 * dashboard Layout, so the shell, nav and auth are unchanged.
 */

import React, { useCallback, useEffect, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Spinner from '../../../components/ui/Spinner';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import * as api from '../../../api/client';
import type { SecureFile } from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; }

const MAX_BYTES = 200 * 1024 * 1024;

function formatBytes ( bytes: number ): string {
    if ( !bytes ) return '0 B';
    const units = [ 'B', 'KB', 'MB', 'GB' ];
    const exponent = Math.min( Math.floor( Math.log( bytes ) / Math.log( 1024 ) ), units.length - 1 );
    return `${( bytes / Math.pow( 1024, exponent ) ).toFixed( exponent === 0 ? 0 : 1 )} ${units[ exponent ]}`;
}

const rupees = ( paise: number ) => `₹${( ( paise || 0 ) / 100 ).toFixed( 0 )}`;

/** Status pill colours. Lime is reserved for actions, so status uses its own set. */
const STATUS_COLOURS: Record<string, { bg: string; fg: string; border: string }> = {
    active: { bg: '#dcfce7', fg: '#166534', border: '#16a34a' },
    pending: { bg: '#fef3c7', fg: '#92400e', border: '#d97706' },
    revoked: { bg: '#fee2e2', fg: '#991b1b', border: '#ef4444' },
};

export default function SecureFilesPage ( { signOut, user }: PageProps ) {
    const toast = useToastContext();
    const confirm = useConfirm();

    const [ name, setName ] = useState( '' );
    const [ mobile, setMobile ] = useState( '' );
    const [ displayName, setDisplayName ] = useState( '' );
    const [ file, setFile ] = useState<File | null>( null );
    const [ uploading, setUploading ] = useState( false );
    const [ step, setStep ] = useState( '' );

    const [ files, setFiles ] = useState<SecureFile[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ loadError, setLoadError ] = useState( '' );
    const [ filterMobile, setFilterMobile ] = useState( '' );

    /** Refetch and replace the table. Used by the filter button and after an upload. */
    const fetchInto = useCallback( async ( mobileFilter?: string ) => {
        const result = await api.listSecureFiles( mobileFilter || undefined );
        if ( result.ok )
        {
            setFiles( result.data.files || [] );
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
        // Settled from the promise callback rather than the effect body: `loading`
        // already starts true, and calling a state-setting helper directly here trips
        // react-hooks/set-state-in-effect even when every write is after an await.
        let cancelled = false;
        api.listSecureFiles().then( result => {
            if ( cancelled ) return;
            if ( result.ok )
            {
                setFiles( result.data.files || [] );
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

    const resetForm = () => {
        setName( '' );
        setMobile( '' );
        setDisplayName( '' );
        setFile( null );
    };

    const handleUpload = async () => {
        if ( !file ) { toast.error( 'Choose a file first' ); return; }
        if ( !name.trim() ) { toast.error( 'Customer name is required' ); return; }
        if ( !mobile.trim() ) { toast.error( 'Customer mobile number is required' ); return; }
        if ( file.size > MAX_BYTES )
        {
            toast.error( `File is larger than ${formatBytes( MAX_BYTES )}` );
            return;
        }

        setUploading( true );
        try
        {
            setStep( 'Registering customer and file…' );
            const contentType = file.type || 'application/octet-stream';
            const ticket = await api.initSecureUpload( {
                name: name.trim(),
                mobile: mobile.trim(),
                displayName: displayName.trim() || file.name,
                originalFilename: file.name,
                contentType,
                sizeBytes: file.size,
            } );
            if ( !ticket.ok )
            {
                toast.error( ticket.failure.message || 'Could not register the file' );
                return;
            }

            setStep( 'Uploading…' );
            const sent = await api.uploadSecureFileBytes( ticket.data.uploadUrl, file, contentType );
            if ( !sent )
            {
                // The record stays `pending`, so nothing is downloadable or billable.
                toast.error( 'Upload failed. The file was not stored; try again.' );
                return;
            }

            setStep( 'Confirming…' );
            const confirmed = await api.confirmSecureUpload( ticket.data.fileId );
            if ( !confirmed.ok )
            {
                toast.error( confirmed.failure.message || 'Upload could not be confirmed' );
                return;
            }

            toast.success( `${displayName.trim() || file.name} registered to ${name.trim()}` );
            resetForm();
            load( filterMobile || undefined );
        } catch ( err: any )
        {
            toast.error( err?.message || 'Upload failed' );
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

    return (
        <Layout onSignOut={ signOut } user={ user }>
            <SEO title="Secure Files" description="Share a file with a verified customer" />

            <div className="sf-wrap">
                <header className="sf-head">
                    <p className="sf-eyebrow">Secure sharing</p>
                    <h1 className="sf-title">Secure files</h1>
                    <p className="sf-lead">
                        Files registered to one customer, who verifies on WhatsApp before
                        downloading. Stored under an unguessable name and never reachable
                        from a public link.
                    </p>
                </header>

                {/* ── upload + register ─────────────────────────────────────────── */ }
                <section className="sf-panel" aria-labelledby="sf-add">
                    <h2 className="sf-h2" id="sf-add">Add a file</h2>
                    <p className="sf-note">
                        The customer login is created automatically from the mobile number.
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
                                disabled={ uploading }
                            />
                            {/* The consequence of a typo is silent, so say it here. */ }
                            <p className="sf-hint">
                                This number receives the WhatsApp OTP. A 10-digit Indian
                                number gets +91 automatically. Check it — the file is
                                registered to whoever this is.
                            </p>
                        </div>

                        <div className="sf-field">
                            <label className="sf-label" htmlFor="sf-display">
                                File name shown to the customer
                            </label>
                            <input
                                id="sf-display"
                                className="sf-input"
                                value={ displayName }
                                onChange={ e => setDisplayName( e.target.value ) }
                                placeholder={ file?.name || 'Trade Licence 2026' }
                                disabled={ uploading }
                            />
                        </div>

                        <div className="sf-field">
                            <label className="sf-label" htmlFor="sf-file">File</label>
                            <input
                                id="sf-file"
                                className="sf-input sf-input-file"
                                type="file"
                                onChange={ e => setFile( e.target.files?.[ 0 ] || null ) }
                                disabled={ uploading }
                            />
                            { file && (
                                <p className="sf-hint">
                                    { formatBytes( file.size ) } · { file.type || 'unknown type' }
                                </p>
                            ) }
                        </div>
                    </div>

                    <div className="sf-actions">
                        <button className="sf-cta" onClick={ handleUpload } disabled={ uploading }>
                            { uploading ? 'Working…' : 'Register and upload' }
                        </button>
                        <span className="sf-aside">
                            { uploading && step
                                ? step
                                : `Customer pays ${rupees( 4900 )} per download.` }
                        </span>
                    </div>
                </section>

                {/* ── registered files ──────────────────────────────────────────── */ }
                <section className="sf-panel" aria-labelledby="sf-list">
                    <div className="sf-listhead">
                        <div>
                            <h2 className="sf-h2" id="sf-list">Registered files</h2>
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
                        <p className="sf-note sf-note-pad">No files registered yet.</p>
                    ) }

                    { !loading && files.length > 0 && (
                        <div className="sf-tablewrap">
                            <table className="sf-table">
                                <thead>
                                    <tr>
                                        { [ 'File', 'Customer', 'Mobile', 'Size', 'Downloads', 'Status', '' ].map( heading => (
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
                                                    <span className="sf-fileorig">{ row.originalFilename }</span>
                                                </td>
                                                <td>{ row.ownerName || '—' }</td>
                                                {/* masked at the API; the full number never reaches the browser */ }
                                                <td className="sf-mono">{ row.ownerPhoneMasked || '—' }</td>
                                                <td>{ formatBytes( row.sizeBytes ) }</td>
                                                <td>{ row.downloadCount ?? 0 }</td>
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
                                                    { row.status !== 'revoked' && (
                                                        <button
                                                            className="sf-revoke"
                                                            onClick={ () => handleRevoke( row ) }
                                                        >
                                                            Revoke
                                                        </button>
                                                    ) }
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
                .sf-wrap{padding:24px;max-width:1100px}

                .sf-head{margin:0 0 28px}
                .sf-eyebrow{
                  margin:0 0 14px;font-size:12px;font-weight:700;
                  letter-spacing:.08em;text-transform:uppercase;color:#1a3a2a;
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
                  border:2px solid #d1f470;border-radius:14px;
                  background:rgba(209,244,112,.22);
                }
                .sf-h2{
                  margin:0 0 6px;font-size:22px;font-weight:700;
                  letter-spacing:-.4px;color:rgba(0,0,0,.95);
                }
                .sf-note{margin:0 0 20px;font-size:15px;color:rgba(26,58,42,.72)}
                .sf-note-pad{display:flex;align-items:center;gap:8px;padding:12px 0;margin:0}

                .sf-grid{
                  display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
                  gap:20px;margin:0 0 20px;
                }
                .sf-field{min-width:0}
                .sf-label{
                  display:block;margin:0 0 8px;font-size:14px;font-weight:600;
                  letter-spacing:-.1px;color:#1a3a2a;
                }
                /* 16px minimum: smaller makes iOS Safari zoom the viewport on focus. */
                .sf-input{
                  width:100%;box-sizing:border-box;min-height:48px;padding:0 14px;
                  font-size:16px;color:rgba(0,0,0,.95);background:#fff;
                  border:2px solid rgba(26,58,42,.18);border-radius:12px;
                  transition:border-color .2s;
                }
                .sf-input:focus{outline:none;border-color:#1a3a2a}
                .sf-input:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
                .sf-input:disabled{opacity:.6}
                .sf-input-file{padding:11px 12px;min-height:48px}
                .sf-hint{margin:8px 0 0;font-size:13px;line-height:1.45;color:rgba(26,58,42,.72)}

                .sf-actions{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
                .sf-aside{font-size:15px;color:rgba(26,58,42,.72)}

                /* The home page CTA: 52px, 50px pill, lime inverting to white. */
                .sf-cta{
                  display:inline-flex;align-items:center;justify-content:center;
                  min-height:52px;padding:0 28px;
                  border:2px solid #d1f470;border-radius:50px;background:#d1f470;
                  color:#1a3a2a;font-size:17px;font-weight:600;cursor:pointer;
                  transition:background-color .2s,transform .2s,box-shadow .2s;
                }
                .sf-cta:hover:not(:disabled){
                  background:#fff;transform:translateY(-2px);
                  box-shadow:0 4px 12px rgba(26,58,42,.12);
                }
                .sf-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
                .sf-cta:disabled{opacity:.55;cursor:default}
                /* Secondary: same geometry, white by default, so it reads as the lesser
                   of the two without introducing a third shape. */
                .sf-cta-quiet{
                  min-height:48px;padding:0 22px;font-size:15px;
                  background:#fff;border-color:rgba(26,58,42,.18);
                }
                .sf-cta-quiet:hover:not(:disabled){background:#d1f470;border-color:#d1f470}

                .sf-listhead{
                  display:flex;justify-content:space-between;align-items:flex-end;
                  gap:20px;flex-wrap:wrap;margin:0 0 8px;
                }
                .sf-filter{display:flex;align-items:flex-end;gap:10px}
                .sf-filter .sf-input{width:190px}

                .sf-alert{
                  margin:0 0 16px;padding:12px 16px;border-radius:12px;
                  border:2px solid #ef4444;background:#fee2e2;color:#7f1d1d;
                  font-size:15px;line-height:1.45;
                }

                /* White table on the tinted panel, so rows stay legible. */
                .sf-tablewrap{
                  overflow-x:auto;background:#fff;
                  border:2px solid rgba(26,58,42,.12);border-radius:12px;
                }
                .sf-table{width:100%;border-collapse:collapse}
                .sf-table th{
                  padding:12px 14px;text-align:left;font-size:12px;font-weight:700;
                  letter-spacing:.06em;text-transform:uppercase;color:rgba(26,58,42,.6);
                  border-bottom:2px solid rgba(26,58,42,.12);white-space:nowrap;
                }
                .sf-table td{
                  padding:12px 14px;font-size:15px;color:rgba(0,0,0,.9);
                  border-bottom:1px solid rgba(26,58,42,.08);vertical-align:top;
                }
                .sf-table tr:last-child td{border-bottom:0}
                .sf-filename{display:block;font-weight:600;letter-spacing:-.2px}
                .sf-fileorig{
                  display:block;margin-top:3px;font-size:13px;color:rgba(26,58,42,.6);
                }
                .sf-mono{font-family:var(--font-mono,ui-monospace,monospace)}

                .sf-status{
                  display:inline-block;padding:3px 10px;border-radius:50px;
                  border:1px solid;font-size:12px;font-weight:600;text-transform:capitalize;
                }

                .sf-revoke{
                  border:2px solid rgba(26,58,42,.18);border-radius:50px;
                  background:#fff;color:#1a3a2a;padding:6px 16px;
                  font-size:14px;font-weight:600;cursor:pointer;transition:background-color .2s;
                }
                .sf-revoke:hover{background:#fee2e2;border-color:#ef4444;color:#991b1b}
                .sf-revoke:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}

                @media(prefers-reduced-motion:reduce){
                  .sf-cta,.sf-input,.sf-revoke{transition:none}
                  .sf-cta:hover:not(:disabled){transform:none}
                }
            ` }</style>
        </Layout>
    );
}
