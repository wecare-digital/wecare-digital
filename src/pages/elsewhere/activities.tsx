import React from 'react';
import ProductPage from '../../components/ProductPage';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/activities/' );

const ActivitiesPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ [
      { label: 'Home', href: '/' },
      { label: 'Shop', href: '/shop/' },
      { label: 'Elsewhere' },
      { label: 'Activities' },
    ] }
  />
);

export default ActivitiesPage;
