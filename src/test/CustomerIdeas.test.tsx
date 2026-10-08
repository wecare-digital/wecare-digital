import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../components/Layout', () => ({ default: ({ children }: any) => <div>{children}</div> }));
vi.mock('../components/SEO', () => ({ default: () => null }));
vi.mock('../contexts/ToastContext', () => ({ useToastContext: () => ({ success: vi.fn(), error: vi.fn() }) }));
vi.mock('../components/wa', () => ({ MaskedPhone: ({ value }: any) => <span>{value}</span> }));
vi.mock('../api/client', () => ({
  listFlowRegistry: vi.fn().mockResolvedValue([]),
  listFlowSubmissions: vi.fn().mockResolvedValue([
    { submissionId: 'idea-1', flowCode: 'WD_IDEA', flowType: 'customer_idea',
      phone: 'fixture', contactId: 'contact-fixture', subject: 'A feature I would love',
      description: 'Request tracking in my language, with one place for every update.',
      formData: JSON.stringify({ follow_up_opt_in: false }), status: 'open', paymentStatus: 'none', createdAt: 1 },
    { submissionId: 'legacy-1', flowCode: 'WD_SR', subject: 'Existing service request',
      phone: 'fixture', status: 'open', paymentStatus: 'none', createdAt: 1 },
  ]),
}));

import FlowResponsesPage from '../pages/workspace/engage/whatsapp/flow-responses';

describe('customer ideas in the workspace', () => {
  it('shows the full thought, contact and explicit follow-up permission without replacing legacy submissions', async () => {
    render(<FlowResponsesPage embedded />);
    await waitFor(() => expect(screen.getByText('A feature I would love')).toBeInTheDocument());
    expect(screen.getByText('Request tracking in my language, with one place for every update.')).toBeInTheDocument();
    expect(screen.getByText("Linked to this sender's contact record.")).toBeInTheDocument();
    expect(screen.getByText('Saved in customer reviews.')).toBeInTheDocument();
    expect(screen.getByText('Existing service request')).toBeInTheDocument();
  });
});
