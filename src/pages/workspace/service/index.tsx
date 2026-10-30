/**
 * Workspace Service — Vault-only milestone.
 *
 * Vault is intentionally manual. It has no customer Meta Flow and this page must not expose
 * Requests, Appointments, Drop Docs or any contextual service launcher until those workflows
 * are added back deliberately in later milestones.
 */
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const SecureFiles = dynamic(
  () => import( '../../../components/workspace/service/SecureFiles' ),
  { ssr: false },
);

const ServicePage: React.FC<PageProps> = ( { signOut, user } ) => (
  <Layout user={ user } onSignOut={ signOut }>
    <SEO
      title="Vault"
      description="Manual Vault document delivery and access management."
      noindex
    />
    <Suspense fallback={ <div className="service-loading">Loading Vault…</div> }>
      <SecureFiles signOut={ signOut } user={ user } embedded />
    </Suspense>

    <style jsx>{`
      .service-loading{
        padding:48px;
        text-align:center;
        color:var(--text-muted);
      }
    `}</style>
  </Layout>
);

export default ServicePage;
