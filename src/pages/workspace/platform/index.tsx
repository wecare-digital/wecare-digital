/**
 * Platform — ONE tabbed hub for every infrastructure / diagnostics surface.
 *
 * Platform is a first-class workspace. The former Settings/Platform hub is retired to a
 * compatibility redirect; MCP Connections, architecture/inventory snapshots, Code Repo,
 * WA Graph Tools, CORS and the design reference remain lazy-loaded tools here. They are in-page
 * tabs on this single hub, each rendering the EXISTING page body via its `embedded`
 * prop — so every src/api/client.ts / workspaceMCP call site inside those pages is
 * unchanged. Architecture snapshot is a large document with its own internal tab
 * system; it renders here as a tab body unchanged.
 *
 * The tab bodies live in src/components/workspace/platform/**. Navigation and search deep-link
 * this hub with ?view=; PageShell opens the matching tool without creating more route files.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

// Loaded per tab: these infra pages are heavy (static registries, Graph tools, a
// 1,600-line design reference), so a static import would download all seven before
// showing one. Generic loader keeps each module's own props (signOut/user/embedded).
function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
    return dynamic( loader, { ssr: false } );
}

const MCPConnectionsPage = lazyTab( () => import( '../../../components/workspace/platform/MCPConnections' ) );
const SystemArchitecturePage = lazyTab( () => import( '../../../components/workspace/platform/SystemArchitecture' ) );
const LambdaFunctionsPage = lazyTab( () => import( '../../../components/workspace/platform/LambdaFunctions' ) );
const CodeRepoPage = lazyTab( () => import( '../../../components/workspace/platform/CodeRepo' ) );
const WaGraphToolsPage = lazyTab( () => import( '../../../components/workspace/platform/WaGraphTools' ) );
const CorsSettingsPage = lazyTab( () => import( '../../../components/workspace/platform/CorsSettings' ) );
const DesignReferencePage = lazyTab( () => import( '../../../components/workspace/platform/DesignReference' ) );

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const TABS: ShellTab[] = [
    { id: 'mcp-connections', label: 'MCP Connections' },
    { id: 'system-architecture', label: 'Architecture snapshot' },
    { id: 'lambda-functions', label: 'Lambda inventory snapshot' },
    { id: 'code-repo', label: 'Code Repo' },
    { id: 'wa-graph-tools', label: 'WA Graph Tools' },
    { id: 'cors-settings', label: 'CORS Settings' },
    { id: 'design-reference', label: 'Design Reference' },
];

// /workspace/platform?view=<id> deep-links open the matching tool.
function resolveDefaultTab ( raw: string | string[] | undefined ): string {
    const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
    return id && TABS.some( ( t ) => t.id === id ) ? id : 'mcp-connections';
}

const PlatformHub: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const router = useRouter();
    const defaultTab = resolveDefaultTab( router.query.view ?? router.query.tab );
    const content = (
        <PageShell
            key={ defaultTab }
            title="Platform"
            subtitle="Infrastructure, integrations and diagnostics"
            tabs={ TABS }
            defaultTab={ defaultTab }
        >
            { ( activeTab ) => (
                <Suspense fallback={ <div style={ { padding: 40, textAlign: 'center' } }>Loading…</div> }>
                    { activeTab === 'mcp-connections' && <MCPConnectionsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'system-architecture' && <SystemArchitecturePage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'lambda-functions' && <LambdaFunctionsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'code-repo' && <CodeRepoPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'wa-graph-tools' && <WaGraphToolsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'cors-settings' && <CorsSettingsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'design-reference' && <DesignReferencePage signOut={ signOut } user={ user } embedded /> }
                </Suspense>
            ) }
        </PageShell>
    );

    if ( embedded ) return content;
    return (
        <>
            <SEO title="Platform | WECARE.DIGITAL" description="Infrastructure, integrations and diagnostics" noindex={ true } />
            { content }
        </>
    );
};

export default PlatformHub;
