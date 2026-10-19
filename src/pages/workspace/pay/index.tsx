/**
 * Compatibility redirect for the retired /workspace/pay route.
 *
 * Payments now lives at /workspace/payments with Collect | Ledger. Preserve old query links so
 * bookmarks and documentation do not break while the migration is staged.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const PayCompatibilityRedirect = () => {
  const router = useRouter();

  useEffect( () => {
    const tab = Array.isArray( router.query.tab ) ? router.query.tab[ 0 ] : router.query.tab;
    const view = tab === 'records' ? 'ledger' : 'collect';
    void router.replace( { pathname: '/workspace/payments', query: { view } } );
  }, [ router ] );

  return null;
};

export default PayCompatibilityRedirect;
