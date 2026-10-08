import React, { type ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, cleanup, within } from '@testing-library/react';

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('../api/client', () => ({ apiCallResult: request }));
vi.mock('../components/Layout', () => ({ default: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock('../components/SEO', () => ({ default: () => null }));
import InternalAgentSettings from '../pages/workspace/settings/internal-agent';

const legacyConfig = { enabled: true, enabledTools: ['send_whatsapp', 'create_contact', 'search_contacts'] };
const catalog = {
  enabled: { search_contacts: { class: 'READ', summary: 'Find contacts by name, phone or email.' } },
  refused: {
    send_whatsapp: { class: 'APPLY', reason: 'Sending is refused. Prepare the details for a person.' },
    create_contact: { class: 'APPLY', reason: 'Contact creation is refused.' },
  },
};
beforeEach(() => request.mockReset());
afterEach(() => cleanup());

async function capabilitySection() {
  await screen.findByRole('heading', { name: 'Tool Capabilities' });
  return screen.getByRole('region', { name: 'Tool Capabilities' });
}

describe('Internal agent capabilities follow executor authority', () => {
  it('fails closed when an older backend returns saved tools but no catalog', async () => {
    request.mockResolvedValue({ ok: true, data: { config: legacyConfig } });
    render(<InternalAgentSettings />);
    const section = await capabilitySection();
    expect(within(section).getByRole('status').textContent).toContain('Capability status unavailable');
    expect(within(section).queryByText('Search contacts')).toBeNull();
    expect(within(section).queryByRole('checkbox')).toBeNull();
    expect(within(section).queryByRole('button')).toBeNull();
  });

  it('shows only backend availability and refusal reasons with no write controls', async () => {
    request.mockResolvedValue({ ok: true, data: { config: legacyConfig, toolCapabilities: catalog } });
    render(<InternalAgentSettings />);
    const section = await capabilitySection();
    expect(within(section).getByText('Search contacts')).toBeTruthy();
    expect(within(section).getByText('Send WhatsApp')).toBeTruthy();
    expect(within(section).getByText(/Sending is refused/)).toBeTruthy();
    expect(within(section).getByText(/Contact creation is refused/)).toBeTruthy();
    expect(within(section).queryByRole('checkbox')).toBeNull();
    expect(within(section).queryByRole('button')).toBeNull();
    expect(within(section).queryByText('All Enabled')).toBeNull();
  });

  it('reflects a backend kill switch even when saved preferences enable the assistant', async () => {
    request.mockResolvedValue({ ok: true, data: { config: legacyConfig, toolCapabilities: {
      enabled: {}, refused: { search_contacts: { class: 'READ', reason: 'The assistant is disabled by policy.' } },
    } } });
    render(<InternalAgentSettings />);
    const section = await capabilitySection();
    expect(within(section).getByText('No actions are currently enabled.')).toBeTruthy();
    expect(within(section).getByText(/disabled by policy/)).toBeTruthy();
  });

  it('does not save legacy tool choices or backend capability authority as preferences', async () => {
    request.mockResolvedValueOnce({ ok: true, data: { config: legacyConfig, toolCapabilities: catalog } })
      .mockResolvedValueOnce({ ok: true, data: {} });
    render(<InternalAgentSettings />);
    await capabilitySection();
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    const payload = JSON.parse(request.mock.calls[1][1].body);
    expect(payload.enabled).toBe(true);
    expect(payload.modelId).toBe('amazon.nova-pro-v1:0');
    expect(payload).not.toHaveProperty('enabledTools');
    expect(payload).not.toHaveProperty('toolCapabilities');
    expect(await screen.findByText('Settings saved successfully!')).toBeTruthy();
  });

  it('fails closed for malformed or contradictory catalogs', async () => {
    request.mockResolvedValue({ ok: true, data: { toolCapabilities: {
      enabled: catalog.enabled,
      refused: { search_contacts: { class: 'READ', reason: 'Refused' } },
    } } });
    render(<InternalAgentSettings />);
    const section = await capabilitySection();
    expect(within(section).getByRole('status').textContent).toContain('Capability status unavailable');
    expect(within(section).queryByText('Search contacts')).toBeNull();
  });

  it('does not keep stale availability after a failed reload', async () => {
    request.mockResolvedValueOnce({ ok: true, data: { toolCapabilities: catalog } })
      .mockResolvedValueOnce({ ok: false, failure: { message: 'Service unavailable' } });
    render(<InternalAgentSettings />);
    await capabilitySection();
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(await screen.findByText('Could not load settings: Service unavailable')).toBeTruthy();
    const section = screen.getByRole('region', { name: 'Tool Capabilities' });
    expect(within(section).getByRole('status').textContent).toContain('Capability status unavailable');
    expect(within(section).queryByText('Search contacts')).toBeNull();
  });
});
