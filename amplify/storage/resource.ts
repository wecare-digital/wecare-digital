import { defineStorage } from '@aws-amplify/backend';

/**
 * Storage Configuration
 *
 * Single bucket: `wecare-digital-get`. It was named `wecare-digital-get` until
 * 2026-09-28, when that bucket was deleted; the name is not a hostname any more, so
 * never interpolate it into a URL. Browser-facing URLs are `wecare.digital/get/<key>`.
 *
 * TWO ROOTS. Live layout (2026-10-25); the canonical key constants are in
 * `amplify/functions/shared/lambda_utils/media_paths.py`:
 *
 * - secure/                     : edge-gated (`wecare-get-miss-redirect` Lambda@Edge),
 *                                 reachable only via a presigned URL, EXCEPT d/public/.
 *   - secure/u/                 : uploads as received — dropdocs/, service-requests/
 *   - secure/d/public/          : deliverables, served publicly with NO authentication,
 *                                 except the customer data in
 *                                 media_paths.PRIVATE_DELIVERABLE_PREFIXES (edge-gated)
 *     - Invoice/                : customer_invoice/, fonts/
 *     - receipts/
 *     - whatsapp/               : incoming/, outgoing/, voice/, transcriptions/, downloads/,
 *                                 calling-ai/, whatsapp-calling/, resumable/, template-headers/
 *       - wa-tpl/               : reusable template media — img/ docs/ vid/ aud/ stk/
 *     - blog/                   : audits/, categories/, editorial/, remediation/
 *     - catalog-deploy/         : catalog/products/, catalog-media/, catalog-relocation/,
 *                                 catalog-always-available/
 * - o/                          : static/CDN assets. `o/` is a LOCATION, not a permission.
 *   - o/stream/media/           : m/ (branding), ivr/, reports/, docs/
 *
 * NOT DEPLOYED. No Amplify storage bucket exists in the account (checked 2026-10-25), and
 * `defineStorage` would create a NEW bucket rather than govern `wecare-digital-get`, which
 * the repository forbids without explicit approval. So the access map below does not
 * control access to the media bucket at all; Lambda roles, the bucket policy and the edge
 * function do. It still names the retired `o/stack/*` and `o/public/*` trees. `secure/*`
 * stays absent from it; granting the gated root here would be a disclosure.
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
