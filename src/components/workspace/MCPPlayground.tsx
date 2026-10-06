import React, { useMemo, useState } from 'react';
import Button from '../ui/Button';
import Select, { type SelectOption } from '../ui/Select';
import { MCPConnection, workspaceMCP } from '../../lib/workspace-mcp';
import styles from '../../styles/MCPConnections.module.css';

const reads = [
  { id: 'apps', provider: 'meta-social', label: 'List authorized Meta apps', tool: 'devtools_app_list', arguments: { action: 'list', limit: 10 } },
  { id: 'settings', provider: 'meta-social', label: 'Read WECARE app settings', tool: 'devtools_app', arguments: { action: 'basic_settings', app_id: '2238810740192680' } },
  { id: 'limits', provider: 'meta-social', label: 'Check WECARE API rate limits', tool: 'devtools_api_usage', arguments: { action: 'rate_limits', app_id: '2238810740192680', lookback_minutes: 60 } },
  { id: 'businesses', provider: 'whatsapp', label: 'List WhatsApp businesses', tool: 'whatsapp_biz_businesses', arguments: { action: 'list' } },
];

export function playgroundRequest(provider: string, operation: string) {
  if (operation === 'verify') return { name: 'connection_verify', arguments: { provider } };
  const read = reads.find(item => item.provider === provider && item.id === operation);
  if (!read) throw new Error('Choose an available read.');
  return { name: 'provider_read', arguments: { provider, tool: read.tool, arguments: read.arguments } };
}

export function playgroundJSON(value: unknown): string {
  const clean = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(clean);
    if (item && typeof item === 'object') return Object.fromEntries(Object.entries(item).map(([key, data]) =>
      [key, /token|secret|password|authorization|verifier|private.?key|api.?key|credential/i.test(key) ? '[redacted]' : clean(data)]));
    if (typeof item === 'string') {
      try { const parsed = JSON.parse(item); if (parsed && typeof parsed === 'object') return clean(parsed); } catch { /* Plain text stays text. */ }
    }
    return item;
  };
  const text = JSON.stringify(clean(value), null, 2);
  return text.length > 50000 ? `${text.slice(0, 50000)}\n… Display limited to 50,000 characters.` : text;
}

export default function MCPPlayground({ connections, names, onVerified }: { connections: MCPConnection[]; names: Record<string, string>; onVerified?: (provider: string, status: string) => void }) {
  const [provider, setProvider] = useState('aws');
  const [operation, setOperation] = useState('verify');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');
  const [error, setError] = useState('');
  const [completed, setCompleted] = useState('');
  const connection = connections.find(item => item.provider === provider);
  /* The two option lists, memoised. Same order, same values, same visible text as the
     <option> rows they replaced, with 'verify' kept as the Read list's first row. */
  const connectionOptions: SelectOption[] = useMemo(
    () => connections.map(item => ({ value: item.provider, label: names[item.provider] || item.provider })),
    [connections, names]
  );
  const readOptions: SelectOption[] = useMemo(
    () => [
      { value: 'verify', label: 'Check connection and view data' },
      ...reads.filter(item => item.provider === provider).map(item => ({ value: item.id, label: item.label })),
    ],
    [provider]
  );
  const request = playgroundRequest(provider, operation);
  const run = async () => {
    setBusy(true); setResult(''); setError(''); setCompleted('');
    try {
      const value = await workspaceMCP<Record<string, unknown>>(request.name, request.arguments);
      if (value.isError) throw new Error('The provider refused this read. Check its connection and permissions.');
      setResult(playgroundJSON(value)); setCompleted(new Date().toLocaleString());
      if (operation === 'verify' && typeof value.status === 'string') onVerified?.(provider, value.status);
    } catch (e) { setError(e instanceof Error ? e.message : 'The read could not complete.'); }
    finally { setBusy(false); }
  };
  return <section className={styles.activity} aria-labelledby="mcp-playground-title" id="playground">
    <h2 id="mcp-playground-title">MCP Playground</h2>
    <p>Check a connection and inspect its data, or run an available account read. Results belong to your current staff account.</p>
    <div className={styles.playgroundControls}>
      {/* SHAPE (a), design 5.2 - both wrapping <label>s are gone and Select owns the pair. A
          <button> is a labelable element too, so leaving them would have made the accessible
          names "Connection AWS" and "Read Check connection and view data", and a label
          forwards clicks to its control, which can double-activate a button.
          `disabled` is a straight prop pass; every statement of both handlers is kept in
          order, including the three resets that clear the previous result. */}
      <Select label="Connection" value={provider} disabled={busy || !connections.length}
        onChange={v => {
          setProvider(v); setOperation('verify'); setResult(''); setError(''); setCompleted('');
        }}
        options={connectionOptions} />
      <Select label="Read" value={operation} disabled={busy}
        onChange={v => { setOperation(v); setResult(''); setError(''); setCompleted(''); }}
        options={readOptions} />
      <Button variant="primary" disabled={busy || !connection} onClick={() => void run()}>{busy ? 'Checking…' : 'Run read'}</Button>
    </div>
    {connection && <p>Current connection status: <strong>{connection.status.replaceAll('_', ' ')}</strong></p>}
    {error && <p className={styles.notice} role="alert">{error}</p>}
    <div aria-live="polite">{completed && <p>Read completed: {completed}</p>}</div>
    {result && <pre className={styles.result} aria-label="MCP read result">{result}</pre>}
    <details><summary>Request for your development workflow</summary>
      <p>This request uses the same AWS workspace MCP tools available to the configured Kiro and Codex bridge. Desktop and dashboard authorizations are separate.</p>
      <pre className={styles.result}>{JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: request }, null, 2)}</pre>
    </details>
    <p>Use the playground for integration checks, app settings, API health and documentation connection checks. Plivo and Sinch provide documentation discovery; Razorpay returns a collection summary. Code changes and deployments require your development workflow; automated code jobs remain disabled.</p>
  </section>;
}
