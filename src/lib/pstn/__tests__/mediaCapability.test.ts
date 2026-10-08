/**
 * Audio capture preflight — the softphone's device matrix, at contract level.
 *
 * Why this exists
 * ---------------
 * `the retired WebRTC hook` called `navigator.mediaDevices.getUserMedia`
 * with no guard, and the hook surfaces failures with `setError(e.message)`. In a
 * container where `navigator.mediaDevices` is undefined that message reads
 *
 *     Cannot read properties of undefined (reading 'getUserMedia')
 *
 * which tells an operator nothing and points a developer at the wrong layer. The
 * cause is never "the code is broken"; it is one of a small, known set of
 * container conditions, and each one has a different fix.
 *
 * Both native shells are real targets here: `ios/` and `android/` exist and
 * package.json has cap:add:ios / cap:add:android.
 *
 * The container conditions, and why each is in the table
 * -----------------------------------------------------
 *  - getUserMedia is secure-context only. In an insecure context the browser does
 *    not merely reject the call, it omits `navigator.mediaDevices` entirely, so the
 *    symptom is a TypeError rather than a permission error.
 *  - `isSecureContext` is the correct test, NOT `location.protocol === 'https:'`.
 *    http://localhost IS a secure context, so a protocol check breaks local
 *    development, and an https page inside an insecure parent frame is NOT one, so
 *    a protocol check also misses a real failure.
 *  - On WKWebView, a custom scheme such as capacitor:// counts as secure on
 *    iOS 14.6 and later. So "insecure context" is the wrong first guess inside the
 *    iOS shell, and this module must not offer it.
 *  - The actual iOS trap: `navigator.mediaDevices` is undefined when the app has
 *    no microphone usage description in Info.plist. A native manifest omission
 *    presenting as a JavaScript undefined is not diagnosable from the error alone,
 *    so the module names it.
 *
 * Sources (content rephrased for compliance with licensing restrictions):
 *  - [getUserMedia is secure-context only](https://stackoverflow.com/questions/67144074/ot-publisher-access-denied-end-user-denied-permission-to-hardware-devices-getus)
 *  - [mediaDevices undefined without the Info.plist microphone description](https://stackoverflow.com/questions/68620046/capacitor-3-react-app-mediadevices-is-undefined-ios-14-5)
 *  - [custom schemes are treated as secure on WKWebView from ~iOS 14.6](https://forum.ionicframework.com/t/mediastream-for-video-and-audio/230695)
 *  - [capacitor://localhost with an explicit port aborts](https://github.com/ionic-team/capacitor/issues/6759)
 *  - [CallKit and WKWebView contend for the microphone](https://stackoverflow.com/questions/67885347/ios-14-5-wkwebviews-getusermedia-errors-notreadableerror-after-callkit-takes-ov)
 *
 * This is a preflight, not a call. Browser routing is off
 * (PSTN_BROWSER_ROUTING_ENABLED absent on every function), so there is no live
 * call to place and nothing here dials anything.
 */
import { describe, expect, it, vi } from 'vitest';

import {
  AudioCapabilityError,
  acquireAudioStream,
  classifyMediaError,
  describeAudioBlocker,
  detectContainer,
  inspectAudioCapability,
} from '../mediaCapability';

const IOS_WEBVIEW_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148';
const IOS_SAFARI_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
const ANDROID_WEBVIEW_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36; wv';
const ANDROID_CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36';
const DESKTOP_UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';

/** A minimal environment. Injected rather than patched onto globals so one test
 *  cannot leak a broken navigator into the next. */
function env(overrides: Record<string, unknown> = {}) {
  return {
    userAgent: DESKTOP_UA,
    protocol: 'https:',
    isSecureContext: true,
    platform: undefined,
    mediaDevices: { getUserMedia: vi.fn(async () => ({ id: 'stream' })) },
    ...overrides,
  } as any;
}

// ==========================================================================
// container detection — which shell are we actually in
// ==========================================================================
describe('detectContainer', () => {
  it('names the desktop browser', () => {
    expect(detectContainer(DESKTOP_UA, 'https:')).toBe('browser');
  });

  it('separates the Android WebView from Android Chrome', () => {
    // The `; wv` token is the only reliable marker: both strings contain
    // "Chrome" and "Safari", so matching on those cannot tell them apart.
    expect(detectContainer(ANDROID_WEBVIEW_UA, 'https:')).toBe('android-webview');
    expect(detectContainer(ANDROID_CHROME_UA, 'https:')).toBe('browser');
  });

  it('separates WKWebView from iOS Safari', () => {
    // WKWebView omits the "Safari/" token. iOS Safari includes it. There is no
    // WebView-specific token on iOS, so the absence is the signal.
    expect(detectContainer(IOS_WEBVIEW_UA, 'https:')).toBe('ios-wkwebview');
    expect(detectContainer(IOS_SAFARI_UA, 'https:')).toBe('browser');
  });

  it('trusts a capacitor scheme over the user agent', () => {
    // A custom scheme can only come from the native shell, so it outranks a UA
    // string, which is trivially spoofable and gets rewritten by shells.
    expect(detectContainer(DESKTOP_UA, 'capacitor:')).toBe('ios-wkwebview');
  });

  it('does not guess when there is nothing to go on', () => {
    expect(detectContainer('', '')).toBe('unknown');
  });
});

// ==========================================================================
// the happy path
// ==========================================================================
describe('inspectAudioCapability', () => {
  it('reports usable when the container can capture audio', () => {
    const cap = inspectAudioCapability(env());
    expect(cap.usable).toBe(true);
    expect(cap.blocker).toBe('OK');
    expect(cap.secureContext).toBe(true);
  });

  // ------------------------------------------------------------------
  // secure context
  // ------------------------------------------------------------------
  it('uses isSecureContext rather than the protocol, so http://localhost works', () => {
    const cap = inspectAudioCapability(
      env({ protocol: 'http:', isSecureContext: true, userAgent: DESKTOP_UA }),
    );
    expect(cap.usable).toBe(true);
    expect(cap.blocker).toBe('OK');
  });

  it('refuses an https page inside an insecure context', () => {
    // A protocol check would call this fine. It is not: an https document in an
    // insecure parent frame has no mediaDevices.
    const cap = inspectAudioCapability(
      env({ protocol: 'https:', isSecureContext: false, mediaDevices: undefined }),
    );
    expect(cap.usable).toBe(false);
    expect(cap.blocker).toBe('INSECURE_CONTEXT');
  });

  it('does not blame the secure context inside the iOS shell', () => {
    // capacitor:// is secure on WKWebView from iOS 14.6, so "serve over https"
    // is the wrong advice there and would send someone down a dead end. The
    // missing Info.plist description is the real cause.
    const cap = inspectAudioCapability(
      env({
        userAgent: IOS_WEBVIEW_UA,
        protocol: 'capacitor:',
        isSecureContext: true,
        mediaDevices: undefined,
      }),
    );
    expect(cap.container).toBe('ios-wkwebview');
    expect(cap.blocker).toBe('NO_MEDIA_DEVICES');
    expect(cap.reason).toMatch(/Info\.plist|NSMicrophoneUsageDescription/i);
    expect(cap.reason).not.toMatch(/serve the app over https/i);
  });

  // ------------------------------------------------------------------
  // the two shapes of "no API"
  // ------------------------------------------------------------------
  it('distinguishes an absent mediaDevices from an absent getUserMedia', () => {
    expect(inspectAudioCapability(env({ mediaDevices: undefined })).blocker)
      .toBe('NO_MEDIA_DEVICES');
    expect(inspectAudioCapability(env({ mediaDevices: {} })).blocker)
      .toBe('NO_GET_USER_MEDIA');
  });

  it('points the Android WebView at its own permission plumbing', () => {
    const cap = inspectAudioCapability(
      env({ userAgent: ANDROID_WEBVIEW_UA, mediaDevices: undefined }),
    );
    expect(cap.container).toBe('android-webview');
    expect(cap.reason).toMatch(/RECORD_AUDIO|onPermissionRequest/i);
  });

  it('reports no DOM rather than throwing during server rendering', () => {
    const cap = inspectAudioCapability(null);
    expect(cap.usable).toBe(false);
    expect(cap.blocker).toBe('NO_DOM');
  });

  it('never returns an empty reason', () => {
    const cases = [
      env(),
      env({ mediaDevices: undefined }),
      env({ mediaDevices: {} }),
      env({ isSecureContext: false, mediaDevices: undefined }),
      null,
    ];
    for (const e of cases) {
      const cap = inspectAudioCapability(e as any);
      expect(cap.reason.length).toBeGreaterThan(0);
    }
  });
});

// ==========================================================================
// classifying what getUserMedia actually threw
// ==========================================================================
describe('classifyMediaError', () => {
  const named = (name: string) => Object.assign(new Error(name), { name });

  it.each([
    ['NotAllowedError', 'PERMISSION_DENIED'],
    ['SecurityError', 'PERMISSION_DENIED'],
    ['NotFoundError', 'NO_MICROPHONE'],
    ['OverconstrainedError', 'NO_MICROPHONE'],
    ['NotReadableError', 'MICROPHONE_BUSY'],
    ['TrackStartError', 'MICROPHONE_BUSY'],
    ['AbortError', 'ABORTED'],
  ])('maps %s to %s', (name, blocker) => {
    expect(classifyMediaError(named(name))).toBe(blocker);
  });

  it('maps the undefined-property TypeError to the missing API, not to UNKNOWN', () => {
    // This is the error the unguarded call actually produced, and it is a
    // container problem rather than a media problem.
    const err = new TypeError(
      "Cannot read properties of undefined (reading 'getUserMedia')",
    );
    expect(classifyMediaError(err)).toBe('NO_MEDIA_DEVICES');
  });

  it('does not invent a cause for an unrecognised error', () => {
    expect(classifyMediaError(named('KettleError'))).toBe('UNKNOWN');
    expect(classifyMediaError(undefined)).toBe('UNKNOWN');
  });
});

describe('describeAudioBlocker', () => {
  it('gives container-specific advice for the same blocker', () => {
    const ios = describeAudioBlocker('PERMISSION_DENIED', 'ios-wkwebview');
    const web = describeAudioBlocker('PERMISSION_DENIED', 'browser');
    expect(ios).not.toBe(web);
    expect(ios).toMatch(/Settings/i);
  });

  it('explains the CallKit contention that only affects the iOS shell', () => {
    expect(describeAudioBlocker('MICROPHONE_BUSY', 'ios-wkwebview'))
      .toMatch(/CallKit|another app/i);
  });

  it('covers every blocker it can be handed', () => {
    const blockers = [
      'OK', 'NO_DOM', 'INSECURE_CONTEXT', 'NO_MEDIA_DEVICES',
      'NO_GET_USER_MEDIA', 'PERMISSION_DENIED', 'NO_MICROPHONE',
      'MICROPHONE_BUSY', 'ABORTED', 'UNKNOWN',
    ] as const;
    for (const b of blockers) {
      for (const c of ['browser', 'android-webview', 'ios-wkwebview', 'unknown'] as const) {
        expect(describeAudioBlocker(b, c).length).toBeGreaterThan(0);
      }
    }
  });
});

// ==========================================================================
// acquisition — the guard in front of the real call
// ==========================================================================
describe('acquireAudioStream', () => {
  it('returns the stream when the container is capable', async () => {
    const e = env();
    const stream = await acquireAudioStream({ audio: true }, e);
    expect(stream).toEqual({ id: 'stream' });
    expect(e.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true });
  });

  it('refuses before calling getUserMedia when the container cannot capture', async () => {
    const e = env({ mediaDevices: undefined });
    await expect(acquireAudioStream({ audio: true }, e))
      .rejects.toBeInstanceOf(AudioCapabilityError);
  });

  it('carries the blocker and container on the error, not just a string', async () => {
    const e = env({ userAgent: IOS_WEBVIEW_UA, mediaDevices: undefined });
    await expect(acquireAudioStream({ audio: true }, e)).rejects.toMatchObject({
      blocker: 'NO_MEDIA_DEVICES',
      container: 'ios-wkwebview',
    });
  });

  it('translates a rejection from getUserMedia into the same shape', async () => {
    const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
    const e = env({
      mediaDevices: { getUserMedia: vi.fn(async () => { throw denied; }) },
    });
    await expect(acquireAudioStream({ audio: true }, e)).rejects.toMatchObject({
      blocker: 'PERMISSION_DENIED',
    });
  });

  it('keeps the original error reachable for a developer', async () => {
    const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
    const e = await acquireAudioStream(
      { audio: true },
      env({ mediaDevices: { getUserMedia: vi.fn(async () => { throw denied; }) } }),
    ).catch((err) => err);
    expect(e.cause).toBe(denied);
  });

  it('never surfaces a raw undefined-property message to the operator', async () => {
    const e = env({ mediaDevices: undefined });
    const err = await acquireAudioStream({ audio: true }, e).catch((x) => x);
    expect(err.message).not.toMatch(/Cannot read propert/i);
    expect(err.message.length).toBeGreaterThan(20);
  });
});
