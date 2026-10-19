/**
 * Compatibility redirect for the retired Settings/Platform route.
 *
 * Platform is a first-class workspace at /workspace/platform. Preserve the old ?tab= intent
 * for bookmarks and deep links while keeping Settings from becoming a product-navigation bucket.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const PlatformSettingsCompatibilityRedirect = () => {
  const router = useRouter();

  useEffect( () => {
    const tab = Array.isArray( router.query.tab ) ? router.query.tab[ 0 ] : router.query.tab;
    const view = Array.isArray( router.query.view ) ? router.query.view[ 0 ] : router.query.view;
    const selected = view || tab;

    void router.replace( {
      pathname: '/workspace/platform',
      query: selected ? { view: selected } : {},
    } );
  }, [ router ] );

  return null;
};

export default PlatformSettingsCompatibilityRedirect;
