import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/dastavez/drafting/' );

const DraftingPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( '/dastavez/drafting' ) }
  />
);

export default DraftingPage;
