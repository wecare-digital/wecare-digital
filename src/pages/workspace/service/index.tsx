/**
 * /workspace/service — sends the operator to the Service Ops hub.
 *
 * It was a 57-line grid of six cards with zero network calls: a second front door to
 * destinations the Service Ops hub already owns. Four of its six cards
 * (submit-request, track-request, amend-request and the Customer Service Hub) are
 * nav children of /workspace/engage/service-ops, so the page's only function was to
 * ask which door you wanted before letting you through one.
 *
 * WHY A REDIRECT AND NOT A DELETION. Nothing in navigationConfig or settingsConfig
 * points here, so by the usual rule this would just be unlinked. But it is a real,
 * short, guessable URL that somebody may have bookmarked, and deleting the page file
 * turns that bookmark into a 404 rather than into the page they wanted. A redirect
 * costs one file and keeps the URL honest.
 *
 * Nothing becomes unreachable. The two cards that were NOT Service Ops destinations
 * — /workspace/engage/whatsapp/flow-responses ('Flow Responses') and
 * /workspace/engage/whatsapp/flow-hub ('Flow Hub') — are both already listed in the
 * gear's WhatsApp group, so they stay findable by name in the command palette.
 *
 * The three siblings (service/submit-request, track-request, amend-request) are
 * untouched: each is a Service Ops nav child AND a declared inner page of the
 * service-operations module home, which tests/test_module_homes.py asserts exists.
 *
 * Follows the two precedents in the tree, src/pages/workspace/admin/index.tsx and
 * src/pages/workspace/forms/index.tsx.
 */

import { useEffect } from 'react';
import { useRouter } from 'next/router';

const ServiceIndex = () => {
  const router = useRouter();

  useEffect( () => {
    // replace, not push: this is a signpost, and leaving it in history means Back
    // lands here and bounces forward again.
    router.replace( '/workspace/engage/service-ops' );
  }, [ router ] );

  return null;
};

export default ServiceIndex;
