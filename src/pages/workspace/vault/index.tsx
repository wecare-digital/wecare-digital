import React from 'react';
import SEO from '../../../components/SEO';
import PageShell from '../../../components/PageShell';
import VaultWorkspace from '../../../components/workspace/pay/VaultWorkspace';
export default function VaultPage(){return <><SEO title="Vault" description="Private file upload, verified payment and access delivery" noindex/><PageShell title="Vault" tabs={[]} showChrome={false}>{()=> <VaultWorkspace/>}</PageShell></>;}
