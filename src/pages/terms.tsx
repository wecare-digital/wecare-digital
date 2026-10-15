import React from 'react';
import PageMeta from '../components/PageMeta';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';
import LegalDocument from '../components/LegalDocument';
import { TERMS_SECTIONS, TERMS_INTRO } from '../content/legal/terms';

/**
 * /terms — Terms of Service.
 *
 * ROUTING: '/terms' must be in the EXACT-MATCH allowlist in _app.tsx or this renders an
 * empty body with HTTP 200. trailingSlash means the URL is /terms/.
 *
 * THE REAL DOCUMENT, all 45 sections plus the 12 sub-clauses of section 14, rewritten into
 * plain English on the owner's instruction. THIS REPO IS THE SOURCE OF TRUTH - there is no
 * upstream page to sync with. src/content/legal/terms.ts records exactly what the
 * rewrite changed and, more importantly, what it did not.
 *
 * noindex was removed with the placeholder. It existed because an indexed empty legal
 * page is the document a regulator or a payment provider gets pointed at; that reasoning
 * does not apply to a complete one, and terms of service should be findable.
 *
 * THE NOTICE SAYS THIS IS THE AGREEMENT, deliberately. It previously read "these Terms
 * are a summary of the agreement in force and are provided for information", which is
 * exactly backwards - it described the operative contract as a non-binding summary of
 * some other document that does not exist. Telling readers that the terms they are
 * agreeing to are merely informational is not a cautious disclaimer, it is an argument
 * against your own enforceability. The genuinely useful caveat, that this is not legal
 * advice about their particular situation, is kept.
 */

// "Terms of service / payment / refunds / delivery" - all four complete the frame, and
// all are 7 or 8 characters so the pill barely moves. Tints reused verbatim.
const CYCLE_WORDS: CycleWord[] = [
  { word: 'service', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'payment', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'refunds', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'delivery', tint: '#ede9fe', dot: '#9849e8' },
];

const TermsPage: React.FC = () => (
  <>
    <PageMeta
      title="Terms of Service — WECARE.DIGITAL"
      description="The agreement between you and WECARE.DIGITAL when you use our services: orders, payments, refunds, delivery, professional services and dispute resolution."
      path="/terms/"
    />
    <RotatingHero
      ariaLabel="Terms of service"
      badgeLabel="Legal Stuff — WECARE.DIGITAL"
      frame="Terms of"
      words={ CYCLE_WORDS }
      sub="The agreement between you and WECARE.DIGITAL when you use our services."
    >
      <LegalDocument
        sections={ TERMS_SECTIONS }
        intro={ TERMS_INTRO }
        notice={ <>
          These Terms are the agreement between you and WECARE.DIGITAL, and they apply
          when you use our services. They are not legal advice about your particular
          situation. If you want to know how a clause applies to you, ask us at{ ' ' }
          <a href="mailto:one@wecare.digital">one@wecare.digital</a>.
        </> }
      />
    </RotatingHero>
  </>
);

export default TermsPage;
