/**
 * WhatsApp Cloud API error codes → human-readable reason + suggested action.
 *
 * Canonical codes returned by the WhatsApp Business Platform. Used to turn a raw
 * Meta error code (stored on failed messages) into a readable tooltip in the UI.
 *
 * Reference: Meta "Cloud API error codes"
 * https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
 * (content paraphrased for compliance with licensing).
 */

export type WaErrorCategory =
    | 'auth' | 'rate_limit' | 'integrity' | 'template'
    | 'delivery' | 'media' | 'flow' | 'other';

export interface WaErrorInfo {
    title: string;
    reason: string;
    action: string;
    category: WaErrorCategory;
    retriable: boolean;
}

export const WA_ERROR_CODES: Record<number, WaErrorInfo> = {
    // ── Authorization ──
    0: { title: 'Auth error', reason: 'The app behind the sender could not be authenticated.', action: 'Reconnect the WhatsApp sender.', category: 'auth', retriable: false },
    3: { title: 'API method', reason: 'The calling app is missing the required permissions.', action: 'Reconnect with the full permission set.', category: 'auth', retriable: false },
    10: { title: 'Permission denied', reason: 'The phone number is not registered to this WABA or messaging permission was revoked.', action: 'Verify the number is connected to your account.', category: 'auth', retriable: false },
    190: { title: 'Access token expired', reason: 'The access token rotated or was invalidated.', action: 'Reconnect the sender to refresh the token.', category: 'auth', retriable: false },
    200: { title: 'Permission error', reason: 'A required capability (templates/media/flows) is disabled.', action: 'Check the WABA status in WhatsApp Manager.', category: 'auth', retriable: false },

    // ── Rate limit / throughput ──
    4: { title: 'Too many calls', reason: 'App-level API call rate limit reached.', action: 'Back off and retry with exponential delay.', category: 'rate_limit', retriable: true },
    80007: { title: 'Rate limit reached', reason: 'Sender-level send rate exceeded.', action: 'Retry after a short delay.', category: 'rate_limit', retriable: true },
    130429: { title: 'Throughput limit', reason: 'Too many messages per second on the WABA.', action: 'Spread sends out / pace the campaign.', category: 'rate_limit', retriable: true },
    131048: { title: 'Spam rate limit', reason: 'Volume was flagged as spammy by quality signals.', action: 'Pause the campaign and review template quality.', category: 'rate_limit', retriable: false },
    131056: { title: 'Pair rate limit', reason: 'Too many messages sent to the same recipient too quickly.', action: 'Hold sends to that contact for ~30 minutes.', category: 'rate_limit', retriable: true },
    133016: { title: 'Registration limit', reason: 'Too many register/deregister attempts in 72 hours.', action: 'Wait out the 72-hour window.', category: 'rate_limit', retriable: false },

    // ── Integrity / account ──
    368: { title: 'Temporarily blocked', reason: 'A policy violation triggered a temporary block on the WABA.', action: 'Resolve the flagged item in WhatsApp Manager.', category: 'integrity', retriable: false },
    130497: { title: 'Country restriction', reason: 'Messaging to the destination country is restricted for your business.', action: 'Use a different channel for that country.', category: 'integrity', retriable: false },
    131031: { title: 'Account locked', reason: 'The account was disabled for repeated policy violations.', action: 'Submit an appeal to restore the account.', category: 'integrity', retriable: false },

    // ── Template ──
    100: { title: 'Invalid parameter', reason: 'Variables do not match the template format, or a required variable / flow button component was omitted.', action: 'Match the template parameters exactly and include all variables.', category: 'template', retriable: false },
    132000: { title: 'Parameter count mismatch', reason: 'Number of variables sent does not match the template definition.', action: 'Match {{1}}, {{2}}… exactly to the approved template.', category: 'template', retriable: false },
    132001: { title: 'Template does not exist', reason: 'Wrong template name/language, or the template is not approved.', action: 'Confirm name + language match an approved template.', category: 'template', retriable: false },
    132005: { title: 'Translation too long', reason: 'A localized version exceeds the character cap.', action: 'Shorten the body/header for that locale.', category: 'template', retriable: false },
    132007: { title: 'Format policy violation', reason: 'Disallowed formatting or content in the template.', action: 'Edit the template and resubmit for approval.', category: 'template', retriable: false },
    132012: { title: 'Parameter format mismatch', reason: 'A variable type does not match its component (e.g. text in a URL slot).', action: 'Send the correct value type for each component.', category: 'template', retriable: false },
    132015: { title: 'Template paused', reason: 'Quality rating dropped to low, so sending is paused.', action: 'Improve the template content and resubmit.', category: 'template', retriable: false },
    132016: { title: 'Template disabled', reason: 'The template was paused too many times and is disabled.', action: 'Create a new template with improved copy.', category: 'template', retriable: false },
    132068: { title: 'Flow blocked', reason: 'The attached Flow violates policy.', action: 'Review, fix and republish the Flow.', category: 'flow', retriable: false },
    132069: { title: 'Flow throttled', reason: 'Too many flow messages sent within an hour.', action: 'Pace flow sends.', category: 'flow', retriable: true },

    // ── Delivery ──
    131026: { title: 'Message undeliverable', reason: 'Recipient may not have WhatsApp, has not accepted terms, or is on an old client.', action: 'Fall back to SMS/email for this contact.', category: 'delivery', retriable: false },
    131047: { title: 'Re-engagement required', reason: 'More than 24h since the user last messaged — no open session.', action: 'Send an approved template instead of a free-form message.', category: 'delivery', retriable: false },
    131049: { title: 'Per-user marketing limit', reason: 'Meta throttled a marketing message to protect the recipient.', action: 'Reduce marketing frequency; utility/transactional templates are unaffected.', category: 'delivery', retriable: false },
    131051: { title: 'Unsupported message type', reason: 'The message type is not supported for this recipient/device.', action: 'Use a supported message type.', category: 'delivery', retriable: false },
    131060: { title: 'Message no longer available', reason: 'The sender deleted or expired the message before WhatsApp could hand it over.', action: 'Ask the sender to resend it; nothing can be recovered from this webhook.', category: 'delivery', retriable: false },

    // ── Media ──
    131052: { title: 'Media download error', reason: 'The media the user sent could not be fetched.', action: 'Ask the user to resend the file.', category: 'media', retriable: true },
    131053: { title: 'Media upload error', reason: 'Outbound media is the wrong format, too large, or corrupted.', action: 'Check the file against WhatsApp media specs.', category: 'media', retriable: false },

    // ── Flows ──
    139000: { title: 'Flow blocked by integrity', reason: 'The WABA cannot publish flows right now.', action: 'Resolve account integrity issues first.', category: 'flow', retriable: false },
    139001: { title: 'Cannot update published flow', reason: 'Published flows are immutable.', action: 'Clone, edit and publish a new version.', category: 'flow', retriable: false },

    // ── Miscellaneous ──
    131000: { title: 'Unknown error', reason: 'An unidentified upstream failure occurred.', action: 'Retry once; if it persists, contact support.', category: 'other', retriable: true },
    131005: { title: 'Access denied', reason: 'Permission was revoked between messages.', action: 'Reconnect the sender.', category: 'auth', retriable: false },
    131008: { title: 'Missing required parameter', reason: 'A required field is missing from the request.', action: 'Check the API reference for that message type.', category: 'template', retriable: false },
    131009: { title: 'Invalid parameter value', reason: 'A value is outside the supported set (e.g. a flow-button or header component is malformed).', action: 'Validate the request payload before sending.', category: 'template', retriable: false },
    131016: { title: 'Service unavailable', reason: 'Temporary upstream outage at Meta.', action: 'Retry with backoff.', category: 'other', retriable: true },
    131021: { title: 'Sender = recipient', reason: 'The sender number matches the recipient number.', action: 'You cannot message your own number.', category: 'other', retriable: false },
    131037: { title: 'Missing display name', reason: 'The sender has no approved display name.', action: 'Set and approve a display name for the number.', category: 'auth', retriable: false },
    131042: { title: 'Payment issue', reason: 'A billing problem is blocking the WABA.', action: 'Update payment details for the account.', category: 'integrity', retriable: false },
    131045: { title: 'Incorrect certificate', reason: 'The phone number registration is in a bad state.', action: 'Reconnect/re-register the number.', category: 'auth', retriable: false },
    131057: { title: 'Account in maintenance', reason: 'Temporary platform-side maintenance.', action: 'Wait and retry — this clears on its own.', category: 'other', retriable: true },
};

/**
 * Build a readable description for a Meta error code. Falls back to any provided
 * raw message when the code is unknown.
 */
export function describeWaError ( code?: number | string | null, rawMessage?: string | null ): WaErrorInfo | null {
    const n = typeof code === 'string' ? parseInt( code, 10 ) : code;
    if ( n && WA_ERROR_CODES[ n ] ) return WA_ERROR_CODES[ n ];
    if ( rawMessage )
    {
        return { title: 'Send failed', reason: rawMessage, action: 'Check the message and try again.', category: 'other', retriable: false };
    }
    if ( n )
    {
        return { title: `Error ${n}`, reason: 'Unrecognised WhatsApp error code.', action: 'See Meta error code reference.', category: 'other', retriable: false };
    }
    return null;
}

/** One-line tooltip text: "131047 · Re-engagement required — <reason> Fix: <action>" */
export function waErrorTooltip ( code?: number | string | null, rawMessage?: string | null ): string | null {
    const info = describeWaError( code, rawMessage );
    if ( !info ) return null;
    const prefix = code ? `${code} · ${info.title}` : info.title;
    return `${prefix} — ${info.reason} Fix: ${info.action}`;
}
