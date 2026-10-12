/** The CDN serves HTTP 404; every missing path then navigates to the canonical home. */
import React, { useEffect } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import PublicShare from '../components/PublicShare';
import ContributeBlock from '../components/ContributeBlock';

const NotFound: React.FC = () => {
  const router = useRouter();
  useEffect( () => { void router.replace( '/' ); }, [ router ] );
  return (
    <>
      <Head>
        <title>WECARE.DIGITAL</title>
        {/* noindex, follow. The page is a waypoint, so it should never be indexed - but the
            link out of it leads back into the site and there is no reason to stop a crawler
            using it. The canonical points at the destination, not at this URL, and overrides
            _app.tsx's computed one because next/head dedupes by key. */}
        <meta name="robots" content="noindex, follow" />
        <link rel="canonical" key="canonical" href="https://wecare.digital/" />
      </Head>

      <main className="nf-shell">
        <div className="nf-in">
          <p className="nf-sub">This page is unavailable.</p>
          {/* A full document load, deliberately. This is the escape hatch from a route that
              does not exist, so the router's own state is the thing least worth trusting;
              and on a static export the anchor works with no JavaScript at all, which is
              the one property a 404 page should never give up. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a className="nf-cta" href="/">Go to WECARE.DIGITAL</a>

          {/* Subscribe + Share, so no public route is without the block. NOTE: this page
              redirects to '/' on mount, so a visitor rarely sees it - the block is here for
              sitewide consistency, not because the 404 is a real destination. */}
          <ContributeBlock />
          <PublicShare />
        </div>

        <style jsx>{`
          /* padding-top clears the fixed header - 108px, and 96px below 768px, the same two
             values the home page carries. min-height uses dvh after vh so a phone browser
             sizes this to the viewport it actually shows rather than the one it would show
             with the chrome hidden. */
          .nf-shell{
            min-height:100vh;
            min-height:100dvh;
            padding-top:108px;
            box-sizing:border-box;
            background:#fff;
            font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
            color:#1a1a1a;
            display:flex;
            align-items:center;
          }
          .nf-in{width:100%;max-width:1300px;margin:0 auto;padding:64px 24px 96px;box-sizing:border-box}
          .nf-sub{margin:0 0 24px;font-size:18px;line-height:1.5;color:rgba(0,0,0,.6)}
          /* The lime pill, matching .home-close-cta, so the one action here looks like the
             one action on the home page. */
          .nf-cta{
            display:inline-flex;align-items:center;justify-content:center;
            min-height:52px;padding:0 28px;
            background:#d1f470;border:2px solid #1a3a2a;border-radius:50px;
            color:#1a3a2a;font-size:17px;font-weight:600;text-decoration:none;
            transition:background-color .2s,transform .2s;
          }
          .nf-cta:hover{background:#fff;transform:translateY(-1px)}
          .nf-cta:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

          @media(max-width:767px){
            .nf-shell{padding-top:96px}
            .nf-in{padding:40px 16px 64px}
          }
          @media(prefers-reduced-motion:reduce){.nf-cta{transition:none}}
        `}</style>
      </main>
    </>
  );
};

export default NotFound;
