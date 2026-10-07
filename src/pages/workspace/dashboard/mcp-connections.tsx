import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import MCPPlayground from '../../../components/workspace/MCPPlayground';
import { useUserRole } from '../../../hooks/useUserRole';
import { MCPConnection, metaAuthorizationURL, workspaceMCP } from '../../../lib/workspace-mcp';
import styles from '../../../styles/MCPConnections.module.css';

const names: Record<string, string> = {
  'meta-social': 'Meta Social', whatsapp: 'WhatsApp Business Tools', aws: 'AWS', github: 'GitHub',
  wix: 'Wix', razorpay: 'Razorpay', 'google-cloud': 'Google Cloud', 'google-ads': 'Google Ads',
  'meta-ads': 'Meta Ads', plivo: 'Plivo', sinch: 'Sinch',
};
const descriptions: Record<string, string> = {
  'remote-mcp': 'Connect your account, then verify an authorized read.',
  'oauth-sdk': 'Connect your Google account, then verify an authorized read.',
  sdk: 'Check the AWS-backed account connection.',
  'pending-adapter': 'Dashboard connection is not available yet.',
  'documentation-only': 'Documentation access. Live account access is not connected.',
};
const statusNames: Record<string, string> = {
  consent_required: 'Sign-in needed', authorized_unverified: 'Ready to verify', verified: 'Verified',
  refresh_or_consent_required: 'Check renewal', refresh_pending: 'Automatic renewal available', sdk: 'Ready to check',
  'pending-adapter': 'Adapter pending', 'documentation-only': 'Documentation only',
  documentation_verified: 'Documentation verified',
  mcp_client_required: 'MCP client required',
  authenticated: 'MCP authenticated · account read pending',
};
interface Authorization { url: string; expires: number; }

export default function MCPConnections({ user, signOut }: { user?: any; signOut?: () => void }) {
  const role = useUserRole();
  const admin = role.groups.includes('Admin');
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [authorizations, setAuthorizations] = useState<Record<string, Authorization>>({});
  const [readProvider, setReadProvider] = useState('aws');
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [checks, setChecks] = useState<Record<string, string>>({});
  const [activity, setActivity] = useState<string[]>([]);
  const [now, setNow] = useState(Date.now());
  const load = useCallback(async () => {
    setBusy(true); setError('');
    try { setConnections((await workspaceMCP<{ connections: MCPConnection[] }>('connections_list')).connections); }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to load connections.'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { if (admin && !role.loading) void load(); }, [admin, role.loading, load]);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const run = async (providers: string[]) => {
    setBusy(true); setError('');
    for (const provider of providers) {
      try {
        const value = await workspaceMCP<Record<string, unknown>>(
          'connection_verify', { provider },
        );
        setChecks(old => ({ ...old, [provider]: statusNames[String(value.status)] || 'Check needed' }));
        setFailures(old => { const next = { ...old }; delete next[provider]; return next; });
        setAuthorizations(old => { const next = { ...old }; delete next[provider]; return next; });
        const read = (value.read || {}) as Record<string, unknown>;
        const detail = provider === 'aws' ? `Account ${read.account} · ${read.region}`
          : provider === 'github' ? `${read.repository} · ${read.defaultBranch}`
          : value.status === 'documentation_verified' ? 'Documentation MCP verified; live account access is separate'
          : value.status === 'authenticated' ? 'MCP tool discovery passed; account read remains pending' : 'Authorized read passed';
        setActivity(old => [`${names[provider] || provider}: ${detail}`, ...old].slice(0, 20));
      } catch (e) {
        setChecks(old => ({ ...old, [provider]: 'Check needed' }));
        setFailures(old => ({ ...old, [provider]: e instanceof Error ? e.message : 'Check failed' }));
        setActivity(old => [`${names[provider] || provider}: ${e instanceof Error ? e.message : 'Check failed'}`, ...old].slice(0, 20));
      }
    }
    await load();
  };
  const connect = async (provider: string) => {
    setBusy(true); setError('');
    try {
      const result = await workspaceMCP<{ authorizationUrl: string; expiresIn: number }>('connection_authorize', { provider });
      const url = metaAuthorizationURL(result.authorizationUrl);
      setAuthorizations(old => ({ ...old, [provider]: { url, expires: Date.now() + Math.min(result.expiresIn, 600) * 1000 } }));
      setChecks(old => { const next = { ...old }; delete next[provider]; return next; });
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unable to start sign-in.';
      setFailures(old => ({ ...old, [provider]: message }));
      setChecks(old => ({ ...old, [provider]: 'Authorization blocked' }));
      setAuthorizations(old => { const next = { ...old }; delete next[provider]; return next; });
    }
    finally { setBusy(false); }
  };
  return <Layout user={user} onSignOut={signOut}>
    <SEO title="MCP Connections" description="Manage workspace integrations" noindex />
    <main className={`inner-page-container ${styles.page}`}>
      <header className={styles.header}>
        <div><Link href="/workspace/dashboard/">Dashboard</Link><h1>MCP Connections</h1>
          <p>Connect accounts and check your workspace integrations in one place.</p></div>
        {admin && <Button icon="refresh" disabled={busy} onClick={() => void load()}>Refresh</Button>}
      </header>
      {role.loading ? <p role="status">Checking your access…</p> : !admin ?
        <p className={styles.notice}>A staff Admin account is required to manage MCP connections.</p> : <>
        <p className={styles.notice}>Connections are saved securely for your staff account and remain after signing out or closing your browser. Google access renews automatically while its saved authorization remains valid. Check renewal before reconnecting. Meta may require new consent when permissions or access expire. After sign-in, return here and select Verify. Desktop MCP authorizations are separate.</p>
        {error && <p className={styles.notice} role="alert">{error}</p>}
        <div className={styles.toolbar}>
          <span>{selected.length} selected</span>
          <Button variant="primary" disabled={busy || !selected.length} onClick={() => void run(selected)}>Check selected</Button>
          {busy && <span role="status">Working…</span>}
        </div>
        <div className={styles.grid}>
          {connections.map(connection => {
            const provider = connection.provider;
            const remote = connection.kind === 'remote-mcp' || connection.kind === 'oauth-sdk';
            const supported = remote || connection.kind === 'sdk' || connection.kind === 'documentation-only';
            const authorization = authorizations[provider];
            const validLink = authorization && authorization.expires > now;
            return <section className={styles.card} key={provider} aria-label={names[provider] || provider}>
              <div className={styles.cardHeader}><h2>{names[provider] || provider}</h2>
                {supported && <input type="checkbox" aria-label={`Select ${names[provider] || provider}`} checked={selected.includes(provider)} disabled={busy}
                  onChange={e => setSelected(old => e.target.checked ? [...old, provider] : old.filter(item => item !== provider))} />}</div>
              <span className={styles.badge}>{checks[provider] || statusNames[connection.status] || connection.status}</span>
              <p>{descriptions[connection.kind] || 'Connection status unavailable.'}</p>
              {remote && <p>{connection.automaticRefresh === true ? 'Saved authorization supports automatic renewal.' : 'Saved authorization persists; renewal depends on the provider.'}</p>}
              {failures[provider] && <p className={styles.notice} role="alert">{failures[provider]}</p>}
              {connection.lastVerifiedAt && <p>Last verified: {new Date(connection.lastVerifiedAt * 1000).toLocaleString()}</p>}
              <div className={styles.actions}>
                {remote && <Button variant="primary" disabled={busy} onClick={() => void connect(provider)}>Connect</Button>}
                {supported && <Button disabled={busy} onClick={() => void run([provider])}>{remote ? 'Verify' : 'Check connection'}</Button>}
                {supported && <a href="#playground" onClick={() => setReadProvider(provider)}>View data</a>}
              </div>
              {validLink && <div className={styles.notice}><a href={authorization.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Continue with {provider.startsWith('google-') ? 'Google' : 'Meta'} ↗</a><p>Complete sign-in, then return and verify.</p></div>}
              {authorization && !validLink && <p className={styles.notice}>Sign-in link expired. Select Connect for a fresh link.</p>}
            </section>;
          })}
        </div>
        {!connections.length && !busy && <p>No connections loaded. Use Refresh to retry.</p>}
        <MCPPlayground key={readProvider} connections={connections} names={names} selectedProvider={readProvider} onProviderChange={setReadProvider} onVerified={(provider, status) => {
          setConnections(old => old.map(item => item.provider === provider ? { ...item, status, lastVerifiedAt: Math.floor(Date.now() / 1000) } : item));
          setChecks(old => ({ ...old, [provider]: statusNames[status] || status }));
        }} />
        <section className={styles.activity} aria-label="Connection activity"><h2>Connection activity</h2>
          <div aria-live="polite">{activity.length ? <ul>{activity.map((entry, i) => <li key={`${i}-${entry}`}>{entry}</li>)}</ul> : <p>Your checks will appear here.</p>}</div>
        </section>
      </>}
    </main>
  </Layout>;
}
