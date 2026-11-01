/** Channel Settings — sender identities and per-channel configuration. */
import React from 'react';
import Link from 'next/link';
import PageHeader from '../../../../components/PageHeader';
import SEO from '../../../../components/SEO';
import { colors } from '../../../../lib/design-tokens';
import { WHATSAPP_PHONES } from '../../../../config/constants';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const SettingsPage: React.FC<PageProps> = ( { embedded } ) => {
    const senders = [
        { ch: 'WhatsApp', id: `${WHATSAPP_PHONES.primary.name} · ${WHATSAPP_PHONES.primary.display}`, cfg: '/workspace/communications?view=manage&section=whatsapp' },
        { ch: 'WhatsApp', id: `${WHATSAPP_PHONES.secondary.name} · ${WHATSAPP_PHONES.secondary.display}`, cfg: '/workspace/communications?view=manage&section=whatsapp' },
        { ch: 'SMS', id: 'Sender WDBEEP · India DLT', cfg: '/workspace/engage/channels?tab=sms' },
        { ch: 'RCS', id: 'Sinch RCS bot', cfg: '/workspace/engage/channels?tab=rcs' },
        { ch: 'Email', id: 'noreply@wecare.digital (SES)', cfg: '/workspace/engage/channels?tab=email' },
        { ch: 'Voice', id: 'Business Calling · IVR', cfg: '/workspace/engage/channels?tab=voice' },
    ];

    const configs = [
        { label: 'WhatsApp Settings', desc: 'Profile, webhooks, WABA, calling, templates, flows', href: '/workspace/communications?view=manage&section=whatsapp' },
        { label: 'SMS', desc: 'Sender IDs and India DLT templates', href: '/workspace/engage/channels?tab=sms' },
        { label: 'RCS', desc: 'Bot config & templates (Sinch)', href: '/workspace/engage/channels?tab=rcs' },
        { label: 'Email', desc: 'SES from-address & campaigns', href: '/workspace/engage/channels?tab=email' },
        { label: 'Voice', desc: 'Plivo PSTN and AWS voice origination', href: '/workspace/engage/channels?tab=voice' },
        { label: 'Push', desc: 'Mobile push apps and device tokens', href: '/workspace/engage/channels?tab=push' },
    ];

    const content = (
        <>
            <div className="st-wrap">
                <PageHeader title="Channel Settings" subtitle="Sender identities & per-channel configuration" icon="settings" />
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
        <>
            <SEO title="Channel Settings | WECARE.DIGITAL" description="Unified channel settings & consent" noindex={ true } />
            { content }
        </>
    );
};

export default SettingsPage;
