/**
 * Meta Business Agent — [retired public path]/meta-agent
 * Onboard + configure Meta's Business AI Agent on WhatsApp (per WABA phone number).
 * Backed by the wecare-meta-business-agent Lambda (POST /meta-agent).
 * API: https://api.facebook.com/{entity_id}/agent_onboarding + /agent_config/settings
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import Button from '../../../../components/ui/Button';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { fetchAuthSession } from 'aws-amplify/auth';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

// WhatsApp Business phone-number IDs (entity_id) — from backend `entities` action
const WABAS = [
    { label: 'WABA 1 (+91 93309 94400)', id: '1016149501586345' },
    { label: 'WABA-T (+91 99033 00044)', id: '1055232054343117' },
];
const INTERVALS = [ 0, 300, 900, 1800, 3600, 7200, 28800, 86400 ];

const AUDIENCE_OPTIONS: SelectOption[] = [
    { value: 'EVERYONE', label: 'Everyone' },
    { value: 'ALLOWLISTED_ONLY', label: 'Allowlisted numbers only (controlled rollout)' },
];

/**
 * The Audience control, and why it owns a piece of state rather than reading `settings`.
 *
 * It was UNCONTROLLED - React's uncontrolled default attribute, seeded from
 * `settings.ai_audience`, with an onChange that called `save` and nothing else. One of the four
 * sites design section 5.2 lists as supplying neither `value` nor `onChange`, or only one of
 * the two. The native element kept the operator's choice across a
 * parent re-render on its own, with no variable behind it. A controlled Select has nothing to
 * keep it, and `save` is followed immediately by `loadSettings()` - so pointing `value` at
 * `settings.ai_audience` would make the control snap back to the server's answer, including
 * while the request is still in flight and including when it fails.
 *
 * So the choice lives here, `setAudience` runs BEFORE `onSave`, and `initial` is read once at
 * mount - which is exactly what the uncontrolled attribute did, since this control mounts when
 * `settings` first arrives and is not remounted afterwards.
 */
const AudienceSelect: React.FC<{ initial: string; onSave: ( value: string ) => void }> = ( { initial, onSave } ) => {
    const [ audience, setAudience ] = useState( initial );
    return (
        <Select
            ariaLabel="Audience"
            value={ audience }
            onChange={ value => { setAudience( value ); onSave( value ); } }
            options={ AUDIENCE_OPTIONS }
        />
    );
};

interface Settings {
    agent_id?: string; channel?: string;
    rollout?: { enabled: boolean };
    handoff?: { enabled: boolean; message?: string } | null;
    followup?: { enabled: boolean; followup_interval_in_seconds?: number; message?: string } | null;
    ai_audience?: 'ALLOWLISTED_ONLY' | 'EVERYONE' | null;
}

const MetaAgentPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const confirm = useConfirm();
    const [ entityId, setEntityId ] = useState( WABAS[ 0 ].id );
    const [ settings, setSettings ] = useState<Settings | null>( null );
    const [ loading, setLoading ] = useState( false );
    const [ busy, setBusy ] = useState( '' );

    const call = async ( action: string, extra: Record<string, any> = {} ) => {
        let token: string | null = null;
        try { token = ( await fetchAuthSession() ).tokens?.accessToken?.toString() ?? null; } catch { token = null; }
        const res = await fetch( `${API_BASE}/meta-agent`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...( token ? { Authorization: `Bearer ${token}` } : {} ) },
            body: JSON.stringify( { action, entityId, ...extra } ),
        } );
        if ( res.status === 401 || res.status === 403 ) { toast.error( 'Not authorized — please sign in again' ); return {}; }
        return res.json();
    };

    const loadSettings = useCallback( async () => {
        setLoading( true );
        try
        {
            const data = await call( 'settings' );
            const s = Array.isArray( data.settings ) ? data.settings[ 0 ] : data.settings;
            setSettings( s || null );
        } catch { toast.error( 'Failed to load agent settings' ); }
        finally { setLoading( false ); }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ entityId ] );

    useEffect( () => { loadSettings(); }, [ loadSettings ] );

    const onboard = async () => {
        if ( !( await confirm( 'Trigger Meta Business Agent onboarding for this WhatsApp number? This creates the agent and schedules data-prep jobs.' ) ) ) return;
        setBusy( 'onboard' );
        try
        {
            const d = await call( 'onboard', { channel: 'whatsapp' } );
            if ( d.onboarding?.agent_id ) toast.success( `Onboarding triggered — agent ${d.onboarding.agent_id}` );
            else toast.error( `Onboarding: ${JSON.stringify( d.onboarding?.error || d )}` );
            loadSettings();
        } finally { setBusy( '' ); }
    };

    const toggle = async ( enabled: boolean ) => {
        setBusy( 'toggle' );
        try
        {
            await call( enabled ? 'enable' : 'disable' );
            toast.success( enabled ? 'Agent enabled — it will respond to new conversations' : 'Agent disabled' );
            loadSettings();
        } finally { setBusy( '' ); }
    };

    const save = async ( patch: Record<string, any> ) => {
        setBusy( 'save' );
        try { await call( 'settings_update', patch ); toast.success( 'Settings saved' ); loadSettings(); }
        finally { setBusy( '' ); }
    };

    // ── Skills (system instructions) ──
    const [ skills, setSkills ] = useState( '' );
    const loadSkills = useCallback( async () => {
        const d = await call( 'skills' );
        const s = Array.isArray( d.skills ) ? d.skills[ 0 ] : d.skills;
        setSkills( s?.system_instructions || s?.instructions || '' );
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ entityId ] );
    const saveSkills = async () => {
        setBusy( 'skills' );
        try { await call( 'skills_update', { instructions: skills } ); toast.success( 'Skills saved' ); }
        finally { setBusy( '' ); }
    };

    // ── FAQs (knowledge) ──
    const [ faqs, setFaqs ] = useState<any[]>( [] );
    const [ faqQ, setFaqQ ] = useState( '' );
    const [ faqA, setFaqA ] = useState( '' );
    const loadFaqs = useCallback( async () => {
        const d = await call( 'knowledge', { resource: 'faqs' } );
        setFaqs( Array.isArray( d.items ) ? d.items : ( d.items?.data || [] ) );
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ entityId ] );
    const addFaq = async () => {
        if ( !faqQ.trim() || !faqA.trim() ) return;
        setBusy( 'faq' );
        try { await call( 'knowledge_add', { resource: 'faqs', item: { question: faqQ, answer: faqA } } ); setFaqQ( '' ); setFaqA( '' ); toast.success( 'FAQ added' ); loadFaqs(); }
        finally { setBusy( '' ); }
    };
    const removeFaq = async ( id: string ) => {
        if ( !( await confirm( 'Remove this FAQ?' ) ) ) return;
        await call( 'knowledge_remove', { resource: 'faqs', itemId: id } ); toast.success( 'Removed' ); loadFaqs();
    };

    // ── Allowlist ──
    const [ allow, setAllow ] = useState<any[]>( [] );
    const [ allowPhone, setAllowPhone ] = useState( '' );
    const loadAllow = useCallback( async () => {
        const d = await call( 'allowlist' );
        setAllow( Array.isArray( d.allowlist ) ? d.allowlist : ( d.allowlist?.data || [] ) );
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ entityId ] );
    const addAllow = async () => {
        if ( !allowPhone.trim() ) return;
        setBusy( 'allow' );
        try { await call( 'allowlist_add', { consumerPhoneNumber: allowPhone.trim() } ); setAllowPhone( '' ); toast.success( 'Added to allowlist' ); loadAllow(); }
        finally { setBusy( '' ); }
    };
    const removeAllow = async ( id: string ) => {
        if ( !( await confirm( 'Remove from allowlist?' ) ) ) return;
        await call( 'allowlist_remove', { entryId: id } ); toast.success( 'Removed' ); loadAllow();
    };

    // ── Test ──
    const [ testMsg, setTestMsg ] = useState( '' );
    const [ testOut, setTestOut ] = useState( '' );
    const runTest = async () => {
        if ( !testMsg.trim() ) return;
        setBusy( 'test' );
        try { const d = await call( 'agent_test', { message: testMsg } ); setTestOut( JSON.stringify( d.result || d, null, 2 ) ); }
        finally { setBusy( '' ); }
    };

    useEffect( () => { loadSkills(); loadFaqs(); loadAllow(); }, [ loadSkills, loadFaqs, loadAllow ] );

    const enabled = !!settings?.rollout?.enabled;

    const body = (
        <>
            <SEO title="Meta Business Agent" description="Onboard and configure Meta's WhatsApp Business AI agent" />
            <div style={ { padding: embedded ? 0 : 'var(--space-6)', maxWidth: 820 } }>
                <h1 style={ { fontSize: 'var(--h2)', fontWeight: 700, margin: '0 0 var(--space-4)', color: 'var(--text)' } }>Meta Business Agent</h1>

                <div style={ card }>
                    <label style={ lbl }>WhatsApp Business number</label>
                    <select value={ entityId } onChange={ e => setEntityId( e.target.value ) } style={ { width: '100%' } }>
                        { WABAS.map( w => <option key={ w.id } value={ w.id }>{ w.label }</option> ) }
                    </select>
                    <div style={ { marginTop: 'var(--space-3)', display: 'flex', gap: 'var(--space-2)' } }>
                        <Button onClick={ onboard } disabled={ busy !== '' }>{ busy === 'onboard' ? 'Onboarding…' : 'Trigger onboarding' }</Button>
                        <Button variant="secondary" onClick={ loadSettings } disabled={ loading }>Refresh</Button>
                    </div>
                </div>

                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                        <h2 style={ h2 }>Agent status</h2>
                        <span className={ `status-pill ${enabled ? 'status-read' : 'status-queued'}` }>{ enabled ? 'ON' : 'OFF' }</span>
                    </div>
                    { loading ? <p style={ { color: 'var(--text-muted)' } }>Loading…</p> : !settings ? (
                        <p style={ { color: 'var(--text-muted)' } }>No agent settings yet — run onboarding first.</p>
                    ) : (
                        <>
                            <p style={ { color: 'var(--text-muted)', fontSize: 13, margin: '4px 0 12px' } }>
                                Agent ID: { settings.agent_id || '—' } · Channel: { settings.channel || 'whatsapp' }
                            </p>
                            <div style={ { display: 'flex', gap: 'var(--space-2)' } }>
                                <Button onClick={ () => toggle( true ) } disabled={ enabled || busy !== '' }>Enable</Button>
                                <Button variant="secondary" onClick={ () => toggle( false ) } disabled={ !enabled || busy !== '' }>Disable</Button>
                            </div>
                        </>
                    ) }
                </div>

                { settings && (
                    <div style={ card }>
                        <h2 style={ h2 }>Audience</h2>
                        <AudienceSelect
                            initial={ settings.ai_audience || 'EVERYONE' }
                            onSave={ value => save( { aiAudience: value } ) }
                        />
                    </div>
                ) }

                {/* Allowlist */ }
                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-2)' } }>
                        <h2 style={ h2 }>Allowlist</h2>
                        <Button variant="secondary" onClick={ loadAllow } disabled={ busy !== '' }>Refresh</Button>
                    </div>
                    <p style={ { color: 'var(--text-muted)', fontSize: 13, margin: '0 0 10px' } }>Limit the agent to specific consumer numbers (used when Audience = Allowlisted only).</p>
                    <div style={ { display: 'flex', gap: 'var(--space-2)', marginBottom: 10 } }>
                        <input value={ allowPhone } onChange={ e => setAllowPhone( e.target.value ) } placeholder="+15551234567" style={ { flex: 1 } } />
                        <Button onClick={ addAllow } disabled={ busy !== '' || !allowPhone.trim() }>Add</Button>
                    </div>
                    { allow.length === 0 ? <p style={ { color: 'var(--text-muted)', fontSize: 13 } }>No allowlisted numbers.</p> : (
                        <ul style={ { listStyle: 'none', padding: 0, margin: 0 } }>
                            { allow.map( ( a: any ) => (
                                <li key={ a.id } style={ { display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' } }>
                                    <span>{ a.consumer_phone_number || a.phone || a.id }</span>
                                    <button onClick={ () => removeAllow( a.id ) } style={ { border: 'none', background: 'none', color: 'var(--danger, #dc2626)', cursor: 'pointer' } }>Remove</button>
                                </li>
                            ) ) }
                        </ul>
                    ) }
                </div>

                {/* Skills / system instructions */ }
                <div style={ card }>
                    <h2 style={ h2 }>Skills — system instructions</h2>
                    <p style={ { color: 'var(--text-muted)', fontSize: 13, margin: '0 0 8px' } }>Instructions that shape how the agent responds (tone, policies, do/don&apos;t).</p>
                    <textarea value={ skills } onChange={ e => setSkills( e.target.value ) } rows={ 6 } placeholder="e.g. You are WECARE's support assistant. Be concise, polite, and never share pricing you are unsure about…" style={ { width: '100%', fontFamily: 'inherit', fontSize: 13 } } />
                    <div style={ { marginTop: 8, display: 'flex', gap: 'var(--space-2)' } }>
                        <Button onClick={ saveSkills } disabled={ busy !== '' }>{ busy === 'skills' ? 'Saving…' : 'Save skills' }</Button>
                        <Button variant="secondary" onClick={ loadSkills } disabled={ busy !== '' }>Reload</Button>
                    </div>
                </div>

                {/* FAQs knowledge */ }
                <div style={ card }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-2)' } }>
                        <h2 style={ h2 }>Knowledge — FAQs</h2>
                        <Button variant="secondary" onClick={ loadFaqs } disabled={ busy !== '' }>Refresh</Button>
                    </div>
                    <div style={ { display: 'grid', gap: 8, marginBottom: 10 } }>
                        <input value={ faqQ } onChange={ e => setFaqQ( e.target.value ) } placeholder="Question" style={ { width: '100%' } } />
                        <textarea value={ faqA } onChange={ e => setFaqA( e.target.value ) } rows={ 2 } placeholder="Answer" style={ { width: '100%', fontFamily: 'inherit' } } />
                        <div><Button onClick={ addFaq } disabled={ busy !== '' || !faqQ.trim() || !faqA.trim() }>Add FAQ</Button></div>
                    </div>
                    { faqs.length === 0 ? <p style={ { color: 'var(--text-muted)', fontSize: 13 } }>No FAQs yet.</p> : (
                        <ul style={ { listStyle: 'none', padding: 0, margin: 0 } }>
                            { faqs.map( ( f: any, i: number ) => (
                                <li key={ f.id || i } style={ { padding: '8px 0', borderBottom: '1px solid var(--border)' } }>
                                    <div style={ { display: 'flex', justifyContent: 'space-between', gap: 8 } }>
                                        <div><strong style={ { fontSize: 13 } }>{ f.question }</strong><div style={ { fontSize: 13, color: 'var(--text-muted)' } }>{ f.answer }</div></div>
                                        { f.id && <button onClick={ () => removeFaq( f.id ) } style={ { border: 'none', background: 'none', color: 'var(--danger, #dc2626)', cursor: 'pointer', flexShrink: 0 } }>Remove</button> }
                                    </div>
                                </li>
                            ) ) }
                        </ul>
                    ) }
                </div>

                {/* Test */ }
                <div style={ card }>
                    <h2 style={ h2 }>Test the agent</h2>
                    <p style={ { color: 'var(--text-muted)', fontSize: 13, margin: '0 0 8px' } }>Send a test message and see the agent&apos;s response.</p>
                    <div style={ { display: 'flex', gap: 'var(--space-2)', marginBottom: 8 } }>
                        <input value={ testMsg } onChange={ e => setTestMsg( e.target.value ) } placeholder="Type a customer message…" style={ { flex: 1 } } />
                        <Button onClick={ runTest } disabled={ busy !== '' || !testMsg.trim() }>{ busy === 'test' ? 'Running…' : 'Send' }</Button>
                    </div>
                    { testOut && <pre style={ { background: 'var(--surface-2, #f5f5f5)', padding: 12, borderRadius: 8, fontSize: 12, overflow: 'auto', maxHeight: 240 } }>{ testOut }</pre> }
                </div>
            </div>
        </>
    );

    return embedded ? body : <Layout user={ user } onSignOut={ signOut }>{ body }</Layout>;
};

const card: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)', marginBottom: 'var(--space-4)', boxShadow: 'var(--shadow-sm)' };
const h2: React.CSSProperties = { fontSize: 'var(--h4)', fontWeight: 600, margin: '0 0 var(--space-2)', color: 'var(--text)' };
const lbl: React.CSSProperties = { display: 'block', fontSize: 13, color: 'var(--text-secondary)', marginBottom: 6 };

export default MetaAgentPage;
