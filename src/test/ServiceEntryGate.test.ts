/**
 * The unified WhatsApp-login gate: signed-in → straight to checkout; signed-out → the one
 * sign-in with a return to the SAME destination; the pending action survives out of band.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock( '../lib/customerAuth', () => ( {
  getSession: vi.fn(),
  restoreSession: vi.fn(),
} ) );

import { getSession, restoreSession } from '../lib/customerAuth';
import {
  goToServiceAction, takePendingAction, stashPendingAction, isSignedIn,
  CHECKOUT_PATH, SIGN_IN_PATH,
} from '../lib/serviceEntry';

const mockGet = getSession as unknown as ReturnType<typeof vi.fn>;
const mockRestore = restoreSession as unknown as ReturnType<typeof vi.fn>;

function fakeRouter () {
  return { push: vi.fn().mockResolvedValue( true ) };
}

beforeEach( () => {
  mockGet.mockReset();
  mockRestore.mockReset();
  window.sessionStorage.clear();
} );

describe( 'goToServiceAction', () => {
  it( 'signed in → pushes the checkout destination directly, no sign-in', async () => {
    mockGet.mockReturnValue( { accessToken: 't', expiresAt: Date.now() + 1e6 } );
    const router = fakeRouter();
    await goToServiceAction( router, { destination: CHECKOUT_PATH } );
    expect( router.push ).toHaveBeenCalledWith( CHECKOUT_PATH );
    expect( mockRestore ).not.toHaveBeenCalled();
  } );

  it( 'signed out (and no restorable session) → pushes the one sign-in with a return to the destination', async () => {
    mockGet.mockReturnValue( null );
    mockRestore.mockResolvedValue( null );
    const router = fakeRouter();
    await goToServiceAction( router, { destination: CHECKOUT_PATH } );
    expect( router.push ).toHaveBeenCalledWith(
      `${SIGN_IN_PATH}?return=${encodeURIComponent( CHECKOUT_PATH )}` );
  } );

  it( 'a restorable server session counts as signed in → straight to checkout', async () => {
    mockGet.mockReturnValue( null );
    mockRestore.mockResolvedValue( { accessToken: 't', expiresAt: Date.now() + 1e6 } );
    const router = fakeRouter();
    await goToServiceAction( router, { destination: CHECKOUT_PATH } );
    expect( router.push ).toHaveBeenCalledWith( CHECKOUT_PATH );
  } );

  it( 'stashes the pending action out of band so it survives the round trip, single-use', async () => {
    mockGet.mockReturnValue( null );
    mockRestore.mockResolvedValue( null );
    const router = fakeRouter();
    await goToServiceAction( router, {
      action: { kind: 'submit-request', productId: 'p1', variantId: 'v1', label: 'Submit a request' },
    } );
    const taken = takePendingAction();
    expect( taken?.kind ).toBe( 'submit-request' );
    expect( taken?.productId ).toBe( 'p1' );
    // single use: a second read is empty
    expect( takePendingAction() ).toBeNull();
  } );

  it( 'defaults the destination to the one checkout path', async () => {
    mockGet.mockReturnValue( { accessToken: 't', expiresAt: Date.now() + 1e6 } );
    const router = fakeRouter();
    await goToServiceAction( router, {} );
    expect( router.push ).toHaveBeenCalledWith( CHECKOUT_PATH );
  } );
} );

describe( 'isSignedIn / stash', () => {
  it( 'isSignedIn reflects getSession', () => {
    mockGet.mockReturnValue( null );
    expect( isSignedIn() ).toBe( false );
    mockGet.mockReturnValue( { accessToken: 't', expiresAt: Date.now() + 1e6 } );
    expect( isSignedIn() ).toBe( true );
  } );

  it( 'takePendingAction returns null when nothing stashed', () => {
    expect( takePendingAction() ).toBeNull();
  } );

  it( 'stash then take round-trips', () => {
    stashPendingAction( { kind: 'contribute', label: 'Contribute' } );
    expect( takePendingAction()?.kind ).toBe( 'contribute' );
  } );
} );
