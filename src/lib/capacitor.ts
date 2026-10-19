/**
 * Capacitor Native Integration - WECARE.DIGITAL
 *
 * Initializes all native plugins (push, splash, status bar, haptics,
 * deep links, keyboard) when running inside a Capacitor shell.
 * Safe no-op on web.
 */

import { Capacitor } from '@capacitor/core';
import { App, type URLOpenListenerEvent } from '@capacitor/app';
import { SplashScreen } from '@capacitor/splash-screen';
import { StatusBar, Style } from '@capacitor/status-bar';
import { PushNotifications } from '@capacitor/push-notifications';
import { Browser } from '@capacitor/browser';
import { Haptics, ImpactStyle } from '@capacitor/haptics';
import { Keyboard } from '@capacitor/keyboard';

/* ── Helpers ── */
export const isNative = () => Capacitor.isNativePlatform();
export const isIOS = () => Capacitor.getPlatform() === 'ios';
export const isAndroid = () => Capacitor.getPlatform() === 'android';

/* ── Push Notifications ── */
export async function initPushNotifications(
  onToken: (token: string) => void,
  onNotification: (data: any) => void,
) {
  if (!isNative()) return;

  const perm = await PushNotifications.requestPermissions();
  if (perm.receive !== 'granted') return;

  await PushNotifications.register();

  PushNotifications.addListener('registration', (token) => {
    console.log('[Push] Token:', token.value);
    onToken(token.value);
  });

  PushNotifications.addListener('registrationError', (err) => {
    console.error('[Push] Registration error:', err);
  });

  PushNotifications.addListener('pushNotificationReceived', (notification) => {
    console.log('[Push] Received:', notification);
    onNotification(notification);
  });

  PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
    console.log('[Push] Action:', action);
    onNotification(action.notification);
  });
}

/* ── Status Bar ── */
export async function configureStatusBar(dark = true, backgroundColor = '#1a3a2a') {
  if (!isNative()) return;
  await StatusBar.setStyle({ style: dark ? Style.Dark : Style.Light });
  if (isAndroid()) {
    await StatusBar.setBackgroundColor({ color: backgroundColor });
  }
}

/* ── Splash Screen ── */
export async function hideSplash() {
  if (!isNative()) return;
  await SplashScreen.hide({ fadeOutDuration: 300 });
}

/* ── Haptics ── */
export async function hapticTap() {
  if (!isNative()) return;
  await Haptics.impact({ style: ImpactStyle.Light });
}

export async function hapticSuccess() {
  if (!isNative()) return;
  await Haptics.notification({ type: 'SUCCESS' as any });
}

export async function hapticError() {
  if (!isNative()) return;
  await Haptics.notification({ type: 'ERROR' as any });
}

/* ── External Browser ── */
export async function openExternal(url: string) {
  if (isNative()) {
    await Browser.open({ url, presentationStyle: 'popover' });
  } else {
    window.open(url, '_blank', 'noopener');
  }
}

/* ── Deep Links ── */
export function initDeepLinks(navigate: (path: string) => void) {
  if (!isNative()) return;

  App.addListener('appUrlOpen', (event: URLOpenListenerEvent) => {
    // Handle wecare:// scheme and universal links. Rewritten onto the apex, which is
    // the host Amplify serves; retired legacy frontend host was retired and only 301'd here.
    let url: URL;
    try {
      url = new URL(event.url
        .replace('wecare://', 'https://wecare.digital/')
      );
    } catch {
      return;
    }
    // Short links — let the redirect Lambda resolve the code.
    //
    // TWO forms. Only the first is live as a URL:
    //   wecare.digital/r/<code>   canonical since 2026-09-26, what we mint now
    //   r.wecare.digital/<code>   every link issued before that — host now NXDOMAIN
    //
    // r.wecare.digital was RETIRED on 2026-09-28 (Route 53 record deleted under
    // confirmation YES R53-DELETE-001; API Gateway custom domain deleted in 396b87ad),
    // so that form no longer resolves in a browser at all. The branch below is kept
    // anyway, and deliberately: a native OS matches an incoming link against the host
    // list in the app manifest WITHOUT a DNS lookup, so an old link printed on physical
    // material or sitting in an already-delivered message can still be handed to the app
    // even though a browser would fail on it. When that happens this branch is the only
    // thing that resolves the code — and it does so via the apex, never by fetching the
    // dead host. Removing it would turn a link that still works into one that does not,
    // for installed users only, which is the worst failure shape.
    //
    // Do NOT read this branch as evidence the subdomain is alive. It is tolerance for
    // links already in the wild, not a live route. See PROTECTED_TABLES in
    // operations/system-cleanup for why those codes must keep resolving.
    const isApexShortLink =
      url.hostname === 'wecare.digital'
      && /^\/r\/.+/.test(url.pathname);

    if (url.hostname === 'r.wecare.digital' || isApexShortLink) {
      const code = isApexShortLink
        ? url.pathname.replace(/^\/r\//, '')
        : url.pathname.replace(/^\//, '');
      if (code) navigate(`/workspace/link?opened=${code}`);
      return;
    }
    const path = url.pathname;
    if (path) navigate(path);
  });
}

/* ── Back Button (Android) ── */
export function initBackButton(goBack: () => void) {
  if (!isAndroid()) return;

  App.addListener('backButton', ({ canGoBack }) => {
    if (canGoBack) {
      goBack();
    } else {
      App.exitApp();
    }
  });
}

/* ── Keyboard ── */
export function initKeyboard(
  onShow?: (height: number) => void,
  onHide?: () => void,
) {
  if (!isNative()) return;

  Keyboard.addListener('keyboardWillShow', (info) => {
    onShow?.(info.keyboardHeight);
  });

  Keyboard.addListener('keyboardWillHide', () => {
    onHide?.();
  });
}

/* ── Master Init ── */
export interface InitCapacitorOptions {
  push: (path: string) => void;
  back: () => void;
  /**
   * Called with the device's native push token (FCM on Android, APNs on iOS) once the user
   * grants permission and registration succeeds. The caller forwards it to the backend
   * (POST /push/register) so it can create the SNS platform endpoint. Optional: omit it and
   * push is simply not initialised (the previous behaviour). It lives in _app.tsx rather than
   * here so this module stays free of the API client — the token-to-backend hop needs the
   * authenticated fetch, and keeping that dependency out of the native-init module avoids
   * pulling the whole client into the plugin layer.
   */
  onPushToken?: (token: string, platform: 'ios' | 'android') => void;
  /** Called when a push notification is received or tapped (optional). */
  onPushNotification?: (data: unknown) => void;
  /** Android status-bar background for this shell. Internal CRM keeps green; public app uses white. */
  statusBarBackground?: string;
}

export async function initCapacitor(opts: InitCapacitorOptions) {
  if (!isNative()) return;

  await configureStatusBar(true, opts.statusBarBackground || '#1a3a2a');
  await hideSplash();
  initDeepLinks((path) => opts.push(path));
  initBackButton(() => opts.back());
  initKeyboard();

  // Push: only armed when the caller supplies a token sink. requestPermissions() shows the OS
  // prompt, so gating on onPushToken keeps a build that does not wire delivery from asking.
  if (opts.onPushToken) {
    const platform: 'ios' | 'android' = isIOS() ? 'ios' : 'android';
    await initPushNotifications(
      (token) => opts.onPushToken!(token, platform),
      (data) => opts.onPushNotification?.(data),
    );
  }
}
