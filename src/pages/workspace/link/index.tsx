/**
 * Compatibility redirect for the retired top-level Links workspace.
 *
 * Short links, click analytics and lifecycle controls now live under
 * Communications → Manage → Links. The public /r/{code} redirect surface is unchanged.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const LinksCompatibilityRedirect = () => {
  const router = useRouter();

  useEffect( () => {
    void router.replace( {
      pathname: '/workspace/communications',
      query: { view: 'manage', section: 'links' },
    } );
  }, [ router ] );

  return null;
};

export default LinksCompatibilityRedirect;
