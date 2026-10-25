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
/**
 * Arm push for a device that ALREADY granted notification permission. Never prompts.
 *
 * This runs from _app.tsx's mount effect, i.e. on every launch of BOTH native shells, before
 * anyone has signed in or tapped anything. It used to call requestPermissions(), which put the
 * OS notification prompt in front of every first launch - including the public WECARE.DIGITAL
 * shell, whose visitors have no staff session and so can never complete POST /push/register.
 * .kiro/steering/00-common.md requires a prompt to follow a clear user action and an explanation,
 * and never to appear on load.
 *
 * checkPermissions() reads the state without showing anything, so a device that granted earlier
 * keeps registering exactly as before. Asking a device that has not been asked is now the job of
 * an explicit, explained opt-in control, which does not exist yet - that is the release gate for
 * push on new installs, stated rather than worked around with a launch-time prompt.
 */
export async function initPushNotifications(
  onToken: (token: string) => void,
  onNotification: (data: any) => void,
) {
  if (!isNative()) return;

  const perm = await PushNotifications.checkPermissions();
  if (perm.receive !== 'granted') return;

  await PushNotifications.register();

  PushNotifications.addListener('registration', (token) => {
    // The token itself is not logged: it addresses this device for pushes.
    console.log('[Push] Registered');
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
    // Short links use the canonical apex path only.
    const isApexShortLink =
      url.hostname === 'wecare.digital'
      && /^\/r\/.+/.test(url.pathname);

    if (isApexShortLink) {
      const code = url.pathname.replace(/^\/r\//, '');
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
   * Called with the device's native push token (FCM on Android, APNs on iOS) when the device has
   * already granted notification permission and registration succeeds - launch never prompts.
   * The caller forwards it to the backend
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

  // Push: only armed when the caller supplies a token sink, and only for a device that already
  // granted permission - initPushNotifications never shows the OS prompt (see its note).
  if (opts.onPushToken) {
    const platform: 'ios' | 'android' = isIOS() ? 'ios' : 'android';
    await initPushNotifications(
      (token) => opts.onPushToken!(token, platform),
      (data) => opts.onPushNotification?.(data),
    );
  }
}
