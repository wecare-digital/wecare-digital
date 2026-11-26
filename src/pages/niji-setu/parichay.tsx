import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/niji-setu/parichay/' );

const ParichayPage: React.FC = () => (
  <ProductPage
    mobileFoundation
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( '/niji-setu/parichay' ) }
  />
);

export default ParichayPage;
