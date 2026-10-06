/**
 * WhatsApp Send Test Console (Part 4 E + tools)
 * Exercises the live /wa-business/messages/send/* routes plus the
 * TTL rules/validate, template validate, and preset endpoints.
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { WHATSAPP_PHONES } from '../../../../config/constants';
import ProductMessageComposer from '../../../../components/ProductMessageComposer';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const PHONES = [
    { key: 'primary', ...WHATSAPP_PHONES.primary },
    { key: 'secondary', ...WHATSAPP_PHONES.secondary },
];

/** The index is the state, so the option value is the index as a string. */
const PHONE_OPTIONS: SelectOption[] = PHONES.map( ( p, i ) => ( {
    value: String( i ),
    label: `${ p.name } — ${ p.display }`,
} ) );
const MEDIA_TYPE_OPTIONS: SelectOption[] = [ 'image', 'video', 'document', 'audio', 'sticker' ]
    .map( t => ( { value: t, label: t } ) );
const FLOW_MODE_OPTIONS: SelectOption[] = [
    { value: 'published', label: 'published' },
    { value: 'draft', label: 'draft' },
];
const TTL_CATEGORY_OPTIONS: SelectOption[] = [ 'AUTHENTICATION', 'UTILITY', 'MARKETING' ]
    .map( c => ( { value: c, label: c } ) );
const RESUME_TARGET_OPTIONS: SelectOption[] = [
    { value: 'handle', label: 'header handle (for template headers)' },
    { value: 'media', label: 'media id (for sending)' },
];

type SendTab = 'text' | 'template' | 'media' | 'flow' | 'tools' | 'mediamgmt' | 'flowadmin' | 'product';

const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 16, marginBottom: 16 };
const input: React.CSSProperties = { width: '100%', padding: '8px 10px', border: '1px solid #d0d0d0', borderRadius: 6, marginTop: 4, marginBottom: 10, fontSize: 14 };
const label: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#444' };
const btn: React.CSSProperties = { padding: '9px 16px', background: '#1a1a1a', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14, fontWeight: 600 };
const tabBtn = ( active: boolean ): React.CSSProperties => ( { padding: '8px 14px', border: 'none', borderBottom: active ? '2px solid #1a1a1a' : '2px solid transparent', background: 'none', cursor: 'pointer', fontWeight: active ? 700 : 500, color: active ? '#1a1a1a' : '#777' } );
/** Layout only: the two margins the shared `input` object carried. */
const selectLayout: React.CSSProperties = { marginTop: 4, marginBottom: 10 };

const SendTestConsole: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const [ phoneIdx, setPhoneIdx ] = useState( 0 );
    const [ to, setTo ] = useState( '' );
    const [ tab, setTab ] = useState<SendTab>( 'text' );
    const [ busy, setBusy ] = useState( false );

    const phone = PHONES[ phoneIdx ];

    // text
    const [ text, setText ] = useState( '' );
    // template
    const [ tplName, setTplName ] = useState( '' );
    const [ tplLang, setTplLang ] = useState( 'en' );
    // media
    const [ mediaType, setMediaType ] = useState<'image' | 'video' | 'document' | 'audio' | 'sticker'>( 'image' );
    const [ mediaUrl, setMediaUrl ] = useState( '' );
    const [ caption, setCaption ] = useState( '' );
    // flow
    const [ flowName, setFlowName ] = useState( '' );
    const [ flowScreen, setFlowScreen ] = useState( 'WELCOME' );
    const [ flowMode, setFlowMode ] = useState<'published' | 'draft'>( 'published' );
    const [ flowCta, setFlowCta ] = useState( 'Open' );
    const [ flowBody, setFlowBody ] = useState( 'Tap below to continue' );

    // tools
    const [ ttlRules, setTtlRules ] = useState<api.TtlRules | null>( null );
    const [ ttlCategory, setTtlCategory ] = useState( 'UTILITY' );
    const [ ttlSeconds, setTtlSeconds ] = useState( 43200 );
    const [ ttlResult, setTtlResult ] = useState<api.TtlValidationResult | null>( null );
    const [ presets, setPresets ] = useState<api.TemplatePresetSummary[]>( [] );
    const [ validateJson, setValidateJson ] = useState( '' );
    const [ validateResult, setValidateResult ] = useState<api.TemplateValidationResult | null>( null );

    // media management
    const [ mmFile, setMmFile ] = useState<File | null>( null );
    const [ mmUploadedId, setMmUploadedId ] = useState( '' );
    const [ mmLookupId, setMmLookupId ] = useState( '' );
    const [ mmInfo, setMmInfo ] = useState<api.WaMediaInfo | null>( null );
    const [ mmResumeTarget, setMmResumeTarget ] = useState<'handle' | 'media'>( 'handle' );
    const [ mmProgress, setMmProgress ] = useState( '' );

    // flow admin
    const [ faFlowId, setFaFlowId ] = useState( '' );
    const [ faFlowJson, setFaFlowJson ] = useState( '' );
    const [ faAssetResult, setFaAssetResult ] = useState<any>( null );
    const [ faSourceWaba, setFaSourceWaba ] = useState( WHATSAPP_PHONES.secondary.wabaId );
    const [ faDestWaba, setFaDestWaba ] = useState( WHATSAPP_PHONES.primary.wabaId );
    const [ faMigrateResult, setFaMigrateResult ] = useState<any>( null );
    const [ faSyncWaba, setFaSyncWaba ] = useState( WHATSAPP_PHONES.primary.wabaId );
    const [ faSyncResult, setFaSyncResult ] = useState<any>( null );

    const loadTools = useCallback( async () => {
        try
        {
            const [ rules, ps ] = await Promise.all( [ api.getTemplateTtlRules(), api.listTemplatePresets() ] );
            setTtlRules( rules );
            setPresets( ps );
        } catch ( e: any )
        {
            toast.error( e?.message || 'Failed to load tools' );
        }
    }, [ toast ] );

    useEffect( () => { if ( tab === 'tools' ) loadTools(); }, [ tab, loadTools ] );

    const requireTo = (): boolean => {
        if ( !to.trim() ) { toast.error( 'Recipient (to) is required, e.g. 919900000000' ); return false; }
        return true;
    };

    const report = ( r: { success?: boolean; messageId?: string; error?: string } ) => {
        if ( r?.success && r.messageId ) toast.success( `Sent — ${r.messageId}` );
        else if ( r?.success ) toast.success( 'Sent' );
        else toast.error( r?.error || 'Send failed' );
    };

    const doSend = async ( fn: () => Promise<any> ) => {
        setBusy( true );
        try { report( await fn() ); }
        catch ( e: any ) { toast.error( e?.message || 'Request failed' ); }
        finally { setBusy( false ); }
    };

    const sendText = () => requireTo() && doSend( () => api.sendTestText( to, text, { phoneId: phone.metaPhoneId } ) );
    const sendTpl = () => requireTo() && doSend( () => api.sendTestTemplate( to, tplName, { language: tplLang, phoneId: phone.metaPhoneId } ) );
    const sendMedia = () => requireTo() && doSend( () => api.sendTestMedia( to, mediaType, { mediaUrl, caption, phoneId: phone.metaPhoneId } ) );
    const sendFlow = () => requireTo() && doSend( () => api.sendTestFlow( to, { flowName, screen: flowScreen, mode: flowMode, flowCta, bodyText: flowBody, phoneId: phone.metaPhoneId } ) );

    const runValidateTtl = async () => {
        try { setTtlResult( await api.validateTemplateTtl( ttlCategory, Number( ttlSeconds ) ) ); }
        catch ( e: any ) { toast.error( e?.message || 'Validation failed' ); }
    };

    const runValidateTemplate = async () => {
        let def: any;
        try { def = JSON.parse( validateJson ); }
        catch { toast.error( 'Invalid JSON' ); return; }
        try { setValidateResult( await api.validateTemplateDefinition( def ) ); }
        catch ( e: any ) { toast.error( e?.message || 'Validation failed' ); }
    };

    const loadPreset = async ( name: string ) => {
        const p = await api.getTemplatePreset( name );
        if ( p ) { setValidateJson( JSON.stringify( p, null, 2 ) ); toast.success( `Loaded preset ${name}` ); }
    };

    // ── media management helpers ──
    const fileToBase64 = ( file: File ): Promise<string> => new Promise( ( resolve, reject ) => {
        const r = new FileReader();
        r.onload = () => resolve( ( ( r.result as string ) || '' ).split( ',' )[ 1 ] || '' );
        r.onerror = reject;
        r.readAsDataURL( file );
    } );

    const uploadMedia = async () => {
        if ( !mmFile ) { toast.error( 'Pick a file first' ); return; }
        setBusy( true );
        try
        {
            const b64 = await fileToBase64( mmFile );
            const r = await api.uploadWaMedia( { phoneId: phone.metaPhoneId, fileData: b64, contentType: mmFile.type, filename: mmFile.name } );
            if ( r.mediaId ) { setMmUploadedId( r.mediaId ); setMmLookupId( r.mediaId ); toast.success( `Uploaded — ${r.mediaId}` ); }
            else toast.error( r.error || 'Upload failed' );
        } catch ( e: any ) { toast.error( e?.message || 'Upload failed' ); }
        finally { setBusy( false ); }
    };

    const lookupMedia = async () => {
        if ( !mmLookupId.trim() ) { toast.error( 'Media ID required' ); return; }
        try { setMmInfo( await api.getWaMedia( mmLookupId.trim(), { phoneId: phone.metaPhoneId } ) ); }
        catch ( e: any ) { toast.error( e?.message || 'Lookup failed' ); }
    };

    const removeMedia = async () => {
        if ( !mmLookupId.trim() ) { toast.error( 'Media ID required' ); return; }
        const ok = await api.deleteWaMedia( mmLookupId.trim(), phone.metaPhoneId );
        if ( ok ) { toast.success( 'Deleted' ); setMmInfo( null ); } else toast.error( 'Delete failed' );
    };

    const resumableUpload = async () => {
        if ( !mmFile ) { toast.error( 'Pick a file first' ); return; }
        setBusy( true );
        setMmProgress( 'Starting session…' );
        try
        {
            const s = await api.startResumableMediaSession( mmFile.name, mmFile.type, mmFile.size );
            if ( !s.sessionId ) { toast.error( s.error || 'Session failed' ); return; }
            const buf = new Uint8Array( await mmFile.arrayBuffer() );
            const CHUNK = 256 * 1024;
            for ( let off = 0; off < buf.length; off += CHUNK )
            {
                const slice = buf.subarray( off, Math.min( off + CHUNK, buf.length ) );
                let bin = '';
                for ( let i = 0; i < slice.length; i++ ) bin += String.fromCharCode( slice[ i ] );
                const res = await api.uploadResumableChunk( s.sessionId, btoa( bin ) );
                setMmProgress( `Uploaded ${res.received || 0}/${mmFile.size} bytes` );
                if ( res.error ) { toast.error( res.error ); return; }
            }
            const fin = await api.finishResumableMedia( s.sessionId, { target: mmResumeTarget, phoneId: phone.metaPhoneId } );
            if ( fin.headerHandle ) { setMmProgress( `Done — header handle: ${fin.headerHandle.slice( 0, 24 )}…` ); toast.success( 'Resumable upload complete (handle)' ); }
            else if ( fin.mediaId ) { setMmProgress( `Done — mediaId: ${fin.mediaId}` ); setMmUploadedId( fin.mediaId ); toast.success( 'Resumable upload complete (media)' ); }
            else { toast.error( fin.error || 'Finish failed' ); }
        } catch ( e: any ) { toast.error( e?.message || 'Resumable upload failed' ); }
        finally { setBusy( false ); }
    };

    // ── flow admin helpers ──
    const submitFlowAsset = async () => {
        if ( !faFlowId.trim() ) { toast.error( 'Flow ID required' ); return; }
        let parsed: any;
        try { parsed = JSON.parse( faFlowJson ); } catch { toast.error( 'Flow JSON is invalid' ); return; }
        setBusy( true );
        try { setFaAssetResult( await api.uploadFlowAsset( faFlowId.trim(), parsed, { wabaId: phone.wabaId } ) ); }
        catch ( e: any ) { toast.error( e?.message || 'Asset upload failed' ); }
        finally { setBusy( false ); }
    };

    const runMigrate = async () => {
        setBusy( true );
        try { setFaMigrateResult( await api.migrateFlows( faSourceWaba, faDestWaba ) ); }
        catch ( e: any ) { toast.error( e?.message || 'Migrate failed' ); }
        finally { setBusy( false ); }
    };

    const runSync = async () => {
        setBusy( true );
        try
        {
            const r = await api.syncFlows( faSyncWaba );
            setFaSyncResult( r );
            if ( r.success ) toast.success( `Synced ${r.synced}/${r.total} flows` );
            else toast.error( ( r.error && ( r.error.message || JSON.stringify( r.error ) ) ) || 'Sync failed' );
        } catch ( e: any ) { toast.error( e?.message || 'Sync failed' ); }
        finally { setBusy( false ); }
    };

    const content = (
        <div style={ { maxWidth: 820, margin: '0 auto', padding: 16 } }>
            <SEO title="WhatsApp Send Test Console" description="Send live WhatsApp test messages and validate templates/TTL." noindex />
            <h1 style={ { fontSize: 22, fontWeight: 700, marginBottom: 4 } }>Send Test Console</h1>
            <p style={ { color: '#777', fontSize: 13, marginBottom: 16 } }>Send live test messages and validate templates/TTL against the deployed WhatsApp Business API.</p>

            <div style={ card }>
                <div style={ { display: 'flex', gap: 16, flexWrap: 'wrap' } }>
                    <div style={ { flex: 1, minWidth: 220 } }>
                        <div style={ label }>From (phone)</div>
                        <Select ariaLabel="From (phone)" value={ String( phoneIdx ) }
                            onChange={ v => setPhoneIdx( Number( v ) ) }
                            options={ PHONE_OPTIONS } style={ selectLayout } />
                    </div>
                    <div style={ { flex: 1, minWidth: 220 } }>
                        <div style={ label }>To (E.164, no +)</div>
                        <input style={ input } value={ to } onChange={ e => setTo( e.target.value ) } placeholder="919900000000" />
                    </div>
                </div>
            </div>

            <div style={ { display: 'flex', gap: 4, borderBottom: '1px solid #e5e5e5', marginBottom: 16 } }>
                { ( [ 'text', 'template', 'media', 'product', 'flow', 'tools', 'mediamgmt', 'flowadmin' ] as SendTab[] ).map( t => (
                    <button key={ t } style={ tabBtn( tab === t ) } onClick={ () => setTab( t ) }>{ t === 'mediamgmt' ? 'Media Mgmt' : t === 'flowadmin' ? 'Flow Admin' : t[ 0 ].toUpperCase() + t.slice( 1 ) }</button>
                ) ) }
            </div>

            { tab === 'text' && (
                <div style={ card }>
                    <div style={ label }>Message text</div>
                    <textarea style={ { ...input, minHeight: 90 } } value={ text } onChange={ e => setText( e.target.value ) } placeholder="Hello from WECARE.DIGITAL" />
                    <button style={ btn } disabled={ busy } onClick={ sendText }>Send text</button>
                </div>
            ) }

            { tab === 'template' && (
                <div style={ card }>
                    <div style={ label }>Template name</div>
                    <input style={ input } value={ tplName } onChange={ e => setTplName( e.target.value ) } placeholder="order_confirmation" />
                    <div style={ label }>Language code</div>
                    <input style={ input } value={ tplLang } onChange={ e => setTplLang( e.target.value ) } placeholder="en" />
                    <button style={ btn } disabled={ busy } onClick={ sendTpl }>Send template</button>
                </div>
            ) }

            { tab === 'media' && (
                <div style={ card }>
                    <div style={ label }>Media type</div>
                    <Select ariaLabel="Media type" value={ mediaType }
                        onChange={ v => setMediaType( v as any ) }
                        options={ MEDIA_TYPE_OPTIONS } style={ selectLayout } />
                    <div style={ label }>Media URL (public)</div>
                    <input style={ input } value={ mediaUrl } onChange={ e => setMediaUrl( e.target.value ) } placeholder="https://wecare.digital/get/o/stream/media/..." />
                    <div style={ label }>Caption (image/video/document)</div>
                    <input style={ input } value={ caption } onChange={ e => setCaption( e.target.value ) } />
                    <button style={ btn } disabled={ busy } onClick={ sendMedia }>Send media</button>
                </div>
            ) }

            { tab === 'product' && (
                <ProductMessageComposer
                    phoneNumberId={ phone.metaPhoneId }
                    recipient={ to }
                    onSent={ () => toast.success( 'Product message sent' ) }
                    onError={ ( m ) => toast.error( m ) }
                />
            ) }

            { tab === 'flow' && (
                <div style={ card }>
                    <div style={ label }>Flow name</div>
                    <input style={ input } value={ flowName } onChange={ e => setFlowName( e.target.value ) } placeholder="lead-generation-flow" />
                    <div style={ { display: 'flex', gap: 12 } }>
                        <div style={ { flex: 1 } }>
                            <div style={ label }>Initial screen</div>
                            <input style={ input } value={ flowScreen } onChange={ e => setFlowScreen( e.target.value ) } />
                        </div>
                        <div style={ { flex: 1 } }>
                            <div style={ label }>Mode</div>
                            <Select ariaLabel="Mode" value={ flowMode }
                                onChange={ v => setFlowMode( v as any ) }
                                options={ FLOW_MODE_OPTIONS } style={ selectLayout } />
                        </div>
                    </div>
                    <div style={ label }>CTA label</div>
                    <input style={ input } value={ flowCta } onChange={ e => setFlowCta( e.target.value ) } />
                    <div style={ label }>Body text</div>
                    <input style={ input } value={ flowBody } onChange={ e => setFlowBody( e.target.value ) } />
                    <button style={ btn } disabled={ busy } onClick={ sendFlow }>Send flow</button>
                </div>
            ) }

            { tab === 'tools' && (
                <>
                    <div style={ card }>
                        <h3 style={ { marginTop: 0, fontSize: 15 } }>Template TTL</h3>
                        { ttlRules && (
                            <div style={ { fontSize: 12, color: '#666', marginBottom: 8 } }>
                                { Object.entries( ttlRules.categories ).map( ( [ c, r ] ) => <div key={ c }>{ r.description }</div> ) }
                            </div>
                        ) }
                        <div style={ { display: 'flex', gap: 12 } }>
                            <div style={ { flex: 1 } }>
                                <div style={ label }>Category</div>
                                <Select ariaLabel="Category" value={ ttlCategory }
                                    onChange={ v => setTtlCategory( v ) }
                                    options={ TTL_CATEGORY_OPTIONS } style={ selectLayout } />
                            </div>
                            <div style={ { flex: 1 } }>
                                <div style={ label }>TTL seconds (-1 = 30 days)</div>
                                <input style={ input } type="number" value={ ttlSeconds } onChange={ e => setTtlSeconds( Number( e.target.value ) ) } />
                            </div>
                        </div>
                        <button style={ btn } onClick={ runValidateTtl }>Validate TTL</button>
                        { ttlResult && (
                            <div style={ { marginTop: 10, fontSize: 13, color: ttlResult.ok ? '#1a3a2a' : '#a11' } }>
                                { ttlResult.ok ? `Valid — ${ttlResult.human}` : ttlResult.error }
                                { ttlResult.warnings?.map( ( w, i ) => <div key={ i } style={ { color: '#a60' } }>{ w }</div> ) }
                            </div>
                        ) }
                    </div>

                    <div style={ card }>
                        <h3 style={ { marginTop: 0, fontSize: 15 } }>Template validation</h3>
                        <div style={ { fontSize: 12, color: '#666', marginBottom: 8 } }>
                            Presets:{ ' ' }
                            { presets.map( p => (
                                <button key={ p.name } onClick={ () => loadPreset( p.name ) } style={ { ...btn, padding: '3px 8px', fontSize: 11, marginRight: 6, background: '#444' } }>{ p.name }{ p.hasFlowButton ? ' (flow)' : '' }</button>
                            ) ) }
                        </div>
                        <textarea style={ { ...input, minHeight: 140, fontFamily: 'monospace', fontSize: 12 } } value={ validateJson } onChange={ e => setValidateJson( e.target.value ) } placeholder='{"name":"order_ok","language":"en","category":"UTILITY","components":[...]}' />
                        <button style={ btn } onClick={ runValidateTemplate }>Validate template</button>
                        { validateResult && (
                            <div style={ { marginTop: 10, fontSize: 13 } }>
                                <div style={ { color: validateResult.ok ? '#1a3a2a' : '#a11', fontWeight: 600 } }>{ validateResult.ok ? 'Valid' : 'Invalid' }</div>
                                { validateResult.errors?.map( ( e, i ) => <div key={ i } style={ { color: '#a11' } }>• { e }</div> ) }
                                { validateResult.warnings?.map( ( w, i ) => <div key={ i } style={ { color: '#a60' } }>⚠ { w }</div> ) }
                            </div>
                        ) }
                    </div>
                </>
            ) }

            { tab === 'mediamgmt' && (
                <>
                    <div style={ card }>
                        <h3 style={ { marginTop: 0, fontSize: 15 } }>Upload media (single request)</h3>
                        <input style={ input } type="file" onChange={ e => setMmFile( e.target.files?.[ 0 ] || null ) } />
                        <button style={ btn } disabled={ busy } onClick={ uploadMedia }>Upload</button>
                        { mmUploadedId && <div style={ { marginTop: 8, fontSize: 12, color: '#1a3a2a' } }>Media ID: { mmUploadedId }</div> }
                    </div>

                    <div style={ card }>
                        <h3 style={ { marginTop: 0, fontSize: 15 } }>Resumable upload (chunked)</h3>
                        <p style={ { fontSize: 12, color: '#777', marginTop: 0 } }>Uses the same file picked above. Sends 256KB chunks then finishes.</p>
                        <div style={ label }>Finish as</div>
                        <Select ariaLabel="Finish as" value={ mmResumeTarget }
                            onChange={ v => setMmResumeTarget( v as any ) }
                            options={ RESUME_TARGET_OPTIONS } style={ selectLayout } />
                        <button style={ btn } disabled={ busy } onClick={ resumableUpload }>Start resumable upload</button>
                        { mmProgress && <div style={ { marginTop: 8, fontSize: 12, color: '#444' } }>{ mmProgress }</div> }
                    </div>

                    <div style={ card }>
                        <h3 style={ { marginTop: 0, fontSize: 15 } }>Lookup / delete media</h3>
                        <div style={ label }>Media ID</div>
                        <input style={ input } value={ mmLookupId } onChange={ e => setMmLookupId( e.target.value ) } placeholder="media id" />
                        <div style={ { display: 'flex', gap: 8 } }>
                            <button style={ btn } onClick={ lookupMedia }>Get info</button>
                            <button style={ { ...btn, background: '#7a1a1a' } } onClick={ removeMedia }>Delete</button>
                        </div>
                        { mmInfo && (
                            <div style={ { marginTop: 10, fontSize: 12, color: '#444' } }>
                                <div>MIME: { mmInfo.mimeType } · { mmInfo.fileSize } bytes</div>
                                <div>URL (masked): { mmInfo.url }</div>
                                <div>Expires in: { mmInfo.urlExpiresInSeconds }s</div>
                                { mmInfo.downloadUrl && <div><a href={ mmInfo.downloadUrl } target="_blank" rel="noreferrer">Download (S3, 1h)</a></div> }
                            </div>
                        ) }
                    </div>
                </>
            ) }

            { tab === 'flowadmin' && (
                <>
                    <div style={ card }>
                        <h3 style={ { marginTop: 0, fontSize: 15 } }>Upload flow asset (FLOW_JSON)</h3>
                        <div style={ label }>Flow ID</div>
                        <input style={ input } value={ faFlowId } onChange={ e => setFaFlowId( e.target.value ) } placeholder="Meta flow id" />
                        <div style={ label }>Flow JSON</div>
                        <textarea style={ { ...input, minHeight: 140, fontFamily: 'monospace', fontSize: 12 } } value={ faFlowJson } onChange={ e => setFaFlowJson( e.target.value ) } placeholder='{"version":"7.0","screens":[...]}' />
                        <button style={ btn } disabled={ busy } onClick={ submitFlowAsset }>Upload asset</button>
                        { faAssetResult && (
                            <div style={ { marginTop: 10, fontSize: 13 } }>
                                <div style={ { color: faAssetResult.hasErrors ? '#a11' : '#1a3a2a', fontWeight: 600 } }>{ faAssetResult.hasErrors ? 'Validation errors' : 'Uploaded' }</div>
                                { ( faAssetResult.validationErrors || [] ).map( ( v: any, i: number ) => <div key={ i } style={ { color: '#a11' } }>• { typeof v === 'string' ? v : JSON.stringify( v ) }</div> ) }
                            </div>
                        ) }
                    </div>

                    <div style={ card }>
                        <h3 style={ { marginTop: 0, fontSize: 15 } }>Migrate flows between WABAs</h3>
                        <div style={ { display: 'flex', gap: 12 } }>
                            <div style={ { flex: 1 } }>
                                <div style={ label }>Source WABA ID</div>
                                <input style={ input } value={ faSourceWaba } onChange={ e => setFaSourceWaba( e.target.value ) } />
                            </div>
                            <div style={ { flex: 1 } }>
                                <div style={ label }>Dest WABA ID</div>
                                <input style={ input } value={ faDestWaba } onChange={ e => setFaDestWaba( e.target.value ) } />
                            </div>
                        </div>
                        <button style={ btn } disabled={ busy } onClick={ runMigrate }>Migrate</button>
                        { faMigrateResult && (
                            <div style={ { marginTop: 10, fontSize: 13, color: '#444' } }>
                                Migrated: { ( faMigrateResult.migratedFlows || [] ).length } · Failed: { ( faMigrateResult.failedFlows || [] ).length }
                            </div>
                        ) }
                    </div>

                    <div style={ card }>
                        <h3 style={ { marginTop: 0, fontSize: 15 } }>Sync flows into registry</h3>
                        <div style={ label }>WABA ID</div>
                        <input style={ input } value={ faSyncWaba } onChange={ e => setFaSyncWaba( e.target.value ) } />
                        <button style={ btn } disabled={ busy } onClick={ runSync }>Sync from Meta</button>
                        { faSyncResult && faSyncResult.success && (
                            <div style={ { marginTop: 10, fontSize: 13, color: '#1a3a2a' } }>Synced { faSyncResult.synced }/{ faSyncResult.total } flows</div>
                        ) }
                    </div>
                </>
            ) }
        </div>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default SendTestConsole;
