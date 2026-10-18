/**
 * Connect WABA — in-app Embedded Signup (protected)
 *
 * Lets an authenticated admin connect a WhatsApp Business Account via Meta's
 * Embedded Signup (Facebook Login for Business). Same flow as the public
 * /partners/ page, but inside the dashboard and not gated by the public flag
 * (only needs NEXT_PUBLIC_FB_ES_CONFIG_ID).
 */
import React from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import EmbeddedSignupPanel from '../../../components/EmbeddedSignupPanel';
import { useToastContext } from '../../../contexts/ToastContext';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 24, marginBottom: 16 };

const ConnectWabaPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();

    const content = (
        <div style={ { maxWidth: 820, margin: '0 auto', padding: 16 } }>
            <SEO title="Connect WABA — Embedded Signup" description="Connect a WhatsApp Business Account via Meta Embedded Signup." noindex />
            <h1 style={ { fontSize: 22, fontWeight: 700, marginBottom: 4 } }>Connect WhatsApp Business Account</h1>
            <p style={ { color: '#777', fontSize: 13, marginBottom: 16 } }>
                Link a WABA through Meta’s official Embedded Signup. The authorization is exchanged
                server-side; tokens are stored securely and never shown in the browser.
            </p>

            <div style={ card }>
                <EmbeddedSignupPanel
                    admin
                    onConnected={ ( r ) => toast.success( `Connected WABA ${r.wabaId || ''}` ) }
                />
            </div>

            <div style={ { ...card, fontSize: 13, color: '#555' } }>
                <div style={ { fontWeight: 700, color: '#1a3a2a', marginBottom: 8 } }>Before you start</div>
                <ul style={ { margin: 0, paddingLeft: 18, lineHeight: 1.7 } }>
                    <li>A Meta Tech Provider Configuration (config id) must be set for this app.</li>
                    <li>Your Meta Business must have completed Business Verification.</li>
                    <li>On finish, the connected WABA is subscribed to our app and its number registered.</li>
                </ul>
            </div>
        </div>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default ConnectWabaPage;
