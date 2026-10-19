/**
 * Compatibility redirect for the retired standalone Links workspace.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const LegacyLinks = () => {
  const router = useRouter();

  useEffect( () => {
    void router.replace( { pathname: '/workspace/content', query: { view: 'links' } } );
  }, [ router ] );

  return null;
};

export default LegacyLinks;
