/**
 * Compatibility redirect for the retired standalone Links workspace.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const LegacyLinks = () => {
  const router = useRouter();

  useEffect( () => {
    void router.replace( { pathname: '/workspace/communications', query: { view: 'manage', section: 'links' } } );
  }, [ router ] );

  return null;
};

export default LegacyLinks;
