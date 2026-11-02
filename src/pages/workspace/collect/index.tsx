import React from 'react';
import SEO from '../../../components/SEO';
import PageShell from '../../../components/PageShell';
import CollectWorkbench from '../../../components/workspace/pay/CollectWorkbench';
export default function CollectPage(){return <><SEO title="Collect" description="Custom invoices, payment and receipt evidence" noindex/><PageShell title="Collect" tabs={[]} showChrome={false}>{()=> <CollectWorkbench/>}</PageShell></>;}
