import Head from 'next/head';
import React from 'react';
import PageShell from './PageShell';
import RotatingHero from '../RotatingHero';

interface UpcomingProductPageProps {
  name: string;
  path: string;
  description: string;
}

// A holding destination, not an advertised or operational product. Use the existing public
// hero and shell; no offers, checkout, financial data, tender feeds or launch-date claims.
export default function UpcomingProductPage( { name, path, description }: UpcomingProductPageProps ) {
  return (
    <>
      <PageShell title={ name } canonical={ path } description={ description } />
      <Head><meta name="robots" content="noindex, follow" /></Head>
      <RotatingHero
        ariaLabel={ name }
        frame={ name }
        words={ [ { word: 'Coming soon', tint: '#dbeafe', dot: '#2563eb' } ] }
        sub={ description }
        mobileFoundation
      />
    </>
  );
}
