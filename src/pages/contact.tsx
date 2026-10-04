import React from 'react';
import PageMeta from '../components/PageMeta';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';
import ContactLocation from '../components/ContactLocation';

/**
 * /contact — the request entry point.
 *
 * "CUSTOMERSERVICE" NAMING REMOVED 2026-09-27 (owner instruction). The word named a portal
 * with no page at any address: the in-repo [retired public path] route went in PR #47 on
 * 2026-09-24 and nothing replaced it. The only [retired public path] route left in the codebase
 * is the ADMIN flow dashboard under /workspace/forms/, which is not a customer
 * destination. This page is where a customer actually starts a request.
 *
 * ROUTING: _app.tsx keeps an EXACT-MATCH public route allowlist. '/contact' must be
 * registered there or this page renders an empty body with HTTP 200 - a 404 that does
 * not look like one. next.config.js also sets trailingSlash, so the URL is /contact/.
 *
 * Note the neighbouring routes this is NOT: [retired public path] is the authenticated CRM
 * contact list and /contact-test is an older public test page. Three similar names,
 * three different things - do not consolidate them without checking the allowlist and
 * the dashboard nav.
 *
 * The rotation carries the five request actions, which is the owner's request and
 * also does useful work: it tells a visitor what this page is for before they read a
 * word of body copy.
 */

// Phrased as verbs so every variant completes the frame as a sentence, and kept within
// two characters of each other - 14 to 16 - because the pill animates to each word's
// MEASURED width and a short outlier makes it lurch. "Drop Docs" became "drop
// documents" for exactly that reason: at 9 characters it was a 7-character outlier
// against "submit a request".
//
// Tints and dots are reused verbatim from the Grahak OS hero and the VayuLok
// rotation. No new colours. Order alternates cool and warm so the change always
// registers.
const CYCLE_WORDS: CycleWord[] = [
  { word: 'submit a request', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'amend a request', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'track a request', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'drop documents', tint: '#ede9fe', dot: '#9849e8' },
  { word: 'leave a review', tint: '#fee2e2', dot: '#dc2626' },
];

const ContactPage: React.FC = () => (
  <>
    <PageMeta
      title="Contact — WECARE.DIGITAL"
      description="Submit a request, amend or track an existing one, drop documents, or leave a review."
      path="/contact/"
    />
    <RotatingHero
      ariaLabel="Contact WECARE.DIGITAL"
      badgeLabel="Requests by WECARE.DIGITAL"
      frame="You can"
      words={ CYCLE_WORDS }
      sub="Every request is tracked end to end, with transparent pricing and one place to check where things stand."
    >
      {/* The map and the postal address. ContactLocation styles itself; styled-jsx
          cannot reach into it from here, which is why it takes no className. The map is
          keyless - it needs no Google credential at all, so nothing has to be restricted,
          rotated or kept out of the built page. See that file's header for the measured
          reason the query is plain text rather than a place_id. */}
      <ContactLocation />

      {/* THE CAPABILITY STRIP HAS MOVED TO THE HOME PAGE, at the owner's request. It used
          to sit here as <ContactCapabilities /> - the seven things the arrival map can do.
          It is now src/components/PlatformCapabilities.tsx and renders on '/'.
          This page is better for it: /contact/ is where someone goes to reach us, and a
          seven-item platform showcase underneath the address competed with that job. */}
    </RotatingHero>
  </>
);

export default ContactPage;
