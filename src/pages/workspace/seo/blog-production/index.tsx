/**
 * Blog Production — ONE staged page for the whole blog pipeline.
 *
 * Workspace redesign (FEAT-006): the five pipeline routes (waves, a single wave,
 * source review, QA sign-off, publish queue) used to be separate pages under
 * /workspace/seo/blog-production/**. They are now step tabs on this single hub, each
 * rendering the EXISTING page body via its `embedded` prop — so every seoApi
 * (seoToolsFetch) call site inside those bodies is unchanged, and each stage keeps
 * its own query params (?id= / ?source= / ?batch=) because they all now live on the
 * one /workspace/seo/blog-production route.
 *
 * The tab bodies live in src/components/workspace/seo/blog-production/** (relocated
 * out of the routes tree so each stops being its own route). Deep-links between the
 * stages are ?tab=<stage> plus the stage's own params; PageShell is re-keyed on the
 * full query so a client-side navigation between stages re-reads the active tab.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import PageShell, { ShellTab } from '../../../../components/PageShell';

function lazyTab<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
    return dynamic( loader, { ssr: false } );
}

const WavesPage = lazyTab( () => import( '../../../../components/workspace/seo/blog-production/Waves' ) );
const BatchPage = lazyTab( () => import( '../../../../components/workspace/seo/blog-production/Batch' ) );
const ReviewPage = lazyTab( () => import( '../../../../components/workspace/seo/blog-production/Review' ) );
const QaPage = lazyTab( () => import( '../../../../components/workspace/seo/blog-production/Qa' ) );
const PublishPage = lazyTab( () => import( '../../../../components/workspace/seo/blog-production/Publish' ) );

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const TABS: ShellTab[] = [
    { id: 'waves', label: 'Production waves' },
    { id: 'batch', label: 'Wave detail' },
    { id: 'review', label: 'Source review' },
    { id: 'qa', label: 'QA review' },
    { id: 'publish', label: 'Publish queue' },
];

// /workspace/seo/blog-production?tab=<id> deep-links open the matching stage.
function resolveDefaultTab ( raw: string | string[] | undefined ): string {
    const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
    return id && TABS.some( ( t ) => t.id === id ) ? id : 'waves';
}

const BlogProductionHub: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
    const router = useRouter();
    const defaultTab = resolveDefaultTab( router.query.tab );
    const content = (
        <PageShell
            className="blog-production-shell"
            // Re-key on the full path+query so a cross-stage deep-link (which only
            // changes the query) re-reads the active tab and the stage params.
            key={ router.asPath }
            title="Blog Production"
            subtitle="Waves, source review, QA sign-off and the publish queue"
            tabs={ TABS }
            defaultTab={ defaultTab }
        >
            { ( activeTab ) => (
                <Suspense fallback={ <div style={ { padding: 40, textAlign: 'center' } }>Loading…</div> }>
                    { activeTab === 'waves' && <WavesPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'batch' && <BatchPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'review' && <ReviewPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'qa' && <QaPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'publish' && <PublishPage signOut={ signOut } user={ user } embedded /> }
                </Suspense>
            ) }
        </PageShell>
    );

    if ( embedded ) return content;
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Blog Production | WECARE.DIGITAL" description="The AWS-native blog production pipeline" />
            { content }
        </Layout>
    );
};

export default BlogProductionHub;
