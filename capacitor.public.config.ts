import type { CapacitorConfig } from '@capacitor/cli';
import { KeyboardResize } from '@capacitor/keyboard';

/**
 * Public customer-app shell.
 *
 * This is intentionally separate from capacitor.config.ts, which belongs to the internal
 * Stack CRM app. The bundle id is required from the release environment so a temporary
 * engineering default can never become a permanent App Store / Play Store identifier.
 */
const appId = process.env.WECARE_PUBLIC_APP_ID;
if ( !appId ) {
  throw new Error( 'WECARE_PUBLIC_APP_ID is required for the public WECARE.DIGITAL app shell.' );
}

const config: CapacitorConfig = {
  appId,
  appName: 'WECARE.DIGITAL',
  webDir: 'out',
  plugins: {
    SplashScreen: {
      launchShowDuration: 1200,
      launchAutoHide: true,
      backgroundColor: '#ffffff',
      showSpinner: false,
      splashFullScreen: true,
      splashImmersive: true,
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#ffffff',
      overlaysWebView: false,
    },
    Keyboard: {
      resize: KeyboardResize.Body,
      resizeOnFullScreen: true,
    },
  },
  ios: {
    scheme: 'WECARE.DIGITAL',
    contentInset: 'automatic',
    preferredContentMode: 'mobile',
    backgroundColor: '#ffffff',
  },
  android: {
    backgroundColor: '#ffffff',
    allowMixedContent: false,
    captureInput: true,
    webContentsDebuggingEnabled: false,
  },
};

export default config;
