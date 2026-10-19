/**
 * Channel Settings — unified settings home: consent/opt-in overview (from ContactsTable),
 * sender identities, and deep links to each channel's own configuration.
 */
import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import SEO from '../../../../components/SEO';
import * as api from '../../../../api/client';
import { colors } from '../../../../lib/design-tokens';
import { WHATSAPP_PHONES } from '../../../../config/constants';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const SettingsPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const [ contacts, setContacts ] = useState<api.Contact[]>( [] );

    useEffect( () => { api.listContacts().then( setContacts ).catch( () => { } ); }, [] );

    const consent = useMemo( () => {
        const total = contacts.length || 1;
        const wa = contacts.filter( c => c.optInWhatsApp || c.allowlistWhatsApp ).length;
        const sms = contacts.filter( c => c.optInSms || c.allowlistSms ).length;
        const email = contacts.filter( c => c.optInEmail || c.allowlistEmail ).length;
        return [
            { ch: 'WhatsApp', fg: '#15803d', bg: '#f0fdf4', n: wa, pct: Math.round( wa / total * 100 ) },
            { ch: 'SMS', fg: '#1d4ed8', bg: '#eff6ff', n: sms, pct: Math.round( sms / total * 100 ) },
            { ch: 'Email', fg: '#b45309', bg: '#fffbeb', n: email, pct: Math.round( email / total * 100 ) },
        ];
    }, [ contacts ] );

    const senders = [
        { ch: 'WhatsApp', id: `${WHATSAPP_PHONES.primary.name} · ${WHATSAPP_PHONES.primary.display}`, cfg: '/workspace/communications?view=manage&section=whatsapp' },
        { ch: 'WhatsApp', id: `${WHATSAPP_PHONES.secondary.name} · ${WHATSAPP_PHONES.secondary.display}`, cfg: '/workspace/communications?view=manage&section=whatsapp' },
        { ch: 'SMS', id: 'Sender WDBEEP · India DLT', cfg: '/workspace/engage/sms' },
        { ch: 'RCS', id: 'Sinch RCS bot', cfg: '/workspace/engage/rcs' },
        { ch: 'Email', id: 'noreply@wecare.digital (SES)', cfg: '/workspace/engage/ses' },
        { ch: 'Voice', id: 'Business Calling · IVR', cfg: '/workspace/engage/voice' },
    ];

    const configs = [
        { label: 'WhatsApp Settings', desc: 'Profile, webhooks, WABA, calling, templates, flows', href: '/workspace/communications?view=manage&section=whatsapp' },
        { label: 'SMS', desc: 'Sender IDs and India DLT templates', href: '/workspace/engage/sms' },
        { label: 'RCS', desc: 'Bot config & templates (Sinch)', href: '/workspace/engage/rcs' },
        { label: 'Email', desc: 'SES from-address & campaigns', href: '/workspace/engage/ses' },
        { label: 'Voice', desc: 'Plivo PSTN and AWS voice origination', href: '/workspace/engage/voice' },
        { label: 'Push', desc: 'Mobile push apps and device tokens', href: '/workspace/engage/push' },
    ];

    const content = (
        <>
            <div className="st-wrap">
                <PageHeader title="Channel Settings" subtitle="Consent, sender identities & per-channel configuration" icon="settings" />

                <div className="st-section">Consent / opt-in ({ contacts.length } contacts)</div>
                <div className="st-consent">
                    { consent.map( c => (
                        <div key={ c.ch } className="st-consent-card">
                            <span className="st-pill" style={ { color: c.fg, background: c.bg } }>{ c.ch }</span>
                            <div className="st-consent-num">{ c.n }</div>
                            <div className="st-consent-bar"><div style={ { width: `${c.pct}%`, background: c.fg } } /></div>
                            <div className="st-consent-pct">{ c.pct }% opted in</div>
                        </div>
                    ) ) }
                </div>

                <div className="st-section">Sender identities</div>
                <div className="st-senders">
                    { senders.map( ( s, i ) => (
                        <Link key={ i } href={ s.cfg } className="st-sender">
                            <span className="st-sender-ch">{ s.ch }</span>
                            <span className="st-sender-id">{ s.id }</span>
                        </Link>
                    ) ) }
                </div>

                <div className="st-section">Per-channel configuration</div>
                <div className="st-configs">
                    { configs.map( c => (
                        <Link key={ c.href + c.label } href={ c.href } className="st-config">
                            <span className="st-config-label">{ c.label }</span>
                            <p className="st-config-desc">{ c.desc }</p>
                        </Link>
                    ) ) }
                </div>
            </div>
            <style jsx>{ `
                .st-wrap { padding: 20px; max-width: 1000px; margin: 0 auto; }
                .st-section { font-size: var(--text-xs); font-weight: 700; text-transform: uppercase; color: ${colors.textMuted}; margin: 22px 0 10px; }
                .st-consent { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
                .st-consent-card { border: 1px solid ${colors.border}; border-radius: 12px; padding: 14px; background: #fff; }
                .st-pill { font-size: var(--text-xs); font-weight: 700; padding: 3px 9px; border-radius: 9999px; }
                .st-consent-num { font-size: var(--text-3xl); font-weight: 700; color: ${colors.text}; margin: 8px 0 4px; }
                .st-consent-bar { height: 8px; background: ${colors.bgSecondary}; border-radius: 9999px; overflow: hidden; }
                .st-consent-bar div { height: 100%; border-radius: 9999px; }
                .st-consent-pct { font-size: var(--text-xs); color: ${colors.textMuted}; margin-top: 4px; }
                .st-senders { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
                .st-sender { display: flex; flex-direction: column; gap: 2px; border: 1px solid ${colors.border}; border-radius: 10px; padding: 12px; background: #fff; text-decoration: none; }
                .st-sender:hover { border-color: ${colors.primary}; }
                .st-sender-ch { font-size: var(--text-xs); font-weight: 700; color: ${colors.textMuted}; text-transform: uppercase; }
                .st-sender-id { font-size: var(--text-sm); color: ${colors.text}; }
                .st-configs { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
                .st-config { border: 1px solid ${colors.border}; border-radius: 12px; padding: 14px; background: #fff; text-decoration: none; }
                .st-config:hover { border-color: ${colors.primary}; }
                .st-config-label { font-size: var(--text-md); font-weight: 700; color: ${colors.text}; }
                .st-config-desc { font-size: var(--text-xs); color: ${colors.textSecondary}; margin: 4px 0 0; }
            ` }</style>
        </>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Channel Settings | WECARE.DIGITAL" description="Unified channel settings & consent" noindex={ true } />
            { content }
        </Layout>
    );
};

export default SettingsPage;
