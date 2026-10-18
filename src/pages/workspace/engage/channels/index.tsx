/**
 * Channels — ONE tabbed page for every non-WhatsApp messaging channel.
 *
 * Workspace redesign (FEAT-004): the six channel routes (SMS, RCS, Email, Voice,
 * Call History, Push) used to be separate gear rows. They are now in-page tabs on
 * this single page, each rendering the EXISTING channel page via its `embedded`
 * prop — so every src/api/client.ts call site inside those pages is unchanged and
 * each route still works standalone. RCS and Email already compose their own
 * inbox/broadcast/logs sub-tabs; those render inside the tab body here.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import PageShell, { ShellTab } from '../../../../components/PageShell';

// Loaded per tab: a channel page pulls the unified inbox/composer, so a static
// import would download all six before showing one. Generic loader keeps each
// module's own props (signOut/user/embedded) intact.
function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
    return dynamic( loader, { ssr: false } );
}

const SmsPage = lazyTab( () => import( '../sms' ) );
const RcsPage = lazyTab( () => import( '../rcs' ) );
const VoicePage = lazyTab( () => import( '../voice' ) );
const VoiceInPage = lazyTab( () => import( '../voice-in' ) );
const EmailPage = lazyTab( () => import( '../ses' ) );
const PushPage = lazyTab( () => import( '../push' ) );

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const TABS: ShellTab[] = [
    { id: 'sms', label: 'SMS' },
    { id: 'rcs', label: 'RCS' },
    { id: 'voice', label: 'Voice (outbound)' },
    { id: 'voice-in', label: 'Call History' },
    { id: 'email', label: 'Email' },
    { id: 'push', label: 'Push' },
];

const ChannelsHub: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const content = (
        <PageShell
            title="Channels"
            subtitle="SMS, RCS, Voice, Email & Push — every channel beside WhatsApp"
            tabs={ TABS }
            defaultTab="sms"
        >
            { ( activeTab ) => (
                <Suspense fallback={ <div style={ { padding: 40, textAlign: 'center' } }>Loading…</div> }>
                    { activeTab === 'sms' && <SmsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'rcs' && <RcsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'voice' && <VoicePage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'voice-in' && <VoiceInPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'email' && <EmailPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'push' && <PushPage signOut={ signOut } user={ user } embedded /> }
                </Suspense>
            ) }
        </PageShell>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Channels | WECARE.DIGITAL" description="SMS, RCS, Voice, Email and Push in one place" noindex={ true } />
            { content }
        </Layout>
    );
};

export default ChannelsHub;
