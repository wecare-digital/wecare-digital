import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';
import MetaCatalogView from '../../components/MetaCatalogView';

const child = productChildByPath( '/ritual-guru/ritva/' );

const RitvaPage: React.FC = () => (
  <>
    <MetaCatalogView
      productId="native:ritual-guru-ritva"
      variantId="2b1655cf-198a-438d-93b6-c57612b819b6"
      name="Ritva"
      value={ 99 }
    />
    <ProductPage
      mobileFoundation
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( '/ritual-guru/ritva' ) }
    />
  </>
);

export default RitvaPage;
