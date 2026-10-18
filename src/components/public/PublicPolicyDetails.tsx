import React from 'react';
import { useRouter } from 'next/router';
import PolicyDetails from './PolicyDetails';
import { publicPolicyDetailsForRoute } from '../../content/publicPolicyDetails';

/**
 * One shared tail disclosure for public pages that do not already render PolicyDetails
 * inside their own commerce block. The resolver deliberately returns null for home,
 * the redirect-only 404 document, and product routes that already own the component.
 */
const PublicPolicyDetails: React.FC = () => {
  const router = useRouter();
  const policy = publicPolicyDetailsForRoute( router.pathname );
  if ( !policy ) return null;

  return (
    <section
      aria-label="Policy details"
      style={ {
        width: '100%',
        maxWidth: 1300,
        margin: '0 auto',
        padding: '0 24px 48px',
        boxSizing: 'border-box',
      } }
    >
      <div style={ { width: '100%', maxWidth: 700 } }>
        <PolicyDetails
          overview={ policy.overview }
          shipping={ policy.shipping }
          returns={ policy.returns }
          refunds={ policy.refunds }
          disclaimer={ policy.disclaimer }
        />
      </div>
    </section>
  );
};

export default PublicPolicyDetails;
