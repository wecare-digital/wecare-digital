/**
 * Unified Broadcast — one composer to send a campaign across any channel.
 *
 * Consolidates the separate per-channel campaign pages (whatsapp/campaign, ses/campaign,
 * rcs/campaign, sms) into one flow: pick channel → audience (opt-in filtered) → message
 * → send with live progress. Uses each channel's existing send API.
 */
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { colors } from '../../../../lib/design-tokens';
import Select, { type SelectOption } from '../../../../components/ui/Select';

/* The SMS classification rows, hoisted - this is the India TRANSACTIONAL/PROMOTIONAL DLT
   class on an outbound broadcast, so the two values are exactly as they were. */
const SMS_TYPE_OPTIONS: SelectOption[] = [
    { value: 'TRANSACTIONAL', label: 'Transactional' },
    { value: 'PROMOTIONAL', label: 'Promotional' },
];

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

type Channel = 'auto' | 'whatsapp' | 'sms' | 'rcs' | 'email';
const CH_META: Record<Channel, { label: string; fg: string; bg: string }> = {
    auto: { label: 'Auto (best channel)', fg: '#1a3a2a', bg: '#ecfccb' },
    whatsapp: { label: 'WhatsApp', fg: '#15803d', bg: '#f0fdf4' },
    sms: { label: 'SMS', fg: '#1d4ed8', bg: '#eff6ff' },
    rcs: { label: 'RCS', fg: '#0f766e', bg: '#f0fdfa' },
    email: { label: 'Email', fg: '#b45309', bg: '#fffbeb' },
};

// Smart routing: pick the highest-priority channel a contact is reachable on.
const pickChannel = ( c: api.Contact ): Exclude<Channel, 'auto' | 'whatsapp'> | null => {
    if ( c.phone && ( c.optInSms || c.allowlistSms ) ) return 'sms';
    if ( c.phone ) return 'rcs';
    if ( c.email && ( c.optInEmail || c.allowlistEmail ) ) return 'email';
    return null;
};

const eligible = ( c: api.Contact, ch: Channel ): boolean => {
    if ( ch === 'auto' ) return !!c.phone || !!c.email;
    if ( ch === 'email' ) return !!c.email && ( c.optInEmail || c.allowlistEmail );
    if ( ch === 'sms' ) return !!c.phone && ( c.optInSms || c.allowlistSms );
    if ( ch === 'whatsapp' ) return !!c.phone && ( c.optInWhatsApp || c.allowlistWhatsApp );
    return !!c.phone; // rcs — phone-based
};

const BroadcastPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ channel, setChannel ] = useState<Channel>( 'sms' );
    const [ contacts, setContacts ] = useState<api.Contact[]>( [] );
    const [ selected, setSelected ] = useState<Set<string>>( new Set() );
    const [ search, setSearch ] = useState( '' );
    const [ content, setContent ] = useState( '' );
    const [ subject, setSubject ] = useState( '' );
    const [ smsType, setSmsType ] = useState<'TRANSACTIONAL' | 'PROMOTIONAL'>( 'TRANSACTIONAL' );
    const [ templates, setTemplates ] = useState<api.WhatsAppTemplate[]>( [] );
    const [ templateName, setTemplateName ] = useState( '' );
    const [ sending, setSending ] = useState( false );
    const [ progress, setProgress ] = useState<{ sent: number; failed: number; total: number } | null>( null );

    useEffect( () => {
        api.listContacts().then( setContacts ).catch( () => toast.error( 'Failed to load contacts' ) );
        api.listTemplates().then( t => setTemplates( ( t || [] ).filter( ( x: any ) => x.status === 'APPROVED' ) ) ).catch( () => { } );
    }, [ toast ] );

    // Reset selection when channel changes (eligibility differs).
    useEffect( () => { setSelected( new Set() ); }, [ channel ] );

    const audience = useMemo( () => {
        const q = search.trim().toLowerCase();
        return contacts.filter( c => eligible( c, channel ) )
            .filter( c => !q || c.name?.toLowerCase().includes( q ) || c.phone?.includes( q ) || c.email?.toLowerCase().includes( q ) );
    }, [ contacts, channel, search ] );

    /* The fetched template list, memoised on `templates`: same order, same values, same
       visible text, with the '' placeholder row kept as the first option. */
    const templateOptions: SelectOption[] = useMemo(
        () => [
            { value: '', label: 'Select a template…' },
            ...templates.map( ( t: any ) => ( { value: t.name, label: t.name } ) ),
        ],
        [ templates ]
    );

    const toggle = ( id: string ) => setSelected( prev => { const n = new Set( prev ); n.has( id ) ? n.delete( id ) : n.add( id ); return n; } );
    const selectAll = () => setSelected( new Set( audience.map( c => c.contactId ) ) );
    const clearAll = () => setSelected( new Set() );

    const canSend = selected.size > 0 && !sending && (
        channel === 'whatsapp' ? !!templateName :
            channel === 'email' ? ( !!subject.trim() && !!content.trim() ) :
                !!content.trim()
    );

    // Send free text to one contact on a specific (non-WhatsApp) channel.
    const sendOne = useCallback( async ( c: api.Contact, ch: string ): Promise<boolean> => {
        if ( ch === 'sms' ) { const r = await api.sendSmsAws( { contactId: c.contactId, phoneNumber: c.phone, content, messageType: smsType } ); return !!( r && ( r.messageId || r.status === 'sent' ) ); }
        if ( ch === 'rcs' ) { const r = await api.sendRcs( { phoneNumber: c.phone, text: content } ); return !!( r && ( r.success || r.messageId ) ); }
        if ( ch === 'email' ) { const r = await api.sendEmailMessage( c.contactId, subject || 'Message from WECARE.DIGITAL', content ); return !!r; }
        if ( ch === 'whatsapp' ) { const r = await api.sendWhatsAppTemplateMessage( { contactId: c.contactId, templateName } ); return !!r; }
        return false;
    }, [ content, smsType, subject, templateName ] );

    const send = useCallback( async () => {
        const targets = contacts.filter( c => selected.has( c.contactId ) );
        if ( !targets.length ) return;
        setSending( true );
        setProgress( { sent: 0, failed: 0, total: targets.length } );
        let sent = 0, failed = 0;
        for ( let i = 0; i < targets.length; i++ )
        {
            const c = targets[ i ];
            try
            {
                const useCh = channel === 'auto' ? pickChannel( c ) : channel;
                const ok = useCh ? await sendOne( c, useCh ) : false;
                ok ? sent++ : failed++;
            } catch { failed++; }
            setProgress( { sent, failed, total: targets.length } );
            if ( i % 10 === 9 ) await new Promise( r => setTimeout( r, 200 ) ); // gentle throttle
        }
        setSending( false );
        toast[ failed === 0 ? 'success' : 'warning' ]( `Broadcast done — ${sent} sent, ${failed} failed` );
    }, [ contacts, selected, channel, sendOne, toast ] );

    const content_ = (
        <>
            <div className="bc-wrap">
                <PageHeader title="Broadcast" subtitle="Send a campaign across any channel — one composer" icon="message" />

                {/* Step 1: channel */ }
                <div className="bc-step-label">1 · Channel</div>
                <div className="bc-channels">
                    { ( Object.keys( CH_META ) as Channel[] ).map( ch => (
                        <button key={ ch } className={ `bc-ch ${channel === ch ? 'active' : ''}` }
                            style={ channel === ch ? { color: CH_META[ ch ].fg, background: CH_META[ ch ].bg, borderColor: CH_META[ ch ].fg } : {} }
                            onClick={ () => setChannel( ch ) }>{ CH_META[ ch ].label }</button>
                    ) ) }
                </div>

                <div className="bc-cols">
                    {/* Step 2: audience */ }
                    <div className="bc-audience">
                        <div className="bc-step-label">2 · Audience ({ selected.size } selected · { audience.length } eligible)</div>
                        <div className="bc-aud-toolbar">
                            <input className="bc-search" placeholder="Search contacts…" value={ search } onChange={ e => setSearch( e.target.value ) } />
                            <button className="bc-mini" onClick={ selectAll }>All</button>
                            <button className="bc-mini" onClick={ clearAll }>None</button>
                        </div>
                        <div className="bc-aud-list">
                            { audience.length === 0 ? <div className="bc-empty">No eligible contacts (opt-in required)</div> :
                                audience.map( c => (
                                    <label key={ c.contactId } className="bc-aud-row">
                                        <input type="checkbox" checked={ selected.has( c.contactId ) } onChange={ () => toggle( c.contactId ) } />
                                        <span className="bc-aud-name">{ c.name || c.phone || c.email }</span>
                                        <span className="bc-aud-sub">{ channel === 'email' ? c.email : c.phone }</span>
                                    </label>
                                ) ) }
                        </div>
                    </div>

                    {/* Step 3: message */ }
                    <div className="bc-message">
                        <div className="bc-step-label">3 · Message</div>
                        { channel === 'whatsapp' ? (
                            <>
                                <p className="bc-hint">WhatsApp broadcasts must use an approved template.</p>
                                { /* `.bc-input` SKINNED the native control and is dropped rather than
                                     forwarded. The fetched list is memoised below. */ }
                                <Select ariaLabel="Template" value={ templateName }
                                    onChange={ v => setTemplateName( v ) }
                                    options={ templateOptions } />
                            </>
                        ) : (
                            <>
                                { channel === 'email' && (
                                    <input className="bc-input" placeholder="Subject" value={ subject } onChange={ e => setSubject( e.target.value ) } />
                                ) }
                                <textarea className="bc-textarea" placeholder="Message…" value={ content } onChange={ e => setContent( e.target.value ) } rows={ 6 } />
                                { channel === 'sms' && (
                                    <Select ariaLabel="SMS type" value={ smsType }
                                        onChange={ v => setSmsType( v as any ) }
                                        options={ SMS_TYPE_OPTIONS } />
                                ) }
                            </>
                        ) }

                        <button className="bc-send" disabled={ !canSend } onClick={ send }>
                            { sending ? `Sending… ${progress?.sent || 0}/${progress?.total || 0}` : `Send to ${selected.size} via ${CH_META[ channel ].label}` }
                        </button>
                        { progress && !sending && (
                            <div className="bc-result">✓ { progress.sent } sent{ progress.failed ? ` · ${progress.failed} failed` : '' }</div>
                        ) }
                    </div>
                </div>
            </div>

            <style jsx>{ `
                .bc-wrap { padding: 20px; max-width: 1100px; margin: 0 auto; }
                .bc-step-label { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: ${colors.textMuted}; margin: 16px 0 8px; }
                .bc-channels { display: flex; gap: 10px; flex-wrap: wrap; }
                .bc-ch { padding: 9px 18px; border: 1px solid ${colors.border}; border-radius: 9999px; background: #fff; font-size: 14px; font-weight: 600; cursor: pointer; color: ${colors.textSecondary}; }
                .bc-ch.active { border-width: 1.5px; }
                .bc-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 6px; }
                .bc-aud-toolbar { display: flex; gap: 8px; margin-bottom: 8px; }
                .bc-search { flex: 1; padding: 8px 12px; border: 1px solid ${colors.border}; border-radius: 9px; font-size: 13px; }
                .bc-mini { padding: 8px 12px; border: 1px solid ${colors.border}; border-radius: 9px; background: #fff; font-size: 12px; cursor: pointer; }
                .bc-aud-list { border: 1px solid ${colors.border}; border-radius: 12px; max-height: 420px; overflow-y: auto; background: #fff; }
                .bc-aud-row { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-bottom: 1px solid ${colors.borderLight}; cursor: pointer; }
                .bc-aud-row:hover { background: ${colors.bgHover}; }
                .bc-aud-name { font-size: 13px; font-weight: 600; color: ${colors.text}; }
                .bc-aud-sub { font-size: 12px; color: ${colors.textMuted}; margin-left: auto; }
                .bc-empty { padding: 30px; text-align: center; color: ${colors.textMuted}; font-size: 13px; }
                .bc-input, .bc-textarea { width: 100%; padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 14px; font-family: inherit; margin-bottom: 10px; }
                .bc-textarea { resize: vertical; }
                .bc-hint { font-size: 12px; color: ${colors.textMuted}; margin: 0 0 8px; }
                .bc-send { width: 100%; background: ${colors.primary}; color: #fff; padding: 12px; border: none; border-radius: 11px; font-size: 14px; font-weight: 700; cursor: pointer; margin-top: 4px; }
                .bc-send:disabled { opacity: 0.5; cursor: not-allowed; }
                .bc-result { margin-top: 10px; font-size: 13px; color: ${colors.text}; font-weight: 600; }
                @media (max-width: 800px) { .bc-cols { grid-template-columns: 1fr; } }
            ` }</style>
        </>
    );

    if ( embedded ) return content_;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Broadcast | WECARE.DIGITAL" description="Unified cross-channel broadcast" noindex={ true } />
            { content_ }
        </Layout>
    );
};

export default BroadcastPage;
