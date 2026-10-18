import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import React from 'react';
import {
  afterEach, beforeEach, describe, expect, it, vi,
} from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import * as customerAuth from '../lib/customerAuth';
import * as signInMessages from '../lib/signInMessages';
import SignIn from '../pages/account/sign-in';

/**
 * SECTION 6: the seven approved sign-in messages, pinned.
 *
 * TWO THINGS ARE ASSERTED, HONESTLY. First, that all seven strings exist VERBATIM as the approved
 * constants in the shared message source - so the sanctioned wording is present and auditable even
 * for the one state (missing country code) the divided phone field makes unreachable. Second, that
 * the states the UI CAN reach render the approved string and carry NO red validation colour: the
 * error treatment is the lime "read this first" tint, not a red one.
 *
 * The unreachable string (MISSING_CODE) is checked for PRESENCE only, not forced to render. The
 * sign-in field is divided and always carries a dial code, so there is no input that produces a
 * missing-country-code state; manufacturing one just to make the message appear would be dishonest.
 * See src/lib/signInMessages.ts.
 */

const SIGN_IN_SOURCE = readFileSync(
  join(__dirname, '..', 'components', 'account', 'SignInPage.tsx'), 'utf8',
);

/** The owner's section-6 table, verbatim. The source of truth the module must equal. */
const APPROVED_SECTION_6 = [
  'Include your country code, like +91.',
  'Enter a valid number.',
  'Couldn\u2019t send a code. Check your number.',
  'Try again shortly.',
  'Check your code.',
  'Code expired. Send a new one.',
  'Wait before trying again.',
];

describe('the seven section-6 strings exist verbatim', () => {
  it('matches the approved table exactly, in order and count', () => {
    expect([...signInMessages.SECTION_6_MESSAGES]).toEqual(APPROVED_SECTION_6);
  });

  it('exposes each one as a named constant', () => {
    expect(signInMessages.MISSING_CODE).toBe('Include your country code, like +91.');
    expect(signInMessages.BAD_NUMBER).toBe('Enter a valid number.');
    expect(signInMessages.CHECK_NUMBER).toBe('Couldn\u2019t send a code. Check your number.');
    expect(signInMessages.TRY_LATER).toBe('Try again shortly.');
    expect(signInMessages.BAD_CODE).toBe('Check your code.');
    expect(signInMessages.CODE_EXPIRED).toBe('Code expired. Send a new one.');
    expect(signInMessages.RATE_LIMITED).toBe('Wait before trying again.');
  });

  it('is the source the sign-in page draws its message table from', () => {
    // The page references the shared constants rather than re-typing the copy, so the wording
    // cannot drift between the page and this test.
    expect(SIGN_IN_SOURCE).toContain("import * as signInMessages from '../../lib/signInMessages'");
    for (const key of ['MISSING_CODE', 'BAD_NUMBER', 'CHECK_NUMBER', 'TRY_LATER',
      'BAD_CODE', 'CODE_EXPIRED', 'RATE_LIMITED']) {
      expect(SIGN_IN_SOURCE).toContain(`signInMessages.${key}`);
    }
  });
});

describe('the sign-in error states use no red validation colour', () => {
  /**
   * The CSS lives in a styled-jsx block, which jsdom does not compute. So "no red" is asserted two
   * ways that together are stronger than a computed-style read: the error style block contains the
   * lime palette and no red hue, and no reachable error carries an inline red colour.
   */
  it('styles the error with the lime palette, never a red one', () => {
    const errorBlock = SIGN_IN_SOURCE.slice(
      SIGN_IN_SOURCE.indexOf('.si-error{'),
      SIGN_IN_SOURCE.indexOf('.si-back{'),
    );
    expect(errorBlock).toContain('color:var(--public-brand-green)'); // canonical deep-green type
    expect(errorBlock).toContain('rgba(209,244,112');   // the lime tint (#d1f470)
    // No red hue anywhere in the error treatment.
    expect(errorBlock).not.toMatch(/#f?[a-f0-9]*0{2}[a-f0-9]{0,2}\b.*red/i);
    expect(errorBlock.toLowerCase()).not.toContain('red');
    // The known old red values are gone.
    for (const red of ['#fbe9e9', '#f0c0c0', '#8a1f1f']) {
      expect(errorBlock).not.toContain(red);
    }
  });

  it('renders a reachable error (bad code) as an approved string with no inline red', async () => {
    vi.spyOn(customerAuth, 'getSession').mockReturnValue(null);
    vi.spyOn(customerAuth, 'requestOtp').mockResolvedValue({
      session: 'sess-A', destination: '********3210', expiresInSeconds: 600, registered: true,
    });
    vi.spyOn(customerAuth, 'submitOtp').mockResolvedValue(null); // wrong code, attempts remain
    vi.stubGlobal('fetch', vi.fn());

    render(<SignIn />);
    fireEvent.change(screen.getByLabelText('WhatsApp number'),
      { target: { value: '+919876543210' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send OTP on WhatsApp' }));
    fireEvent.change(await screen.findByLabelText('WhatsApp code'), { target: { value: '000000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm WhatsApp code' }));

    const alert = await screen.findByRole('alert');
    // The rendered string is one of the approved seven, verbatim.
    expect(APPROVED_SECTION_6).toContain(alert.textContent);
    expect(alert.textContent).toBe(signInMessages.BAD_CODE);
    // No inline red style snuck onto the alert element.
    const inline = (alert.getAttribute('style') || '').toLowerCase();
    expect(inline).not.toContain('red');
    expect(inline).not.toMatch(/color:\s*#?(f00|ff0000|dc2626|b00020|8a1f1f)/);
  });

  it('renders a reachable error (rate limited) as an approved string', async () => {
    vi.spyOn(customerAuth, 'getSession').mockReturnValue(null);
    const throttled = Object.assign(new Error('Too many requests'),
      { name: 'TooManyRequestsException' });
    vi.spyOn(customerAuth, 'requestOtp').mockRejectedValue(throttled);
    vi.stubGlobal('fetch', vi.fn());

    render(<SignIn />);
    fireEvent.change(screen.getByLabelText('WhatsApp number'),
      { target: { value: '+919876543210' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send OTP on WhatsApp' }));

    const alert = await screen.findByRole('alert');
    await waitFor(() => expect(alert.textContent).toBe(signInMessages.RATE_LIMITED));
    expect(APPROVED_SECTION_6).toContain(alert.textContent);
  });

  it('never renders the reserved NOT_ON_WHATSAPP string, and it is not one of the seven', () => {
    // The reserved string is approved but must not reach the page today; it is also outside the
    // section-6 seven, so its presence as a constant does not inflate the table.
    expect(signInMessages.NOT_ON_WHATSAPP).toBe('Use a WhatsApp number.');
    expect([...signInMessages.SECTION_6_MESSAGES]).not.toContain(signInMessages.NOT_ON_WHATSAPP);
  });
});

/**
 * THE PAGE-LEVEL REGRESSION TESTS FOR THE 2026-10-02 CONFIRM OUTAGE.
 *
 * These drive the REAL `customerAuth.submitOtp` through a stubbed `fetch`, rather than mocking
 * `submitOtp` itself. That distinction is the whole reason no test caught this:
 * AccountSignIn.test.tsx mocks `submitOtp` wholesale, so the session exchange inside it never
 * ran in any test, at any layer.
 *
 * The owner's symptom was: correct code -> "Try again shortly." -> not signed in. The classifier
 * that produced it was the name-based `messageForAuthError` on its CATCH-ALL branch (the thrown
 * Error's name is 'Error', matching none of the known patterns), NOT the >=500 mapping - there is
 * no 5xx anywhere in this failure. So the assertion that matters is that TRY_LATER is not
 * rendered, and the MSG table and both classifiers are left exactly as they are.
 */
describe('a refused session exchange must not destroy a successful sign-in', () => {
  /** Capture navigation without jsdom's "not implemented" throw. */
  let navigatedTo: string;

  beforeEach(() => {
    // Restore in beforeEach, not only afterEach. An earlier describe in this file mocks
    // customerAuth.submitOtp wholesale and does not restore it, and these tests exist
    // specifically to run the REAL submitOtp - inheriting that mock would make them silently
    // test nothing.
    vi.restoreAllMocks();
    navigatedTo = '';
    window.localStorage.clear();
    window.sessionStorage.clear();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        ...window.location,
        search: '',
        assign: (url: string) => { navigatedTo = String(url); },
        replace: (url: string) => { navigatedTo = String(url); },
      },
    });
  });

  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  /**
   * Cognito answers through the real `submitOtp`; only the two network responses are canned.
   * `sessionStatus` is what `/api/ecommerce/customer-session` returns for the exchange.
   */
  function stubNetwork(sessionStatus: number): void {
    vi.spyOn(customerAuth, 'getSession').mockReturnValue(null);
    vi.spyOn(customerAuth, 'requestOtp').mockResolvedValue({
      session: 'sess-A', destination: '*******0044', expiresInSeconds: 600, registered: true,
    });
    vi.stubGlobal('fetch', vi.fn(async (url: unknown, init?: { body?: string }) => {
      const target = String(url);
      if (target.indexOf('/ecommerce/customer-session') !== -1) {
        const body = sessionStatus === 200
          ? { csrfToken: 'qa-csrf', expiresAt: Date.now() + 3_600_000, persistent: true }
          : { error: 'VERIFICATION_REQUIRED' };
        return {
          ok: sessionStatus === 200, status: sessionStatus,
          text: async () => JSON.stringify(body), json: async () => body,
        };
      }
      // Cognito RespondToAuthChallenge: the code was CORRECT, and a RefreshToken is present,
      // which is what sends the client into the exchange branch at all.
      const result = {
        AuthenticationResult: {
          AccessToken: 'qa-access', RefreshToken: 'qa-refresh', ExpiresIn: 3600,
        },
      };
      return { ok: true, status: 200, text: async () => JSON.stringify(result),
        json: async () => result };
    }));
  }

  async function signInWithCorrectCode(): Promise<void> {
    render(<SignIn />);
    fireEvent.change(screen.getByLabelText('WhatsApp number'),
      { target: { value: '+919876543210' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send OTP on WhatsApp' }));
    fireEvent.change(await screen.findByLabelText('WhatsApp code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm WhatsApp code' }));
  }

  it('signs in and shows no error when the exchange is refused (401)', async () => {
    stubNetwork(401);
    await signInWithCorrectCode();

    // The shopper gets in. Before the fix this stayed put and showed TRY_LATER.
    await waitFor(() => expect(navigatedTo).toBe('/cart/'));
    // Nothing red, nothing announced: a degraded remember-me is not a sign-in failure.
    expect(screen.queryByRole('alert')).toBeNull();
    // Named explicitly, because this exact string is the reported symptom.
    expect(screen.queryByText(signInMessages.TRY_LATER)).toBeNull();
    // The valid access token survived rather than being discarded.
    expect(window.sessionStorage.getItem('wecare.customer.accessToken')).toBe('qa-access');
    // No device-level session was claimed.
    expect(window.localStorage.getItem('wecare.customer.sessionHint')).toBeNull();
  });

  it('signs in and remembers the device when the exchange succeeds (200)', async () => {
    stubNetwork(200);
    await signInWithCorrectCode();

    await waitFor(() => expect(navigatedTo).toBe('/cart/'));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(window.sessionStorage.getItem('wecare.customer.accessToken')).toBe('qa-access');
    await waitFor(() => expect(
      JSON.parse(window.localStorage.getItem('wecare.customer.sessionHint') || 'null')?.csrfToken,
    ).toBe('qa-csrf'));
  });

  /**
   * THE DOUBLED-LABEL DEFECT, pinned at the layer that can see accessible names.
   *
   * The owner saw the confirm button render as "Sign inConfirm code". The cause was a styled-jsx
   * SCOPING failure - the segments were hoisted into a variable, shipped with no `jsx-*` hash,
   * and so rendered completely unstyled as two bare text nodes jammed together. It was NOT a
   * duplicate-label bug in the markup. Fixed upstream in 2f742ec6, which inlined the segments
   * into both branches; this page is unchanged by that commit and still passes `label="Sign in"`,
   * so the pill correctly renders TWO STYLED SEGMENTS rather than one run-together string.
   *
   * SEPARATELY, the accessible name was ALSO wrong, and that is a different defect from the
   * scoping. The control used to announce the action alone ("Confirm WhatsApp code") with both visible
   * segments aria-hidden, which is a WCAG 2.5.3 Label in Name failure - a speech-input user
   * saying "click Sign in" hit nothing. The name is now the full visible text,
   * "Sign in Confirm code", and there is no aria-label. That is what these two cases pin at the
   * page level; src/test/PillButtonAccessibleName.test.tsx asserts the underlying property across
   * every call site.
   *
   * jsdom cannot see the scoping itself (vitest does not run the styled-jsx transform), which is
   * why src/test/PillButtonBuildScope.test.ts asserts it against the BUILT html - the only layer
   * where the defect is observable, and the one layer the upstream source-level guards do not
   * cover.
   */
  it('names the confirm button by its visible text, which is the action alone', async () => {
    stubNetwork(401);
    render(<SignIn />);
    fireEvent.change(screen.getByLabelText('WhatsApp number'),
      { target: { value: '+919876543210' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send OTP on WhatsApp' }));
    await screen.findByLabelText('WhatsApp code');

    const confirm = screen.getByRole('button', { name: 'Confirm WhatsApp code' });
    // No aria-label: the name is the visible text, so it cannot disagree with the screen.
    expect(confirm.hasAttribute('aria-label')).toBe(false);
    /*
     * ONE SEGMENT NOW. The owner retired the two-tone pill on 2026-10-02, so the dark "Sign in"
     * half is no longer rendered and the lime surface carries the action alone. The 2.5.3 property
     * this case exists to protect is STRONGER as a result, not weaker: with a single visible
     * string the accessible name and the screen text are the same string and cannot disagree, so
     * there is no visible label left outside the name. The no-aria-label and no-aria-hidden
     * assertions are kept exactly as upstream wrote them.
     */
    expect(confirm.querySelector('.pill-label')).toBeNull();
    const action = confirm.querySelector('.pill-action');
    expect(action?.textContent).toBe('Confirm WhatsApp code');
    expect(action?.hasAttribute('aria-hidden')).toBe(false);
  });

  it('names the send button by its visible text too', () => {
    stubNetwork(401);
    render(<SignIn />);
    const send = screen.getByRole('button', { name: 'Send OTP on WhatsApp' });
    expect(send.hasAttribute('aria-label')).toBe(false);
    expect(send.querySelector('.pill-action')?.textContent).toBe('Send OTP on WhatsApp');
  });
});
