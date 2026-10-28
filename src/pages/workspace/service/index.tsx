/**
 * Canonical Service workspace.
 *
 * Service is organized by operator job, not by every backend table or customer-facing step:
 * Requests | Appointments | Drop Docs | Vault.
 *
 * Submit/Track/Amend, Sehat appointments, Secure Files, Enterprise cases, Reviews and FAQ remain real
 * capabilities, but they open contextually from the relevant mode instead of becoming fourteen
 * permanent tabs. The shared ResponsesQueue is the authoritative submission/request queue across
 * website and WhatsApp Flows.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

function lazyPanel<P> ( loader: () => Promise<{ default: React.ComponentType<P> }> ) {
  return dynamic( loader, { ssr: false } );
}

const Requests = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/RequestResponses' ) );
const Appointments = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/Appointments' ) );
const Documents = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/Documents' ) );
const SubmitRequest = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/SubmitRequest' ) );
const TrackRequest = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/TrackRequest' ) );
const AmendRequest = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/AmendRequest' ) );
const SehatAppointments = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/SehatAppointments' ) );
const SecureFiles = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/SecureFiles' ) );
const Enterprise = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/Enterprise' ) );
const Reviews = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/Reviews' ) );
const Faq = lazyPanel<PageProps>( () => import( '../../../components/workspace/service/Faq' ) );

type View = 'requests' | 'appointments' | 'documents' | 'vault';
type Action = 'submit' | 'track' | 'amend' | 'sehat-appointments' | 'secure-files' | 'enterprise' | 'reviews' | 'faq';

const VALID_VIEWS = new Set<View>( [ 'requests', 'appointments', 'documents', 'vault' ] );
const VALID_ACTIONS = new Set<Action>( [
  'submit', 'track', 'amend', 'sehat-appointments', 'secure-files', 'enterprise', 'reviews', 'faq',
] );

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

function viewFrom ( raw: string | string[] | undefined ): View {
  const value = one( raw ) as View;
  return VALID_VIEWS.has( value ) ? value : 'requests';
}

function actionFrom ( raw: string | string[] | undefined ): Action | null {
  const value = one( raw ) as Action;
  return VALID_ACTIONS.has( value ) ? value : null;
}

const ACTION_LABELS: Record<Action, string> = {
  submit: 'Submit request',
  track: 'Track request',
  amend: 'Amend request',
  'sehat-appointments': 'Sehat appointments',
  'secure-files': 'Vault',
  enterprise: 'Enterprise cases',
  reviews: 'Reviews',
  faq: 'FAQ',
};

const ServicePage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const view = viewFrom( router.query.view );
  const action = actionFrom( router.query.action );

  const go = ( nextView: View, nextAction?: Action ) => {
    const query: Record<string, string> = { view: nextView };
    if ( nextAction ) query.action = nextAction;
    void router.push( { pathname: '/workspace/service', query } );
  };

  const clearAction = () => go( view );

  const renderAction = () => {
    switch ( action ) {
      case 'submit': return <SubmitRequest signOut={ signOut } user={ user } embedded />;
      case 'track': return <TrackRequest signOut={ signOut } user={ user } embedded />;
      case 'amend': return <AmendRequest signOut={ signOut } user={ user } embedded />;
      case 'sehat-appointments': return <SehatAppointments signOut={ signOut } user={ user } embedded />;
      case 'secure-files': return <SecureFiles signOut={ signOut } user={ user } embedded manageOnly />;
      case 'enterprise': return <Enterprise signOut={ signOut } user={ user } embedded />;
      case 'reviews': return <Reviews signOut={ signOut } user={ user } embedded />;
      case 'faq': return <Faq signOut={ signOut } user={ user } embedded />;
      default: return null;
    }
  };

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Service" description="Customer requests, appointments and documents." noindex />
      <div className="service-page">
        <header className="service-head">
          <div>
            <p className="eyebrow">Workspace</p>
            <h1>Service</h1>
            <p>Customer requests, appointments and documents in one operational workspace.</p>
          </div>
        </header>

        <nav className="service-tabs" aria-label="Service">
          { ( [ 'requests', 'appointments', 'documents', 'vault' ] as View[] ).map( ( id ) => (
            <button key={ id } type="button" className={ view === id && !action ? 'active' : '' }
              aria-current={ view === id && !action ? 'page' : undefined }
              onClick={ () => go( id ) }>
              { id === 'requests' ? 'Requests' : id === 'appointments' ? 'Appointments' : id === 'documents' ? 'Drop Docs' : 'Vault' }
            </button>
          ) ) }
        </nav>

        <Suspense fallback={ <div className="service-loading">Loading…</div> }>
          { action ? (
            <section aria-label={ ACTION_LABELS[ action ] }>
              <button type="button" className="service-back" onClick={ clearAction }>
                ← { view === 'requests' ? 'Requests' : view === 'appointments' ? 'Appointments' : view === 'documents' ? 'Drop Docs' : 'Vault' }
              </button>
              <div className="action-head">
                <h2>{ ACTION_LABELS[ action ] }</h2>
              </div>
              { renderAction() }
            </section>
          ) : (
            <>
              { view === 'requests' && (
                <section>
                  <div className="context-actions" aria-label="Request actions">
                    <button type="button" onClick={ () => go( 'requests', 'submit' ) }>+ Submit request</button>
                    <button type="button" onClick={ () => go( 'requests', 'track' ) }>Track</button>
                    <button type="button" onClick={ () => go( 'requests', 'amend' ) }>Amend</button>
                  </div>
                  <Requests signOut={ signOut } user={ user } embedded />
                  <div className="secondary-tools" aria-label="Service management">
                    <button type="button" onClick={ () => go( 'requests', 'enterprise' ) }>
                      <strong>Enterprise cases</strong><span>Case management and escalation</span>
                    </button>
                    <button type="button" onClick={ () => go( 'requests', 'reviews' ) }>
                      <strong>Reviews</strong><span>Customer reviews and moderation</span>
                    </button>
                    <button type="button" onClick={ () => go( 'requests', 'faq' ) }>
                      <strong>FAQ</strong><span>Customer-service knowledge entries</span>
                    </button>
                  </div>
                </section>
              ) }
              { view === 'appointments' && (
                <section>
                  <div className="context-actions" aria-label="Appointment actions">
                    <button type="button" onClick={ () => go( 'appointments', 'sehat-appointments' ) }>Manage Sehat appointments</button>
                  </div>
                  <Appointments signOut={ signOut } user={ user } embedded />
                </section>
              ) }
              { view === 'documents' && (
                <section>
                  <Documents signOut={ signOut } user={ user } embedded />
                </section>
              ) }
              { view === 'vault' && (
                <section>
                  <SecureFiles signOut={ signOut } user={ user } embedded manageOnly />
                </section>
              ) }
            </>
          ) }
        </Suspense>
      </div>

      <style jsx>{`
        .service-page{width:min(100%,1280px);margin:0 auto;padding:clamp(16px,3vw,32px);box-sizing:border-box;min-width:0}
        .service-head{margin-bottom:18px}
        .eyebrow{margin:0 0 4px;color:var(--text-muted);font-size:var(--text-xs);font-weight:700;text-transform:uppercase;letter-spacing:.08em}
        .service-head h1{margin:0;color:var(--text);font-size:clamp(28px,5vw,48px);line-height:1.05;letter-spacing:-.035em}
        .service-head>div>p:last-child{margin:8px 0 0;color:var(--text-muted);font-size:var(--text-md);max-width:720px}
        .service-tabs{display:flex;gap:6px;width:max-content;max-width:100%;padding:4px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:14px;margin-bottom:18px}
        .service-tabs button{min-height:44px;min-width:92px;padding:8px 16px;border:0;border-radius:10px;background:transparent;color:var(--text-muted);font:inherit;font-weight:700;cursor:pointer}
        .service-tabs button.active{background:#fff;color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.08)}
        .context-actions{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
        .context-actions button,.service-back{min-height:44px;padding:8px 14px;border:1px solid var(--border);border-radius:12px;background:#fff;color:var(--text);font:inherit;font-weight:650;cursor:pointer}
        .context-actions button:hover,.context-actions button:focus-visible,.service-back:hover,.service-back:focus-visible{border-color:var(--lime);background:var(--bg-secondary)}
        .service-back{border-color:transparent;padding-inline-start:0;margin-bottom:6px}
        .action-head h2{margin:0 0 14px;color:var(--text);font-size:var(--h3)}
        .secondary-tools{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:20px}
        .secondary-tools button{min-height:86px;padding:14px;text-align:left;border:1px solid var(--border);border-radius:14px;background:#fff;color:var(--text);font:inherit;cursor:pointer;display:flex;flex-direction:column;gap:4px}
        .secondary-tools button:hover,.secondary-tools button:focus-visible{border-color:var(--lime);background:var(--bg-secondary)}
        .secondary-tools strong{font-size:var(--text-md)}
        .secondary-tools span{font-size:var(--text-xs);color:var(--text-muted);line-height:1.4}
        .service-loading{padding:48px;text-align:center;color:var(--text-muted)}
        @media(max-width:760px){
          .service-page{padding-left:max(14px,env(safe-area-inset-left));padding-right:max(14px,env(safe-area-inset-right));padding-bottom:max(24px,env(safe-area-inset-bottom))}
          .service-tabs{width:100%;overflow-x:auto}
          .service-tabs button{flex:1;min-width:104px}
          .secondary-tools{grid-template-columns:1fr}
        }
        @media(max-width:420px){
          .service-tabs button{min-width:96px;padding-inline:10px}
          .context-actions{display:grid;grid-template-columns:1fr 1fr}
          .context-actions button:first-child{grid-column:1/-1}
        }
        @media(prefers-reduced-motion:reduce){.service-tabs{scroll-behavior:auto}}
        @media(forced-colors:active){.service-tabs,.context-actions button,.secondary-tools button{border-color:CanvasText}}
      `}</style>
    </Layout>
  );
};

export default ServicePage;
