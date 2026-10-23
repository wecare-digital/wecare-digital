import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

vi.mock('../components/Layout', () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock('../components/SEO', () => ({ default: () => null }));
vi.mock('../components/PageHeader', () => ({ default: () => null }));
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => ({ confirm: vi.fn() }) }));
const authFetch = vi.fn();
vi.mock('../api/client', () => ({ authFetch: (...args: unknown[]) => authFetch(...args) }));
import Catalog from '../components/workspace/commerce/Catalog';

describe('always-available native catalog', () => {
  it('shows the variant price and saves edits without stock controls or mutations', async () => {
    const product = {
      id: 'native:elsewhere-activities', title: 'Activities', slug: 'elsewhere-activities',
      status: 'draft', currency: 'INR', updatedAt: '2026-10-23T00:00:00Z',
      metaEnabled: false, websiteEnabled: false,
      variants: [{ sku: 'ACT1', label: 'Standard', priceMinor: 9900, inventory: 0, trackInventory: true }],
    };
    authFetch.mockImplementation(async (_url: string, init?: RequestInit) => ({
      ok: true,
      json: async () => init?.method === 'PATCH' ? { product } : { products: [product] },
    }));
    render(<Catalog />);
    const row = await screen.findByRole('button', { name: /Activities.*99/ });
    expect(row).not.toHaveTextContent('NaN');
    fireEvent.click(row);
    const editor = within(screen.getByRole('region', { name: 'Product editor' }));
    expect(editor.queryByText(/units available/i)).toBeNull();
    expect(editor.queryByLabelText(/stock/i)).toBeNull();
    fireEvent.change(editor.getByLabelText('Variant label'), { target: { value: 'Consultation' } });
    fireEvent.click(editor.getByRole('button', { name: 'Save variant' }));
    await waitFor(() => expect(authFetch.mock.calls.some(call => call[1]?.method === 'PATCH')).toBe(true));
    const patch = authFetch.mock.calls.find(call => call[1]?.method === 'PATCH')![1];
    expect(JSON.parse(patch.body as string)).toEqual({
      expectedUpdatedAt: product.updatedAt, priceMinor: 9900, label: 'Consultation',
    });
  });
});
