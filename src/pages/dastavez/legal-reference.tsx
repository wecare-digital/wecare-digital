import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/dastavez/legal-reference/' );

const LegalReferencePage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( '/dastavez/legal-reference' ) }
  />
);

export default LegalReferencePage;
