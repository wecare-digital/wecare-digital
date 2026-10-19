/**
 * Compatibility redirect for the retired Contacts workspace name.
 *
 * Customer identity, address, consent and activity now live at /workspace/customers.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const ContactsCompatibilityRedirect = () => {
  const router = useRouter();

  useEffect( () => {
    const query = { ...router.query };
    void router.replace( { pathname: '/workspace/customers', query } );
  }, [ router ] );

  return null;
};

export default ContactsCompatibilityRedirect;
