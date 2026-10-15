import React from 'react';
import ProductPage from '../../components/ProductPage';
import { productChildByPath } from '../../content/productChildren';

const child = productChildByPath( '/dastavez/registration/' );

const RegistrationPage: React.FC = () => (
  <ProductPage
    product={ child.product }
    canonicalPath={ child.path }
    crumbs={ [
      { label: 'Home', href: '/' },
      { label: 'Shop', href: '/shop/' },
      { label: 'Dastavez', href: '/dastavez/' },
      { label: 'Registration' },
    ] }
  />
);

export default RegistrationPage;
