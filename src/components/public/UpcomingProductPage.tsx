import Head from 'next/head';
import React from 'react';
import PageShell from './PageShell';
import RotatingHero from '../RotatingHero';

interface UpcomingProductPageProps {
  name: string;
  path: string;
  description: string;
  subject: string;
}

// A holding destination, not an advertised or operational product. Use the existing public
// hero and shell; no offers, checkout, financial data, tender feeds or launch-date claims.
export default function UpcomingProductPage( { name, path, description, subject }: UpcomingProductPageProps ) {
  return (
    <>
      <PageShell title={ name } canonical={ path } description={ description } />
      <Head><meta name="robots" content="noindex, follow" /></Head>
      <RotatingHero
        badgeLabel={ `${name} by WECARE.DIGITAL` }
        ariaLabel={ name }
        frame={ name }
        words={ [
          { word: subject, tint: '#dbeafe', dot: '#2563eb' },
          { word: 'Not launched', tint: '#ede9fe', dot: '#9849e8' },
        ] }
        sub={ description }
        mobileFoundation
      />
    </>
  );
}
