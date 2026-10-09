import React from 'react';
import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

vi.mock('../components/Layout', () => ({ default: ({ children }: any) => <div>{children}</div> }));
vi.mock('../components/SEO', () => ({ default: () => null }));
vi.mock('../contexts/ToastContext', () => {
  const toast = { success: vi.fn(), error: vi.fn() };
  return { useToastContext: () => toast };
});
vi.mock('../components/wa', () => ({ MaskedPhone: () => <span>Verified customer</span> }));
vi.mock('../api/client', () => ({
  listFlowRegistry: vi.fn().mockResolvedValue([]),
  listFlowSubmissions: vi.fn().mockResolvedValue([{ submissionId: 'WD-HELP-EXAMPLE',
    submissionNumber: 'WD-HELP-EXAMPLE', flowCode: 'WD_Orders', flowType: 'order_lookup',
    subject: 'Help finding an order', description: 'The order is missing from my account.',
    orderReference: 'CUSTOMER-SUPPLIED-REFERENCE', customerUuid: 'PUBLIC-CUSTOMER-ID',
    tags: ['Orders', 'Order verification pending'], status: 'awaiting_order_verification',
    paymentStatus: 'none', createdAt: 1 }]),
}));

import FlowResponsesPage from '../pages/workspace/engage/whatsapp/flow-responses';

it('shows customer-supplied reference as a verification task without claiming a linked order or payment', async () => {
  render(<FlowResponsesPage embedded />);
  expect(await screen.findByText('Help finding an order')).toBeInTheDocument();
  expect(screen.getByText('Customer reference: CUSTOMER-SUPPLIED-REFERENCE')).toBeInTheDocument();
  expect(screen.getByText('Customer ID: PUBLIC-CUSTOMER-ID')).toBeInTheDocument();
  expect(screen.getByText('No verified order is linked. Verify ownership before requesting a service payment.')).toBeInTheDocument();
  expect(screen.getByText('AWAITING ORDER VERIFICATION')).toBeInTheDocument();
  expect(screen.getByText('Orders · Order verification pending')).toBeInTheDocument();
});
