/**
 * Audio capture preflight for the browser softphone.
 *
 * The problem this solves is diagnostic, not functional. `getUserMedia` can fail
 * for half a dozen container reasons, and in the most common one the browser does
 * not reject the call at all - it omits `navigator.mediaDevices` entirely, so the
 * failure arrives as
 *
 *     TypeError: Cannot read properties of undefined (reading 'getUserMedia')
 *
 * the WhatsApp calling page shows failures with `setError(e.message)`, so that string was
 * what an operator saw. It names the wrong layer: nothing is undefined by mistake,
 * the container simply does not expose the API. Each reason it might not has a
 * different fix, and several of them are in the native project rather than in any
 * of this code.
 *
 * Both shells are real targets: `ios/` and `android/` exist in this repo.
 *
 * What the checks are based on
 * ---------------------------
 * `isSecureContext` is the test, deliberately NOT `location.protocol === 'https:'`:
 * http://localhost IS a secure context, so a protocol check breaks local
 * development, and an https document inside an insecure parent frame is NOT one, so
 * a protocol check also misses a real failure.
 *
 * Inside WKWebView a custom scheme such as capacitor:// counts as secure from
 * iOS 14.6 onward, so "serve it over https" is the wrong first suggestion there.
 * The real iOS cause of an absent `mediaDevices` is a missing microphone usage
 * description in Info.plist - a native manifest omission that surfaces as a
 * JavaScript undefined, which is not diagnosable from the error text alone. Both
 * manifests in this repo currently do declare it (`NSMicrophoneUsageDescription`
 * in ios/App/App/Info.plist, `RECORD_AUDIO` in the Android manifest), so this is a
 * regression guard as much as a diagnosis.
 *
 * Sources (content rephrased for compliance with licensing restrictions):
 *  - [getUserMedia is available only in a secure context](https://stackoverflow.com/questions/67144074/ot-publisher-access-denied-end-user-denied-permission-to-hardware-devices-getus)
 *  - [mediaDevices is undefined without the Info.plist microphone description](https://stackoverflow.com/questions/68620046/capacitor-3-react-app-mediadevices-is-undefined-ios-14-5)
 *  - [custom schemes count as secure on WKWebView from around iOS 14.6](https://forum.ionicframework.com/t/mediastream-for-video-and-audio/230695)
 *  - [capacitor://localhost with an explicit port aborts](https://github.com/ionic-team/capacitor/issues/6759)
 *  - [CallKit and a WKWebView renderer contend for the microphone](https://stackoverflow.com/questions/67885347/ios-14-5-wkwebviews-getusermedia-errors-notreadableerror-after-callkit-takes-ov)
 *
 * This module does not import @capacitor/core. Doing so would pull the whole
 * plugin surface into a preflight that runs on the call path, and into every test
 * that touches it. The environment is injected instead.
 */

export type AudioBlocker =
  | 'OK'
  | 'NO_DOM'
  | 'INSECURE_CONTEXT'
  | 'NO_MEDIA_DEVICES'
  | 'NO_GET_USER_MEDIA'
  | 'PERMISSION_DENIED'
  | 'NO_MICROPHONE'
  | 'MICROPHONE_BUSY'
  | 'ABORTED'
  | 'UNKNOWN';

export type WebContainer = 'browser' | 'android-webview' | 'ios-wkwebview' | 'unknown';

export interface AudioCapability {
  /** True only when a getUserMedia call is worth attempting. */
  usable: boolean;
  blocker: AudioBlocker;
  /** Operator-facing and actionable. Never empty. */
  reason: string;
  container: WebContainer;
  secureContext: boolean;
}

/** The slice of the runtime this module reads. Injectable so a test cannot leak a
 *  broken navigator into the next one. */
export interface MediaEnv {
  userAgent: string;
  protocol: string;
  isSecureContext: boolean;
  mediaDevices?: { getUserMedia?: (c: unknown) => Promise<MediaStream> };
}

export class AudioCapabilityError extends Error {
  readonly blocker: AudioBlocker;
  readonly container: WebContainer;

  constructor(blocker: AudioBlocker, container: WebContainer, cause?: unknown) {
    super(describeAudioBlocker(blocker, container), { cause });
    this.name = 'AudioCapabilityError';
    this.blocker = blocker;
    this.container = container;
  }
}

/** Read the live runtime. Returns null during server rendering. */
export function currentMediaEnv(): MediaEnv | null {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return null;
  return {
    userAgent: navigator.userAgent || '',
    protocol: window.location?.protocol || '',
    isSecureContext: Boolean(window.isSecureContext),
    mediaDevices: navigator.mediaDevices as MediaEnv['mediaDevices'],
  };
}

export function detectContainer(userAgent: string, protocol: string): WebContainer {
  // A custom scheme can only come from the native shell, so it outranks the user
  // agent - which is trivially spoofable and gets rewritten by shells anyway.
  const scheme = String(protocol || '').toLowerCase();
  if (scheme.startsWith('capacitor') || scheme.startsWith('ionic')) {
    return 'ios-wkwebview';
  }

  const ua = String(userAgent || '');
  if (!ua) return 'unknown';

  // Android's WebView appends `; wv`. Both Android strings contain "Chrome" and
  // "Safari", so that token is the only thing that separates them.
  if (/\bwv\b/.test(ua) || /;\s*wv[);]/.test(ua)) return 'android-webview';

  if (/iPhone|iPad|iPod/.test(ua)) {
    // There is no WebView-specific token on iOS. WKWebView omits "Safari/" and
    // iOS Safari includes it, so the absence is the signal.
    return /Safari\//.test(ua) ? 'browser' : 'ios-wkwebview';
  }

  if (/Mozilla|Chrome|Safari|Firefox|Edg\//.test(ua)) return 'browser';
  return 'unknown';
}

export function inspectAudioCapability(
  environment: MediaEnv | null = currentMediaEnv(),
): AudioCapability {
  if (!environment) {
    return {
      usable: false,
      blocker: 'NO_DOM',
      reason: describeAudioBlocker('NO_DOM', 'unknown'),
      container: 'unknown',
      secureContext: false,
    };
  }

  const container = detectContainer(environment.userAgent, environment.protocol);
  const secureContext = Boolean(environment.isSecureContext);

  const settle = (blocker: AudioBlocker): AudioCapability => ({
    usable: blocker === 'OK',
    blocker,
    reason: describeAudioBlocker(blocker, container),
    container,
    secureContext,
  });

  if (!environment.mediaDevices) {
    // Order matters. An insecure context is only the explanation OUTSIDE the
    // native shells: capacitor:// is already secure on WKWebView, so blaming the
    // context there sends someone to reconfigure TLS for a problem that lives in
    // Info.plist.
    if (!secureContext && container === 'browser') return settle('INSECURE_CONTEXT');
    if (!secureContext && container === 'unknown') return settle('INSECURE_CONTEXT');
    return settle('NO_MEDIA_DEVICES');
  }

  if (typeof environment.mediaDevices.getUserMedia !== 'function') {
    return settle('NO_GET_USER_MEDIA');
  }

  if (!secureContext) return settle('INSECURE_CONTEXT');

  return settle('OK');
}

/** Map what getUserMedia threw onto a cause. Never guesses. */
export function classifyMediaError(error: unknown): AudioBlocker {
  if (!error) return 'UNKNOWN';

  const name = String((error as { name?: string }).name || '');
  const message = String((error as { message?: string }).message || '');

  // The unguarded call's own failure mode: a TypeError about reading a property
  // of undefined is the container missing the API, not a media problem.
  if (name === 'TypeError' && /undefined|null/i.test(message)
      && /getUserMedia|mediaDevices/i.test(message)) {
    return 'NO_MEDIA_DEVICES';
  }

  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
    case 'SecurityError':
      return 'PERMISSION_DENIED';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return 'NO_MICROPHONE';
    case 'NotReadableError':
    case 'TrackStartError':
      return 'MICROPHONE_BUSY';
    case 'AbortError':
      return 'ABORTED';
    default:
      return 'UNKNOWN';
  }
}

export function describeAudioBlocker(
  blocker: AudioBlocker,
  container: WebContainer,
): string {
  const ios = container === 'ios-wkwebview';
  const android = container === 'android-webview';

  switch (blocker) {
    case 'OK':
      return 'Microphone capture is available.';

    case 'NO_DOM':
      return 'No browser environment. Audio capture can only be checked in the browser, '
        + 'not during server rendering.';

    case 'INSECURE_CONTEXT':
      return 'This page is not a secure context, so the browser withholds microphone '
        + 'access entirely. Serve the app over https. Note that http://localhost is '
        + 'already a secure context, and an https page inside an insecure parent frame '
        + 'is not.';

    case 'NO_MEDIA_DEVICES':
      if (ios) {
        return 'The iOS shell exposes no media devices. The usual cause is a missing '
          + 'NSMicrophoneUsageDescription in Info.plist - without it WKWebView omits '
          + 'navigator.mediaDevices rather than prompting. A capacitor:// origin is '
          + 'already a secure context on iOS 14.6 and later, so TLS is not the problem. '
          + 'Also check the origin carries no explicit port, which aborts capture.';
      }
      if (android) {
        return 'The Android WebView exposes no media devices. Confirm RECORD_AUDIO is '
          + 'declared in AndroidManifest.xml and that the host app grants the WebView\'s '
          + 'onPermissionRequest for audio capture - the manifest permission alone is '
          + 'not enough.';
      }
      return 'This browser exposes no media devices, so microphone capture is '
        + 'unavailable. Confirm the page is a secure context and that no policy is '
        + 'blocking media capture.';

    case 'NO_GET_USER_MEDIA':
      return 'This browser exposes media devices but no getUserMedia, so it cannot '
        + 'capture audio. It is too old for the softphone.';

    case 'PERMISSION_DENIED':
      if (ios) {
        return 'Microphone access was refused. Grant it in iOS Settings for this app, '
          + 'then reopen the screen - iOS does not re-prompt once refused.';
      }
      if (android) {
        return 'Microphone access was refused. Grant it in Android app permissions, '
          + 'then reopen the screen.';
      }
      return 'Microphone access was refused. Allow it in the browser\'s site '
        + 'permissions and reload.';

    case 'NO_MICROPHONE':
      return 'No microphone the browser can use was found. Connect or enable an input '
        + 'device and try again.';

    case 'MICROPHONE_BUSY':
      if (ios) {
        return 'The microphone is held by something else. On iOS a native call layer '
          + 'such as CallKit takes exclusive hold and the WKWebView renderer cannot '
          + 'also capture, so end any other call or recording first.';
      }
      return 'The microphone is in use by another app or tab. Close it and try again.';

    case 'ABORTED':
      if (ios) {
        return 'Capture was aborted by the system. On iOS this is also what an origin '
          + 'carrying an explicit port produces - capacitor://localhost works where '
          + 'capacitor://localhost:8080 aborts.';
      }
      return 'Capture was aborted by the system before it started. Try again.';

    case 'UNKNOWN':
    default:
      return 'Microphone capture failed for an unrecognised reason. The underlying '
        + 'error is attached for diagnosis rather than guessed at here.';
  }
}

/**
 * Acquire an audio stream, or throw an `AudioCapabilityError` that says why.
 *
 * Preflights first so an incapable container fails with a diagnosis instead of a
 * TypeError, and translates a rejection from getUserMedia into the same shape, so
 * one catch handles both.
 */
export async function acquireAudioStream(
  constraints: MediaStreamConstraints = { audio: true },
  environment: MediaEnv | null = currentMediaEnv(),
): Promise<MediaStream> {
  const capability = inspectAudioCapability(environment);
  if (!capability.usable || !environment?.mediaDevices?.getUserMedia) {
    throw new AudioCapabilityError(
      capability.usable ? 'NO_GET_USER_MEDIA' : capability.blocker,
      capability.container,
    );
  }

  try {
    return await environment.mediaDevices.getUserMedia(constraints);
  } catch (error) {
    throw new AudioCapabilityError(
      classifyMediaError(error), capability.container, error);
  }
}
