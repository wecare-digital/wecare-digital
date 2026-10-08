import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import MCPPlayground, { playgroundJSON, playgroundRequest } from '../components/workspace/MCPPlayground';
import { workspaceMCP } from '../lib/workspace-mcp';

vi.mock('../lib/workspace-mcp', () => ({ workspaceMCP: vi.fn() }));
const request = vi.mocked(workspaceMCP);
const connections = [
  { provider: 'aws', kind: 'sdk', status: 'sdk' },
  { provider: 'meta-social', kind: 'remote-mcp', status: 'consent_required' },
  { provider: 'whatsapp', kind: 'remote-mcp', status: 'consent_required' },
];
beforeEach(() => { cleanup(); vi.clearAllMocks(); });

/**
 * The two playground controls are ui/Select now, so a `fireEvent.change` has nothing to
 * change: the trigger is a <button role="combobox"> and the rows are <li role="option">.
 * This is the SAME USER ACTION expressed against the real markup - open the menu, click the
 * row - and every assertion in this file is untouched, because none of them was ever about
 * the element type.
 */
const choose = (field: string, option: string) => {
  fireEvent.click(screen.getByRole('combobox', { name: field }));
  fireEvent.click(screen.getByRole('option', { name: option }));
};

describe('MCP playground', () => {
  it('runs a connection check and displays actual data with its verified status', async () => {
    request.mockResolvedValue({ provider: 'aws', status: 'verified', read: { account: '775261844268' } });
    const verified = vi.fn();
    render(<MCPPlayground connections={connections} names={{ aws: 'AWS' }} onVerified={verified} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run read' }));
    await waitFor(() => expect(screen.getByLabelText('MCP read result').textContent).toContain('775261844268'));
    expect(request).toHaveBeenCalledWith('connection_verify', { provider: 'aws' });
    expect(verified).toHaveBeenCalledWith('aws', 'verified');
  });
  it('keeps failed authorization distinct from a successful empty collection', async () => {
    request.mockRejectedValue(new Error('Provider OAuth consent required'));
    render(<MCPPlayground connections={connections} names={{}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run read' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('consent required');
    expect(screen.queryByLabelText('MCP read result')).toBeNull();
  });
  it('runs a bounded Meta collection read and treats provider errors as failures', async () => {
    request.mockResolvedValue({ isError: true });
    render(<MCPPlayground connections={connections} names={{}} />);
    choose('Connection', 'meta-social');
    choose('Read', 'List authorized Meta apps');
    fireEvent.click(screen.getByRole('button', { name: 'Run read' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('refused');
    expect(request).toHaveBeenCalledWith('provider_read', { provider: 'meta-social', tool: 'devtools_app_list', arguments: { action: 'list', limit: 10 } });
  });
  it('does not display the last connection’s data after switching providers', async () => {
    request.mockResolvedValue({ status: 'verified', read: { account: '775261844268' } });
    render(<MCPPlayground connections={connections} names={{}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run read' }));
    await screen.findByLabelText('MCP read result');
    choose('Connection', 'whatsapp');
    expect(screen.queryByLabelText('MCP read result')).toBeNull();
  });
  it('refuses unlisted operations and binds settings reads to the WECARE app', () => {
    expect(() => playgroundRequest('whatsapp', 'settings')).toThrow();
    expect(() => playgroundRequest('meta-social', 'send')).toThrow();
    expect(playgroundRequest('meta-social', 'settings').arguments).toMatchObject({ arguments: { app_id: '2238810740192680' } });
  });
  it('redacts credentials in nested objects and JSON text blocks, and bounds the display', () => {
    const result = playgroundJSON({ token: 'fixture-token', content: [{ text: '{"api_key":"fixture-key","count":2}' }], nested: { private_key: 'fixture-private', name: 'WECARE' } });
    expect(result).not.toContain('fixture-');
    expect(result).toContain('WECARE');
    expect(result).toContain('"count": 2');
    expect(playgroundJSON({ text: 'a'.repeat(60000) })).toContain('Display limited');
  });
});
