/**
 * Meta Business AI Agent — management console
 * Control where the AI's answers come from and how it behaves:
 *   - Status & Settings (enable/disable, audience, handoff, follow-up)
 *   - Business Info (structured knowledge)
 *   - FAQs (authored Q&A — the answers the AI gives)
 *   - Allowlist (controlled rollout)
 * Backend: POST ${API_BASE}/meta-agent  (wecare-meta-business-agent)
 */

import React, { useState, useEffect, useCallback } from 'react';
import * as api from '../../../../api/client';
import { API_BASE } from '../../../../config/constants';
import { useToastContext } from '../../../../contexts/ToastContext';
import Spinner from '../../../../components/ui/Spinner';
import MaybeLayout from '../../../../components/MaybeLayout';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

type WabaKey = api.WabaKey;
type Tab = 'settings' | 'business' | 'faqs' | 'skills' | 'websites' | 'allowlist' | 'routing' | 'connectors' | 'techprovider';

const WABAS: { key: WabaKey; label: string }[] = [
    { key: 'WABA1', label: 'WABA1 · WECARE.DIGITAL (+91 93309 94400)' },
    { key: 'WABA2', label: 'WABA2 · Manish Agarwal (+91 99033 00044)' },
];
const INTERVALS = [ 0, 300, 900, 1800, 3600, 7200, 28800, 86400 ];
const intervalLabel = ( s: number ) =>
    s === 0 ? 'Off' : s < 3600 ? `${s / 60} min` : s < 86400 ? `${s / 3600} hr` : '1 day';

const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 20, marginBottom: 16 };
const label: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: '#6b7280', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em' };
const input: React.CSSProperties = { width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, marginBottom: 12 };
const btn = ( bg: string ): React.CSSProperties => ( { padding: '8px 16px', background: bg, color: '#fff', border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer' } );

const WABA_OPTIONS: SelectOption[] = WABAS.map( w => ( { value: w.key, label: w.label } ) );
const AUDIENCE_OPTIONS: SelectOption[] = [
    { value: 'EVERYONE', label: 'Everyone' },
    { value: 'ALLOWLISTED_ONLY', label: 'Allowlisted only' },
];
/** The interval is a NUMBER in state, so the option value is that number as a string. */
const INTERVAL_OPTIONS: SelectOption[] = INTERVALS.map( s => ( { value: String( s ), label: intervalLabel( s ) } ) );
const AUTH_TYPE_OPTIONS: SelectOption[] = [
    { value: 'API_KEY', label: 'API_KEY (header)' },
    { value: 'NONE', label: 'NONE' },
];
/* Layout only. The WABA picker and the two settings rows are flex children, so they need a
   size: the native control sized itself to its widest option, while the trigger shows the
   selected one and would otherwise collapse. */
const WABA_SELECT_STYLE: React.CSSProperties = { flex: '0 1 300px', minWidth: 0 };
const ROW_SELECT_STYLE: React.CSSProperties = { flex: '0 0 200px' };
/** The marginBottom the shared `input` object carried. */
const FIELD_SELECT_STYLE: React.CSSProperties = { marginBottom: 12 };

const pillBase: React.CSSProperties = { fontSize: 12, fontWeight: 600, padding: '3px 10px', borderRadius: 999, whiteSpace: 'nowrap' };
const Pill = ( { ok, okText, badText }: { ok: boolean; okText: string; badText: string } ) => (
    <span style={ { ...pillBase, background: ok ? '#ecfdf5' : '#fef2f2', color: ok ? '#047857' : '#b91c1c' } }>{ ok ? okText : badText }</span>
);

type TabBtnProps = { id: Tab; active: boolean; onSelect: ( id: Tab ) => void; children: React.ReactNode };
const TabBtn = ( { id, active, onSelect, children }: TabBtnProps ) => (
    <button onClick={ () => onSelect( id ) } style={ {
        padding: '8px 14px', border: 'none', borderBottom: active ? '2px solid #059669' : '2px solid transparent',
        background: 'none', color: active ? '#059669' : '#6b7280', fontWeight: 600, fontSize: 14, cursor: 'pointer',
    } }>{ children }</button>
);

function AiAgentPageBody ( { }: PageProps ) {
    const toast = useToastContext();
    const [ waba, setWaba ] = useState<WabaKey>( 'WABA1' );
    const [ tab, setTab ] = useState<Tab>( 'settings' );

    // Settings + eligibility
    const [ eligible, setEligible ] = useState<boolean | null>( null );
    const [ settings, setSettings ] = useState<api.AgentSettings | null>( null );
    const [ settingsLoading, setSettingsLoading ] = useState( false );
    const [ saving, setSaving ] = useState( false );

    // Business info
    const [ info, setInfo ] = useState<api.AgentBusinessInfo>( {} );
    const [ infoLoading, setInfoLoading ] = useState( false );

    // FAQs
    const [ faqs, setFaqs ] = useState<api.AgentFaq[]>( [] );
    const [ faqsLoading, setFaqsLoading ] = useState( false );
    const [ newQ, setNewQ ] = useState( '' );
    const [ newA, setNewA ] = useState( '' );

    // Routing (bot vs AI) — shared across WABAs
    const [ routing, setRouting ] = useState<api.AiRoutingConfig | null>( null );
    const [ routingLoading, setRoutingLoading ] = useState( false );
    const [ rKeywords, setRKeywords ] = useState( '' );
    const [ rContains, setRContains ] = useState( '' );

    // Skills
    const [ skills, setSkills ] = useState<api.AgentSkill[]>( [] );
    const [ skillsLoading, setSkillsLoading ] = useState( false );
    const [ skTitle, setSkTitle ] = useState( '' );
    const [ skDesc, setSkDesc ] = useState( '' );
    const [ skBody, setSkBody ] = useState( '' );

    // Websites
    const [ sites, setSites ] = useState<api.AgentWebsite[]>( [] );
    const [ sitesLoading, setSitesLoading ] = useState( false );
    const [ newUrl, setNewUrl ] = useState( '' );

    // Allowlist
    const [ allow, setAllow ] = useState<api.AgentAllowlistEntry[]>( [] );
    const [ allowLoading, setAllowLoading ] = useState( false );
    const [ newPhone, setNewPhone ] = useState( '' );

    // Connectors (external APIs the agent can call)
    const [ connectors, setConnectors ] = useState<api.AgentConnector[]>( [] );
    const [ connErr, setConnErr ] = useState<string>( '' );
    const [ connLoading, setConnLoading ] = useState( false );
    const [ cName, setCName ] = useState( 'WECARE_API' );
    const [ cDesc, setCDesc ] = useState( 'WECARE.DIGITAL catalog product lookup' );
    // The custom domain, not the raw execute-api host. The previous default hardcoded
    // the API Gateway id into the browser bundle, and it bypassed wecare.digital/api -
    // so the connector would have been registered against a URL that skips the custom
    // domain mapping and every auth behaviour attached to it.
    const [ cUrl, setCUrl ] = useState( API_BASE );
    const [ cAuth, setCAuth ] = useState<'API_KEY' | 'NONE'>( 'API_KEY' );
    const [ cHeaderName, setCHeaderName ] = useState( 'X-Agent-Token' );
    const [ cHeaderValue, setCHeaderValue ] = useState( '' );

    // Tech Provider panel (both-WABA overview + per-connector logs/tools)
    const [ providers, setProviders ] = useState<api.AgentProviderStatus[]>( [] );
    const [ provLoading, setProvLoading ] = useState( false );
    const [ provDetail, setProvDetail ] = useState<Record<string, { logs?: api.AgentConnectorLogs; tools?: api.AgentTool[]; open?: boolean }>>( {} );

    // ── loaders ──
    const loadSettings = useCallback( async () => {
        setSettingsLoading( true );
        try
        {
            const [ el, st ] = await Promise.all( [ api.aiAgentApi.eligibility( waba ), api.aiAgentApi.getSettings( waba ) ] );
            setEligible( el?.eligibility?.is_eligible ?? null );
            const s = st?.settings;
            setSettings( Array.isArray( s ) ? ( s[ 0 ] ?? null ) : ( s ?? null ) );
        } catch { toast.error( 'Failed to load agent settings' ); }
        finally { setSettingsLoading( false ); }
    }, [ waba, toast ] );

    const loadInfo = useCallback( async () => {
        setInfoLoading( true );
        try { const r = await api.aiAgentApi.getBusinessInfo( waba ); setInfo( r?.business_info ?? {} ); }
        catch { toast.error( 'Failed to load business info' ); }
        finally { setInfoLoading( false ); }
    }, [ waba, toast ] );

    const loadFaqs = useCallback( async () => {
        setFaqsLoading( true );
        try { const r = await api.aiAgentApi.listFaqs( waba ); setFaqs( Array.isArray( r?.faqs ) ? r!.faqs : [] ); }
        catch { toast.error( 'Failed to load FAQs' ); }
        finally { setFaqsLoading( false ); }
    }, [ waba, toast ] );

    const loadAllow = useCallback( async () => {
        setAllowLoading( true );
        try { const r = await api.aiAgentApi.listAllowlist( waba ); setAllow( Array.isArray( r?.allowlist ) ? r!.allowlist : [] ); }
        catch { toast.error( 'Failed to load allowlist' ); }
        finally { setAllowLoading( false ); }
    }, [ waba, toast ] );

    const loadSites = useCallback( async () => {
        setSitesLoading( true );
        try { const r = await api.aiAgentApi.listWebsites( waba ); setSites( Array.isArray( r?.websites ) ? r!.websites : [] ); }
        catch { toast.error( 'Failed to load websites' ); }
        finally { setSitesLoading( false ); }
    }, [ waba, toast ] );

    const loadSkills = useCallback( async () => {
        setSkillsLoading( true );
        try { const r = await api.aiAgentApi.listSkills( waba ); setSkills( Array.isArray( r?.skills ) ? r!.skills : [] ); }
        catch { toast.error( 'Failed to load skills' ); }
        finally { setSkillsLoading( false ); }
    }, [ waba, toast ] );

    const loadRouting = useCallback( async () => {
        setRoutingLoading( true );
        try
        {
            const r = await api.getAiRouting();
            const cfg = r?.routing || null;
            setRouting( cfg );
            setRKeywords( ( cfg?.keywords || [] ).join( ', ' ) );
            setRContains( ( cfg?.contains || [] ).join( ', ' ) );
        } catch { toast.error( 'Failed to load routing' ); }
        finally { setRoutingLoading( false ); }
    }, [ toast ] );

    const loadConnectors = useCallback( async () => {
        setConnLoading( true ); setConnErr( '' );
        try
        {
            const r = await api.aiAgentApi.listConnectors( waba );
            const c = r?.connectors;
            if ( Array.isArray( c ) ) setConnectors( c );
            else { setConnectors( [] ); if ( c && ( c as any ).error ) setConnErr( JSON.stringify( ( c as any ).error ).slice( 0, 300 ) ); }
        } catch { toast.error( 'Failed to load connectors' ); }
        finally { setConnLoading( false ); }
    }, [ waba, toast ] );

    const loadProviders = useCallback( async () => {
        setProvLoading( true );
        try
        {
            const r = await api.aiAgentApi.providerStatus();
            setProviders( Array.isArray( r?.providers ) ? r!.providers : [] );
        } catch { toast.error( 'Failed to load Tech Provider status' ); }
        finally { setProvLoading( false ); }
    }, [ toast ] );

    useEffect( () => {
        if ( tab === 'settings' ) loadSettings();
        else if ( tab === 'business' ) loadInfo();
        else if ( tab === 'faqs' ) loadFaqs();
        else if ( tab === 'skills' ) loadSkills();
        else if ( tab === 'websites' ) loadSites();
        else if ( tab === 'allowlist' ) loadAllow();
        else if ( tab === 'routing' ) loadRouting();
        else if ( tab === 'connectors' ) loadConnectors();
        else if ( tab === 'techprovider' ) loadProviders();
    }, [ tab, waba, loadSettings, loadInfo, loadFaqs, loadSkills, loadSites, loadAllow, loadRouting, loadConnectors, loadProviders ] );

    // ── settings mutators ──
    const saveSettings = async ( patch: Partial<api.AgentSettings> & { enabled?: boolean; aiAudience?: string } ) => {
        setSaving( true );
        try
        {
            const r = await api.aiAgentApi.updateSettings( waba, patch );
            if ( r?.settings ) { setSettings( r.settings ); toast.success( 'Agent settings updated' ); }
            else toast.error( 'Update failed (check terms accepted)' );
        } catch { toast.error( 'Update failed' ); }
        finally { setSaving( false ); }
    };

    const saveRouting = async ( patch: Partial<api.AiRoutingConfig> ) => {
        setSaving( true );
        try
        {
            const r = await api.updateAiRouting( patch );
            if ( r?.routing )
            {
                setRouting( r.routing );
                setRKeywords( ( r.routing.keywords || [] ).join( ', ' ) );
                setRContains( ( r.routing.contains || [] ).join( ', ' ) );
                toast.success( 'Routing updated' );
            } else toast.error( 'Routing update failed' );
        } catch { toast.error( 'Routing update failed' ); }
        finally { setSaving( false ); }
    };

    const enabled = !!settings?.rollout?.enabled;
    const audience = settings?.ai_audience ?? 'EVERYONE';

    return (
        <div style={ { padding: '4px 4px 40px' } }>
            {/* WABA selector + eligibility */ }
            <div style={ { display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' } }>
                <Select ariaLabel="WhatsApp Business Account" value={ waba }
                    onChange={ v => setWaba( v as WabaKey ) }
                    options={ WABA_OPTIONS } style={ WABA_SELECT_STYLE } />
                { eligible !== null && (
                    <span style={ {
                        fontSize: 12, fontWeight: 600, padding: '4px 10px', borderRadius: 10,
                        background: eligible ? '#f0fdf4' : '#fef2f2', color: eligible ? '#059669' : '#dc2626'
                    } }>
                        { eligible ? '● Eligible (terms accepted)' : '● Not eligible — accept AI terms in WhatsApp Manager' }
                    </span>
                ) }
                { enabled && <span style={ { fontSize: 12, fontWeight: 700, padding: '4px 10px', borderRadius: 10, background: '#ecfdf5', color: '#047857' } }>AI ON · { audience }</span> }
            </div>

            <div style={ { borderBottom: '1px solid #e5e7eb', marginBottom: 20, display: 'flex', gap: 4, flexWrap: 'wrap' } }>
                <TabBtn id="settings" active={ tab === 'settings' } onSelect={ setTab }>Status & Settings</TabBtn>
                <TabBtn id="business" active={ tab === 'business' } onSelect={ setTab }>Business Info</TabBtn>
                <TabBtn id="faqs" active={ tab === 'faqs' } onSelect={ setTab }>FAQs</TabBtn>
                <TabBtn id="skills" active={ tab === 'skills' } onSelect={ setTab }>Skills</TabBtn>
                <TabBtn id="websites" active={ tab === 'websites' } onSelect={ setTab }>Websites</TabBtn>
                <TabBtn id="routing" active={ tab === 'routing' } onSelect={ setTab }>Routing (Bot vs AI)</TabBtn>
                <TabBtn id="connectors" active={ tab === 'connectors' } onSelect={ setTab }>Connectors</TabBtn>
                <TabBtn id="techprovider" active={ tab === 'techprovider' } onSelect={ setTab }>Tech Provider</TabBtn>
                <TabBtn id="allowlist" active={ tab === 'allowlist' } onSelect={ setTab }>Allowlist</TabBtn>
            </div>

            {/* ── SETTINGS ── */ }
            { tab === 'settings' && ( settingsLoading ? <Spinner /> : (
                <div style={ card }>
                    <h3 style={ { margin: '0 0 16px', fontSize: 16, color: '#1a1a1a' } }>Agent behaviour</h3>
                    <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #f3f4f6' } }>
                        <div><b>AI responder</b><div style={ { fontSize: 12, color: '#6b7280' } }>When on, the AI answers customers directly.</div></div>
                        <button disabled={ saving } onClick={ () => saveSettings( { enabled: !enabled } ) }
                            style={ btn( enabled ? '#dc2626' : '#059669' ) }>{ enabled ? 'Turn OFF' : 'Turn ON' }</button>
                    </div>
                    <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #f3f4f6' } }>
                        <div><b>Audience</b><div style={ { fontSize: 12, color: '#6b7280' } }>Who the AI replies to.</div></div>
                        <Select ariaLabel="Audience" value={ audience } disabled={ saving }
                            onChange={ v => saveSettings( { aiAudience: v } ) }
                            options={ AUDIENCE_OPTIONS } style={ ROW_SELECT_STYLE } />
                    </div>
                    <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #f3f4f6' } }>
                        <div><b>Handoff to human</b><div style={ { fontSize: 12, color: '#6b7280' } }>{ settings?.handoff?.message || 'Connecting you to our team.' }</div></div>
                        <button disabled={ saving } onClick={ () => saveSettings( { handoff: { enabled: !settings?.handoff?.enabled, message: settings?.handoff?.message || 'Connecting you to our team.' } } ) }
                            style={ btn( settings?.handoff?.enabled ? '#6b7280' : '#059669' ) }>{ settings?.handoff?.enabled ? 'Enabled' : 'Disabled' }</button>
                    </div>
                    <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0' } }>
                        <div><b>Follow-up after inactivity</b></div>
                        <Select ariaLabel="Follow-up after inactivity" disabled={ saving }
                            value={ String( settings?.followup?.followup_interval_in_seconds ?? 0 ) }
                            onChange={ v => saveSettings( { followup: { enabled: Number( v ) > 0, followup_interval_in_seconds: Number( v ) } } ) }
                            options={ INTERVAL_OPTIONS } style={ ROW_SELECT_STYLE } />
                    </div>
                </div>
            ) ) }

            {/* ── BUSINESS INFO ── */ }
            { tab === 'business' && ( infoLoading ? <Spinner /> : (
                <div style={ card }>
                    <h3 style={ { margin: '0 0 16px', fontSize: 16, color: '#1a1a1a' } }>Business info the AI can reference</h3>
                    <label style={ label }>Business description</label>
                    <textarea style={ { ...input, minHeight: 70 } } value={ info.business_description || '' } onChange={ e => setInfo( { ...info, business_description: e.target.value } ) } />
                    <label style={ label }>How to purchase</label>
                    <textarea style={ { ...input, minHeight: 50 } } value={ info.purchase_info || '' } onChange={ e => setInfo( { ...info, purchase_info: e.target.value } ) } />
                    <label style={ label }>Payment method</label>
                    <textarea style={ { ...input, minHeight: 50 } } value={ info.payment_method || '' } onChange={ e => setInfo( { ...info, payment_method: e.target.value } ) } />
                    <label style={ label }>Delivery & shipping</label>
                    <textarea style={ { ...input, minHeight: 50 } } value={ info.delivery_and_shipping || '' } onChange={ e => setInfo( { ...info, delivery_and_shipping: e.target.value } ) } />
                    <label style={ label }>Return policy</label>
                    <textarea style={ { ...input, minHeight: 50 } } value={ info.return_policy || '' } onChange={ e => setInfo( { ...info, return_policy: e.target.value } ) } />
                    <div style={ { display: 'flex', gap: 12 } }>
                        <div style={ { flex: 1 } }><label style={ label }>Contact email</label>
                            <input style={ input } value={ info.contact_info?.email || '' } onChange={ e => setInfo( { ...info, contact_info: { ...info.contact_info, email: e.target.value } } ) } /></div>
                        <div style={ { flex: 1 } }><label style={ label }>Hours</label>
                            <input style={ input } value={ info.contact_info?.hours_of_operation || '' } onChange={ e => setInfo( { ...info, contact_info: { ...info.contact_info, hours_of_operation: e.target.value } } ) } /></div>
                    </div>
                    <label style={ label }>Address</label>
                    <input style={ input } value={ info.contact_info?.address || '' } onChange={ e => setInfo( { ...info, contact_info: { ...info.contact_info, address: e.target.value } } ) } />
                    <button disabled={ saving } onClick={ async () => {
                        setSaving( true );
                        try { const r = await api.aiAgentApi.updateBusinessInfo( waba, info ); if ( r?.business_info ) { setInfo( r.business_info ); toast.success( 'Business info saved' ); } else toast.error( 'Save failed' ); }
                        finally { setSaving( false ); }
                    } } style={ btn( '#059669' ) }>Save business info</button>
                </div>
            ) ) }

            {/* ── FAQs ── */ }
            { tab === 'faqs' && (
                <div>
                    <div style={ card }>
                        <h3 style={ { margin: '0 0 12px', fontSize: 16, color: '#1a1a1a' } }>Add an FAQ (this becomes the AI&apos;s answer)</h3>
                        <label style={ label }>Question (as a customer would ask)</label>
                        <input style={ input } value={ newQ } onChange={ e => setNewQ( e.target.value ) } placeholder="What is your return policy?" />
                        <label style={ label }>Answer (complete & self-contained)</label>
                        <textarea style={ { ...input, minHeight: 70 } } value={ newA } onChange={ e => setNewA( e.target.value ) } />
                        <button disabled={ saving || !newQ.trim() || !newA.trim() } onClick={ async () => {
                            setSaving( true );
                            try { const r = await api.aiAgentApi.createFaq( waba, newQ.trim(), newA.trim() ); if ( r?.faq ) { setNewQ( '' ); setNewA( '' ); toast.success( 'FAQ added' ); loadFaqs(); } else toast.error( 'Add failed' ); }
                            finally { setSaving( false ); }
                        } } style={ btn( '#059669' ) }>Add FAQ</button>
                    </div>
                    { faqsLoading ? <Spinner /> : (
                        <div style={ card }>
                            <h3 style={ { margin: '0 0 12px', fontSize: 16, color: '#1a1a1a' } }>FAQs ({ faqs.length })</h3>
                            { faqs.length === 0 && <div style={ { color: '#9ca3af', fontSize: 14 } }>No FAQs yet.</div> }
                            { faqs.map( f => (
                                <div key={ f.id } style={ { borderBottom: '1px solid #f3f4f6', padding: '10px 0' } }>
                                    <div style={ { fontWeight: 600, color: '#1a1a1a' } }>{ f.question }</div>
                                    <div style={ { fontSize: 13, color: 'rgba(0, 0, 0, 0.54)', margin: '4px 0' } }>{ f.answer }</div>
                                    <button onClick={ async () => {
                                        if ( !f.id ) return;
                                        const ok = await api.aiAgentApi.deleteFaq( waba, f.id );
                                        if ( ok?.deleted ) { toast.success( 'Deleted' ); loadFaqs(); } else toast.error( 'Delete failed' );
                                    } } style={ { ...btn( '#fef2f2' ), color: '#dc2626', padding: '4px 10px', fontSize: 12 } }>Delete</button>
                                </div>
                            ) ) }
                        </div>
                    ) }
                </div>
            ) }

            {/* ── SKILLS ── */ }
            { tab === 'skills' && (
                <div>
                    <div style={ card }>
                        <h3 style={ { margin: '0 0 8px', fontSize: 16, color: '#1a1a1a' } }>Add a skill (behaviour / tone directive)</h3>
                        <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 12px' } }>Skills shape how the AI responds. Title must be lowercase letters, numbers and hyphens (e.g. brand-voice).</p>
                        <label style={ label }>Title (lowercase-hyphen)</label>
                        <input style={ input } value={ skTitle } onChange={ e => setSkTitle( e.target.value ) } placeholder="brand-voice" />
                        <label style={ label }>When to apply (description)</label>
                        <input style={ input } value={ skDesc } onChange={ e => setSkDesc( e.target.value ) } placeholder="Apply to every conversation." />
                        <label style={ label }>Instructions</label>
                        <textarea style={ { ...input, minHeight: 90 } } value={ skBody } onChange={ e => setSkBody( e.target.value ) } placeholder="Reply warmly and concisely..." />
                        <button disabled={ saving || !skTitle.trim() || !skBody.trim() } onClick={ async () => {
                            setSaving( true );
                            try { const r = await api.aiAgentApi.createSkill( waba, skTitle.trim(), skDesc.trim(), skBody.trim() ); if ( r?.skill ) { setSkTitle( '' ); setSkDesc( '' ); setSkBody( '' ); toast.success( 'Skill added' ); loadSkills(); } else toast.error( 'Add failed (title must be lowercase-hyphen)' ); }
                            finally { setSaving( false ); }
                        } } style={ btn( '#059669' ) }>Add skill</button>
                    </div>
                    { skillsLoading ? <Spinner /> : (
                        <div style={ card }>
                            <h3 style={ { margin: '0 0 12px', fontSize: 16, color: '#1a1a1a' } }>Skills ({ skills.length })</h3>
                            { skills.length === 0 && <div style={ { color: '#9ca3af', fontSize: 14 } }>No skills yet.</div> }
                            { skills.map( s => (
                                <div key={ s.id } style={ { borderBottom: '1px solid #f3f4f6', padding: '10px 0' } }>
                                    <div style={ { fontWeight: 600, color: '#1a1a1a' } }>{ s.title || '(untitled)' }</div>
                                    { s.description && <div style={ { fontSize: 12, color: '#9ca3af' } }>{ s.description }</div> }
                                    <div style={ { fontSize: 13, color: 'rgba(0, 0, 0, 0.54)', margin: '4px 0', whiteSpace: 'pre-wrap' } }>{ s.skill }</div>
                                    <button onClick={ async () => {
                                        if ( !s.id ) return;
                                        const ok = await api.aiAgentApi.deleteSkill( waba, s.id );
                                        if ( ok?.deleted ) { toast.success( 'Deleted' ); loadSkills(); } else toast.error( 'Delete failed' );
                                    } } style={ { ...btn( '#fef2f2' ), color: '#dc2626', padding: '4px 10px', fontSize: 12 } }>Delete</button>
                                </div>
                            ) ) }
                        </div>
                    ) }
                </div>
            ) }

            {/* ── WEBSITES ── */ }
            { tab === 'websites' && (
                <div>
                    <div style={ card }>
                        <h3 style={ { margin: '0 0 8px', fontSize: 16, color: '#1a1a1a' } }>Website knowledge sources</h3>
                        <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 12px' } }>The AI crawls these URLs and answers from their content.</p>
                        <div style={ { display: 'flex', gap: 8 } }>
                            <input style={ { ...input, marginBottom: 0 } } value={ newUrl } onChange={ e => setNewUrl( e.target.value ) } placeholder="https://wecare.digital/" />
                            <button disabled={ saving || !newUrl.trim() } onClick={ async () => {
                                setSaving( true );
                                try { const r = await api.aiAgentApi.addWebsite( waba, newUrl.trim() ); if ( r?.website ) { setNewUrl( '' ); toast.success( 'Website added' ); loadSites(); } else toast.error( 'Add failed' ); }
                                finally { setSaving( false ); }
                            } } style={ btn( '#059669' ) }>Add</button>
                        </div>
                    </div>
                    { sitesLoading ? <Spinner /> : (
                        <div style={ card }>
                            { sites.length === 0 && <div style={ { color: '#9ca3af', fontSize: 14 } }>No websites added.</div> }
                            { sites.map( s => (
                                <div key={ s.id } style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #f3f4f6', padding: '8px 0' } }>
                                    <span style={ { fontSize: 13 } }>{ s.url } { s.crawl_status && <span style={ { fontSize: 11, color: '#9ca3af' } }>· { s.crawl_status }</span> }</span>
                                    <button onClick={ async () => {
                                        const ok = await api.aiAgentApi.removeWebsite( waba, s.id );
                                        if ( ok?.deleted ) { toast.success( 'Removed' ); loadSites(); } else toast.error( 'Remove failed' );
                                    } } style={ { ...btn( '#fef2f2' ), color: '#dc2626', padding: '4px 10px', fontSize: 12 } }>Remove</button>
                                </div>
                            ) ) }
                        </div>
                    ) }
                </div>
            ) }

            {/* ── ROUTING (BOT vs AI) ── */ }
            { tab === 'routing' && ( routingLoading ? <Spinner /> : (
                <div style={ card }>
                    <h3 style={ { margin: '0 0 8px', fontSize: 16, color: '#1a1a1a' } }>Bot vs AI routing</h3>
                    <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 16px' } }>
                        When the AI holds a conversation, messages matching these rules are handled by YOUR deterministic
                        bot (menu, flows, catalog, commands). Everything else is answered by the Meta AI. Applies to both WABAs.
                    </p>
                    <div style={ { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 } }>
                        <b>Hybrid routing</b>
                        <button disabled={ saving } onClick={ () => saveRouting( { enabled: !( routing?.enabled ?? true ) } ) }
                            style={ btn( ( routing?.enabled ?? true ) ? '#059669' : '#6b7280' ) }>
                            { ( routing?.enabled ?? true ) ? 'ON (bot handles triggers)' : 'OFF (AI handles everything)' }
                        </button>
                    </div>
                    <label style={ label }>Keyword triggers (exact match, comma-separated)</label>
                    <textarea style={ { ...input, minHeight: 60 } } value={ rKeywords } onChange={ e => setRKeywords( e.target.value ) }
                        placeholder="get started, menu, hi, subscribe" />
                    <label style={ label }>Contains triggers (message contains any, comma-separated)</label>
                    <textarea style={ { ...input, minHeight: 60 } } value={ rContains } onChange={ e => setRContains( e.target.value ) }
                        placeholder="track request, appointment, pay, catalog" />
                    <label style={ label }>Command prefix</label>
                    <input style={ input } value={ routing?.commandPrefix ?? '/' }
                        onChange={ e => setRouting( routing ? { ...routing, commandPrefix: e.target.value } : routing ) } placeholder="/" />
                    <p style={ { fontSize: 12, color: '#9ca3af', margin: '0 0 12px' } }>
                        Also always handled by the bot: button/ice-breaker taps, list & flow replies, and catalog/cart orders.
                    </p>
                    <button disabled={ saving } onClick={ () => saveRouting( {
                        keywords: rKeywords.split( ',' ).map( s => s.trim() ).filter( Boolean ),
                        contains: rContains.split( ',' ).map( s => s.trim() ).filter( Boolean ),
                        commandPrefix: routing?.commandPrefix ?? '/',
                    } ) } style={ btn( '#059669' ) }>Save routing</button>
                </div>
            ) ) }

            {/* ── CONNECTORS ── */ }
            { tab === 'connectors' && (
                <div>
                    <div style={ card }>
                        <h3 style={ { margin: '0 0 8px', fontSize: 16, color: '#1a1a1a' } }>Connectors (external APIs the agent can call)</h3>
                        <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 12px' } }>
                            Define an external API the Meta AI can call. Name must be letters/numbers/underscores.
                            For our token-gated tool endpoint use API key auth with header <code>X-Agent-Token</code>.
                            Requires Tech-Provider connector access to be fully provisioned on this WABA.
                        </p>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 } }>
                            <div><label style={ label }>Name</label><input style={ input } value={ cName } onChange={ e => setCName( e.target.value ) } /></div>
                            <div><label style={ label }>Auth type</label>
                                <Select ariaLabel="Auth type" value={ cAuth }
                                    onChange={ v => setCAuth( v as 'API_KEY' | 'NONE' ) }
                                    options={ AUTH_TYPE_OPTIONS } style={ FIELD_SELECT_STYLE } />
                            </div>
                            <div style={ { gridColumn: '1 / span 2' } }><label style={ label }>Description</label><input style={ input } value={ cDesc } onChange={ e => setCDesc( e.target.value ) } /></div>
                            <div style={ { gridColumn: '1 / span 2' } }><label style={ label }>Base URL</label><input style={ input } value={ cUrl } onChange={ e => setCUrl( e.target.value ) } /></div>
                            { cAuth === 'API_KEY' && ( <>
                                <div><label style={ label }>Header name</label><input style={ input } value={ cHeaderName } onChange={ e => setCHeaderName( e.target.value ) } /></div>
                                <div><label style={ label }>Header value (token)</label><input style={ input } value={ cHeaderValue } onChange={ e => setCHeaderValue( e.target.value ) } placeholder="agent connector token" /></div>
                            </> ) }
                        </div>
                        <button disabled={ saving || !cName.trim() || !cUrl.trim() } onClick={ async () => {
                            setSaving( true );
                            try
                            {
                                const connector: api.AgentConnectorInput = {
                                    name: cName.trim(), description: cDesc.trim(), base_url: cUrl.trim(),
                                    auth_type: cAuth,
                                    ...( cAuth === 'API_KEY' ? { auth_config: { api_key: { headers: [ { field_name: cHeaderName.trim(), value: cHeaderValue } ] } } } : {} ),
                                };
                                const r = await api.aiAgentApi.addConnector( waba, connector );
                                const created = r?.created as any;
                                if ( created && !created.error ) { toast.success( 'Connector created' ); loadConnectors(); }
                                else toast.error( 'Create failed: ' + JSON.stringify( created?.error || r ).slice( 0, 160 ) );
                            } finally { setSaving( false ); }
                        } } style={ btn( '#059669' ) }>Create connector</button>
                    </div>
                    { connLoading ? <Spinner /> : (
                        <div style={ card }>
                            { connErr && <div style={ { color: '#b45309', fontSize: 12, marginBottom: 8 } }>Read note: { connErr }</div> }
                            { connectors.length === 0 && !connErr && <div style={ { color: '#9ca3af', fontSize: 14 } }>No connectors yet.</div> }
                            { connectors.map( c => (
                                <div key={ c.id } style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #f3f4f6', padding: '10px 0' } }>
                                    <div style={ { fontSize: 13 } }>
                                        <b>{ c.name }</b> <span style={ { color: '#9ca3af' } }>· { c.auth_type } · { c.connection_status?.status || '—' }</span>
                                        <div style={ { color: '#6b7280', fontSize: 12 } }>{ c.base_url }</div>
                                    </div>
                                    <button onClick={ async () => {
                                        const ok = await api.aiAgentApi.removeConnector( waba, c.id );
                                        if ( ok?.deleted ) { toast.success( 'Removed' ); loadConnectors(); } else toast.error( 'Remove failed (may be propagating)' );
                                    } } style={ { ...btn( '#fef2f2' ), color: '#dc2626', padding: '4px 10px', fontSize: 12 } }>Remove</button>
                                </div>
                            ) ) }
                        </div>
                    ) }
                </div>
            ) }

            {/* ── TECH PROVIDER ── */ }
            { tab === 'techprovider' && (
                <div>
                    <div style={ card }>
                        <h3 style={ { margin: '0 0 8px', fontSize: 16, color: '#1a1a1a' } }>Tech Provider — both WABAs</h3>
                        <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 8px' } }>
                            Per-WABA workspace, eligibility and connector state. Reading connectors works on both WABAs.
                            Connector <b>create</b> on Meta may return a cosmetic <code>500 &quot;Membrane: Authorization failed&quot;</code>
                            while the connector is actually provisioned (backend re-lists and reports the real result).
                            A WABA showing <b>&quot;Workspace not confirmed&quot;</b> means Meta hasn&apos;t finished provisioning its
                            connector workspace yet — create returns <code>400 &quot;No workspace found&quot;</code> until it does.
                        </p>
                        <button onClick={ loadProviders } style={ { ...btn( '#059669' ), padding: '6px 12px', fontSize: 13 } }>Refresh</button>
                    </div>
                    { provLoading ? <Spinner /> : providers.map( p => (
                        <div key={ p.waba } style={ card }>
                            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 } }>
                                <div>
                                    <b style={ { fontSize: 15 } }>{ p.waba }</b>
                                    <span style={ { color: '#9ca3af', fontSize: 12, marginLeft: 8 } }>phone { p.entityId } · waba { p.wabaId }</span>
                                </div>
                                <div style={ { display: 'flex', gap: 6, flexWrap: 'wrap' } }>
                                    <Pill ok={ p.connectorsReadable } okText="Connector API readable" badText="No connector access" />
                                    <Pill ok={ p.workspaceProvisioned } okText="Workspace writable" badText="Workspace not confirmed" />
                                    <Pill ok={ p.eligible } okText="Agent eligible" badText={ `Not eligible (${p.eligibilityStatus})` } />
                                    <span style={ { ...pillBase, background: '#eef2ff', color: '#3730a3' } }>{ p.connectorCount } connector{ p.connectorCount === 1 ? '' : 's' }</span>
                                </div>
                            </div>
                            { p.connectors.length === 0 && <div style={ { color: '#9ca3af', fontSize: 13, marginTop: 10 } }>No connectors on this WABA yet.</div> }
                            { p.connectors.map( c => {
                                const key = `${p.waba}:${c.id}`;
                                const det = provDetail[ key ] || {};
                                return (
                                    <div key={ c.id } style={ { borderTop: '1px solid #f3f4f6', padding: '10px 0' } }>
                                        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 } }>
                                            <div style={ { fontSize: 13 } }>
                                                <b>{ c.name }</b> <span style={ { color: '#9ca3af' } }>· { c.authType || '—' } · { c.status || '—' }</span>
                                                <div style={ { color: '#6b7280', fontSize: 12 } }>{ c.baseUrl }</div>
                                            </div>
                                            <div style={ { display: 'flex', gap: 6 } }>
                                                <button style={ { ...btn( '#f3f4f6' ), padding: '4px 10px', fontSize: 12 } } onClick={ async () => {
                                                    const [ lg, tl ] = await Promise.all( [
                                                        api.aiAgentApi.connectorLogs( p.waba, c.id ),
                                                        api.aiAgentApi.listTools( p.waba, c.id ),
                                                    ] );
                                                    const logs = ( lg?.logs && !( lg.logs as any ).error ) ? lg.logs as api.AgentConnectorLogs : undefined;
                                                    const tools = Array.isArray( tl?.tools ) ? tl!.tools as api.AgentTool[] : [];
                                                    setProvDetail( d => ( { ...d, [ key ]: { logs, tools, open: !det.open } } ) );
                                                } }>{ det.open ? 'Hide' : 'Logs & tools' }</button>
                                                <button style={ { ...btn( '#fef2f2' ), color: '#dc2626', padding: '4px 10px', fontSize: 12 } } onClick={ async () => {
                                                    const ok = await api.aiAgentApi.removeConnector( p.waba, c.id );
                                                    if ( ok?.deleted ) { toast.success( 'Removed' ); loadProviders(); } else toast.error( 'Remove failed (may be propagating)' );
                                                } }>Remove</button>
                                            </div>
                                        </div>
                                        { det.open && (
                                            <div style={ { background: '#f9fafb', borderRadius: 8, padding: 10, marginTop: 8, fontSize: 12 } }>
                                                <div style={ { fontWeight: 600, marginBottom: 4 } }>Call stats</div>
                                                { det.logs?.stats ? (
                                                    <div style={ { color: '#374151' } }>
                                                        total { String( det.logs.stats.total ?? '—' ) } · success { String( det.logs.stats.success ?? '—' ) } · errors { String( det.logs.stats.error ?? '—' ) }
                                                        { det.logs.stats.success_rate != null && <> · rate { String( det.logs.stats.success_rate ) }</> }
                                                    </div>
                                                ) : <div style={ { color: '#9ca3af' } }>No stats yet.</div> }
                                                <div style={ { fontWeight: 600, margin: '8px 0 4px' } }>Tools ({ ( det.tools || [] ).length })</div>
                                                { ( det.tools || [] ).length === 0 && <div style={ { color: '#9ca3af' } }>No tools defined.</div> }
                                                { ( det.tools || [] ).map( ( t, i ) => (
                                                    <div key={ t.id || i } style={ { borderTop: '1px solid #eef0f2', padding: '4px 0' } }>
                                                        <b>{ t.name || t.id }</b>{ t.description ? <span style={ { color: '#6b7280' } }> — { t.description }</span> : null }
                                                    </div>
                                                ) ) }
                                            </div>
                                        ) }
                                    </div>
                                );
                            } ) }
                        </div>
                    ) ) }
                </div>
            ) }

            {/* ── ALLOWLIST ── */ }
            { tab === 'allowlist' && (
                <div>
                    <div style={ card }>
                        <h3 style={ { margin: '0 0 8px', fontSize: 16, color: '#1a1a1a' } }>Allowlist</h3>
                        <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 12px' } }>Only used when Audience = &quot;Allowlisted only&quot;. Add consumer numbers in E.164 (e.g. +918100640044).</p>
                        <div style={ { display: 'flex', gap: 8 } }>
                            <input style={ { ...input, marginBottom: 0 } } value={ newPhone } onChange={ e => setNewPhone( e.target.value ) } placeholder="+918100640044" />
                            <button disabled={ saving || !newPhone.trim() } onClick={ async () => {
                                setSaving( true );
                                try { const r = await api.aiAgentApi.addAllowlist( waba, newPhone.trim() ); if ( r?.entry ) { setNewPhone( '' ); toast.success( 'Added' ); loadAllow(); } else toast.error( 'Add failed' ); }
                                finally { setSaving( false ); }
                            } } style={ btn( '#059669' ) }>Add</button>
                        </div>
                    </div>
                    { allowLoading ? <Spinner /> : (
                        <div style={ card }>
                            { allow.length === 0 && <div style={ { color: '#9ca3af', fontSize: 14 } }>No numbers allowlisted.</div> }
                            { allow.map( a => (
                                <div key={ a.id } style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #f3f4f6', padding: '8px 0' } }>
                                    <span style={ { fontFamily: 'monospace', fontSize: 14 } }>{ a.consumer_phone_number }</span>
                                    <button onClick={ async () => {
                                        const ok = await api.aiAgentApi.removeAllowlist( waba, a.id );
                                        if ( ok?.deleted ) { toast.success( 'Removed' ); loadAllow(); } else toast.error( 'Remove failed' );
                                    } } style={ { ...btn( '#fef2f2' ), color: '#dc2626', padding: '4px 10px', fontSize: 12 } }>Remove</button>
                                </div>
                            ) ) }
                        </div>
                    ) }
                </div>
            ) }
        </div>
    );
}
/** Shell-only view of the props: not all six pages declare these. */
type AnyShellProps = { user?: unknown; signOut?: () => void };


/**
 * Standalone shell. This page renders no chrome of its own - it was written as an
 * embedded tab body - so as a live route it had no sidebar, no breadcrumb and no
 * back link, and the sidebar was the only way out. MaybeLayout renders children
 * bare when `embedded`, so every hub that embeds it is unaffected.
 */
const AiAgentPage: React.FC<PageProps> = ( props ) => (
  <MaybeLayout embedded={ props.embedded } user={ ( props as AnyShellProps ).user }
    onSignOut={ ( props as AnyShellProps ).signOut }>
    <AiAgentPageBody { ...props } />
  </MaybeLayout>
);

export default AiAgentPage;
