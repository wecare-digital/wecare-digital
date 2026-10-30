/**
 * Workspace Service — Vault + Contribute milestone.
 *
 * These are the only two visible Service capabilities in this milestone:
 * - Vault: manual secure-download operations, no customer Meta Flow.
 * - Contribute: voluntary payment, no fulfilment Flow.
 *
 * Requests, Appointments, Drop Docs and other Flow-backed service launchers stay out until their
 * contracts are deliberately added back.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
type ServiceView = 'vault' | 'contribute';

const SecureFiles = dynamic(
  () => import( '../../../components/workspace/service/SecureFiles' ),
  { ssr: false },
);
const Contribute = dynamic(
  () => import( '../../../components/workspace/service/Contribute' ),
  { ssr: false },
);

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

function serviceView ( raw: string | string[] | undefined ): ServiceView {
  return one( raw ) === 'contribute' ? 'contribute' : 'vault';
}

const ServicePage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const active = serviceView( router.query.view );

  const select = ( view: ServiceView ) => {
    void router.push( {
      pathname: '/workspace/service',
      query: view === 'vault' ? {} : { view },
    } );
  };

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO
        title="Service"
        description="Vault delivery and voluntary contribution operations."
        noindex
      />

      <nav className="service-switch" aria-label="Service workspace">
        <button type="button" aria-pressed={ active === 'vault' }
          className={ active === 'vault' ? 'active' : '' } onClick={ () => select( 'vault' ) }>
          Vault
        </button>
        <button type="button" aria-pressed={ active === 'contribute' }
          className={ active === 'contribute' ? 'active' : '' } onClick={ () => select( 'contribute' ) }>
          Contribute
        </button>
      </nav>

      <Suspense fallback={ <div className="service-loading">Loading { active === 'vault' ? 'Vault' : 'Contribute' }…</div> }>
        { active === 'vault'
          ? <SecureFiles signOut={ signOut } user={ user } embedded />
          : <Contribute /> }
      </Suspense>

      <style jsx>{`
        .service-switch{
          display:inline-flex;
          gap:6px;
          padding:5px;
          margin:0 0 22px;
          border:1px solid var(--border);
          border-radius:999px;
          background:var(--surface);
        }
        .service-switch button{
          min-height:38px;
          padding:0 16px;
          border:0;
          border-radius:999px;
          background:transparent;
          color:var(--text-muted);
          font:800 14px/1 var(--font-sans);
          cursor:pointer;
        }
        .service-switch button.active{
          background:var(--lime);
          color:var(--accent);
        }
        .service-switch button:focus-visible{
          outline:2px solid var(--accent);
          outline-offset:2px;
        }
        .service-loading{
          padding:48px;
          text-align:center;
          color:var(--text-muted);
        }
      `}</style>
    </Layout>
  );
};

export default ServicePage;
