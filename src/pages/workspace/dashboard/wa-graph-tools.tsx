/**
 * WhatsApp Graph Admin Tools
 * One hub for the WhatsApp Business Platform admin modules that proxy the Meta Graph API:
 * Campaign Schedules, Commerce Settings, QR Codes, Conversational Automation,
 * Link Preview Validator, Assigned Users, and AI-Provider Pricing Policy.
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import Spinner from '../../../components/ui/Spinner';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import Select, { type SelectOption } from '../../../components/ui/Select';
import DateTimeField from '../../../components/ui/DateTimeField';
import * as api from '../../../api/client';
import { WHATSAPP_PHONES } from '../../../config/constants';

interface PageProps { signOut?: () => void; user?: any; }

const PHONES = [
    { label: `WABA 1 · ${WHATSAPP_PHONES.primary.name}`, phoneId: WHATSAPP_PHONES.primary.metaPhoneId, wabaId: WHATSAPP_PHONES.primary.wabaId },
    { label: `WABA 2 · ${WHATSAPP_PHONES.secondary.name}`, phoneId: WHATSAPP_PHONES.secondary.metaPhoneId, wabaId: WHATSAPP_PHONES.secondary.wabaId },
];

const TABS = [
    'Schedules', 'Commerce', 'QR Codes', 'Conversational Automation',
    'Link Preview', 'Throughput', 'Direct Send', 'Marketing (MM Lite)', 'Catalog → Flow', 'Assigned Users', 'AI Pricing Policy',
] as const;
type Tab = typeof TABS[ number ];

const card: React.CSSProperties = { border: '1px solid var(--border)', borderRadius: 12, padding: 20, background: 'var(--surface)', marginBottom: 16 };
const input: React.CSSProperties = { width: '100%', padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 8, fontSize: 'var(--text-md)', marginTop: 4 };
const label: React.CSSProperties = { fontSize: 'var(--text-sm)', color: 'var(--text-muted)', display: 'block' };

/* Hoisted option rows. The account list is derived from PHONES so the two cannot drift, and
   its value is the INDEX as a string, which is what `phoneIdx` holds as a number. */
const PHONE_OPTIONS: SelectOption[] = PHONES.map( ( p, i ) => ( { value: String( i ), label: p.label } ) );
const DIRECT_SEND_CATEGORY_OPTIONS: SelectOption[] = [
    { value: 'utility', label: 'utility' },
    { value: 'authentication', label: 'authentication' },
];

/* LAYOUT ONLY - the 320px the account control carried as a flex child, and the `marginTop: 4`
   the `input` object gave the field controls. */
const ACCOUNT_SELECT_STYLE: React.CSSProperties = { flex: '0 0 320px' };
const FIELD_SELECT_STYLE: React.CSSProperties = { marginTop: 4 };

export default function WAGraphTools ( { signOut, user }: PageProps ) {
    const toast = useToastContext();
    const confirm = useConfirm();
    const [ tab, setTab ] = useState<Tab>( 'Schedules' );
    const [ phoneIdx, setPhoneIdx ] = useState( 0 );
    const phone = PHONES[ phoneIdx ];

    return (
        <Layout onSignOut={ signOut } user={ user }>
            <SEO title="WA Graph Tools" description="WhatsApp Business Platform admin tools" />
            <div style={ { padding: 24, maxWidth: 1000 } }>
                <h1 style={ { fontSize: 'var(--h2)', fontWeight: 600, margin: 0 } }>WhatsApp Graph Admin Tools</h1>
                <p style={ { color: 'var(--text-secondary)', marginTop: 8 } }>
                    Manage Meta Graph API features for your WhatsApp Business accounts. All calls run server-side with secure token handling.
                </p>

                {/* Account selector */ }
                <div style={ { ...card, display: 'flex', gap: 16, alignItems: 'center' } }>
                    { /* The `label` caption is UNASSOCIATED - no `for`, no wrapped control - so it
                         was never a name source. It stays and the control takes `ariaLabel`.
                         `phoneIdx` is a NUMBER in state, so the option value is that index as a
                         string and `Number( v )` does the conversion the native handler already
                         did: `value` is always a string in this contract and the state shape is
                         unchanged. */ }
                    <label style={ label }>Account</label>
                    <Select ariaLabel="Account" value={ String( phoneIdx ) }
                        onChange={ v => setPhoneIdx( Number( v ) ) }
                        options={ PHONE_OPTIONS } style={ ACCOUNT_SELECT_STYLE } />
                    <span style={ { color: 'var(--text-muted)', fontSize: 'var(--text-sm)' } }>
                        phoneId { phone.phoneId } · wabaId { phone.wabaId }
                    </span>
                </div>

                {/* Tabs */ }
                <div style={ { display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 } }>
                    { TABS.map( t => (
                        <button key={ t } onClick={ () => setTab( t ) } style={ {
                            padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
                            border: `1px solid ${tab === t ? 'var(--accent)' : 'var(--border)'}`,
                            background: tab === t ? 'var(--accent-light, #eef2ff)' : 'var(--bg-secondary)',
                            fontWeight: tab === t ? 600 : 400, fontSize: 'var(--text-sm)',
                        } }>{ t }</button>
                    ) ) }
                </div>

                { tab === 'Schedules' && <SchedulesTab wabaId={ phone.wabaId } toast={ toast } /> }
                { tab === 'Commerce' && <CommerceTab phoneId={ phone.phoneId } toast={ toast } /> }
                { tab === 'QR Codes' && <QrTab phoneId={ phone.phoneId } toast={ toast } confirm={ confirm } /> }
                { tab === 'Conversational Automation' && <ConvAutomationTab phoneId={ phone.phoneId } toast={ toast } /> }
                { tab === 'Link Preview' && <LinkPreviewTab toast={ toast } /> }
                { tab === 'Throughput' && <ThroughputTab phoneId={ phone.phoneId } toast={ toast } /> }
                { tab === 'Direct Send' && <DirectSendTab phoneId={ phone.phoneId } wabaId={ phone.wabaId } toast={ toast } /> }
                { tab === 'Marketing (MM Lite)' && <MarketingTab phoneId={ phone.phoneId } wabaId={ phone.wabaId } toast={ toast } /> }
                { tab === 'Catalog → Flow' && <CatalogFlowTab toast={ toast } confirm={ confirm } /> }
                { tab === 'Assigned Users' && <AssignedUsersTab wabaId={ phone.wabaId } toast={ toast } confirm={ confirm } /> }
                { tab === 'AI Pricing Policy' && <AiPolicyTab toast={ toast } confirm={ confirm } /> }
            </div>
        </Layout>
    );
}

// ── Schedules ──
function SchedulesTab ( { wabaId, toast }: { wabaId: string; toast: any } ) {
    const [ rows, setRows ] = useState<api.CampaignSchedule[]>( [] );
    const [ loading, setLoading ] = useState( false );
    const [ form, setForm ] = useState( { hsm_id: '', audience_id: '', waba_cs_id: '', name: '', description: '', delivery_time: '' } );
    const [ saving, setSaving ] = useState( false );

    const load = useCallback( async () => {
        setLoading( true );
        try { setRows( await api.listSchedules( wabaId ) ); }
        catch ( e: any ) { toast.error( e.message || 'Failed to load schedules' ); }
        finally { setLoading( false ); }
    }, [ wabaId, toast ] );
    useEffect( () => { load(); }, [ load ] );

    const create = async () => {
        if ( !form.hsm_id || !form.audience_id || !form.waba_cs_id || !form.name || !form.description || !form.delivery_time )
        {
            toast.error( 'All fields are required' ); return;
        }
        setSaving( true );
        try
        {
            const res = await api.createSchedule( wabaId, { ...form, delivery_time: Math.floor( new Date( form.delivery_time ).getTime() / 1000 ) } );
            if ( res.success ) { toast.success( 'Schedule created' ); setForm( { hsm_id: '', audience_id: '', waba_cs_id: '', name: '', description: '', delivery_time: '' } ); load(); }
            else toast.error( res.error || 'Failed to create schedule' );
        } finally { setSaving( false ); }
    };

    return (
        <div style={ card }>
            <h3>Campaign Schedules</h3>
            { loading ? <Spinner /> : (
                <table style={ { width: '100%', fontSize: 'var(--text-sm)', borderCollapse: 'collapse', marginBottom: 16 } }>
                    <thead><tr style={ { textAlign: 'left', color: 'var(--text-muted)' } }><th>Name</th><th>Delivery</th><th>Status</th></tr></thead>
                    <tbody>
                        { rows.length === 0 && <tr><td colSpan={ 3 } style={ { color: 'var(--text-muted)', padding: 8 } }>No schedules</td></tr> }
                        { rows.map( r => (
                            <tr key={ r.id } style={ { borderTop: '1px solid var(--border-light)' } }>
                                <td style={ { padding: 6 } }>{ r.name }</td>
                                <td>{ r.delivery_time ? new Date( r.delivery_time * 1000 ).toLocaleString() : '—' }</td>
                                <td>{ r.status }</td>
                            </tr>
                        ) ) }
                    </tbody>
                </table>
            ) }
            <h4>Create schedule</h4>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
                { ( [ 'name', 'description', 'hsm_id', 'audience_id', 'waba_cs_id' ] as const ).map( k => (
                    <div key={ k }><label style={ label }>{ k }</label>
                        <input style={ input } value={ ( form as any )[ k ] } onChange={ e => setForm( { ...form, [ k ]: e.target.value } ) } /></div>
                ) ) }
                { /* `delivery_time` is posted verbatim, and DateTimeField emits the same
                     `YYYY-MM-DDTHH:MM` the native control did, so the request body is
                     unchanged. The bare <label> beside it named nothing - no htmlFor, no
                     wrapping - so the field takes the words as its own label and gains an
                     accessible name. `input` was the local appearance style object; the
                     component draws itself from form-controls.css, so only the label's own
                     type style is carried across. */ }
                <DateTimeField label="delivery_time" style={ label } value={ form.delivery_time }
                    onChange={ v => setForm( { ...form, delivery_time: v } ) } />
            </div>
            <div style={ { marginTop: 12 } }><Button variant="primary" onClick={ create } loading={ saving }>Create Schedule</Button></div>
        </div>
    );
}

// ── Commerce ──
function CommerceTab ( { phoneId, toast }: { phoneId: string; toast: any } ) {
    const [ s, setS ] = useState<api.CommerceSettings>( {} );
    const [ loading, setLoading ] = useState( false );
    const [ saving, setSaving ] = useState( false );
    const load = useCallback( async () => {
        setLoading( true );
        try { setS( await api.getCommerceSettings( phoneId ) ); } catch ( e: any ) { toast.error( e.message ); } finally { setLoading( false ); }
    }, [ phoneId, toast ] );
    useEffect( () => { load(); }, [ load ] );
    const save = async () => {
        setSaving( true );
        try
        {
            const res = await api.updateCommerceSettings( phoneId, { is_cart_enabled: !!s.is_cart_enabled, is_catalog_visible: !!s.is_catalog_visible } );
            res.success ? toast.success( 'Commerce settings saved' ) : toast.error( res.error || 'Failed' );
        } finally { setSaving( false ); }
    };
    return (
        <div style={ card }>
            <h3>Commerce Settings</h3>
            { loading ? <Spinner /> : (
                <>
                    <label style={ { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 } }>
                        <input type="checkbox" checked={ !!s.is_cart_enabled } onChange={ e => setS( { ...s, is_cart_enabled: e.target.checked } ) } /> Cart enabled
                    </label>
                    <label style={ { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 } }>
                        <input type="checkbox" checked={ !!s.is_catalog_visible } onChange={ e => setS( { ...s, is_catalog_visible: e.target.checked } ) } /> Catalog visible
                    </label>
                    <Button variant="primary" onClick={ save } loading={ saving }>Save</Button>
                </>
            ) }
        </div>
    );
}

// ── QR Codes ──
function QrTab ( { phoneId, toast, confirm }: { phoneId: string; toast: any; confirm: any } ) {
    const [ rows, setRows ] = useState<api.QrCode[]>( [] );
    const [ loading, setLoading ] = useState( false );
    const [ msg, setMsg ] = useState( '' );
    const [ saving, setSaving ] = useState( false );
    const load = useCallback( async () => {
        setLoading( true );
        try { setRows( await api.listQrCodes( phoneId ) ); } catch ( e: any ) { toast.error( e.message ); } finally { setLoading( false ); }
    }, [ phoneId, toast ] );
    useEffect( () => { load(); }, [ load ] );
    const create = async () => {
        if ( !msg.trim() ) { toast.error( 'Prefilled message required' ); return; }
        setSaving( true );
        try { const r = await api.createQrCode( phoneId, msg.trim() ); r.success ? ( toast.success( 'QR created' ), setMsg( '' ), load() ) : toast.error( r.error || 'Failed' ); }
        finally { setSaving( false ); }
    };
    const del = async ( code: string ) => {
        if ( !( await confirm( { title: 'Delete QR code', message: 'This invalidates the deep link permanently.', danger: true, confirmText: 'Delete' } ) ) ) return;
        const r = await api.deleteQrCode( phoneId, code ); r.success ? ( toast.success( 'Deleted' ), load() ) : toast.error( r.error || 'Failed' );
    };
    return (
        <div style={ card }>
            <h3>Message QR Codes</h3>
            <div style={ { display: 'flex', gap: 8, marginBottom: 16 } }>
                <input style={ { ...input, marginTop: 0 } } placeholder="Prefilled message" value={ msg } onChange={ e => setMsg( e.target.value ) } />
                <Button variant="primary" onClick={ create } loading={ saving }>Create</Button>
            </div>
            { loading ? <Spinner /> : rows.map( q => (
                <div key={ q.code } style={ { display: 'flex', alignItems: 'center', gap: 12, borderTop: '1px solid var(--border-light)', padding: '8px 0' } }>
                    { q.qr_image_url && <img src={ q.qr_image_url } alt="qr" width={ 48 } height={ 48 } /> }
                    <div style={ { flex: 1 } }>
                        <div style={ { fontFamily: 'var(--font-mono)' } }>{ q.code }</div>
                        <div style={ { fontSize: 'var(--text-sm)', color: 'var(--text-muted)' } }>{ q.prefilled_message }</div>
                    </div>
                    <Button variant="danger" size="sm" onClick={ () => del( q.code ) }>Delete</Button>
                </div>
            ) ) }
            { !loading && rows.length === 0 && <p style={ { color: 'var(--text-muted)' } }>No QR codes</p> }
        </div>
    );
}

// ── Conversational Automation ──
function ConvAutomationTab ( { phoneId, toast }: { phoneId: string; toast: any } ) {
    const [ welcome, setWelcome ] = useState( true );
    const [ prompts, setPrompts ] = useState( '' );
    const [ commands, setCommands ] = useState<api.BotCommand[]>( [ { command_name: '', command_description: '' } ] );
    const [ saving, setSaving ] = useState( false );
    const [ loading, setLoading ] = useState( false );

    // Load the LIVE config from Meta so the editor reflects what's actually set.
    const load = useCallback( async () => {
        setLoading( true );
        try
        {
            const ca = await api.getConversationalAutomation( phoneId );
            setWelcome( ca.enable_welcome_message );
            setPrompts( ( ca.prompts || [] ).join( '\n' ) );
            setCommands( ca.commands.length ? ca.commands : [ { command_name: '', command_description: '' } ] );
        } catch ( e: any ) { toast.error( e.message || 'Failed to load current config' ); }
        finally { setLoading( false ); }
    }, [ phoneId, toast ] );
    useEffect( () => { load(); }, [ load ] );

    const save = async () => {
        const promptList = prompts.split( '\n' ).map( p => p.trim() ).filter( Boolean ).slice( 0, 4 );
        const cmds = commands.filter( c => c.command_name && c.command_description );
        setSaving( true );
        try
        {
            const r = await api.configureConversationalAutomation( phoneId, { enable_welcome_message: welcome, prompts: promptList, commands: cmds } );
            r.success ? toast.success( 'Saved' ) : toast.error( r.error || 'Failed' );
        } finally { setSaving( false ); }
    };
    return (
        <div style={ card }>
            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                <h3 style={ { margin: 0 } }>Conversational Automation</h3>
                <Button variant="secondary" size="sm" onClick={ load } loading={ loading }>Reload live config</Button>
            </div>
            <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 } }>
                Commands appear when a user types <b>/</b> in the chat. Ice-breakers show only in a brand-new chat thread. Names are lower-cased and cannot contain emojis.
            </p>
            <label style={ { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, marginTop: 12 } }>
                <input type="checkbox" checked={ welcome } onChange={ e => setWelcome( e.target.checked ) } /> Enable welcome message
            </label>
            <label style={ label }>Ice-breaker prompts (one per line, max 4)</label>
            <textarea style={ { ...input, minHeight: 80 } } value={ prompts } onChange={ e => setPrompts( e.target.value ) } />
            <label style={ { ...label, marginTop: 12 } }>Commands (max 30, unique names)</label>
            { commands.map( ( c, i ) => (
                <div key={ i } style={ { display: 'flex', gap: 8, marginTop: 6 } }>
                    <input style={ { ...input, marginTop: 0 } } placeholder="command_name" value={ c.command_name }
                        onChange={ e => setCommands( commands.map( ( x, j ) => j === i ? { ...x, command_name: e.target.value } : x ) ) } />
                    <input style={ { ...input, marginTop: 0 } } placeholder="description" value={ c.command_description }
                        onChange={ e => setCommands( commands.map( ( x, j ) => j === i ? { ...x, command_description: e.target.value } : x ) ) } />
                </div>
            ) ) }
            <div style={ { marginTop: 8, display: 'flex', gap: 8 } }>
                <Button variant="secondary" size="sm" onClick={ () => setCommands( [ ...commands, { command_name: '', command_description: '' } ] ) } disabled={ commands.length >= 30 }>+ Command</Button>
                <Button variant="primary" onClick={ save } loading={ saving }>Save</Button>
            </div>
        </div>
    );
}

// ── Link Preview ──
function LinkPreviewTab ( { toast }: { toast: any } ) {
    const [ url, setUrl ] = useState( '' );
    const [ result, setResult ] = useState<api.LinkPreviewResult | null>( null );
    const [ loading, setLoading ] = useState( false );
    const check = async () => {
        if ( !url.startsWith( 'http' ) ) { toast.error( 'Enter a valid http(s) URL' ); return; }
        setLoading( true );
        try { setResult( await api.checkLinkPreview( url ) ); } catch ( e: any ) { toast.error( e.message ); } finally { setLoading( false ); }
    };
    return (
        <div style={ card }>
            <h3>Link Preview Validator</h3>
            <div style={ { display: 'flex', gap: 8 } }>
                <input style={ { ...input, marginTop: 0 } } placeholder="https://example.com/page" value={ url } onChange={ e => setUrl( e.target.value ) } />
                <Button variant="primary" onClick={ check } loading={ loading }>Check</Button>
            </div>
            { result && (
                <div style={ { marginTop: 16 } }>
                    <p style={ { fontWeight: 600, color: result.ok ? '#166534' : '#92400e' } }>{ result.ok ? '✓ Looks good for WhatsApp previews' : '⚠ Issues found' }</p>
                    <table style={ { fontSize: 'var(--text-sm)', marginTop: 8 } }>
                        <tbody>{ Object.entries( result.og || {} ).map( ( [ k, v ] ) => (
                            <tr key={ k }><td style={ { color: 'var(--text-muted)', paddingRight: 12 } }>{ k }</td><td>{ v || <em style={ { color: '#b91c1c' } }>missing</em> }</td></tr>
                        ) ) }</tbody>
                    </table>
                    { result.warnings?.length > 0 && (
                        <ul style={ { marginTop: 8, color: '#92400e' } }>{ result.warnings.map( ( w, i ) => <li key={ i }>{ w }</li> ) }</ul>
                    ) }
                    { result.note && <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 8 } }>{ result.note }</p> }
                </div>
            ) }
        </div>
    );
}

// ── Throughput ──
function ThroughputTab ( { phoneId, toast }: { phoneId: string; toast: any } ) {
    const [ info, setInfo ] = useState<api.ThroughputInfo | null>( null );
    const [ loading, setLoading ] = useState( false );
    const load = useCallback( async () => {
        setLoading( true );
        try { setInfo( await api.getThroughput( phoneId ) ); }
        catch ( e: any ) { toast.error( e.message || 'Failed to load throughput' ); }
        finally { setLoading( false ); }
    }, [ phoneId, toast ] );
    useEffect( () => { load(); }, [ load ] );

    const levelLabel: Record<string, string> = {
        STANDARD: 'Standard (80 msg/sec)',
        HIGH: 'High (1,000 msg/sec)',
        NOT_APPLICABLE: 'WhatsApp Business app number (fixed 20 msg/sec)',
    };
    const qualityColor: Record<string, string> = { GREEN: '#166534', YELLOW: '#92400e', RED: '#b91c1c' };

    return (
        <div style={ card }>
            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                <h3 style={ { margin: 0 } }>Throughput &amp; Quality</h3>
                <Button variant="secondary" size="sm" onClick={ load } loading={ loading }>Refresh</Button>
            </div>
            <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 } }>
                Throughput is Meta-managed and auto-upgrades to 1,000 msg/sec when eligible (unlimited messaging limit, 100K+ unique recipients / 24h, quality YELLOW or higher). It cannot be set manually.
            </p>
            { loading && !info ? <Spinner /> : info && (
                <table style={ { fontSize: 'var(--text-sm)', marginTop: 12, width: '100%' } }>
                    <tbody>
                        <tr><td style={ { color: 'var(--text-muted)', paddingRight: 16, padding: '6px 16px 6px 0' } }>Phone</td><td>{ info.displayPhoneNumber || phoneId } { info.verifiedName ? `· ${info.verifiedName}` : '' }</td></tr>
                        <tr><td style={ { color: 'var(--text-muted)', padding: '6px 16px 6px 0' } }>Throughput level</td><td style={ { fontWeight: 600 } }>{ levelLabel[ info.throughputLevel ] || info.throughputLevel || 'Unknown' }</td></tr>
                        <tr><td style={ { color: 'var(--text-muted)', padding: '6px 16px 6px 0' } }>Max messages/sec</td><td>{ info.messagesPerSecond ?? '—' }</td></tr>
                        <tr><td style={ { color: 'var(--text-muted)', padding: '6px 16px 6px 0' } }>Quality rating</td><td style={ { fontWeight: 600, color: qualityColor[ info.qualityRating ] || 'inherit' } }>{ info.qualityRating || '—' }</td></tr>
                        <tr><td style={ { color: 'var(--text-muted)', padding: '6px 16px 6px 0' } }>Status</td><td>{ info.status || '—' }</td></tr>
                        { info.platformType && <tr><td style={ { color: 'var(--text-muted)', padding: '6px 16px 6px 0' } }>Platform</td><td>{ info.platformType }</td></tr> }
                    </tbody>
                </table>
            ) }
        </div>
    );
}

// ── Direct Send (Beta) ──
function DirectSendTab ( { phoneId, wabaId, toast }: { phoneId: string; wabaId: string; toast: any } ) {
    const [ to, setTo ] = useState( '' );
    const [ category, setCategory ] = useState<'utility' | 'authentication'>( 'utility' );
    const [ text, setText ] = useState( '' );
    const [ templateName, setTemplateName ] = useState( '' );
    const [ ttl, setTtl ] = useState( '' );
    const [ sending, setSending ] = useState( false );
    const [ resultMsg, setResultMsg ] = useState<{ ok: boolean; text: string; hint?: string } | null>( null );

    // Onboarding: sample upload + generated templates + MM Lite status
    const [ sampleText, setSampleText ] = useState( '' );
    const [ sampleBusy, setSampleBusy ] = useState( false );
    const [ gen, setGen ] = useState<api.GeneratedTemplate[]>( [] );
    const [ genBusy, setGenBusy ] = useState( false );
    const [ mm, setMm ] = useState<{ onboardingStatus: string; time: string } | null>( null );

    const loadGen = useCallback( async () => {
        setGenBusy( true );
        try { setGen( ( await api.listGeneratedTemplates( wabaId ) ).templates ); }
        catch ( e: any ) { toast.error( e.message || 'Failed to load templates' ); }
        finally { setGenBusy( false ); }
    }, [ wabaId, toast ] );
    const loadMm = useCallback( async () => {
        try { setMm( await api.getMmOnboardingStatus( wabaId ) ); } catch { /* non-fatal */ }
    }, [ wabaId ] );
    useEffect( () => { loadMm(); }, [ loadMm ] );

    const uploadSample = async () => {
        if ( !sampleText.trim() ) { toast.error( 'Enter a sample message' ); return; }
        setSampleBusy( true );
        try
        {
            const r = await api.directSendUploadSample( wabaId, { text: sampleText.trim() } );
            if ( r.success ) toast.success( `Sample accepted · classified ${r.category || '—'}` );
            else toast.error( r.directSendHint || r.error || 'Failed' );
        } finally { setSampleBusy( false ); }
    };

    const send = async () => {
        if ( !to ) { toast.error( 'Recipient phone required' ); return; }
        if ( !text ) { toast.error( 'Message body required' ); return; }
        setSending( true ); setResultMsg( null );
        try
        {
            const r = await api.directSend( phoneId, {
                to, category, text,
                templateName: templateName.trim() || undefined,
                ttlSeconds: ttl ? Number( ttl ) : undefined,
            } );
            if ( r.success ) { setResultMsg( { ok: true, text: 'Sent ✓' } ); toast.success( 'Direct Send accepted' ); }
            else { setResultMsg( { ok: false, text: r.error || 'Failed', hint: r.directSendHint } ); toast.error( r.betaGated ? 'Direct Send not enabled for this WABA' : ( r.error || 'Failed' ) ); }
        } catch ( e: any ) { setResultMsg( { ok: false, text: e.message } ); toast.error( e.message ); }
        finally { setSending( false ); }
    };

    return (
        <div style={ card }>
            <h3 style={ { margin: 0 } }>Direct Send <span style={ { fontSize: 'var(--text-xs)', color: '#92400e', background: '#fef3c7', padding: '2px 8px', borderRadius: 6, marginLeft: 8 } }>BETA</span></h3>
            <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 6 } }>
                Send a utility/authentication message without pre-creating a template — Meta auto-generates the template. Requires this WABA to be onboarded to the Direct Send beta by your Meta representative; until then sends return a beta-gate error (139200 / 131064).
            </p>
            <label style={ label }>Recipient phone (digits or +E.164)</label>
            <input style={ input } placeholder="918100640044" value={ to } onChange={ e => setTo( e.target.value ) } />
            <label style={ { ...label, marginTop: 12 } }>Category</label>
            <Select ariaLabel="Category" value={ category }
                onChange={ v => setCategory( v as any ) }
                options={ DIRECT_SEND_CATEGORY_OPTIONS } style={ FIELD_SELECT_STYLE } />
            <label style={ { ...label, marginTop: 12 } }>Message body (max 1024 chars)</label>
            <textarea style={ { ...input, minHeight: 80 } } maxLength={ 1024 } value={ text } onChange={ e => setText( e.target.value ) } />
            <label style={ { ...label, marginTop: 12 } }>Business template name (optional, utility only — lowercase a-z 0-9 _)</label>
            <input style={ input } placeholder="order_shipment_update" value={ templateName } onChange={ e => setTemplateName( e.target.value ) } />
            <label style={ { ...label, marginTop: 12 } }>TTL seconds (optional, 30–43200)</label>
            <input style={ input } type="number" placeholder="3600" value={ ttl } onChange={ e => setTtl( e.target.value ) } />
            <div style={ { marginTop: 12 } }>
                <Button variant="primary" onClick={ send } loading={ sending }>Send</Button>
            </div>
            { resultMsg && (
                <div style={ { marginTop: 12, fontSize: 'var(--text-sm)' } }>
                    <p style={ { fontWeight: 600, color: resultMsg.ok ? '#166534' : '#b91c1c' } }>{ resultMsg.text }</p>
                    { resultMsg.hint && <p style={ { color: '#92400e', marginTop: 4 } }>{ resultMsg.hint }</p> }
                </div>
            ) }

            {/* Onboarding: sample upload */ }
            <div style={ { marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border-light)' } }>
                <h4 style={ { margin: 0 } }>Onboarding — upload sample</h4>
                <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 } }>
                    Upload 3–4 sample messages you plan to send so Meta classifies the use case (returns UTILITY / MARKETING / AUTHENTICATION) and auto-generates templates.
                </p>
                <textarea style={ { ...input, minHeight: 60 } } placeholder="e.g. Hi {{1}}, your order #{{2}} has shipped." value={ sampleText } onChange={ e => setSampleText( e.target.value ) } />
                <div style={ { marginTop: 8 } }>
                    <Button variant="secondary" size="sm" onClick={ uploadSample } loading={ sampleBusy }>Upload sample</Button>
                </div>
            </div>

            {/* Generated templates */ }
            <div style={ { marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border-light)' } }>
                <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                    <h4 style={ { margin: 0 } }>Auto-generated templates</h4>
                    <Button variant="secondary" size="sm" onClick={ loadGen } loading={ genBusy }>Load</Button>
                </div>
                { gen.length > 0 ? (
                    <table style={ { fontSize: 'var(--text-sm)', marginTop: 8, width: '100%' } }>
                        <tbody>{ gen.map( t => (
                            <tr key={ t.name }><td style={ { fontFamily: 'var(--font-mono)', paddingRight: 12 } }>{ t.name }</td><td style={ { color: 'var(--text-muted)' } }>{ t.category }</td><td style={ { color: t.status === 'APPROVED' ? '#166534' : '#92400e' } }>{ t.status }</td></tr>
                        ) ) }</tbody>
                    </table>
                ) : <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 8 } }>No auto-generated templates loaded. (These appear after Direct Send is active and messages are sent.)</p> }
            </div>

            {/* MM Lite onboarding status */ }
            { mm && (
                <div style={ { marginTop: 16, fontSize: 'var(--text-sm)', color: 'var(--text-muted)' } }>
                    Marketing Messages (MM Lite) onboarding: <b style={ { color: 'var(--text-primary)' } }>{ mm.onboardingStatus || 'unknown' }</b>{ mm.time ? ` · ${mm.time}` : '' }
                </div>
            ) }
        </div>
    );
}

// ── Catalog → Flow mapping ──
function CatalogFlowTab ( { toast, confirm }: { toast: any; confirm: any } ) {
    const [ map, setMap ] = useState<Record<string, api.CatalogFlowEntry>>( {} );
    const [ loading, setLoading ] = useState( false );
    const [ saving, setSaving ] = useState( false );
    const [ form, setForm ] = useState( { retailerId: '', flowIdWaba1: '', flowIdWaba2: '', flowCode: '', cta: 'Complete request', body: 'Payment received! Tap below to complete your request.' } );

    const load = useCallback( async () => {
        setLoading( true );
        try { setMap( await api.getCatalogFlowMap() ); }
        catch ( e: any ) { toast.error( e.message || 'Failed to load mapping' ); }
        finally { setLoading( false ); }
    }, [ toast ] );
    useEffect( () => { load(); }, [ load ] );

    const save = async () => {
        if ( !form.retailerId.trim() ) { toast.error( 'Product retailer_id is required' ); return; }
        if ( !form.flowIdWaba1.trim() && !form.flowIdWaba2.trim() ) { toast.error( 'Enter at least one flow ID' ); return; }
        setSaving( true );
        try
        {
            const r = await api.upsertCatalogFlowMap( form );
            if ( r.success ) { toast.success( 'Mapping saved' ); setMap( r.map || {} ); setForm( { retailerId: '', flowIdWaba1: '', flowIdWaba2: '', flowCode: '', cta: 'Complete request', body: 'Payment received! Tap below to complete your request.' } ); }
            else toast.error( r.error || 'Failed' );
        } finally { setSaving( false ); }
    };

    const edit = ( rid: string, e: api.CatalogFlowEntry ) => setForm( { retailerId: rid, flowIdWaba1: e.flowIdWaba1 || '', flowIdWaba2: e.flowIdWaba2 || '', flowCode: e.flowCode || '', cta: e.cta || 'Complete request', body: e.body || '' } );
    const del = async ( rid: string ) => {
        if ( !( await confirm( { title: 'Remove mapping', message: `Stop opening a flow for ${rid}?`, danger: true, confirmText: 'Remove' } ) ) ) return;
        const r = await api.upsertCatalogFlowMap( { retailerId: rid, delete: true } );
        r.success ? ( toast.success( 'Removed' ), setMap( r.map || {} ) ) : toast.error( r.error || 'Failed' );
    };

    return (
        <div style={ card }>
            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                <h3 style={ { margin: 0 } }>Catalog → Flow Mapping</h3>
                <Button variant="secondary" size="sm" onClick={ load } loading={ loading }>Reload</Button>
            </div>
            <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 6 } }>
                Map a catalog product (retailer_id) to the WhatsApp Flow that opens after the customer pays for it. Each product can open its own flow, per WABA. One flow per payment.
            </p>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 12 } }>
                <div><label style={ label }>Product retailer_id</label><input style={ input } placeholder="WD-SUBMIT-REQ" value={ form.retailerId } onChange={ e => setForm( { ...form, retailerId: e.target.value } ) } /></div>
                <div><label style={ label }>Flow code (optional)</label><input style={ input } placeholder="02.WD_POSTPAY" value={ form.flowCode } onChange={ e => setForm( { ...form, flowCode: e.target.value } ) } /></div>
                <div><label style={ label }>Flow ID — WABA 1</label><input style={ input } placeholder="1018621047428701" value={ form.flowIdWaba1 } onChange={ e => setForm( { ...form, flowIdWaba1: e.target.value } ) } /></div>
                <div><label style={ label }>Flow ID — WABA 2</label><input style={ input } placeholder="1935472957154109" value={ form.flowIdWaba2 } onChange={ e => setForm( { ...form, flowIdWaba2: e.target.value } ) } /></div>
                <div><label style={ label }>Button text (CTA)</label><input style={ input } maxLength={ 20 } value={ form.cta } onChange={ e => setForm( { ...form, cta: e.target.value } ) } /></div>
                <div><label style={ label }>Message body</label><input style={ input } value={ form.body } onChange={ e => setForm( { ...form, body: e.target.value } ) } /></div>
            </div>
            <div style={ { marginTop: 12 } }><Button variant="primary" onClick={ save } loading={ saving }>Save mapping</Button></div>

            <h4 style={ { marginTop: 20, marginBottom: 8 } }>Current mappings</h4>
            { Object.keys( map ).length === 0 ? (
                <p style={ { fontSize: 'var(--text-sm)', color: 'var(--text-muted)' } }>No mappings yet.</p>
            ) : (
                <table style={ { fontSize: 'var(--text-sm)', width: '100%' } }>
                    <thead><tr style={ { textAlign: 'left', color: 'var(--text-muted)' } }><th>Product</th><th>WABA1 flow</th><th>WABA2 flow</th><th></th></tr></thead>
                    <tbody>{ Object.entries( map ).map( ( [ rid, e ] ) => (
                        <tr key={ rid } style={ { borderTop: '1px solid var(--border-light)' } }>
                            <td style={ { fontFamily: 'var(--font-mono)', padding: '6px 8px 6px 0' } }>{ rid }</td>
                            <td style={ { padding: '6px 8px 6px 0' } }>{ e.flowIdWaba1 || '—' }</td>
                            <td style={ { padding: '6px 8px 6px 0' } }>{ e.flowIdWaba2 || '—' }</td>
                            <td><Button variant="ghost" size="sm" onClick={ () => edit( rid, e ) }>Edit</Button> <Button variant="danger" size="sm" onClick={ () => del( rid ) }>Delete</Button></td>
                        </tr>
                    ) ) }</tbody>
                </table>
            ) }
        </div>
    );
}

// ── Marketing (MM Lite) ──
function MarketingTab ( { phoneId, wabaId, toast }: { phoneId: string; wabaId: string; toast: any } ) {
    const [ to, setTo ] = useState( '' );
    const [ templateName, setTemplateName ] = useState( '' );
    const [ language, setLanguage ] = useState( 'en' );
    const [ paramsText, setParamsText ] = useState( '' );
    const [ sharing, setSharing ] = useState( true );
    const [ sending, setSending ] = useState( false );
    const [ mm, setMm ] = useState<{ onboardingStatus: string; time: string } | null>( null );

    const loadMm = useCallback( async () => {
        try { setMm( await api.getMmOnboardingStatus( wabaId ) ); } catch { /* non-fatal */ }
    }, [ wabaId ] );
    useEffect( () => { loadMm(); }, [ loadMm ] );

    const send = async () => {
        if ( !to ) { toast.error( 'Recipient phone required' ); return; }
        if ( !templateName ) { toast.error( 'Approved marketing template name required' ); return; }
        setSending( true );
        try
        {
            const params = paramsText.split( ',' ).map( p => p.trim() ).filter( Boolean );
            const r = await api.sendMarketingMessage( phoneId, { to, templateName, language, params, messageActivitySharing: sharing } );
            r.success ? toast.success( 'Marketing message sent' ) : toast.error( r.error || 'Failed' );
        } finally { setSending( false ); }
    };

    const onboarded = mm?.onboardingStatus === 'ONBOARDED';
    return (
        <div style={ card }>
            <h3 style={ { margin: 0 } }>Marketing Messages (MM Lite)</h3>
            <p style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 6 } }>
                Send optimized marketing template messages over Cloud API. Requires an APPROVED marketing template on this WABA.
                Onboarding status: <b style={ { color: onboarded ? '#166534' : '#92400e' } }>{ mm?.onboardingStatus || '…' }</b>
            </p>
            <label style={ label }>Recipient phone (digits or +E.164)</label>
            <input style={ input } placeholder="918100640044" value={ to } onChange={ e => setTo( e.target.value ) } />
            <label style={ { ...label, marginTop: 12 } }>Marketing template name (APPROVED)</label>
            <input style={ input } placeholder="my_marketing_template" value={ templateName } onChange={ e => setTemplateName( e.target.value ) } />
            <label style={ { ...label, marginTop: 12 } }>Language code</label>
            <input style={ input } placeholder="en or en_US" value={ language } onChange={ e => setLanguage( e.target.value ) } />
            <label style={ { ...label, marginTop: 12 } }>Body parameters (comma-separated, optional)</label>
            <input style={ input } placeholder="John, 30%, WD-123" value={ paramsText } onChange={ e => setParamsText( e.target.value ) } />
            <label style={ { display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 } }>
                <input type="checkbox" checked={ sharing } onChange={ e => setSharing( e.target.checked ) } /> Share message activity with Meta (optimizes delivery)
            </label>
            <div style={ { marginTop: 12 } }>
                <Button variant="primary" onClick={ send } loading={ sending } disabled={ !onboarded }>Send marketing message</Button>
            </div>
        </div>
    );
}

// ── Assigned Users ──
const PERMISSION_TASKS = [ 'MANAGE', 'DEVELOP', 'MANAGE_TEMPLATES', 'MANAGE_PHONE', 'VIEW_COST', 'MANAGE_EXTENSIONS', 'VIEW_PHONE_ASSETS', 'MANAGE_PHONE_ASSETS', 'VIEW_TEMPLATES', 'MESSAGING' ];
function AssignedUsersTab ( { wabaId, toast, confirm }: { wabaId: string; toast: any; confirm: any } ) {
    const [ business, setBusiness ] = useState( '' );
    const [ rows, setRows ] = useState<api.AssignedUser[]>( [] );
    const [ loading, setLoading ] = useState( false );
    const [ newUser, setNewUser ] = useState( '' );
    const [ tasks, setTasks ] = useState<string[]>( [ 'MESSAGING' ] );
    const load = async () => {
        if ( !business ) { toast.error( 'business ID required' ); return; }
        setLoading( true );
        try { const r = await api.listAssignedUsers( wabaId, business ); setRows( r.users ); } catch ( e: any ) { toast.error( e.message ); } finally { setLoading( false ); }
    };
    const add = async () => {
        if ( !newUser ) { toast.error( 'user ID required' ); return; }
        const r = await api.addAssignedUser( wabaId, newUser, tasks ); r.success ? ( toast.success( 'User added' ), setNewUser( '' ), load() ) : toast.error( r.error || 'Failed' );
    };
    const remove = async ( uid: string ) => {
        if ( !( await confirm( { title: 'Remove user', message: 'Revoke all access for this user?', danger: true, confirmText: 'Remove' } ) ) ) return;
        const r = await api.removeAssignedUser( wabaId, uid ); r.success ? ( toast.success( 'Removed' ), load() ) : toast.error( r.error || 'Failed' );
    };
    return (
        <div style={ card }>
            <h3>Assigned Users</h3>
            <div style={ { display: 'flex', gap: 8, marginBottom: 12 } }>
                <input style={ { ...input, marginTop: 0 } } placeholder="Business ID" value={ business } onChange={ e => setBusiness( e.target.value ) } />
                <Button variant="secondary" onClick={ load } loading={ loading }>Load</Button>
            </div>
            { rows.map( u => (
                <div key={ u.id } style={ { display: 'flex', alignItems: 'center', gap: 12, borderTop: '1px solid var(--border-light)', padding: '8px 0' } }>
                    <div style={ { flex: 1 } }>{ u.name } <span style={ { color: 'var(--text-muted)' } }>· { u.id } · { u.user_type }</span></div>
                    <Button variant="danger" size="sm" onClick={ () => remove( u.id ) }>Remove</Button>
                </div>
            ) ) }
            <h4 style={ { marginTop: 16 } }>Add user</h4>
            <input style={ input } placeholder="Facebook user ID" value={ newUser } onChange={ e => setNewUser( e.target.value ) } />
            <div style={ { display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0' } }>
                { PERMISSION_TASKS.map( t => (
                    <button key={ t } onClick={ () => setTasks( tasks.includes( t ) ? tasks.filter( x => x !== t ) : [ ...tasks, t ] ) } style={ {
                        padding: '2px 10px', borderRadius: 6, fontSize: 'var(--text-xs)', cursor: 'pointer',
                        border: `1px solid ${tasks.includes( t ) ? 'var(--accent)' : 'var(--border)'}`,
                        background: tasks.includes( t ) ? 'var(--accent-light, #eef2ff)' : 'var(--bg-secondary)',
                    } }>{ t }</button>
                ) ) }
            </div>
            <Button variant="primary" onClick={ add }>Add User</Button>
        </div>
    );
}

// ── AI Pricing Policy ──
function AiPolicyTab ( { toast, confirm }: { toast: any; confirm: any } ) {
    const [ markets, setMarkets ] = useState<api.AiPolicyMarket[]>( [] );
    const [ meta, setMeta ] = useState( { activeCount: 0, analyticsPricingCategory: 'AI_BOT', webhookPricingCategory: 'general_purpose_ai' } );
    const [ loading, setLoading ] = useState( false );
    const [ form, setForm ] = useState<api.AiPolicyMarket>( { countryCode: '', country: '', effectiveDate: '', active: false, note: '' } );
    const load = useCallback( async () => {
        setLoading( true );
        try { const r = await api.listAiPolicyMarkets(); setMarkets( r.markets ); setMeta( { activeCount: r.activeCount, analyticsPricingCategory: r.analyticsPricingCategory, webhookPricingCategory: r.webhookPricingCategory } ); }
        catch ( e: any ) { toast.error( e.message ); } finally { setLoading( false ); }
    }, [ toast ] );
    useEffect( () => { load(); }, [ load ] );
    const save = async () => {
        if ( !form.countryCode ) { toast.error( 'countryCode required' ); return; }
        const r = await api.upsertAiPolicyMarket( form ); r.success ? ( toast.success( 'Saved' ), setForm( { countryCode: '', country: '', effectiveDate: '', active: false, note: '' } ), load() ) : toast.error( r.error || 'Failed' );
    };
    const del = async ( cc: string ) => {
        if ( !( await confirm( { title: 'Delete market', message: `Remove ${cc}?`, danger: true, confirmText: 'Delete' } ) ) ) return;
        const r = await api.deleteAiPolicyMarket( cc ); r.success ? ( toast.success( 'Deleted' ), load() ) : toast.error( r.error || 'Failed' );
    };
    return (
        <div style={ card }>
            <h3>AI-Provider Pricing Policy</h3>
            <p style={ { fontSize: 'var(--text-sm)', color: 'var(--text-muted)' } }>
                Markets where non-template AI-Provider messages are billable. Analytics category <code>{ meta.analyticsPricingCategory }</code>,
                webhook category <code>{ meta.webhookPricingCategory }</code>. Active markets: <b>{ meta.activeCount }</b>. Rates are imported separately (CSV/PDF), not stored here.
            </p>
            { loading ? <Spinner /> : (
                <table style={ { width: '100%', fontSize: 'var(--text-sm)', borderCollapse: 'collapse', margin: '12px 0' } }>
                    <thead><tr style={ { textAlign: 'left', color: 'var(--text-muted)' } }><th>Code</th><th>Country</th><th>Effective</th><th>Active</th><th></th></tr></thead>
                    <tbody>{ markets.map( m => (
                        <tr key={ m.countryCode } style={ { borderTop: '1px solid var(--border-light)' } }>
                            <td style={ { padding: 6, fontFamily: 'var(--font-mono)' } }>{ m.countryCode }</td>
                            <td>{ m.country }</td><td>{ m.effectiveDate }</td>
                            <td>{ m.active ? '✅' : '—' }</td>
                            <td><Button variant="ghost" size="sm" onClick={ () => del( m.countryCode ) }>✕</Button></td>
                        </tr>
                    ) ) }</tbody>
                </table>
            ) }
            <h4>Add / update market</h4>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 } }>
                <div><label style={ label }>countryCode</label><input style={ input } placeholder="+55" value={ form.countryCode } onChange={ e => setForm( { ...form, countryCode: e.target.value } ) } /></div>
                <div><label style={ label }>country</label><input style={ input } value={ form.country } onChange={ e => setForm( { ...form, country: e.target.value } ) } /></div>
                <div><label style={ label }>effectiveDate</label><input style={ input } placeholder="2026-03-11" value={ form.effectiveDate } onChange={ e => setForm( { ...form, effectiveDate: e.target.value } ) } /></div>
            </div>
            <label style={ { display: 'flex', gap: 8, alignItems: 'center', margin: '10px 0' } }>
                <input type="checkbox" checked={ !!form.active } onChange={ e => setForm( { ...form, active: e.target.checked } ) } /> Active (billable)
            </label>
            <Button variant="primary" onClick={ save }>Save Market</Button>
        </div>
    );
}
