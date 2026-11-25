import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/rail/' );

const Page: React.FC = () => (
  <ProductPage
    mobileFoundation
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( child.path ) }
  />
);

export default Page;
