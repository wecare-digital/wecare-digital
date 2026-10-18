/**
 * Flow Publish Checklist (Part 5) — verifies publish preconditions and gates the
 * publish action behind a confirm-danger dialog.
 */
import React, { useState, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import {
    WabaSelector, ValidationErrorList, FlowHealthPanel, FlowPreviewCard,
    StatusBadge, useConfirmDanger, RawJsonDrawer, MetaErrorPanel, WABA_OPTIONS,
} from '../../../components/wa';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

interface CheckItem { label: string; ok: boolean; detail?: string; }

const FlowPublishChecklist: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const confirmDanger = useConfirmDanger();
    const [ wabaId, setWabaId ] = useState( WABA_OPTIONS?.[ 0 ]?.wabaId || '' );
    const [ flowId, setFlowId ] = useState( '' );
    const [ flow, setFlow ] = useState<any>( null );
    const [ loading, setLoading ] = useState( false );
    const [ publishing, setPublishing ] = useState( false );
    const [ error, setError ] = useState<any>( null );

    const load = useCallback( async () => {
        if ( !flowId.trim() ) { toast.error( 'Enter a flowId' ); return; }
        setLoading( true ); setError( null ); setFlow( null );
        try
        {
            const f = await api.getFlow( flowId.trim() );
            if ( !f ) { toast.error( 'Flow not found' ); return; }
            setFlow( f );
        } catch ( e: any ) { setError( e?.message || 'Failed to load flow' ); }
        finally { setLoading( false ); }
    }, [ flowId, toast ] );

    const validationErrors = flow?.validation_errors || [];
    const health = flow?.health_status;
    const canSend = health ? String( health?.can_send_message || 'AVAILABLE' ).toUpperCase() !== 'BLOCKED' : true;

    const checks: CheckItem[] = flow ? [
        { label: 'Flow is in DRAFT status', ok: ( flow.status || '' ).toUpperCase() === 'DRAFT', detail: flow.status },
        { label: 'No validation errors', ok: validationErrors.length === 0, detail: `${validationErrors.length} error(s)` },
        { label: 'JSON version present', ok: !!flow.json_version, detail: flow.json_version },
        { label: 'Data API version set (if dynamic)', ok: !!flow.data_api_version || !flow.endpoint_uri, detail: flow.data_api_version || 'n/a' },
        { label: 'Endpoint URI set (if dynamic)', ok: !!flow.endpoint_uri || !flow.data_api_version, detail: flow.endpoint_uri ? 'set' : 'none' },
        { label: 'Health allows sending', ok: canSend, detail: canSend ? 'AVAILABLE' : 'BLOCKED' },
        { label: 'Preview tested', ok: !!flow.preview?.preview_url, detail: flow.preview?.preview_url ? 'generated' : 'not generated' },
    ] : [];

    const allPass = checks.length > 0 && checks.every( c => c.ok );

    const doPublish = async () => {
        if ( !allPass ) { toast.error( 'Resolve all checklist items before publishing' ); return; }
        const ok = await confirmDanger( 'publish', `Publish flow ${flow.name || flowId}? Published flows are immutable — to change later you must clone and publish a new version.` );
        if ( !ok ) return;
        setPublishing( true );
        try
        {
            const success = await api.publishFlow( flowId.trim() );
            if ( success ) { toast.success( 'Flow published' ); load(); }
            else toast.error( 'Publish failed' );
        } catch ( e: any ) { setError( e?.message || 'Publish failed' ); }
        finally { setPublishing( false ); }
    };

    const content = (
        <div style={ { maxWidth: 760, margin: '0 auto', padding: 16 } }>
            <SEO title="Flow Publish Checklist" description="Verify WhatsApp Flow publish preconditions." noindex />
            <h1 style={ { fontSize: 22, fontWeight: 700, marginBottom: 4 } }>Flow Publish Checklist</h1>
            <p style={ { color: '#777', fontSize: 13, marginBottom: 16 } }>Verify all preconditions before publishing. Published flows are immutable.</p>

            <div style={ { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 16, marginBottom: 16 } }>
                <div style={ { display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' } }>
                    <WabaSelector value={ wabaId } onChange={ setWabaId } />
                    <div style={ { flex: 1, minWidth: 220 } }>
                        <label style={ { fontSize: 12, fontWeight: 600, color: '#444', display: 'block', marginBottom: 4 } }>Flow ID</label>
                        <input value={ flowId } onChange={ e => setFlowId( e.target.value ) } placeholder="1234567890" style={ { width: '100%', padding: '8px 10px', border: '1px solid #d0d0d0', borderRadius: 6, fontSize: 14 } } />
                    </div>
                    <button onClick={ load } disabled={ loading } style={ { padding: '9px 16px', background: '#1a3a2a', color: '#d1f470', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 700 } }>{ loading ? 'Loading…' : 'Load flow' }</button>
                </div>
            </div>

            { error && <MetaErrorPanel error={ error } /> }

            { flow && (
                <>
                    <div style={ { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 16, marginBottom: 16 } }>
                        <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 } }>
                            <strong style={ { fontSize: 15 } }>{ flow.name || flow.id }</strong>
                            <StatusBadge status={ flow.status } />
                        </div>
                        { checks.map( ( c, i ) => (
                            <div key={ i } style={ { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderTop: i ? '1px solid #f5f5f5' : 'none' } }>
                                <span style={ { fontSize: 16, color: c.ok ? '#1a7a3a' : '#a11' } }>{ c.ok ? '✓' : '✕' }</span>
                                <span style={ { fontSize: 14, flex: 1 } }>{ c.label }</span>
                                <span style={ { fontSize: 12, color: '#888' } }>{ c.detail }</span>
                            </div>
                        ) ) }
                        <button onClick={ doPublish } disabled={ !allPass || publishing } style={ {
                            marginTop: 14, padding: '10px 18px', borderRadius: 6, border: 'none', fontWeight: 700, fontSize: 14,
                            cursor: allPass ? 'pointer' : 'not-allowed',
                            background: allPass ? '#1a7a3a' : '#ccc', color: '#fff',
                        } }>{ publishing ? 'Publishing…' : allPass ? 'Publish flow' : 'Resolve all items to publish' }</button>
                    </div>

                    <ValidationErrorList errors={ validationErrors } />
                    <div style={ { marginTop: 16 } }><FlowHealthPanel health={ health } canSend={ canSend } /></div>
                    <div style={ { marginTop: 16 } }><FlowPreviewCard flow={ { id: flow.id, name: flow.name, status: flow.status, previewUrl: flow.preview?.preview_url } } /></div>
                    <RawJsonDrawer data={ flow } label="Raw flow JSON" />
                </>
            ) }
        </div>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default FlowPublishChecklist;
