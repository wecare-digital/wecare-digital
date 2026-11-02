/**
 * Canonical Automation & AI workspace.
 *
 * Staff agent operations are separate from the customer-facing Meta Business Agent, which stays
 * with Communications/WhatsApp. The internal-agent settings page remains configuration only.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/router';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
type View = 'agent' | 'rules' | 'schedules' | 'knowledge';

function lazyPanel<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

const Rules = lazyPanel<PageProps>( () => import( '../../../components/workspace/messaging/Automation' ) );
const Schedules = lazyPanel<PageProps>( () => import( '../../../components/workspace/messaging/Scheduled' ) );
const Knowledge = lazyPanel<PageProps>( () => import( '../../../components/workspace/messaging/DocsScraper' ) );

const TABS: ShellTab[] = [
  { id: 'agent', label: 'Staff agent' },
  { id: 'rules', label: 'Rules' },
  { id: 'schedules', label: 'Schedules' },
  { id: 'knowledge', label: 'Knowledge' },
];

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

function resolveView ( raw: string | string[] | undefined ): View {
  const value = one( raw );
  return value === 'rules' || value === 'schedules' || value === 'knowledge' ? value : 'agent';
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
        title="Automation & AI"
        description="Staff agent, automation rules, schedules and knowledge sources."
        noindex
      />
      <PageShell
        title="Automation & AI"
        subtitle="Operate the staff assistant and the rules, schedules and knowledge that support automated work."
        tabs={ TABS }
        activeTab={ view }
        defaultTab={ view }
        onTabChange={ next => go( resolveView( next ) ) }
      >
        { active => (
          <Suspense fallback={ <div className="automation-state">Loading…</div> }>
            { active === 'agent' && (
              <section className="automation-mode">
                <div className="automation-context">
                  <div>
                    <strong>Legacy assistant retired</strong>
                    <span>The outdated /ai/generate assistant is disconnected. No automated customer messages or payments are issued here.</span>
                  </div>
                  <Link href="/workspace/settings/internal-agent">Agent configuration →</Link>
                </div>
                <p role="status">The legacy staff AI assistant has been retired. Automation rules, schedules and knowledge tools remain available. A replacement agent requires a separate reviewed integration.</p>
              </section>
            ) }
            { active === 'rules' && <Rules signOut={ signOut } user={ user } embedded /> }
            { active === 'schedules' && <Schedules signOut={ signOut } user={ user } embedded /> }
            { active === 'knowledge' && <Knowledge signOut={ signOut } user={ user } embedded /> }
          </Suspense>
        ) }
      </PageShell>

      <style jsx>{`
        .automation-mode{min-width:0}
        .automation-state{padding:48px;text-align:center;color:var(--text-muted)}
        .automation-context{
          display:flex;align-items:flex-start;justify-content:space-between;gap:16px;
          padding:12px 14px;margin:0 0 16px;border:1px solid var(--border);
          border-radius:14px;background:var(--bg-secondary)
        }
        .automation-context>div{display:flex;flex-direction:column;gap:3px;min-width:0}
        .automation-context strong{font-size:var(--text-sm);color:var(--text)}
        .automation-context span{font-size:var(--text-xs);line-height:1.5;color:var(--text-muted)}
        .automation-context :global(a){
          min-height:44px;display:inline-flex;align-items:center;white-space:nowrap;
          padding:8px 12px;border:1px solid var(--border);border-radius:11px;background:#fff;
          color:var(--text);text-decoration:none;font-size:var(--text-sm);font-weight:650
        }
        .automation-context :global(a:hover),.automation-context :global(a:focus-visible){border-color:var(--lime)}
        @media(max-width:640px){
          .automation-context{flex-direction:column}
          .automation-context :global(a){align-self:flex-start}
        }
        @media(forced-colors:active){.automation-context{border-color:CanvasText}}
      `}</style>
    </>
  );
};

export default AutomationWorkspace;
