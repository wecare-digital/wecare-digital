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
    <section className="public-policy-tail" aria-label="Policy details">
      <div className="public-policy-inner">
        <PolicyDetails
          termsHref={ router.pathname === '/terms' || router.pathname === '/privacy' ? null : '/terms/' }
          shipping={ policy.shipping }
          returns={ policy.returns }
          refunds={ policy.refunds }
          disclaimer={ policy.disclaimer }
        />
      </div>
      <style jsx>{`
        .public-policy-tail{
          width:100%;
          max-width:var(--public-content-max);
          margin:0 auto;
          padding:0 var(--public-page-gutter) 48px;
          box-sizing:border-box;
          font-family:var(--font-sans);
          color:var(--public-text);
        }
        .public-policy-inner{width:100%;max-width:var(--public-reading-max)}
        @media(max-width:767px){
          .public-policy-tail{padding-inline:16px;padding-bottom:40px}
        }
      `}</style>
    </section>
  );
};

export default PublicPolicyDetails;
