/**
 * Compatibility redirect for the retired Engage workspace name.
 *
 * Real communication work now lives at /workspace/communications. Nested Engage routes remain
 * temporarily during the staged migration so existing imports, bookmarks and tests keep working
 * until each capability has a canonical replacement.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const EngageCompatibilityRedirect = () => {
  const router = useRouter();

  useEffect( () => {
    const tab = Array.isArray( router.query.tab ) ? router.query.tab[ 0 ] : router.query.tab;
    const legacyToManage: Record<string, string> = {
      scheduled: 'scheduled',
      automation: 'automation',
      content: 'templates',
      analytics: 'analytics',
      logs: 'delivery',
      cost: 'usage',
      search: 'search',
      'meta-agent': 'ai',
      docs: 'docs',
    };

    if ( tab && legacyToManage[ tab ] ) {
      void router.replace( {
        pathname: '/workspace/communications',
        query: { view: 'manage', section: legacyToManage[ tab ] },
      } );
      return;
    }

    void router.replace( '/workspace/communications' );
  }, [ router ] );

  return null;
};

export default EngageCompatibilityRedirect;
