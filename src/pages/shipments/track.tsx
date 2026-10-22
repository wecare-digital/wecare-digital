import React from 'react';
import ProductBuyBox from '../../components/ProductBuyBox';
import ProductPage from '../../components/ProductPage';
import { breadcrumbTrail } from '../../content/breadcrumbTrails';
import { SHIPMENT_TRACK } from '../../content/shipments';

const ShipmentTrackPage: React.FC = () => (
  <ProductPage
      mobileFoundation
    product={ SHIPMENT_TRACK }
    canonicalPath="/shipments/track/"
    belowCta={ <ProductBuyBox slug="shipments-track" /> }
    crumbs={ breadcrumbTrail( '/shipments/track' ) }
  />
);

export default ShipmentTrackPage;
