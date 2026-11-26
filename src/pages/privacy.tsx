import React from 'react';
import PageMeta from '../components/PageMeta';
import Breadcrumbs from '../components/Breadcrumbs';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';
import LegalDocument from '../components/LegalDocument';
import { PRIVACY_SECTIONS, PRIVACY_INTRO } from '../content/legal/privacy';
const CYCLE_WORDS: CycleWord[] = [
  { word: 'choice', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'control', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'consent', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'rights', tint: '#ede9fe', dot: '#9849e8' },
];

const PrivacyPage: React.FC = () => (
  <>
    <PageMeta
      title="Privacy Policy"
      description="How WECARE.DIGITAL collects, uses, stores, shares and protects personal data — what we collect, why, who it is shared with, how long we keep it, and your rights."
      path="/privacy/"
    />
    <RotatingHero
      ariaLabel="Privacy policy"
      badgeLabel="Privacy Policy — WECARE.DIGITAL"
      frame="Your data, your"
      words={ CYCLE_WORDS }
      sub="What we collect, why we collect it, and how to ask us to change or delete it."
      mobileFoundation
    >
      
      <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Privacy' } ] } />
      <LegalDocument
        sections={ PRIVACY_SECTIONS }
        intro={ PRIVACY_INTRO }
        notice={ <>
          For access, correction or erasure of your personal data, withdrawal of consent
          or a privacy grievance, contact{ ' ' }
          <a href="mailto:one@wecare.digital">one@wecare.digital</a>.
          We may verify your identity or authority before acting on a request.
        </> }
      />
    </RotatingHero>
  </>
);

export default PrivacyPage;
