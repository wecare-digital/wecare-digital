import React from 'react';
import ProductPage from '../../components/ProductPage';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/dastavez/drafting/' );

const DraftingPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ [
      { label: 'Home', href: '/' },
      { label: 'Shop', href: '/shop/' },
      { label: 'Dastavez', href: '/dastavez/' },
      { label: 'Drafting' },
    ] }
  />
);

export default DraftingPage;
