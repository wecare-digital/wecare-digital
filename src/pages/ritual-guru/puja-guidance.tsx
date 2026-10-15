import React from 'react';
import ProductPage from '../../components/ProductPage';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/ritual-guru/puja-guidance/' );

const PujaGuidancePage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ [
      { label: 'Home', href: '/' },
      { label: 'Shop', href: '/shop/' },
      { label: 'Ritual Guru', href: '/ritual-guru/' },
      { label: 'Puja Guidance' },
    ] }
  />
);

export default PujaGuidancePage;
