import React from 'react';
import PageMeta from '../../components/PageMeta';
import Breadcrumbs from '../../components/Breadcrumbs';
import RotatingHero, { type CycleWord } from '../../components/RotatingHero';
import PolicyDetails from '../../components/public/PolicyDetails';
import AppointmentAccess from '../../components/public/AppointmentAccess';
import HospitalAssistanceKnowledge from '../../components/public/HospitalAssistanceKnowledge';
import { productPolicyCopy } from '../../content/productCommerce';

const CYCLE_WORDS: CycleWord[] = [
  { word: 'appointments', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'coordination', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'journeys', tint: '#fef3c7', dot: '#f0a818' },
];
const SEHAT_POLICY = productPolicyCopy( 'sehat', 'Arogya Yatra' );

/** Any-hospital assistance intake. Hospital acceptance follows team review. */
export default function SehatPage (): React.ReactElement {
  return <>
    <PageMeta title="Arogya Yatra — hospital requests and medical travel"
      description="Request hospital appointment assistance with Arogya Yatra by WECARE.DIGITAL. Choose Apollo, another hospital or help choosing, with medical travel coordination subject to confirmation."
      path="/elsewhere/arogya-yatra/" />
    <RotatingHero mobileFoundation ariaLabel="Arogya Yatra" badgeLabel="Arogya Yatra by WECARE.DIGITAL"
      frame="Arogya Yatra" words={ CYCLE_WORDS }
      sub="Hospital appointment assistance and related medical travel, wherever you need care">
      <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Arogya Yatra' } ] } />
      <section className="ay-layout" aria-label="Hospital assistance request and service information">
        <div className="ay-form"><AppointmentAccess /></div>
        <HospitalAssistanceKnowledge />
      </section>
      <div className="ay-policies"><PolicyDetails shipping={ SEHAT_POLICY.shipping } returns={ SEHAT_POLICY.returns }
        refunds={ SEHAT_POLICY.refunds } disclaimer={ SEHAT_POLICY.disclaimer } /></div>
      <style jsx>{`
        .ay-layout{display:grid;grid-template-columns:minmax(0,560px) minmax(0,340px);gap:48px;align-items:start;max-width:100%;min-width:0}
        .ay-form{min-width:0}
        .ay-policies{max-width:560px;min-width:0;margin-top:28px}
        @media(max-width:899px){.ay-layout{grid-template-columns:minmax(0,1fr);gap:12px}}
      `}</style>
    </RotatingHero>
  </>;
}
