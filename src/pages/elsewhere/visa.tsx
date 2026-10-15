import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/visa/' );

const VisaPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( '/elsewhere/visa' ) }
  />
);

export default VisaPage;
