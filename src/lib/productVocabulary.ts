/**
 * Versioned, provider-neutral product vocabulary.
 *
 * Why this exists
 * ---------------
 * Before 2026-09-23 ten screens told operators the SMS channel ran on
 * "AWS Pinpoint + Airtel IQ". Neither is true: SMS goes through AWS End User
 * Messaging, and Airtel is a prohibited provider that was retired entirely — its
 * functions, secrets, routes and tables are all gone from the account. One screen
 * listed the Lambda `wecare-sms-in-airtel` with status `active`, and that function does
 * not exist.
 *
 * A false statement about the live system is worse on a dashboard than anywhere else,
 * because an operator reads it while deciding what to do next.
 *
 * The rule
 * --------
 * Ordinary UI names the CAPABILITY, not the provider. "SMS" and "Business Calling" are
 * product words; "AWS End User Messaging" and "Plivo" are implementation. Exact
 * provider and resource names belong on the Technical Details surfaces, which are
 * allowlisted in `scripts/check_ui_labels.py` and checked in CI.
 *
 * A retired provider may still be NAMED where it labels historical data — an old call
 * record genuinely was carried by Airtel and the row has to say something. The gate
 * allows that when the same line carries a historical marker, so write
 * `'Airtel (historical)'` rather than `'Airtel'`.
 *
 * Versioned because these strings appear in navigation, headings, empty states and
 * error states, and a rename that hits only half of them is how the SMS channel came
 * to be described three different ways.
 */

export const VOCABULARY_VERSION = '1';

/** Channel names as a user should see them. Capability, never provider. */
export const channel = {
  whatsapp: 'WhatsApp Business',
  sms: 'SMS',
  rcs: 'RCS',
  email: 'Email',
  voice: 'Business Calling',
  inbox: 'Common Inbox',
  push: 'Push',
} as const;

/**
 * How a channel is described in ordinary UI. Deliberately says what it does, not who
 * carries it — the provider can change without every screen becoming wrong, which is
 * exactly what happened when Airtel and Pinpoint were retired.
 */
export const channelDescription = {
  whatsapp: 'Conversations, templates and calling on WhatsApp Business',
  sms: 'Transactional and promotional SMS, with DLT templates for India',
  rcs: 'Rich messaging where the handset and sender support it',
  email: 'Transactional email and campaigns',
  voice: 'Inbound and outbound calling, IVR and call records',
  inbox: 'Every channel in one thread per customer',
  push: 'Web and mobile push notifications',
} as const;

/**
 * The only place a retired provider name is correct in ordinary UI: labelling data
 * that really was carried by it. The marker is required — the CI gate keys on it.
 */
export const historicalProvider = {
  airtel: 'Airtel (historical)',
  payu: 'PayU (historical)',
  pinpoint: 'Pinpoint (historical)',
} as const;

/** Empty and error states, so "nothing here" and "we could not load" stay distinct. */
export const state = {
  empty: 'Nothing here yet',
  emptyFiltered: 'No results for this filter',
  loadFailed: 'Could not load this. Nothing was changed.',
  // Matches the backend's `providerUnavailable` marker, which exists so an outage is
  // distinguishable from an answer.
  providerUnavailable: 'This service is unavailable right now. Nothing was changed.',
  refused: 'Not permitted from here. Ask an administrator.',
  stale: 'Showing the last known values; these may be out of date.',
  partial: 'Showing a sample, not a total.',
} as const;

export type ChannelKey = keyof typeof channel;
