import React from 'react';
import ProductPage from '../../components/ProductPage';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/trip/' );

const TripPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ [
      { label: 'Home', href: '/' },
      { label: 'Shop', href: '/shop/' },
      { label: 'Trip' },
    ] }
  />
);

export default TripPage;
