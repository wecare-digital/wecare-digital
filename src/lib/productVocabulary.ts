/**
 * Versioned, provider-neutral product vocabulary.
 * Ordinary UI names capabilities rather than implementation providers.
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
 * so implementation changes do not make product copy stale.
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
