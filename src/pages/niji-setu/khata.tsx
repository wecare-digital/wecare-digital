import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/niji-setu/khata/' );

const KhataPage: React.FC = () => (
  <ProductPage
    mobileFoundation
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( '/niji-setu/khata' ) }
  />
);

export default KhataPage;
