import React from 'react';
import ProductPage from '../../components/ProductPage';
import ElsewhereTravelAssistant from '../../components/ElsewhereTravelAssistant';
import { productChildByPath } from '../../content/productChildren';
import MetaCatalogView from '../../components/MetaCatalogView';

const child = productChildByPath( '/elsewhere/activities/' );

const ActivitiesPage: React.FC = () => (
  <>
    <MetaCatalogView
      productId="native:elsewhere-activities"
      variantId="467728ca-5e3e-47c2-b6ba-14e76f9b4cd6"
      name="Activities"
      value={ 99 }
    />
    <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    afterHero={ <ElsewhereTravelAssistant /> }
    suppressProductDetails
    mobileFoundation
    />
  </>
);

export default ActivitiesPage;
