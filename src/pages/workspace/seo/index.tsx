/**
 * Compatibility redirect for the retired standalone SEO hub.
 *
 * Supported AWS-native capabilities now live inside Content. Old blocked external SEO-client
 * routes are intentionally not revived here.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const LegacySeoHub = () => {
  const router = useRouter();

  useEffect( () => {
    const raw = Array.isArray( router.query.tab ) ? router.query.tab[ 0 ] : router.query.tab;
    if ( raw === 'blog' ) {
      void router.replace( { pathname: '/workspace/content', query: { view: 'blog' } } );
      return;
    }
    if ( raw === 'pipeline' ) {
      void router.replace( { pathname: '/workspace/content', query: { view: 'production' } } );
      return;
    }
    if ( raw === 'pages' ) {
      void router.replace( { pathname: '/workspace/content', query: { view: 'seo', area: 'pages' } } );
      return;
    }
    void router.replace( { pathname: '/workspace/content', query: { view: 'seo', area: 'tools' } } );
  }, [ router ] );

  return null;
};

export default LegacySeoHub;
