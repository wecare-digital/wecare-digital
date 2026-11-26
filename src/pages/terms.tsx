import React from 'react';
import PageMeta from '../components/PageMeta';
import Breadcrumbs from '../components/Breadcrumbs';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';
import LegalDocument from '../components/LegalDocument';
import { TERMS_SECTIONS, TERMS_INTRO } from '../content/legal/terms';
const CYCLE_WORDS: CycleWord[] = [
  { word: 'service', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'payment', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'refunds', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'delivery', tint: '#ede9fe', dot: '#9849e8' },
];

const TermsPage: React.FC = () => (
  <>
    <PageMeta
      title="Terms of Service"
      description="The agreement between you and WECARE.DIGITAL when you use our services: orders, payments, refunds, delivery, professional services and dispute resolution."
      path="/terms/"
    />
    <RotatingHero
      ariaLabel="Terms of service"
      badgeLabel="Terms of Service — WECARE.DIGITAL"
      frame="Terms of"
      words={ CYCLE_WORDS }
      sub="The agreement between you and WECARE.DIGITAL when you use our services."
      mobileFoundation
    >
      
      <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Terms' } ] } />
      <LegalDocument
        sections={ TERMS_SECTIONS }
        intro={ TERMS_INTRO }
        notice={ <>
          These Terms do not constitute legal advice for your individual circumstances.
          For questions about your transaction or these Terms, contact{ ' ' }
          <a href="mailto:one@wecare.digital">one@wecare.digital</a>.
        </> }
      />
    </RotatingHero>
  </>
);

export default TermsPage;
