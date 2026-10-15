import React from 'react';
import ProductPage from '../../components/ProductPage';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/dastavez/legal-reference/' );

const LegalReferencePage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ [
      { label: 'Home', href: '/' },
      { label: 'Shop', href: '/shop/' },
      { label: 'Dastavez', href: '/dastavez/' },
      { label: 'Legal Reference' },
    ] }
  />
);

export default LegalReferencePage;
