/**
 * Push-token registration (native app shell, Phase 3).
 *
 * Forwards the device's native push token to the backend so it can create an SNS platform
 * endpoint and map it to the authenticated user. The backend handler
 * (amplify/functions/messaging/push-notifications/handler.py) exposes POST /push/register,
 * injects the userId server-side from the Cognito caller, and expects { deviceToken, platform }.
 *
 * This lives OUTSIDE src/lib/capacitor.ts on purpose: the native-plugin module stays free of
 * the API client, and _app.tsx wires the token sink by handing this function to initCapacitor.
 * On the web it is never called (initCapacitor only arms push inside the native shell).
 */
import { authFetch } from '../api/client';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

/**
 * POST the native push token to the backend. Best-effort: a failure here must never break the
 * app launch, so it swallows errors (the token is re-offered by the OS on the next registration).
 */
export async function registerPushToken( deviceToken: string, platform: 'ios' | 'android' ): Promise<void> {
  if ( !deviceToken ) return;
  try {
    await authFetch( `${API_BASE}/push/register`, {
      method: 'POST',
      body: JSON.stringify( { deviceToken, platform } ),
    } );
  } catch {
    // Non-fatal: the device token is offered again by the OS on the next registration event,
    // so a transient network/auth failure at launch does not permanently lose the token.
  }
}
