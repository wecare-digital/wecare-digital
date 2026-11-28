/**
 * Canonical Automation workspace: rules, schedules and knowledge sources.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
type View = 'rules' | 'schedules' | 'knowledge';

function lazyPanel<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

const Rules = lazyPanel<PageProps>( () => import( '../../../components/workspace/messaging/Automation' ) );
const Schedules = lazyPanel<PageProps>( () => import( '../../../components/workspace/messaging/Scheduled' ) );
const Knowledge = lazyPanel<PageProps>( () => import( '../../../components/workspace/messaging/DocsScraper' ) );

const TABS: ShellTab[] = [
  { id: 'rules', label: 'Rules' },
  { id: 'schedules', label: 'Schedules' },
  { id: 'knowledge', label: 'Knowledge' },
];

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

function resolveView ( raw: string | string[] | undefined ): View {
  const value = one( raw );
  return value === 'rules' || value === 'schedules' || value === 'knowledge' ? value : 'rules';
}

const AutomationWorkspace: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const view = resolveView( router.query.view );

  const go = ( next: View ) => {
    void router.push( { pathname: '/workspace/automation', query: { view: next } } );
  };

  return (
    <>
      <SEO
        title="Automation"
        description="Automation rules, schedules and knowledge sources."
        noindex
      />
      <PageShell
        title="Automation"
        subtitle="Rules, schedules and knowledge that support automated work."
        tabs={ TABS }
        activeTab={ view }
        defaultTab={ view }
        onTabChange={ next => go( resolveView( next ) ) }
      >
        { active => (
          <Suspense fallback={ <div className="automation-state">Loading…</div> }>
            { active === 'rules' && <Rules signOut={ signOut } user={ user } embedded /> }
            { active === 'schedules' && <Schedules signOut={ signOut } user={ user } embedded /> }
            { active === 'knowledge' && <Knowledge signOut={ signOut } user={ user } embedded /> }
          </Suspense>
        ) }
      </PageShell>

      <style jsx>{`
        .automation-state{padding:48px;text-align:center;color:var(--text-muted)}
      `}</style>
    </>
  );
};

export default AutomationWorkspace;
