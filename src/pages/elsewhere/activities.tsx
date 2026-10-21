import React from 'react';
import ProductPage from '../../components/ProductPage';
import ElsewhereTravelAssistant from '../../components/ElsewhereTravelAssistant';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/activities/' );

const ActivitiesPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    afterHero={ <ElsewhereTravelAssistant /> }
    suppressProductDetails
    mobileFoundation
  />
);

export default ActivitiesPage;
