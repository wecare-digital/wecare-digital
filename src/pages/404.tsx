import React, { useEffect } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';

/**
 * PURE REDIRECT TO HOME - no visible 404 page (owner 2026-10-13).
 *
 * The site has no "page not found" screen. Every unknown URL is sent straight to the home page.
 * There are two redirect paths, both pointing at '/', so the bounce works with or without
 * JavaScript and on the static export:
 *   - a <meta http-equiv="refresh"> in the head fires immediately on first paint, before and
 *     without any script, which is the one path a static 404 can always rely on;
 *   - router.replace('/') runs once hydrated, so an in-app navigation that lands here is swapped
 *     for home without a second full load.
 * The body renders nothing visible - no heading, no card, no Subscribe/Share block - because a
 * waypoint that redirects on sight is never meant to be read. noindex so it is never surfaced,
 * and the canonical points at the destination (home), overriding _app.tsx's computed one because
 * next/head dedupes by key.
 */
const NotFound: React.FC = () => {
  const router = useRouter();
  useEffect( () => { void router.replace( '/' ); }, [ router ] );
  return (
    <Head>
      <title>WECARE.DIGITAL</title>
      <meta name="robots" content="noindex, follow" />
      <meta httpEquiv="refresh" content="0; url=/" />
      <link rel="canonical" key="canonical" href="https://wecare.digital/" />
    </Head>
  );
};

export default NotFound;
