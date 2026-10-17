import React from 'react';
import ProductBuyBox from '../../components/ProductBuyBox';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/ritual-guru/diy-puja-kit/' );

const DIYPujaKitPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    belowCta={ <ProductBuyBox slug={ child.product.slug } /> }
    crumbs={ breadcrumbTrail( '/ritual-guru/diy-puja-kit' ) }
  />
);

export default DIYPujaKitPage;
