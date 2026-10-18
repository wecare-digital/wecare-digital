/**
 * [retired public path] — sends the operator to the Responses queue.
 *
 * It used to redirect to [retired public path]/create, which was a `ComingSoon` stub advertising six
 * features (drag & drop builder, custom fields, validation rules, conditional logic,
 * file uploads, submission tracking) with no backend behind any of them. So the whole
 * [retired public path] landing experience was: redirect, then a list of promises. The stub was deleted
 * on 2026-09-25 and this now points at [retired public path]/responses.
 *
 * [retired public path]/responses is the right destination for the same reason navigation.ts lists it
 * first: a submitted request nobody actioned is a customer who paid and heard nothing,
 * so the queue matters more than the builder would have.
 */

import { useEffect } from 'react';
import { useRouter } from 'next/router';

const FormsIndex = () => {
  const router = useRouter();

  useEffect( () => {
    // replace, not push: [retired public path] is a signpost, and leaving it in history means Back
    // lands here and bounces forward again. FEAT-005: Form responses is a tab on the Service hub
    // now, so the signpost forwards to that hub tab.
    router.replace( '/workspace/engage/service-ops?tab=form-responses' );
  }, [ router ] );

  return null;
};

export default FormsIndex;
