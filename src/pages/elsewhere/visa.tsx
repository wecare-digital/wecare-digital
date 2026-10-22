import React from 'react';
import ProductBuyBox from '../../components/ProductBuyBox';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/visa/' );

const VisaPage: React.FC = () => (
  <ProductPage
      mobileFoundation
    product={ child.product }
    canonicalPath={ child.path }
    belowCta={ <ProductBuyBox slug={ child.product.slug } /> }
    crumbs={ breadcrumbTrail( '/elsewhere/visa' ) }
  />
);

export default VisaPage;
