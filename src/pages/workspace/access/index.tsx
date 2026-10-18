/**
 * Access Page - Login entry point
 * URL: https://wecare.digital/workspace/access/
 * 
 * This page shows the login form (via _app.tsx Authenticator).
 * After successful login, redirects to /dashboard.
 */

import React, { useEffect } from 'react';
import { useRouter } from 'next/router';
import Head from 'next/head';
import BrandBadge from '../../../components/BrandBadge';

interface PageProps {
  signOut?: () => void;
  user?: any;
}

const AccessPage: React.FC<PageProps> = ({ user }) => {
  const router = useRouter();

  // If user is authenticated (passed from _app.tsx), redirect to the workspace
  useEffect(() => {
    if (user) {
      router.replace('/workspace/engage/inbox');
    }
  }, [user, router]);

  // Show redirecting message (user is authenticated at this point)
  return (
    <>
      <Head>
        <title>Access | WECARE.DIGITAL</title>
      </Head>
      <div className="acp-wrap">
        <div className="acp-card">
          <BrandBadge label="WECARE.DIGITAL" />
          <p className="acp-note">Redirecting to your workspace…</p>
        </div>
        <style jsx>{`
          /* Brought onto the palette. This used #f5f5f5 behind #1a1a1a with a
             300-weight heading - three values the design contract does not contain,
             on the one screen every signed-in session passes through.
             font-weight 300 is worth calling out: the Inter link in _app.tsx loads
             400;500;600;700;800 and no 300 face, so that heading was being
             synthetically lightened by the browser rather than rendered.
             It is now the same badge the home page and the sign-in form use, on
             white, with the single 20px/400 body level under it. */
          .acp-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#fff;padding:24px}
          .acp-card{display:flex;flex-direction:column;align-items:center;gap:18px;text-align:center}
          .acp-note{margin:0;font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.898)}
        `}</style>
      </div>
    </>
  );
};

export default AccessPage;
