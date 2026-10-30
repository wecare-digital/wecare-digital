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
import { useRouter } from 'next/router';
import SEO from '../../../../components/SEO';
import PageShell, { ShellTab } from '../../../../components/PageShell';

// Loaded per tab: a channel page pulls the unified inbox/composer, so a static
// import would download all six before showing one. Generic loader keeps each
// module's own props (signOut/user/embedded) intact.
function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
    return dynamic( loader, { ssr: false } );
}

// FEAT-005: the channel tab bodies moved OUT of src/pages/workspace/engage/** into
// src/components/workspace/channels/** so each stops being its own route.
const SmsPage = lazyTab( () => import( '../../../../components/workspace/channels/Sms' ) );
const RcsPage = lazyTab( () => import( '../../../../components/workspace/channels/Rcs' ) );
const VoicePage = lazyTab( () => import( '../../../../components/workspace/channels/Voice' ) );
const VoiceInPage = lazyTab( () => import( '../../../../components/workspace/channels/VoiceIn' ) );
const EmailPage = lazyTab( () => import( '../../../../components/workspace/channels/Ses' ) );
const PushPage = lazyTab( () => import( '../../../../components/workspace/channels/Push' ) );

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const TABS: ShellTab[] = [
    { id: 'sms', label: 'SMS' },
    { id: 'rcs', label: 'RCS' },
    { id: 'voice', label: 'Voice (outbound)' },
    { id: 'voice-in', label: 'Call History' },
    { id: 'email', label: 'Email' },
    { id: 'push', label: 'Push' },
];

// FEAT-005: /workspace/engage/channels?tab=<id> deep-links open the matching tab.
function resolveDefaultTab ( raw: string | string[] | undefined ): string {
    const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
    return id && TABS.some( ( t ) => t.id === id ) ? id : 'sms';
}

const ChannelsHub: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const router = useRouter();
    const defaultTab = resolveDefaultTab( router.query.tab );
    const content = (
        <PageShell
            key={ defaultTab }
            title="Channels"
            subtitle="SMS, RCS, Voice, Email & Push — every channel beside WhatsApp"
            tabs={ TABS }
            defaultTab={ defaultTab }
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
        <>
            <SEO title="Channels | WECARE.DIGITAL" description="SMS, RCS, Voice, Email and Push in one place" noindex={ true } />
            { content }
        </>
    );
};

export default ChannelsHub;
