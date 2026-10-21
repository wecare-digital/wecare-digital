import React from 'react';
import ProductPage from '../../components/ProductPage';
import ElsewhereTravelAssistant from '../../components/ElsewhereTravelAssistant';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/activities/' );

const ActivitiesPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( '/elsewhere/activities' ) }
    afterHero={ <ElsewhereTravelAssistant /> }
    suppressProductDetails
  />
);

export default ActivitiesPage;
