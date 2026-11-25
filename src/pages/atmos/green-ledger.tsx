import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/atmos/green-ledger/' );

const Page: React.FC = () => (
  <ProductPage
    mobileFoundation
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( child.path ) }
  />
);

export default Page;
