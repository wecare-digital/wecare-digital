/**
 * Compatibility redirect for the retired Engage Service Ops hub.
 *
 * Service now lives at /workspace/service. Old tab links keep their operational intent so
 * bookmarks and historical task links do not collapse to a generic landing page.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const LEGACY: Record<string, string> = {
  responses: '/workspace/service?view=requests',
  'form-responses': '/workspace/service?view=requests',
  selfservice: '/workspace/service?view=requests',
  orders: '/workspace/commerce',
  submit: '/workspace/service?view=requests&action=submit',
  track: '/workspace/service?view=requests&action=track',
  amend: '/workspace/service?view=requests&action=amend',
  appointments: '/workspace/service?view=appointments',
  'sehat-appointments': '/workspace/service?view=appointments&action=sehat-appointments',
  documents: '/workspace/service?view=documents',
  'secure-files': '/workspace/service?view=documents&action=secure-files',
  enterprise: '/workspace/service?view=requests&action=enterprise',
  reviews: '/workspace/service?view=requests&action=reviews',
  faq: '/workspace/service?view=requests&action=faq',
};

const LegacyServiceOps = () => {
  const router = useRouter();

  useEffect( () => {
    const tab = Array.isArray( router.query.tab ) ? router.query.tab[ 0 ] : router.query.tab;
    if ( !tab ) {
      void router.replace( '/workspace/service' );
      return;
    }
    void router.replace( LEGACY[ tab ] || '/workspace/service' );
  }, [ router ] );

  return null;
};

export default LegacyServiceOps;
