import React from 'react';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/elsewhere/trip/' );

const TripPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ breadcrumbTrail( '/elsewhere/trip' ) }
  />
);

export default TripPage;
