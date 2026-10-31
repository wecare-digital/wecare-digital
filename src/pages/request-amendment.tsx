import React from 'react';
import ProductPage from '../components/ProductPage';
import { customerserviceBySlug } from '../content/customerservice';

/** Standalone public service entry. Paid/private work remains owner-verified in WhatsApp. */
const Page: React.FC = () => (
  <ProductPage product={ customerserviceBySlug( 'request-amendment' ) }
    canonicalPath="/request-amendment/" mobileFoundation />
);

export default Page;
