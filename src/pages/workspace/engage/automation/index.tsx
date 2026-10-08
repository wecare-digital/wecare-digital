/**
 * Automation — cross-channel auto-reply rules.
 * Create rules: when an inbound message matches a trigger (keyword/any) on a channel,
 * auto-reply with text. Evaluated by inbound handlers via lambda_utils/automation.py.
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { colors } from '../../../../lib/design-tokens';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const BLANK: Partial<api.AutomationRule> = { name: '', enabled: true, channel: 'any', triggerType: 'keyword', triggerValue: '', actionType: 'reply', actionValue: '', priority: 100 };

/* The two draft choosers' rows, hoisted. Same order, same values, same visible text. */
const CHANNEL_OPTIONS: SelectOption[] = [
    { value: 'any', label: 'Any channel' },
    { value: 'whatsapp', label: 'WhatsApp' },
    { value: 'sms', label: 'SMS' },
    { value: 'rcs', label: 'RCS' },
    { value: 'email', label: 'Email' },
];
const TRIGGER_TYPE_OPTIONS: SelectOption[] = [
    { value: 'keyword', label: 'When message contains…' },
    { value: 'any', label: 'On any message' },
];

const AutomationPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const toast = useToastContext();
    const [ rules, setRules ] = useState<api.AutomationRule[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ draft, setDraft ] = useState<Partial<api.AutomationRule>>( BLANK );
    const [ saving, setSaving ] = useState( false );

    const load = useCallback( async () => {
        try { setRules( await api.listAutomationRules() ); }
        catch { toast.error( 'Failed to load rules' ); }
        finally { setLoading( false ); }
    }, [ toast ] );
    useEffect( () => { load(); }, [ load ] );

    const create = useCallback( async () => {
        if ( !draft.name?.trim() || !draft.actionValue?.trim() ) { toast.error( 'Name and reply text are required' ); return; }
        if ( draft.triggerType === 'keyword' && !draft.triggerValue?.trim() ) { toast.error( 'Keyword required' ); return; }
        setSaving( true );
        try
        {
            const r = await api.createAutomationRule( draft );
            if ( r ) { toast.success( 'Rule created' ); setDraft( BLANK ); load(); } else toast.error( 'Create failed' );
        } catch { toast.error( 'Create failed' ); }
        finally { setSaving( false ); }
    }, [ draft, toast, load ] );

    const toggle = useCallback( async ( r: api.AutomationRule ) => {
        const updated = await api.updateAutomationRule( r.id, { enabled: !r.enabled } );
        if ( updated ) setRules( prev => prev.map( x => x.id === r.id ? { ...x, enabled: !x.enabled } : x ) );
    }, [] );

    const remove = useCallback( async ( id: string ) => {
        if ( await api.deleteAutomationRule( id ) ) { setRules( prev => prev.filter( x => x.id !== id ) ); toast.success( 'Deleted' ); }
        else toast.error( 'Delete failed' );
    }, [ toast ] );

    const content = (
        <>
            <div className="au-wrap">
                <PageHeader title="Automation" subtitle="Cross-channel auto-reply rules — keyword triggers, instant replies" icon="settings" />

                <div className="au-new">
                    <div className="au-new-title">New rule</div>
                    <div className="au-grid">
                        <input className="au-in" placeholder="Rule name" value={ draft.name } onChange={ e => setDraft( d => ( { ...d, name: e.target.value } ) ) } />
                        { /* `.au-in` SKINNED the native control and is dropped rather than
                             forwarded; `.au-grid` sizes these two, so no width is needed.
                             Both casts are preserved verbatim. */ }
                        <Select ariaLabel="Channel" value={ draft.channel ?? 'any' }
                            onChange={ v => setDraft( d => ( { ...d, channel: v as any } ) ) }
                            options={ CHANNEL_OPTIONS } />
                        <Select ariaLabel="Trigger" value={ draft.triggerType ?? 'keyword' }
                            onChange={ v => setDraft( d => ( { ...d, triggerType: v as any } ) ) }
                            options={ TRIGGER_TYPE_OPTIONS } />
                        { draft.triggerType === 'keyword' && (
                            <input className="au-in" placeholder="keyword (e.g. hours)" value={ draft.triggerValue } onChange={ e => setDraft( d => ( { ...d, triggerValue: e.target.value } ) ) } />
                        ) }
                    </div>
                    <textarea className="au-textarea" placeholder="Auto-reply text…" value={ draft.actionValue } onChange={ e => setDraft( d => ( { ...d, actionValue: e.target.value } ) ) } rows={ 3 } />
                    <button className="au-create" disabled={ saving } onClick={ create }>{ saving ? 'Saving…' : '+ Create rule' }</button>
                </div>

                <div className="au-list">
                    { loading ? <div className="au-empty">Loading…</div> :
                        rules.length === 0 ? <div className="au-empty">No rules yet</div> :
                            rules.map( r => (
                                <div key={ r.id } className={ `au-rule ${r.enabled ? '' : 'off'}` }>
                                    <div className="au-rule-main">
                                        <div className="au-rule-name">{ r.name }</div>
                                        <div className="au-rule-cond">
                                            <span className="au-tag">{ r.channel }</span>
                                            { r.triggerType === 'keyword' ? `contains "${r.triggerValue}"` : 'any message' } → { ( r.actionValue || '' ).slice( 0, 60 ) }
                                        </div>
                                    </div>
                                    <div className="au-rule-actions">
                                        <button className={ `au-toggle ${r.enabled ? 'on' : ''}` } onClick={ () => toggle( r ) }>{ r.enabled ? 'On' : 'Off' }</button>
                                        <button className="au-del" onClick={ () => remove( r.id ) }>Delete</button>
                                    </div>
                                </div>
                            ) ) }
                </div>
            </div>
            <style jsx>{ `
                .au-wrap { padding: 20px; max-width: 900px; margin: 0 auto; }
                .au-new { border: 1px solid ${colors.border}; border-radius: 12px; padding: 16px; background: #fff; margin: 14px 0; }
                .au-new-title { font-size: 13px; font-weight: 700; color: ${colors.text}; margin-bottom: 10px; }
                .au-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 10px; }
                .au-in { padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 9px; font-size: 13px; }
                .au-textarea { width: 100%; padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 9px; font-size: 14px; font-family: inherit; resize: vertical; margin-bottom: 10px; }
                .au-create { background: ${colors.primary}; color: #fff; border: none; padding: 9px 18px; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; }
                .au-create:disabled { opacity: 0.5; cursor: not-allowed; }
                .au-list { display: flex; flex-direction: column; gap: 8px; }
                .au-rule { display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid ${colors.border}; border-radius: 11px; padding: 12px 14px; background: #fff; }
                .au-rule.off { opacity: 0.55; }
                .au-rule-name { font-size: 14px; font-weight: 600; color: ${colors.text}; }
                .au-rule-cond { font-size: 12px; color: ${colors.textSecondary}; margin-top: 3px; }
                .au-tag { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 9999px; background: ${colors.bgSecondary}; color: ${colors.textSecondary}; margin-right: 6px; text-transform: capitalize; }
                .au-rule-actions { display: flex; gap: 8px; flex-shrink: 0; }
                .au-toggle { padding: 5px 14px; border: 1px solid ${colors.border}; border-radius: 9999px; background: #fff; font-size: 12px; cursor: pointer; }
                .au-toggle.on { background: ${colors.lime}; border-color: ${colors.lime}; color: ${colors.primary}; font-weight: 700; }
                .au-del { padding: 5px 12px; border: 1px solid ${colors.danger}; color: ${colors.danger}; background: #fff; border-radius: 9px; font-size: 12px; cursor: pointer; }
                .au-empty { text-align: center; padding: 30px; color: ${colors.textMuted}; }
            ` }</style>
        </>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Automation | WECARE.DIGITAL" description="Cross-channel auto-reply rules" noindex={ true } />
            { content }
        </Layout>
    );
};

export default AutomationPage;
