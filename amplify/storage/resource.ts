import { defineStorage } from '@aws-amplify/backend';

/**
 * Storage Configuration
 *
 * Single bucket: `wecare-digital-get`. It was named `wecare-digital-get` until
 * 2026-09-28, when that bucket was deleted; the name is not a hostname any more, so
 * never interpolate it into a URL. Browser-facing URLs are `wecare.digital/get/<key>`.
 *
 * TWO ROOTS, and every prefix below is rooted. These rules previously read `stack/*`,
 * `public/*` and `stream/*` — one level ABOVE where the data actually lives, the same
 * off-by-one-prefix defect that the media-prefix verification script exists to catch.
 *
 * - o/                   : public root. `o/` is a LOCATION, not a permission —
 *                          everything outside `secure/` is public.
 *   - o/stack/           : user/transactional data (factory reset = wipe o/stack/ only)
 *     - whatsapp-media/  : incoming/, outgoing/, voice/, calling-ai/, template-headers/, downloads/
 *     - invoices/        : Invoice PNGs and PDFs
 *     - voice/           : Voice recordings
 *     - reports/         : Bulk job reports and exports
 *     - store/products/  : Product images
 *   - o/public/          : media Meta fetches by URL (no auth)
 *     - wa-tpl/          : Template message media. DO NOT MOVE OR RENAME — 61 objects
 *                          here are named by Meta-APPROVED templates, Meta refetches
 *                          from the approved URL at send time, and an approved
 *                          template body cannot be edited in place.
 *       - docs/          : PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, TXT (max 100MB)
 *       - img/           : JPEG, PNG (max 5MB)
 *       - vid/           : MP4, 3GP (max 16MB)
 *       - aud/           : AAC, AMR, MP3, M4A, OGG (max 16MB)
 *       - stk/           : WebP stickers (max 500KB)
 *   - o/stream/          : Static internal assets (NEVER wiped)
 *     - media/m/         : Logos, branding images
 *     - media/fonts/     : Invoice PDF fonts
 *     - media/ivr/       : IVR audio files
 *     - docs/            : Scraped documentation (Markdown)
 * - secure/              : gated root. Denied at the edge by the
 *                          `wecare-get-miss-redirect` Lambda@Edge and reachable only
 *                          via a presigned URL, so it is DELIBERATELY absent from the
 *                          access map below. Granting it here would be a disclosure.
 *   - secure/u/          : the upload as received
 *   - secure/d/          : the deliverable rendition
 */
export const storage = defineStorage( {
  name: 'wecare-media',
  access: ( allow ) => ( {
    // User/transactional data — all under o/stack/
    'o/stack/*': [
      allow.authenticated.to( [ 'read', 'write' ] ),
    ],
    // Public media — Meta needs to fetch these via URL (no auth)
    'o/public/*': [
      allow.guest.to( [ 'read' ] ),
      allow.authenticated.to( [ 'read', 'write' ] ),
    ],
    // Static internal assets — read-only for authenticated users
    'o/stream/*': [
      allow.authenticated.to( [ 'read' ] ),
    ],
    // NOTE: no rule for `secure/*` on purpose. See the docstring above.
  } ),
} );

/**
 * SQS Queue Configuration
 *
 * 5 Queues (match deployed reality):
 * 1. inbound-dlq: Failed inbound message processing
 * 2. bulk-queue: Bulk message job processing
 * 3. bulk-dlq: Failed bulk message chunks
 * 4. outbound-dlq: Failed outbound messages
 * 5. eventbridge-dlq: Failed EventBridge -> Lambda target invocations
 *
 * Note: SQS queues are defined via CDK in backend.ts custom resources
 */
export const queueConfig = {
  inboundDlq: {
    name: 'stack-wecare-digital-inbound-dlq',
    visibilityTimeout: 300,
    messageRetentionPeriod: 604800, // 7 days
  },
  bulkQueue: {
    name: 'stack-wecare-digital-bulk-queue',
    visibilityTimeout: 300,
    messageRetentionPeriod: 86400, // 1 day
  },
  bulkDlq: {
    name: 'stack-wecare-digital-bulk-dlq',
    visibilityTimeout: 300,
    messageRetentionPeriod: 604800, // 7 days
  },
  outboundDlq: {
    name: 'stack-wecare-digital-outbound-dlq',
    visibilityTimeout: 300,
    messageRetentionPeriod: 604800, // 7 days
  },
  eventbridgeDlq: {
    name: 'wecare-eventbridge-dlq',
    visibilityTimeout: 300,
    messageRetentionPeriod: 604800, // 7 days
  },
};
