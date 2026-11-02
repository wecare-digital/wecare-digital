/**
 * API Service Layer — public barrel (FEAT-002 decomposition).
 *
 * The implementation was split into a shared core engine (./core) and domain
 * modules (./domains/*). This file preserves the EXACT public export surface so
 * every existing `import ... from '.../api/client'` site keeps working unchanged.
 *
 * Only previously-public names are re-exported here; internal helpers that the
 * domain modules share (apiCall, delay, getAuthToken, recordFailure, WA_BIZ_BASE)
 * stay internal to ./core and are intentionally NOT part of this surface.
 */

// Core engine: re-export the previously-public core symbols explicitly so the
// internal helpers exported from ./core do not leak into the public surface.
export {
  getConnectionStatus,
  getLastApiFailure,
  collectApiFailures,
  authFetch,
  verifyAdminAccess,
  apiCallResult,
  testConnection,
} from './core';
export type { ApiFailureKind, ApiFailure, ApiResult, CheckoutDeliveryAddress } from './core';

// Domain modules: these export only previously-public wrapper + type names.
export * from './domains/contacts';
export * from './domains/messaging';
export * from './domains/telephony';
export * from './domains/whatsapp';
export * from './domains/commerce';
export * from './domains/platform';
