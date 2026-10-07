import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import Page from '../pages/workspace/dashboard/mcp-connections';
import { workspaceMCP } from '../lib/workspace-mcp';
import { useUserRole } from '../hooks/useUserRole';
vi.mock('../components/Layout', () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock('../components/SEO', () => ({ default: () => null }));
vi.mock('../hooks/useUserRole', () => ({ useUserRole: vi.fn() }));
vi.mock('../lib/workspace-mcp', async importOriginal => ({ ...await importOriginal<typeof import('../lib/workspace-mcp')>(), workspaceMCP: vi.fn() }));
const call = vi.mocked(workspaceMCP);
const role = vi.mocked(useUserRole);

it('explains durable account storage and selects the provider for viewing data', async () => {
  render(<Page />);
  const github = await screen.findByRole('region', { name: 'GitHub' });
  expect(screen.getByText(/remain after signing out/)).toBeInTheDocument();
  fireEvent.click(within(github).getByRole('link', { name: 'View data' }));
  expect(screen.getByRole('combobox', { name: 'Connection' })).toHaveValue('github');
  fireEvent.click(screen.getByRole('button', { name: 'Run read' }));
  await waitFor(() => expect(call).toHaveBeenCalledWith('connection_verify', { provider: 'github' }));
});

it('shows renewal checks and provider failures without claiming the grant was lost', async () => {
  call.mockImplementation(async name => {
    if (name === 'connections_list') return { connections: [{ provider: 'google-cloud', kind: 'oauth-sdk', status: 'refresh_or_consent_required' }] };
    throw new Error('Provider access was revoked.');
  });
  render(<Page />);
  const google = await screen.findByRole('region', { name: 'Google Cloud' });
  expect(within(google).getByText('Check renewal')).toBeInTheDocument();
  fireEvent.click(within(google).getByRole('button', { name: 'Verify' }));
  expect(await within(google).findByRole('alert')).toHaveTextContent('Provider access was revoked.');
});
const connections = [{ provider: 'aws', kind: 'sdk', status: 'sdk' }, { provider: 'github', kind: 'sdk', status: 'sdk' },
  { provider: 'whatsapp', kind: 'remote-mcp', status: 'consent_required' }, { provider: 'wix', kind: 'pending-adapter', status: 'pending-adapter' }];
beforeEach(() => {
  vi.clearAllMocks();
  role.mockReturnValue({ role: 'Admin', groups: ['Admin'], isAdmin: true, isPartner: false, wabaId: null, loading: false });
  call.mockImplementation(async name => name === 'connections_list' ? { connections } : { status: 'verified', read: { account: '775261844268', region: 'us-east-1', repository: 'wecare-digital/wecare-digital', defaultBranch: 'stack' } });
});
it('does not load or offer management to Operators', async () => {
  role.mockReturnValue({ role: 'Operator', groups: ['Operator'], isAdmin: true, isPartner: false, wabaId: null, loading: false });
  render(<Page />);
  expect(screen.getByText(/staff Admin account is required/)).toBeInTheDocument();
  expect(call).not.toHaveBeenCalled();
});
it('checks multiple selected providers without offering Connect for pending adapters', async () => {
  render(<Page />);
  await screen.findByLabelText('Select AWS');
  expect(within(screen.getByRole('region', { name: 'Wix' })).queryByRole('button')).toBeNull();
  fireEvent.click(screen.getByLabelText('Select AWS'));
  fireEvent.click(screen.getByLabelText('Select GitHub'));
  fireEvent.click(screen.getByRole('button', { name: 'Check selected' }));
  await waitFor(() => expect(call).toHaveBeenCalledWith('connection_verify', {provider: 'github'}));
  expect(call).toHaveBeenCalledWith('connection_verify', {provider: 'aws'});
  expect(await screen.findByText(/GitHub: wecare-digital/)).toBeInTheDocument();
});
it('shows a validated OAuth link only after the chosen provider starts authorization', async () => {
  const params = new URLSearchParams({ client_id: '2238810740192680', redirect_uri: 'https://wecare.digital/api/workspace/mcp/oauth/callback', code_challenge_method: 'S256', scope: 'business_management whatsapp_business_management' });
  call.mockImplementation(async name => name === 'connection_authorize' ? { authorizationUrl: `https://www.facebook.com/v26.0/dialog/oauth?${params}`, expiresIn: 600 } : { connections });
  render(<Page />);
  const region = await screen.findByRole('region', { name: 'WhatsApp Business Tools' });
  fireEvent.click(within(region).getByRole('button', { name: 'Connect' }));
  expect(await screen.findByRole('link', { name: /Continue with Meta/ })).toHaveAttribute('rel', 'noopener noreferrer');
  expect(call).toHaveBeenCalledWith('connection_authorize', { provider: 'whatsapp' });
});

it('shows a refused Meta client on its card without offering an unusable sign-in link', async () => {
  call.mockImplementation(async name => {
    if (name === 'connections_list') return { connections };
    throw new Error('Meta MCP client registration is unavailable for this cloud callback.');
  });
  render(<Page />);
  const region = await screen.findByRole('region', { name: 'WhatsApp Business Tools' });
  fireEvent.click(within(region).getByRole('button', { name: 'Connect' }));
  expect(await within(region).findByRole('alert')).toHaveTextContent('client registration is unavailable');
  expect(within(region).getByText('Authorization blocked')).toBeInTheDocument();
  expect(within(region).queryByRole('link', { name: /Continue with Meta/ })).toBeNull();
});
