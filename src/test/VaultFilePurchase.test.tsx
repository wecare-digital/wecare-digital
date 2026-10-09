import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import VaultFilePurchase from '../components/VaultFilePurchase';
import * as api from '../api/client';
import * as auth from '../lib/customerAuth';
import * as requests from '../lib/serviceRequests';
import * as prices from '../lib/servicePricing';
import * as cart from '../lib/cart';

vi.mock( '../api/client', () => ( { listMySecureFiles: vi.fn(), redeemSecureFileDownload: vi.fn() } ) );
vi.mock( '../lib/customerAuth', () => ( { getSession: vi.fn(), restoreSession: vi.fn() } ) );
vi.mock( '../lib/serviceRequests', () => ( { postRequestIntent: vi.fn() } ) );
vi.mock( '../lib/servicePricing', () => ( { fetchServicePrices: vi.fn() } ) );
vi.mock( '../lib/cart', () => ( { setServiceLine: vi.fn() } ) );
const file = { fileId: 'f', displayName: 'Report', originalFilename: 'report.pdf', status: 'active' as const, contentType: 'application/pdf', sizeBytes: 12, pricePaise: 4900, downloadCount: 0, createdAt: '' };
const assign = vi.fn();
beforeEach( () => {
  vi.clearAllMocks();
  sessionStorage.clear();
  Object.defineProperty( window, 'location', { configurable: true, value: { assign, search: '' } } );
  vi.mocked( auth.getSession ).mockReturnValue( { accessToken: 'token', expiresAt: Date.now() + 10000 } );
  vi.mocked( prices.fetchServicePrices ).mockResolvedValue( { vault: { available: true, paise: 7700, rupees: '77', currency: 'INR' } } as Awaited<ReturnType<typeof prices.fetchServicePrices>> );
  vi.mocked( api.listMySecureFiles ).mockResolvedValue( { ok: true, data: { files: [ file ], count: 1, pricePaise: 4900 } } );
} );
describe( 'Vault file-bound purchase', () => {
  it( 'opens only the linked owned file without consuming its paid grant', async () => {
    window.location.search = '?file=f';
    vi.mocked( api.listMySecureFiles ).mockResolvedValue( { ok: true, data: { files: [ { ...file, paidGrantId: 'paid' }, { ...file, fileId: 'other', displayName: 'Other file' } ], count: 2, pricePaise: 4900 } } );
    render( <VaultFilePurchase /> );
    expect( await screen.findByRole( 'button', { name: 'Download your file' } ) ).toBeTruthy();
    expect( screen.queryByText( 'Other file' ) ).toBeNull();
    expect( api.redeemSecureFileDownload ).not.toHaveBeenCalled();
    expect( sessionStorage.getItem( 'wecare.vault.selectedFile' ) ).toBe( 'f' );
  } );
  it( 'keeps the file pointer across the canonical sign-in return', async () => {
    sessionStorage.setItem( 'wecare.vault.selectedFile', 'missing' );
    render( <VaultFilePurchase /> );
    expect( await screen.findByText( /This file is not available/ ) ).toBeTruthy();
    expect( requests.postRequestIntent ).not.toHaveBeenCalled();
    expect( screen.queryByText( 'Report' ) ).toBeNull();
  } );
  it( 'rejects an invalid link pointer and clears stale selection', async () => {
    window.location.search = '?file=https%3A%2F%2Fevil.example';
    sessionStorage.setItem( 'wecare.vault.selectedFile', 'missing' );
    render( <VaultFilePurchase /> );
    expect( await screen.findByText( 'Report' ) ).toBeTruthy();
    expect( sessionStorage.getItem( 'wecare.vault.selectedFile' ) ).toBeNull();
  } );
  it( 'binds the selected file and uses the live Wix price', async () => {
    vi.mocked( requests.postRequestIntent ).mockResolvedValue( { kind: 'ok', intent: { intentId: 'intent', variantId: 'vault', kind: 'VAULT', amountPaise: null, currency: 'INR', targetRequestId: null } } );
    render( <VaultFilePurchase /> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Continue to payment' } ) );
    await waitFor( () => expect( assign ).toHaveBeenCalledWith( '/cart/' ) );
    expect( requests.postRequestIntent ).toHaveBeenCalledWith( 'token', 'VAULT', undefined, 'f' );
    expect( cart.setServiceLine ).toHaveBeenCalledWith( 'vault', 'intent', 7700 );
  } );
  it( 'downloads an already paid file without another checkout', async () => {
    vi.mocked( api.listMySecureFiles ).mockResolvedValue( { ok: true, data: { files: [ { ...file, paidGrantId: 'paid' } ], count: 1, pricePaise: 4900 } } );
    vi.mocked( api.redeemSecureFileDownload ).mockResolvedValue( { ok: true, data: { downloadUrl: 'https://example.com/private.pdf', expiresInSeconds: 60 } } );
    render( <VaultFilePurchase /> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Download your file' } ) );
    await waitFor( () => expect( api.redeemSecureFileDownload ).toHaveBeenCalledWith( 'f', 'paid' ) );
    expect( requests.postRequestIntent ).not.toHaveBeenCalled();
  } );
  it( 'offers no purchase for an empty file collection', async () => {
    vi.mocked( api.listMySecureFiles ).mockResolvedValue( { ok: true, data: { files: [], count: 0, pricePaise: 4900 } } );
    render( <VaultFilePurchase /> );
    expect( await screen.findByText( /No documents are ready yet/ ) ).toBeTruthy();
    expect( screen.queryByRole( 'button', { name: 'Continue to payment' } ) ).toBeNull();
  } );
} );

it( 'does not offer another payment for a paid file whose grant is consumed or unavailable', async () => {
  vi.mocked( api.listMySecureFiles ).mockResolvedValue( { ok: true, data: { files: [ { ...file, vaultPaymentStatus: 'PAID' } ], count: 1, pricePaise: 4900 } } );
  render( <VaultFilePurchase /> );
  await screen.findByText( 'Report' );
  expect( screen.queryByRole( 'button', { name: 'Continue to payment' } ) ).toBeNull();
  expect( screen.getByText( /Already paid/ ) ).toBeInTheDocument();
  expect( requests.postRequestIntent ).not.toHaveBeenCalled();
} );
