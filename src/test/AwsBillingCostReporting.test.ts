/**
 * `getAWSBilling` once dropped `costReportingEnabled` and `note` while mapping
 * the `/billing` response, so a payload that said "spend was not measured"
 * reached the dashboard as a $0.00 bill. These tests pin the two fields to that
 * mapping, because nothing else stops them being dropped a second time.
 *
 * They exercise the real client against a stubbed `fetch` — no mock of the
 * client itself, or the thing under test would be the mock.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// aws-amplify/auth is pulled in by the client for the Bearer token. The token
// path is not what is being tested, so it returns nothing and the client
// proceeds without an Authorization header.
vi.mock( 'aws-amplify/auth', () => ( {
  fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ),
} ) );

// Retries are real and would otherwise make this suite sleep for seconds.
vi.mock( '../config/constants', async ( importOriginal ) => {
  const actual = await importOriginal<typeof import( '../config/constants' )>();
  return { ...actual, RETRY_CONFIG: { maxRetries: 2, baseDelayMs: 1, maxDelayMs: 2 } };
} );

import { getAWSBilling } from '../api/client';

function jsonResponse ( status: number, body: unknown = {}, statusText = '' ): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => body,
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach( () => {
  fetchMock = vi.fn();
  vi.stubGlobal( 'fetch', fetchMock );
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
} );

describe( 'getAWSBilling — cost reporting disabled', () => {
  // The shape the billing Lambda actually returns since Cost Explorer was
  // removed on 2026-09-28: an empty service list and an explicit false.
  const disabledBody = {
    totalCost: 0,
    period: '2026-10-01 to 2026-10-07',
    services: [],
    recommendations: [],
    costReportingEnabled: false,
    note: 'Cost Explorer API calls were removed to avoid per-request charges.',
  };

  it( 'carries costReportingEnabled:false and the note through the mapping', async () => {
    fetchMock.mockResolvedValue( jsonResponse( 200, disabledBody ) );

    const billing = await getAWSBilling();

    expect( billing.costReportingEnabled ).toBe( false );
    expect( billing.note ).toBe( disabledBody.note );
  } );

  it( 'keeps the real zero and the period rather than falling back to estimates', async () => {
    fetchMock.mockResolvedValue( jsonResponse( 200, disabledBody ) );

    const billing = await getAWSBilling();

    // services: [] is truthy, so the disabled payload must stay on the real
    // branch. Reaching getEstimatedBilling() here would render a fabricated
    // 2.40 with invented service rows — worse than the $0.00 being removed.
    expect( billing.totalCost ).toBe( 0 );
    expect( billing.services ).toEqual( [] );
    expect( billing.period ).toBe( disabledBody.period );
  } );
} );

describe( 'getAWSBilling — a real bill is unchanged', () => {
  it( 'reads a response that omits costReportingEnabled as enabled', async () => {
    fetchMock.mockResolvedValue( jsonResponse( 200, {
      totalCost: 7.95,
      period: '2026-09-01 to 2026-09-30',
      services: [
        { service: 'AWS Secrets Manager', cost: 7.95, usage: 20, unit: 'secrets', freeLimit: '$0.40/secret/mo', status: 'paid' },
      ],
    } ) );

    const billing = await getAWSBilling();

    // Absence must mean enabled: a response predating the field, or a partial
    // one, has to keep rendering the bill it reports.
    expect( billing.costReportingEnabled ).not.toBe( false );
    expect( billing.note ).toBeUndefined();
    expect( billing.totalCost ).toBe( 7.95 );
    expect( billing.services ).toHaveLength( 1 );
  } );

  it( 'treats costReportingEnabled:true as enabled', async () => {
    fetchMock.mockResolvedValue( jsonResponse( 200, {
      totalCost: 1.25,
      period: '2026-10-01 to 2026-10-07',
      services: [
        { service: 'AWS Lambda', cost: 1.25, usage: 10, unit: 'requests', freeLimit: '1M/month', status: 'paid' },
      ],
      costReportingEnabled: true,
    } ) );

    const billing = await getAWSBilling();

    expect( billing.costReportingEnabled ).toBe( true );
  } );
} );
