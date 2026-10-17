import React from 'react';
import ProductBuyBox from '../../components/ProductBuyBox';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/hunar/kaushal/' );

const KaushalPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    belowCta={ <ProductBuyBox slug="hunar-kaushal" /> }
    crumbs={ breadcrumbTrail( '/hunar/kaushal' ) }
  />
);

export default KaushalPage;
