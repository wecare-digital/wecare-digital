import React from 'react';
import ProductPage from '../../components/ProductPage';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/visa/' );

const VisaPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ [
      { label: 'Home', href: '/' },
      { label: 'Shop', href: '/shop/' },
      { label: 'Visa' },
    ] }
  />
);

export default VisaPage;
