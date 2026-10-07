import { authFetch } from '../api/client';

export interface MCPConnection {
  provider: string;
  kind: string;
  status: string;
  lastVerifiedAt?: number | null;
  connectionScope?: string;
  persistent?: boolean;
  accessExpiresAt?: number | null;
  automaticRefresh?: boolean | null;
}

export async function workspaceMCP<T>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  const response = await authFetch('/api/workspace/mcp', {
    method: 'POST',
    headers: { 'MCP-Protocol-Version': '2025-11-25' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }),
    signal: AbortSignal.timeout(30000),
  });
  if (response.status === 401 || response.status === 403) throw new Error('Sign in with a staff Admin account to manage connections.');
  if (!response.ok) throw new Error('Connection service unavailable. Please try again.');
  const message = await response.json();
  if (message.error) throw new Error('The connection check could not complete. Please try again.');
  const text = message.result?.content?.find((item: { type: string }) => item.type === 'text')?.text;
  if (typeof text !== 'string') throw new Error('The connection service returned an invalid response.');
  if (message.result?.isError) throw new Error(text);
  return JSON.parse(text) as T;
}

export function metaAuthorizationURL(value: string): string {
  const url = new URL(value);
  const meta = url.origin === 'https://www.facebook.com' && url.pathname === '/v26.0/dialog/oauth';
  const google = url.origin === 'https://accounts.google.com' && url.pathname === '/o/oauth2/v2/auth'
    && url.searchParams.get('client_id') === '756034744787-occ06h9v22rh0kbm83mmedpfqqqfni44.apps.googleusercontent.com';
  // Permissions arrive either as scope, or as a Facebook Login for Business config_id that
  // replaces it. At least one must be present, so a link requesting nothing never passes.
  const permissions = url.searchParams.get('scope') || url.searchParams.get('config_id');
  if ((!meta && !google) || !url.searchParams.get('client_id') || !permissions
    || url.searchParams.get('redirect_uri') !== 'https://wecare.digital/api/workspace/mcp/oauth/callback'
    || url.searchParams.get('code_challenge_method') !== 'S256') {
    throw new Error('The authorization link could not be verified.');
  }
  return url.href;
}
