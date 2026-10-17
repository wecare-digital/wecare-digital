import React from 'react';
import ProductBuyBox from '../../components/ProductBuyBox';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/hunar/prastuti/' );

const PrastutiPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    belowCta={ <ProductBuyBox slug="hunar-prastuti" /> }
    crumbs={ breadcrumbTrail( '/hunar/prastuti' ) }
  />
);

export default PrastutiPage;
