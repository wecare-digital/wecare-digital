/**
 * Shared public chrome for the private, exact-file Vault handoff.
 *
 * /vault intentionally bypasses _app's public branch: invalid/missing targets,
 * authentication handoffs and expired or foreign files must redirect silently.
 * GetPage mounts this only after owner-scoped verification or a failed lookup
 * needs a retry action. It must not mount a floating or inline notice surface.
 */
import React from 'react';
import Header from '../Header';
import Footer from '../Footer';
import PublicShare from '../PublicShare';
import SupportWidget from '../SupportWidget';
import PublicPolicyDetails from './PublicPolicyDetails';
import { SITE_ORIGIN } from '../../config/share';

// Never share /vault/?file=<id>. Its opaque identifier identifies a private file;
// the shared public action dock may advertise only a general, non-file URL.
const SAFE_VAULT_SHARE_URL = `${ SITE_ORIGIN }/orders/`;

export default function CustomerVaultChrome ( { children }: { children: React.ReactNode } ): React.ReactElement {
  return (
    <>
      <Header />
      { children }
      <PublicPolicyDetails />
      <div className="vault-public-action-tail">
        <PublicShare
          url={ SAFE_VAULT_SHARE_URL }
          title="WECARE.DIGITAL Orders"
          label="Share Orders"
        />
        <p className="vault-share-note">
          Sharing opens Orders, not this private document.
        </p>
      </div>
      <Footer />
      <SupportWidget />
      <style jsx>{`
        .vault-public-action-tail{
          width:100%;max-width:var(--public-content-max);margin:0 auto;
          padding:0 var(--public-page-gutter) 48px;box-sizing:border-box;
          font-family:var(--font-sans);color:var(--public-text);
          min-width:0;overflow-x:hidden;overflow-x:clip;
        }
        .vault-share-note{
          max-width:var(--public-reading-max);margin:12px 0 0;
          font-size:var(--public-supporting-size);line-height:1.5;
          color:var(--public-muted);
        }
        @media(max-width:767px){
          .vault-public-action-tail{padding-inline:16px;padding-bottom:40px}
        }
      `}</style>
    </>
  );
}
