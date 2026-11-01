import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import BrandLockup from './BrandLockup';
import HeaderCart from './HeaderCart';
import VoiceSearchMic from './VoiceSearchMic';
import { CUSTOMER_MENU_HREFS, isPrimaryMenuActivation, menuActionForLabel, stashCustomerMenuAction } from '../lib/customerMenuActions';
import { PLAY_STORE } from '../config/analytics';
import type { MaterialSymbol } from '../config/materialSymbols';

/**
 * No props.
 *
 * There was one - `homeBrand?: boolean` - passed from _app.tsx as
 * `homeBrand={ router.pathname === '/' }` and used to add an `hdr-home` class to the
 * <header>. NO CSS RULE ANYWHERE KEYED OFF THAT CLASS. Four references across two files
 * threading a boolean down to set a class name nothing read, so the home page and every
 * other public page rendered an identical header either way.
 *
 * Removed rather than given a rule, because there is no brief for what a home-specific
 * header should look like, and an unused hook that looks load-bearing is worse than no
 * hook: the next person to touch _app.tsx has to prove it does nothing before they can
 * safely ignore it. If the home header should differ later, the prop is two lines.
 */
interface NavLink {
  label: string;
  /** Omitted only for a visible grouping label such as Elsewhere. */
  href?: string;
  /** router.pathname value that marks this link as the one current page. */
  match?: string;
  /** Extra menu words that should find this destination in navigation search. */
  searchTerms?: string[];
  /** Child destinations shown directly beneath this family item. */
  children?: NavLink[];
  /** True for absolute URLs off this app. Same tab either way. */
  external?: boolean;
}

interface NavSection {
  /** '' renders the links with no structural heading above them. */
  heading: string;
  /** Some structural headings are also real destinations. */
  headingHref?: string;
  headingMatch?: string;
  /** Render this section's destinations with the standard nested-row treatment. */
  nestedLinks?: boolean;
  links: NavLink[];
}

/** One column of the mega menu. Columns may hold more than one section. */
interface NavColumn {
  sections: NavSection[];
}

interface SearchableNavLink extends NavLink {
  href: string;
  searchText: string;
}

/**
 * PUBLIC MENU SOURCE OF TRUTH.
 *
 * Structural headings stay on the existing small uppercase rung.
 * Every family and every destination uses the same 19px/600 navigation rung.
 * Product families are non-clickable labels; only their child destinations are pages.
 * Search is derived from this same graph.
 */
const COLUMNS: NavColumn[] = [
  {
    sections: [
      {
        heading: '',
        links: [
          { label: 'Home', href: '/', match: '/' },
          { label: 'Shop', href: '/shop/', match: '/shop' },
        ],
      },
      {
        heading: 'Products',
        links: [
          { label: 'Grahak OS', href: '/grahak-os/', match: '/grahak-os' },
          { label: 'VayuLok', href: '/vayulok/', match: '/vayulok' },
          { label: 'Sehat', href: '/sehat/', match: '/sehat', searchTerms: [ 'health', 'appointment', 'booking' ] },
          {
            label: 'Elsewhere',
            searchTerms: [ 'travel' ],
            children: [
              { label: 'Visa', href: '/elsewhere/visa/', match: '/elsewhere/visa', searchTerms: [ 'elsewhere' ] },
              { label: 'Trip', href: '/elsewhere/trip/', match: '/elsewhere/trip', searchTerms: [ 'elsewhere', 'travel' ] },
              { label: 'Activities', href: '/elsewhere/activities/', match: '/elsewhere/activities', searchTerms: [ 'elsewhere' ] },
            ],
          },
          { label: 'Expo Week', href: '/expo-week/', match: '/expo-week' },
          {
            label: 'Dastavez',
            children: [
              { label: 'Drafting', href: '/dastavez/drafting/', match: '/dastavez/drafting', searchTerms: [ 'dastavez' ] },
              { label: 'Registration', href: '/dastavez/registration/', match: '/dastavez/registration', searchTerms: [ 'dastavez' ] },
              { label: 'Legal Reference', href: '/dastavez/legal-reference/', match: '/dastavez/legal-reference', searchTerms: [ 'dastavez' ] },
            ],
          },
          {
            label: 'Clear Closure',
            children: [
              { label: 'Guided Resolution', href: '/shop/guided-resolution/' },
              { label: 'Case Submission', href: '/shop/file-assist/' },
              { label: 'Paperwork', href: '/shop/paperwork/' },
            ],
          },
          {
            label: 'Ritual Guru',
            children: [
              { label: 'Puja Guidance', href: '/ritual-guru/puja-guidance/', match: '/ritual-guru/puja-guidance', searchTerms: [ 'ritual guru' ] },
              { label: 'DIY Puja Kit', href: '/ritual-guru/diy-puja-kit/', match: '/ritual-guru/diy-puja-kit', searchTerms: [ 'ritual guru' ] },
              { label: 'Ritva', href: '/ritual-guru/ritva/', match: '/ritual-guru/ritva', searchTerms: [ 'ritual guru', 'astrology', 'vastu' ] },
            ],
          },
          { label: 'Anew', href: '/anew/', match: '/anew' },
          {
            label: 'Hunar',
            searchTerms: [ 'skills', 'learning', 'cv', 'resume', 'profile', 'pitch deck' ],
            children: [
              { label: 'Kaushal', href: '/hunar/kaushal/', match: '/hunar/kaushal', searchTerms: [ 'hunar', 'skills', 'learning' ] },
              { label: 'Prastuti', href: '/hunar/prastuti/', match: '/hunar/prastuti', searchTerms: [ 'hunar', 'cv', 'resume', 'profile', 'pitch', 'deck' ] },
            ],
          },
          { label: 'Niji Setu', href: '/niji-setu/', match: '/niji-setu' },
        ],
      },
    ],
  },
  {
    sections: [
      {
        heading: 'Request',
        links: [
          // Service controls will live on the authenticated order history. Preserve
          // Old service URLs now fall through to Home. Explicit authenticated
          // menu actions still open the Orders hub; exact Vault file links stay intact.
          { label: 'Orders', href: '/orders/', match: '/orders' },
          { label: 'Submit Request', href: '/orders/', match: '/orders', searchTerms: [ 'submit request' ] },
          { label: 'Request Amendment', href: '/orders/', match: '/orders', searchTerms: [ 'amend request' ] },
          { label: 'Drop Docs', href: '/orders/', match: '/orders', searchTerms: [ 'upload documents' ] },
          { label: 'Vault', href: '/orders/', match: '/orders', searchTerms: [ 'files' ] },
          {
            label: 'Shipments',
            searchTerms: [ 'track', 'pickup' ],
            children: [
              { label: 'Track', href: '/orders/', match: '/orders', searchTerms: [ 'shipments', 'tracking' ] },
              { label: 'Pickup Request', href: '/orders/', match: '/orders', searchTerms: [ 'shipments', 'pickup' ] },
            ],
          },
          { label: 'Leave Review', href: CUSTOMER_MENU_HREFS['leave-review'], match: '/orders' },
          { label: 'Subscribe', href: CUSTOMER_MENU_HREFS.subscribe, match: '/orders' },
        ],
      },
    ],
  },
  {
    sections: [
      {
        heading: 'Refer & Earn',
        links: [
          {
            label: 'Partner',
            searchTerms: [ 'refer', 'earn' ],
            children: [
              { label: 'Referral', href: CUSTOMER_MENU_HREFS.referral, match: '/orders', searchTerms: [ 'partner', 'refer', 'earn' ] },
              { label: 'Merchandise', href: '/shop/merchandise/', searchTerms: [ 'partner', 'refer', 'earn' ] },
              { label: 'Kiosk', href: '/shop/kiosk/', searchTerms: [ 'partner', 'refer', 'earn' ] },
            ],
          },
        ],
      },
      {
        heading: 'Extras',
        links: [
          { label: 'Perks', href: 'https://wa.me/message/377GALDW4E26F1', external: true },
          { label: 'Google Play', href: PLAY_STORE.developerUrl, external: true, searchTerms: [ 'android', 'play store', 'google play store' ] },
        ],
      },
      {
        heading: 'With AI',
        links: [
          { label: 'ChatGPT', href: 'https://chatgpt.com/', external: true, searchTerms: [ 'ai', 'assistant', 'plugin', 'connect', 'openai' ] },
          { label: 'Claude', href: 'https://claude.ai/', external: true, searchTerms: [ 'ai', 'assistant', 'plugin', 'connect', 'anthropic' ] },
          { label: 'Gemini', href: 'https://gemini.google.com/', external: true, searchTerms: [ 'ai', 'assistant', 'plugin', 'connect', 'google' ] },
        ],
      },
      {
        heading: 'Contact',
        links: [
          { label: 'Contact us', href: '/contact/', match: '/contact' },
        ],
      },
      {
        heading: 'Legal Stuff',
        links: [
          { label: 'Terms', href: '/terms/', match: '/terms' },
          { label: 'Privacy', href: '/privacy/', match: '/privacy' },
        ],
      },
    ],
  },
];

const flattenMenuLinks = (): SearchableNavLink[] => {
  const result: SearchableNavLink[] = [];
  const push = ( link: NavLink, inheritedTerms: string[] ) => {
    const terms = [ ...inheritedTerms, ...( link.searchTerms || [] ) ];
    if ( link.href ) {
      result.push( {
        ...link,
        href: link.href,
        searchText: [ link.label, ...terms ].join( ' ' ).toLocaleLowerCase(),
      } );
    }
    for ( const child of link.children || [] ) push( child, [ ...terms, link.label ] );
  };

  for ( const column of COLUMNS ) {
    for ( const section of column.sections ) {
      if ( section.headingHref ) {
        result.push( {
          label: section.heading,
          href: section.headingHref,
          match: section.headingMatch,
          searchText: section.heading.toLocaleLowerCase(),
        } );
      }
      for ( const link of section.links ) push( link, section.heading ? [ section.heading ] : [] );
    }
  }

  const seen = new Set<string>();
  return result.filter( link => {
    const key = link.href + '\n' + link.label;
    if ( seen.has( key ) ) return false;
    seen.add( key );
    return true;
  } );
};

const MENU_SEARCH_LINKS = flattenMenuLinks();
const menuSearchKey = ( link: Pick<NavLink, 'label' | 'href'> ) => `${link.href || ''}\n${link.label}`;

/* Visual-only icon lookup. Kept separate from COLUMNS so the navigation data schema,
   labels, order, URLs and hierarchy remain unchanged. */
const NAV_ICON_PATHS: Record<string, string> = {
  Home: 'M3 11.5 12 4l9 7.5V21h-6v-6H9v6H3Z',
  Shop: 'M6 8h12l1 13H5L6 8Zm3 0V6a3 3 0 0 1 6 0v2',
  'Grahak OS': 'M8 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm2 15h4',
  VayuLok: 'M460-160q-50 0-85-35t-35-85h80q0 17 11.5 28.5T460-240q17 0 28.5-11.5T500-280q0-17-11.5-28.5T460-320H80v-80h380q50 0 85 35t35 85q0 50-35 85t-85 35ZM80-560v-80h540q26 0 43-17t17-43q0-26-17-43t-43-17q-26 0-43 17t-17 43h-80q0-59 40.5-99.5T620-840q59 0 99.5 40.5T760-700q0 59-40.5 99.5T620-560H80Zm660 320v-80q26 0 43-17t17-43q0-26-17-43t-43-17H80v-80h660q59 0 99.5 40.5T880-380q0 59-40.5 99.5T740-240Z',
  'Sehat': 'M345-120q-94 0-159.5-65.5T120-345q0-45 17-86t49-73l270-270q32-32 73-49t86-17q94 0 159.5 65.5T840-615q0 45-17 86t-49 73L504-186q-32 32-73 49t-86 17Zm266-286 107-106q20-20 31-47t11-56q0-60-42.5-102.5T615-760q-29 0-56 11t-47 31L406-611l205 205ZM345-200q29 0 56-11t47-31l106-107-205-205-107 106q-20 20-31 47t-11 56q0 60 42.5 102.5T345-200Z',
  Elsewhere: 'm3 12 18-7-7 18-2-7-7-2Z',
  'Expo Week': 'M5 5h14v16H5ZM8 3v4m8-4v4M5 10h14',
  Dastavez: 'M7 3h7l5 5v13H7ZM14 3v5h5M10 13h6m-6 4h6',
  'Clear Closure': 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-4-9 2.5 2.5L16 9',
  'Ritual Guru': 'm12 3 1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6ZM18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8Z',
  Anew: 'M20 7v5h-5M4 17v-5h5M6.5 8A7 7 0 0 1 18 7l2 5M17.5 16A7 7 0 0 1 6 17l-2-5',
  Hunar: 'm387-412 35-114-92-74h114l36-112 36 112h114l-93 74 35 114-92-71-93 71ZM240-40v-309q-38-42-59-96t-21-115q0-134 93-227t227-93q134 0 227 93t93 227q0 61-21 115t-59 96v309l-240-80-240 80Zm240-280q100 0 170-70t70-170q0-100-70-170t-170-70q-100 0-170 70t-70 170q0 100 70 170t170 70ZM320-159l160-41 160 41v-124q-35 20-75.5 31.5T480-240q-44 0-84.5-11.5T320-283v124Zm160-62Z',
  'Niji Setu': 'M440-280H280q-83 0-141.5-58.5T80-480q0-83 58.5-141.5T280-680h160v80H280q-50 0-85 35t-35 85q0 50 35 85t85 35h160v80ZM320-440v-80h320v80H320Zm200 160v-80h160q50 0 85-35t35-85q0-50-35-85t-85-35H520v-80h160q83 0 141.5 58.5T880-480q0 83-58.5 141.5T680-280H520Z',
  Orders: 'M5 5h14v16H5ZM8 3v4m8-4v4M8 11h8m-8 4h5',
  'Submit Request': 'M200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h360v80H200v560h560v-360h80v360q0 33-23.5 56.5T760-120H200Zm120-160v-80h320v80H320Zm0-120v-80h320v80H320Zm0-120v-80h320v80H320Zm360-80v-80h-80v-80h80v-80h80v80h80v80h-80v80h-80Z',
  'Request Amendment': 'M5 19h4l10-10-4-4L5 15Zm8-12 4 4',
  'Drop Docs': 'M7 3h8l4 4v14H7ZM15 3v5h4M12 17V11m-3 3 3-3 3 3',
  Vault: 'M480-320 280-520l56-58 104 104v-326h80v326l104-104 56 58-200 200ZM240-160q-33 0-56.5-23.5T160-240v-120h80v120h480v-120h80v120q0 33-23.5 56.5T720-160H240Z',
  Shipments: 'M3 7h11v10H3Zm11 4h4l3 3v3h-7ZM7 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z',
  'Leave Review': 'M4 4h16v12H9l-5 4Zm4 5h8m-8 4h5',
  Subscribe: 'M12 21a2.5 2.5 0 0 0 2.4-2h-4.8A2.5 2.5 0 0 0 12 21Zm6-5H6l1.5-2V9a4.5 4.5 0 0 1 9 0v5Z',
  Partner: 'M160-80q-33 0-56.5-23.5T80-160v-440q0-33 23.5-56.5T160-680h200v-120q0-33 23.5-56.5T440-880h80q33 0 56.5 23.5T600-800v120h200q33 0 56.5 23.5T880-600v440q0 33-23.5 56.5T800-80H160Zm0-80h640v-440H600q0 33-23.5 56.5T520-520h-80q-33 0-56.5-23.5T360-600H160v440Zm80-80h240v-18q0-17-9.5-31.5T444-312q-20-9-40.5-13.5T360-330q-23 0-43.5 4.5T276-312q-17 8-26.5 22.5T240-258v18Zm320-60h160v-60H560v60Zm-200-60q25 0 42.5-17.5T420-420q0-25-17.5-42.5T360-480q-25 0-42.5 17.5T300-420q0 25 17.5 42.5T360-360Zm200-60h160v-60H560v60ZM440-600h80v-200h-80v200Zm40 220Z',
  Perks: 'M4 9h16v12H4ZM12 9v12M4 13h16M7 9c-2.5-2.5 1.5-5.5 5 0m5-0c2.5-2.5-1.5-5.5-5 0',
  'Google Play': 'M40-240q10-105 64-191t139-140l-77-129q-9-14-4.5-30t18.5-24q14-9 30-5t24 18l80 133q38-16 79.5-24t86.5-8q45 0 86.5 8t79.5 24l80-133q8-14 24-18t30 5q14 8 18 24t-4 30l-77 129q85 54 139 140t64 191H40Zm680.5-151.5Q722-409 711-426t-27-22q-16-5-29 4t-15 26q-2 17 9 34t27.5 22.5Q693-356 706-365t14.5-26.5ZM284-362q16-5 27-22t9.5-34.5Q319-436 306-445t-29.5-3.5Q260-443 249-426t-9 34q2 17 15 26t29 4Z',
  ChatGPT: 'm394-80-70-123H189l-87-154 69-123-69-123 87-154h135l70-123h172l70 123h135l87 154-69 123 69 123-87 154H636L566-80H394Zm243-429h100l54-94-54-94H637l-54 94 54 94ZM430-388h100l54-92-54-92H430l-54 92 54 92Zm0-244h100l54-94-54-94H430l-54 94 54 94ZM224-509h100l54-94-54-94H224l-54 94 54 94Zm0 246h100l54-94-55-94H223l-54 94 55 94Zm206 123h100l54-94-54-94H430l-54 94 54 94Zm207-123h100l54-94-54-94H637l-51 94 51 94Z',
  Claude: 'M12 3v18M3 12h18M5.6 5.6l12.8 12.8m0-12.8L5.6 18.4',
  'App Store': 'M160-615v-60h60v60h-60Zm0 335v-275h60v275h-60Zm292 0H347q-24.75 0-42.37-17.63Q287-315.25 287-340v-280q0-24.75 17.63-42.38Q322.25-680 347-680h105q24.75 0 42.38 17.62Q512-644.75 512-620v280q0 24.75-17.62 42.37Q476.75-280 452-280Zm-105-60h105v-280H347v280Zm228 60v-60h165v-114H635q-24.75 0-42.37-17.63Q575-489.25 575-514v-106q0-24.75 17.63-42.38Q610.25-680 635-680h165v60H635v106h105q24.75 0 42.38 17.62Q800-478.75 800-454v114q0 24.75-17.62 42.37Q764.75-280 740-280H575Z',
  // Material Symbols Outlined "location_on", FILL 0 / wght 400 / GRAD 0 / opsz 48.
  // Exact path from the supplied 48px SVG; menu states still control its color.
  'Contact us': 'M26.48,22.48Q27.5,21.45 27.5,20t-1.02-2.48T24,16.5t-2.47,1.02T20.5,20t1.03,2.47T24,23.5t2.48-1.03ZM24,40.05Q30.65,34 33.83,29.08T37,20.4q0-5.9-3.77-9.65T24,7t-9.23,3.75T11,20.4q0,3.75 3.25,8.68T24,40.05ZM24,44q-8.05-6.85-12.02-12.73T8,20.4q0-7.5 4.83-11.95T24,4T35.18,8.45T40,20.4q0,5-3.98,10.88T24,44Zm0-24Z',
  Terms: 'M7 3h10v18H7ZM10 8h4m-4 4h4m-4 4h4',
  Privacy: 'M12 3 19 6v5c0 4.7-2.8 8.2-7 10-4.2-1.8-7-5.3-7-10V6Z',
};
const SECTION_ICON_PATHS: Record<string, string> = {
  Products: 'M4 7 12 3l8 4-8 4ZM4 12l8 4 8-4M4 17l8 4 8-4',
  Request: 'M6 3h12v18H6ZM9 7h6M9 11h6M9 15h4',
  'Refer & Earn': 'M720-80q-50 0-85-35t-35-85q0-7 1-14.5t3-13.5L322-392q-17 15-38 23.5t-44 8.5q-50 0-85-35t-35-85q0-50 35-85t85-35q23 0 44 8.5t38 23.5l282-164q-2-6-3-13.5t-1-14.5q0-50 35-85t85-35q50 0 85 35t35 85q0 50-35 85t-85 35q-23 0-44-8.5T638-672L356-508q2 6 3 13.5t1 14.5q0 7-1 14.5t-3 13.5l282 164q17-15 38-23.5t44-8.5q50 0 85 35t35 85q0 50-35 85t-85 35Zm0-640q17 0 28.5-11.5T760-760q0-17-11.5-28.5T720-800q-17 0-28.5 11.5T680-760q0 17 11.5 28.5T720-720ZM240-440q17 0 28.5-11.5T280-480q0-17-11.5-28.5T240-520q-17 0-28.5 11.5T200-480q0 17 11.5 28.5T240-440Zm480 280q17 0 28.5-11.5T760-200q0-17-11.5-28.5T720-240q-17 0-28.5 11.5T680-200q0 17 11.5 28.5T720-160Zm0-600ZM240-480Zm480 280Z',
  Extras: 'm12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z',
  Contact: 'M3 6h18v12H3Zm0 1 9 6 9-6',
  'Legal Stuff': 'M12 3 19 6v5c0 4.7-2.8 8.2-7 10-4.2-1.8-7-5.3-7-10V6Z',
};
// Typed as MaterialSymbol so `tsc` refuses a ligature the subset font in config/materialSymbols.ts
// does not ship; an unlisted name would render as its literal text instead of an icon.
const NAV_MATERIAL_SYMBOLS: Partial<Record<string, MaterialSymbol>> = {
  Gemini: 'diamond',
};
const SECTION_MATERIAL_SYMBOLS: Partial<Record<string, MaterialSymbol>> = {
  'With AI': 'neurology',
};

const MATERIAL_NAV_ICON_LABELS = new Set( [
  'VayuLok',
  'Sehat',
  'Hunar',
  'Niji Setu',
  'Submit Request',
  'Vault',
  'Partner',
  'Google Play',
  'ChatGPT',
  'App Store',
] );
// The Contact us SVG uses the source artwork's 48px coordinates (not the 960px material paths).
// Both source types are filled silhouettes; all other row icons stay stroked.
const FILLED_NAV_ICON_LABELS = new Set( [ ...MATERIAL_NAV_ICON_LABELS, 'Contact us' ] );
const navIconViewBox = ( label: string ) => label === 'Contact us'
  ? '0 0 48 48'
  : MATERIAL_NAV_ICON_LABELS.has( label ) ? '0 -960 960 960' : '0 0 24 24';
const MATERIAL_SECTION_ICON_LABELS = new Set( [ 'Refer & Earn' ] );
const FALLBACK_NAV_ICON_PATH = 'M5 5h14v14H5Zm4 4h6m-6 4h6';
const SUBNAV_ICON_PATH = 'M6 7v5a5 5 0 0 0 5 5h7m-3-3 3 3-3 3';
const ROW_CHEVRON_PATH = 'm9 6 6 6-6 6';

const PUBLIC_NAV_ID = 'public-navigation-menu';

const Header: React.FC = () => {
  const [ open, setOpen ] = useState( false );
  const [ query, setQuery ] = useState( '' );
  const [ showProductsMore, setShowProductsMore ] = useState( false );
  const [ productsOverflowing, setProductsOverflowing ] = useState( false );
  const [ localizedSearchText, setLocalizedSearchText ] = useState<Record<string, string>>( {} );
  const router = useRouter();
  const rootRef = useRef<HTMLDivElement | null>( null );
  const triggerRef = useRef<HTMLButtonElement | null>( null );
  const hasOpened = useRef( false );

  const term = query.trim().toLocaleLowerCase();
  const searching = term.length > 0;

  // Search results come only from the menu graph. Family and section names are inherited
  // search terms, so "Elsewhere" returns Visa, Trip and Activities without a dead parent link.
  const filtered = useMemo( () => (
    searching
      ? MENU_SEARCH_LINKS.filter( link => (
        link.searchText.includes( term )
        || ( localizedSearchText[ menuSearchKey( link ) ] || '' ).includes( term )
      ) )
      : MENU_SEARCH_LINKS
  ), [ localizedSearchText, searching, term ] );

  // SupportWidget translates the public menu in-place after render. The canonical search graph
  // above deliberately stays English, so harvest the CURRENT rendered labels just before a query
  // changes the menu into its flat-results view. This makes translated destination, family and
  // section labels searchable without duplicating translations in navigation data or calling the
  // translation API from Header. data-nav-search-key remains stable because data attributes are
  // intentionally outside SupportWidget's translation allowlist.
  const syncLocalizedSearchText = useCallback( () => {
    const root = rootRef.current;
    if ( !root ) return;
    const aliases: Record<string, string> = {};
    for ( const anchor of Array.from( root.querySelectorAll<HTMLAnchorElement>( 'a[data-nav-search-key]' ) ) ) {
      const key = anchor.dataset.navSearchKey;
      if ( !key ) continue;
      const pieces = [ anchor.textContent || '' ];
      const family = anchor.closest<HTMLElement>( '.nav-tree-item[aria-label]' )?.getAttribute( 'aria-label' );
      if ( family ) pieces.push( family );
      const heading = anchor.closest<HTMLElement>( '.nav-group' )
        ?.querySelector<HTMLElement>( '.nav-group-label' )?.textContent;
      if ( heading ) pieces.push( heading );
      aliases[ key ] = pieces.join( ' ' ).toLocaleLowerCase();
    }
    setLocalizedSearchText( previous => {
      const next = { ...previous };
      for ( const [ key, value ] of Object.entries( aliases ) )
      {
        const prior = next[ key ] || '';
        // Preserve aliases harvested before the menu switched into flat search results.
        // Otherwise a translated family term (for example Elsewhere) is lost when a
        // translated child is searched first and React re-renders that child in English.
        next[ key ] = prior ? `${prior} ${value}` : value;
      }
      return next;
    } );
  }, [] );

  const applySearchQuery = useCallback( ( value: string ) => {
    syncLocalizedSearchText();
    setQuery( value );
  }, [ syncLocalizedSearchText ] );

  const close = useCallback( () => {
    setOpen( false );
    setQuery( '' );
    setLocalizedSearchText( {} );
    setShowProductsMore( false );
    setProductsOverflowing( false );
  }, [] );

  // Derive the desktop panel width from its actual viewport position instead of a hard-coded
  // allowance for the brand lockup. This keeps the menu safe if the logo, type size, locale or
  // header spacing changes later. Mobile uses its fixed safe-area insets and ignores this value.
  const syncMenuAvailableWidth = useCallback( () => {
    if ( typeof window === 'undefined' ) return;
    const root = rootRef.current;
    if ( !root ) return;
    const box = root.getBoundingClientRect();
    const direction = window.getComputedStyle( root ).direction;
    const edgeGap = 24;
    const available = direction === 'rtl'
      ? box.right - edgeGap
      : window.innerWidth - box.left - edgeGap;
    root.style.setProperty( '--nav-menu-available-width', `${Math.max( 0, Math.floor( available ) )}px` );
  }, [] );

  useEffect( () => {
    if ( !open || typeof window === 'undefined' ) return undefined;
    syncMenuAvailableWidth();
    window.addEventListener( 'resize', syncMenuAvailableWidth );

    const observed = rootRef.current?.closest<HTMLElement>( '.hdr-in' ) || rootRef.current;
    const observer = typeof ResizeObserver !== 'undefined' && observed
      ? new ResizeObserver( syncMenuAvailableWidth )
      : null;
    if ( observer && observed ) observer.observe( observed );

    return () => {
      window.removeEventListener( 'resize', syncMenuAvailableWidth );
      observer?.disconnect();
    };
  }, [ open, syncMenuAvailableWidth ] );

  // Escape closes from anywhere, an outside pointerdown dismisses, AND the menu closes
  // when the mouse LEAVES it (hover-out), on owner request. None of these existed
  // originally: the menu could only be closed by clicking the trigger again or following
  // a link. Matches the language widget, so both menus answer to the same keys.
  useEffect( () => {
    if ( !open ) return undefined;
    const onKeyDown = ( event: KeyboardEvent ) => { if ( event.key === 'Escape' ) close(); };
    const onPointerDown = ( event: PointerEvent ) => {
      if ( rootRef.current && !rootRef.current.contains( event.target as Node ) ) close();
    };

    // HOVER-OUT CLOSE, mouse only. When the pointer leaves the dropdown the menu closes
    // after a short grace period. The grace (180ms) forgives a pointer that clips a
    // corner or crosses the 8px gap between the trigger and the panel - without it the
    // menu snaps shut on the smallest wobble and feels twitchy. A re-entry cancels the
    // pending close.
    // GUARDED TO FINE POINTERS (mouse/trackpad). On a touch screen there is no hover, and
    // a synthetic mouseleave fires on the tap that dismisses the on-screen keyboard or on
    // a scroll fling - closing the menu then would fight the user. matchMedia('(hover:hover)
    // and (pointer:fine)') is the standard capability query for "has a real hovering
    // pointer", and it is read at event time so a hybrid device that switches input modes
    // is handled correctly.
    let hoverCloseTimer = 0;
    const canHover = () =>
      typeof window.matchMedia === 'function'
      && window.matchMedia( '(hover: hover) and (pointer: fine)' ).matches;
    const onMouseLeave = () => {
      if ( !canHover() ) return;
      window.clearTimeout( hoverCloseTimer );
      hoverCloseTimer = window.setTimeout( close, 180 );
    };
    const onMouseEnter = () => window.clearTimeout( hoverCloseTimer );
    const root = rootRef.current;

    document.addEventListener( 'keydown', onKeyDown );
    document.addEventListener( 'pointerdown', onPointerDown );
    root?.addEventListener( 'mouseleave', onMouseLeave );
    root?.addEventListener( 'mouseenter', onMouseEnter );
    return () => {
      window.clearTimeout( hoverCloseTimer );
      document.removeEventListener( 'keydown', onKeyDown );
      document.removeEventListener( 'pointerdown', onPointerDown );
      root?.removeEventListener( 'mouseleave', onMouseLeave );
      root?.removeEventListener( 'mouseenter', onMouseEnter );
    };
  }, [ close, open ] );

  // Focus returns to the trigger on close, so a keyboard user is not dropped onto
  // <body> and made to tab from the top of the document again.
  useEffect( () => {
    if ( open ) { hasOpened.current = true; return; }
    if ( hasOpened.current ) triggerRef.current?.focus();
  }, [ open ] );

  // Exact selection uses the concrete browser URL when Next.js exposes it. Dynamic
  // /shop/[slug] pages share one router.pathname, so pathname alone can select more than
  // one menu row. asPath distinguishes Guided Resolution, Case Submission and Paperwork.
  const normalizePath = ( value?: string ) => {
    if ( !value || /^[a-z][a-z0-9+.-]*:/i.test( value ) ) return '';
    const path = value.split( /[?#]/, 1 )[ 0 ] || '/';
    return path === '/' ? '/' : ( path.replace( /\/+$/, '' ) || '/' );
  };
  const concretePath = normalizePath( router.asPath );
  const currentPath = concretePath || normalizePath( router.pathname );
  const isActive = ( link: NavLink ) => {
    if ( !link.href ) return false;
    // Orders is the only navigation destination. Customer template links are
    // actions even though their destination is the same clean /orders/ URL.
    if ( link.href === '/orders/' && link.label !== 'Orders' ) return false;
    const destination = normalizePath( link.href );
    if ( !destination ) return false;
    if ( concretePath ) return destination === currentPath;
    return link.match ? router.pathname === link.match : destination === currentPath;
  };

  // When the current page is low in the capped Products rail, opening the menu reveals it
  // immediately on every viewport. Desktop and mobile both show seven product rows now.
  useEffect( () => {
    if ( !open || searching || typeof window === 'undefined' ) return;
    const scroller = rootRef.current?.querySelector<HTMLElement>( '.nav-products-scroll' );
    const active = scroller?.querySelector<HTMLElement>( '.nav-item.active' );
    if ( !scroller || !active ) return;
    const box = scroller.getBoundingClientRect();
    const row = active.getBoundingClientRect();
    if ( row.top < box.top ) scroller.scrollTop -= box.top - row.top;
    else if ( row.bottom > box.bottom ) scroller.scrollTop += row.bottom - box.bottom;
  }, [ currentPath, open, searching ] );

  // The Products rail is intentionally capped at seven rows on desktop and mobile. A scrollbar
  // alone is easy to miss inside the menu, so expose one small icon-only continuation cue while
  // content remains below the fold. The cue is derived from real scroll geometry, not product
  // count, so it stays correct if row heights or the catalogue hierarchy change.
  useEffect( () => {
    if ( !open || searching || typeof window === 'undefined' ) {
      setShowProductsMore( false );
      setProductsOverflowing( false );
      return undefined;
    }
    const scroller = rootRef.current?.querySelector<HTMLElement>( '.nav-products-scroll' );
    if ( !scroller ) {
      setShowProductsMore( false );
      setProductsOverflowing( false );
      return undefined;
    }

    const update = () => {
      const overflow = scroller.scrollHeight - scroller.clientHeight > 2;
      const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      setProductsOverflowing( overflow );
      setShowProductsMore( overflow && remaining > 2 );
    };

    update();
    scroller.addEventListener( 'scroll', update, { passive: true } );
    window.addEventListener( 'resize', update );
    return () => {
      scroller.removeEventListener( 'scroll', update );
      window.removeEventListener( 'resize', update );
    };
  }, [ currentPath, open, searching ] );

  const scrollProductsForward = useCallback( () => {
    if ( typeof window === 'undefined' ) return;
    const scroller = rootRef.current?.querySelector<HTMLElement>( '.nav-products-scroll' );
    if ( !scroller ) return;

    const reduceMotion = typeof window.matchMedia === 'function'
      && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
    const rowHeight = window.matchMedia( '(max-width: 767px)' ).matches ? 52 : 46;
    scroller.scrollBy( {
      top: Math.max( rowHeight, scroller.clientHeight - rowHeight ),
      behavior: reduceMotion ? 'auto' : 'smooth',
    } );
  }, [] );

  // Internal destinations stay inside the site/WebView. In a Capacitor shell an external
  // destination is handed to the native browser instead of being trapped inside the WebView.
  const handleNavClick = useCallback( ( event: React.MouseEvent<HTMLAnchorElement>, link: NavLink ) => {
    const sendAction = menuActionForLabel( link.label );
    if ( sendAction && isPrimaryMenuActivation( event ) ) {
      // A real menu click is the only way to queue one authenticated template.
      // The clean /orders/ URL cannot trigger a template send on its own.
      stashCustomerMenuAction( sendAction );
    }
    const capacitor = typeof window !== 'undefined'
      ? ( window as typeof window & { Capacitor?: { isNativePlatform?: () => boolean } } ).Capacitor
      : undefined;
    if ( link.external && link.href && capacitor?.isNativePlatform?.() ) {
      event.preventDefault();
      close();
      void import( '@capacitor/browser' )
        .then( ( { Browser } ) => Browser.open( { url: link.href! } ) )
        .catch( () => { window.location.href = link.href!; } );
      return;
    }
    close();
  }, [ close ] );

  // NO renderLink() HELPER. The anchor markup is duplicated inline in both branches
  // below, on purpose, and it must stay that way.
  //
  // It was briefly a shared renderLink( link, extraClass ) helper, which silently
  // unstyled the entire menu. styled-jsx only attaches its scoping class to JSX it
  // can see statically inside the return tree; markup produced by a separate function
  // gets a different hash, so none of the .nav-item rules in the style block below
  // matched, and every row fell through to the unscoped global .nav-item in
  // Layout.css:659 - 15px at weight 560 with no lime hover and no active tint.
  //
  // This is the first trap in the design contract, and it is invisible to the tests:
  // 112 browser assertions passed while every row was unstyled, because they assert
  // text, href and aria-current and never read computed style. Only
  // CSS.getMatchedStylesForNode showed that the jsx rules were not matching at all.
  // menucheck.js asserts computed font-size, weight and the active background in Chromium,
  // Firefox and WebKit so this cannot recur silently.

  return (
    <header className="hdr">
      <div className="hdr-in">
        <div className="logo-nav">
          {/* Plain <a>, not next/link, for the same styled-jsx reason as Footer's lockup:
              styled-jsx does not scope capitalised components, so `<Link className="logo">`
              renders with no styles at all. Recorded in
              `.kiro/steering/grahak-os-design.md` (retired 2026-10-09, af7858fa). */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/" className="logo" aria-label="WECARE.DIGITAL home">
            <BrandLockup className="public-header" />
          </a>
          <div className="nav-dropdown" ref={ rootRef }>
            {/* This must stay the FIRST button in the header. Header.test.tsx reaches
                the trigger with container.querySelector('button') to assert the chevron
                is drawn rather than typed, so the search field below is an input and no
                control is added ahead of this element. */}
            <button
              ref={ triggerRef }
              type="button"
              className="nav-trigger"
              aria-label="Open navigation"
              aria-expanded={ open }
              aria-controls={ PUBLIC_NAV_ID }
              aria-keyshortcuts="Enter Space Escape"
              onClick={ () => {
                if ( open ) close();
                else {
                  syncMenuAvailableWidth();
                  setOpen( true );
                  setQuery( '' );
                }
              } }
            >
              <svg className="nav-trigger-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z" />
              </svg>
            </button>
            <nav id={ PUBLIC_NAV_ID } className={ `nav-menu ${open ? 'open' : ''}` } aria-label="Public navigation">
              {/* Not autofocused. The language panel autofocuses its search because
                  searching is the only way to use it, but this menu is readable at a
                  glance - popping the on-screen keyboard over the whole catalogue on a
                  phone would cost more than it saves. */}
              <div className="nav-search-field">
                <input
                  className="nav-search"
                  type="search"
                  value={ query }
                  placeholder="Search"
                  aria-label="Search navigation"
                  onFocus={ syncLocalizedSearchText }
                  onChange={ event => applySearchQuery( event.target.value ) }
                  onKeyDown={ event => { if ( event.key === 'Escape' ) close(); } }
                />
                <VoiceSearchMic onTranscript={ applySearchQuery } />
              </div>

              {/* Flat results while searching: column headings over a filtered list
                  describe categories that are no longer all present, which reads as
                  missing items rather than as a narrowed list. */}
              { searching && (
                <>
                  <p className="nav-search-status" role="status" aria-live="polite" aria-atomic="true">
                    { filtered.length } menu { filtered.length === 1 ? 'result' : 'results' }.
                  </p>
                  <div className="nav-results">
                  { filtered.map( link => (
                    <a
                      key={ link.label + link.href }
                      href={ link.href }
                      data-nav-search-key={ menuSearchKey( link ) }
                      className={ `nav-item ${isActive( link ) ? 'active' : ''}`.trim() }
                      aria-current={ isActive( link ) ? 'page' : undefined }
                      onClick={ event => handleNavClick( event, link ) }
                    >
                      { NAV_MATERIAL_SYMBOLS[ link.label ] ? (
                        <span
                          className="nav-row-material-symbol"
                          aria-hidden="true"
                        >
                          { NAV_MATERIAL_SYMBOLS[ link.label ] }
                        </span>
                      ) : (
                        <svg
                          className={ `nav-row-icon ${FILLED_NAV_ICON_LABELS.has( link.label ) ? 'nav-row-icon-material' : ''}`.trim() }
                          viewBox={ navIconViewBox( link.label ) }
                          aria-hidden="true"
                          focusable="false"
                        >
                          <path d={ NAV_ICON_PATHS[ link.label ] || FALLBACK_NAV_ICON_PATH } />
                        </svg>
                      ) }
                      <span className="nav-item-label">{ link.label }</span>
                    </a>
                  ) ) }
                  { !filtered.length && <p className="nav-empty">No matching page.</p> }
                  </div>
                </>
              ) }

              { !searching && (
                <div className="nav-cols">
                  { COLUMNS.map( ( column, columnIndex ) => (
                    <div key={ columnIndex } className="nav-col">
                      { column.sections.map( ( section, sectionIndex ) => {
                        const isProducts = section.heading === 'Products';
                        const headingActive = Boolean(
                          section.headingHref && section.headingMatch && router.pathname === section.headingMatch
                        );
                        const sectionIconPath = SECTION_ICON_PATHS[ section.heading ];
                        const sectionMaterialSymbol = SECTION_MATERIAL_SYMBOLS[ section.heading ];
                        const label = section.heading && ( section.headingHref
                          ? (
                            <a
                              href={ section.headingHref }
                              data-nav-search-key={ menuSearchKey( { label: section.heading, href: section.headingHref } ) }
                              className={ `nav-group-label nav-group-link ${headingActive ? 'active' : ''}`.trim() }
                              aria-current={ headingActive ? 'page' : undefined }
                              onClick={ close }
                            >
                              { sectionMaterialSymbol ? (
                                <span className="nav-section-material-symbol" aria-hidden="true">
                                  { sectionMaterialSymbol }
                                </span>
                              ) : sectionIconPath ? (
                                <svg
                                  className={ `nav-section-icon ${MATERIAL_SECTION_ICON_LABELS.has( section.heading ) ? 'nav-section-icon-material' : ''}`.trim() }
                                  viewBox={ MATERIAL_SECTION_ICON_LABELS.has( section.heading ) ? '0 -960 960 960' : '0 0 24 24' }
                                  aria-hidden="true"
                                  focusable="false"
                                >
                                  <path d={ sectionIconPath } />
                                </svg>
                              ) : null }
                              <span>{ section.heading }</span>
                            </a>
                          )
                          : (
                            <span className="nav-group-label">
                              { sectionMaterialSymbol ? (
                                <span className="nav-section-material-symbol" aria-hidden="true">
                                  { sectionMaterialSymbol }
                                </span>
                              ) : sectionIconPath ? (
                                <svg
                                  className={ `nav-section-icon ${MATERIAL_SECTION_ICON_LABELS.has( section.heading ) ? 'nav-section-icon-material' : ''}`.trim() }
                                  viewBox={ MATERIAL_SECTION_ICON_LABELS.has( section.heading ) ? '0 -960 960 960' : '0 0 24 24' }
                                  aria-hidden="true"
                                  focusable="false"
                                >
                                  <path d={ sectionIconPath } />
                                </svg>
                              ) : null }
                              <span>{ section.heading }</span>
                            </span>
                          )
                        );

                        const items = section.links.map( link => (
                          <div
                            key={ link.label + ( link.href || '' ) }
                            className={ `nav-tree-item ${link.children?.length ? 'has-children' : ''}`.trim() }
                            role={ link.children?.length ? 'group' : undefined }
                            aria-label={ link.children?.length ? link.label : undefined }
                          >
                            { link.href ? (
                              <a
                                href={ link.href }
                                data-nav-search-key={ menuSearchKey( link ) }
                                className={ `nav-item ${section.nestedLinks ? 'nav-child' : ''} ${isActive( link ) ? 'active' : ''}`.trim() }
                                aria-current={ isActive( link ) ? 'page' : undefined }
                                onClick={ event => handleNavClick( event, link ) }
                              >
                                { NAV_MATERIAL_SYMBOLS[ link.label ] ? (
                                  <span
                          className="nav-row-material-symbol"
                          aria-hidden="true"
                        >
                                    { NAV_MATERIAL_SYMBOLS[ link.label ] }
                                  </span>
                                ) : (
                                  <svg
                                    className={ `nav-row-icon ${FILLED_NAV_ICON_LABELS.has( link.label ) ? 'nav-row-icon-material' : ''}`.trim() }
                                    viewBox={ navIconViewBox( link.label ) }
                                    aria-hidden="true"
                                    focusable="false"
                                  >
                                    <path d={ NAV_ICON_PATHS[ link.label ] || FALLBACK_NAV_ICON_PATH } />
                                  </svg>
                                ) }
                                <span className="nav-item-label">{ link.label }</span>
                                { ( section.nestedLinks || link.children?.length ) ? (
                                  <svg className="nav-row-chevron" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                                    <path d={ ROW_CHEVRON_PATH } />
                                  </svg>
                                ) : null }
                              </a>
                            ) : (
                              <span className="nav-item nav-family-label">
                                { NAV_MATERIAL_SYMBOLS[ link.label ] ? (
                                  <span
                          className="nav-row-material-symbol"
                          aria-hidden="true"
                        >
                                    { NAV_MATERIAL_SYMBOLS[ link.label ] }
                                  </span>
                                ) : (
                                  <svg
                                    className={ `nav-row-icon ${FILLED_NAV_ICON_LABELS.has( link.label ) ? 'nav-row-icon-material' : ''}`.trim() }
                                    viewBox={ navIconViewBox( link.label ) }
                                    aria-hidden="true"
                                    focusable="false"
                                  >
                                    <path d={ NAV_ICON_PATHS[ link.label ] || FALLBACK_NAV_ICON_PATH } />
                                  </svg>
                                ) }
                                <span className="nav-item-label">{ link.label }</span>
                                { link.children?.length ? (
                                  <svg className="nav-row-chevron" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                                    <path d={ ROW_CHEVRON_PATH } />
                                  </svg>
                                ) : null }
                              </span>
                            ) }

                            { link.children?.map( child => child.href && (
                              <a
                                key={ child.label + child.href }
                                href={ child.href }
                                data-nav-search-key={ menuSearchKey( child ) }
                                className={ `nav-item nav-child ${isActive( child ) ? 'active' : ''}`.trim() }
                                aria-current={ isActive( child ) ? 'page' : undefined }
                                onClick={ event => handleNavClick( event, child ) }
                              >
                                <svg className="nav-sub-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                                  <path d={ NAV_ICON_PATHS[ child.label ] || SUBNAV_ICON_PATH } />
                                </svg>
                                <span className="nav-item-label">{ child.label }</span>
                              </a>
                            ) ) }
                          </div>
                        ) );

                        return (
                          <div key={ section.heading || sectionIndex } className={ `nav-group ${isProducts ? 'nav-group-products' : ''}`.trim() }>
                            { label }
                            { isProducts
                              ? (
                                <>
                                  <div className="nav-products-scroll">{ items }</div>
                                  { productsOverflowing && (
                                    <div className={ `nav-products-cue-row ${showProductsMore ? '' : 'is-hidden'}`.trim() }>
                                      <button
                                        type="button"
                                        className="nav-products-more"
                                        aria-label="Scroll to more products"
                                        aria-hidden={ !showProductsMore }
                                        tabIndex={ showProductsMore ? 0 : -1 }
                                        onClick={ scrollProductsForward }
                                      >
                                        <svg
                                          className="nav-products-more-icon"
                                          viewBox="0 -960 960 960"
                                          aria-hidden="true"
                                          focusable="false"
                                        >
                                          <path d="M480-200 240-440l42-42 198 198 198-198 42 42-240 240Zm0-253L240-693l42-42 198 198 198-198 42 42-240 240Z" />
                                        </svg>
                                      </button>
                                    </div>
                                  ) }
                                </>
                              )
                              : items }
                          </div>
                        );
                      } ) }
                    </div>
                  ) ) }
                </div>
              ) }
            </nav>
          </div>
        </div>

        {/* THE SHOPPING BAG, AND IT MUST STAY AFTER .logo-nav IN THE DOM.
            Header.test.tsx reaches the menu trigger with container.querySelector('button') to
            assert the chevron is drawn rather than typed, so the trigger has to remain the FIRST
            button in this header. This control is an anchor, like the logo and every nav row, so
            it adds no button at all - but putting it earlier in the tree would still move the
            reading and tab order ahead of the brand.
            It paints itself: styled-jsx cannot scope a capitalised component, so the <style jsx>
            block below cannot reach it and HeaderCart owns its CSS, including the
            margin-inline-start:auto that pushes it to the end of this flex row. */}
        <HeaderCart />
      </div>
      <style jsx>{`
        /* OPAQUE BY DEFAULT, translucent only where the blur actually works.
           It was rgba(255,255,255,.97) with backdrop-filter:blur(20px) unconditionally.
           Measured, backdrop-filter computes to the keyword none in environments that
           do not support it - and without the blur the 3% translucency is not a frosted
           effect, it is just bleed-through. On the marketing pages that is invisible
           because almost nothing scrolls under the header; on /terms/ and /privacy/,
           which are 40,000 characters of dense prose, lines were faintly legible
           through it and behind the logo.
           So the base rule is a solid #fff, and the translucent treatment is restored
           inside @supports where the blur it depends on is real. */
        /* THE TYPEFACE IS DECLARED HERE, not inherited, and that is the whole point of the
           line. The brand lockup had no font-family of its own: it took body's, which is set
           in src/styles/Layout.css. Nothing was visibly wrong - both stacks begin with Inter
           and measure identically (195.59px vs 195.59px at 800/23px, with Inter present AND
           with it blocked), and font-feature-settings is inherited so both already get Inter's
           cv02/cv03/cv04/cv11 variants. The reason to own it is that the brand mark's typeface
           should not depend on a global stylesheet a refactor could move: with that body rule
           absent the lockup falls to a serif at 98px while the h1 stays Inter at 106px,
           because the h1 declares its own stack. Observed, not imagined.

           This is index.tsx:797's declaration, byte for byte. A shared token both files
           reference would be better still, and is deliberately not done here - it is wider
           than this change. */
        /* inset-inline:0 for the symmetric left/right pair - identical in ltr, and it stops
           the bar being anchored to physical sides in a mirrored document. */
        .hdr{position:fixed;top:0;inset-inline:0;z-index:1001;background:#fff;
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
        @supports ((backdrop-filter:blur(20px)) or (-webkit-backdrop-filter:blur(20px))){
          .hdr{background:rgba(255,255,255,.97);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
        }
        /* overflow-x:clip is ZOOM CONTAINMENT (unified-mobile Phase 1). The header is position:
           fixed, so its content is NOT clipped by html's overflow-x guard - at a 200%-zoom reflow
           to a ~160 CSS-px layout viewport the nowrap brand lockup (WECARE.DIGITAL ~158px) plus the
           46px menu trigger overflow the bar and let the PAGE scroll ~18px horizontally. Clipping
           on the x axis only (overflow-y stays visible, so this is not a scroll container) contains
           that without reflowing the lockup. The desktop mega-menu is position:absolute and
           width:min(760px,...), which fits inside this 1300px box, so it is not clipped; at
           max-width:767px it is position:fixed and escapes this box entirely. Normal-zoom layout is
           unchanged - nothing reaches the clip there. overflow-x:hidden is the clip fallback. NO
           backtick in this comment. */
        .hdr-in{max-width:var(--public-content-max);margin:0 auto;padding:18px 24px;display:flex;align-items:center;box-sizing:border-box;height:108px;min-width:0;overflow-x:hidden;overflow-x:clip}
        /* min-width:0 for the same reason as .logo-nav below: the brand lockup inside is nowrap,
           so this flex item would otherwise hold its full intrinsic width and keep the cluster
           from compressing at a 200%-zoom reflow. The overflow is absorbed by .hdr-in's
           overflow-x:clip, not reflowed onto the page. */
        .logo{display:flex;align-items:center;text-decoration:none;min-width:0}
        /* min-width:0 is the ZOOM-CONTAINMENT floor (unified-mobile Phase 1, unit 3). A flex item
           defaults to min-width:auto, which refuses to shrink below the intrinsic width of its
           content - here the nowrap brand lockup (WECARE.DIGITAL ~158px) plus the 46px menu
           trigger. Without this, .logo-nav keeps its full intrinsic width at a 200%-zoom reflow to
           a ~160 CSS-px layout viewport and, because .hdr-cart is pushed to the end with
           margin-inline-start:auto, the cart glyph's right edge is driven past the viewport
           (measured ~265px at a 160 CSS-px reflow) and the PAGE scrolls horizontally. min-width:0
           lets this cluster compress so the overflow lands inside .hdr-in's overflow-x:clip
           instead of reaching the page. max-width:100% keeps it from ever exceeding the row.
           Normal-zoom layout is unchanged - nothing reaches this floor there. */
        .logo-nav{display:flex;align-items:center;gap:10px;min-width:0;max-width:100%}
        .nav-dropdown{position:relative;min-width:0}
        /* SOFT NEUTRAL CHIP at rest, not a bare invisible button. It was
           background:none, so the chevron floated with no target - it read as
           decoration rather than a control. A soft #f4f7ee fill with a #e3ecc9
           hairline gives it a visible, tappable chip while staying quieter than the
           lime hover state below it. Hover/focus/expanded still brighten to the lime
           tint, so the interaction feedback is unchanged. */
        .nav-trigger{min-width:46px;min-height:46px;background:#f4f7ee;border:0;border-radius:10px;cursor:pointer;padding:8px;display:flex;align-items:center;justify-content:center;
          transition:background-color .18s ease}
        /* THE HOVER STATE INVERTS NOW, because the old one was not a state change at all.
           rgba(209,244,112,.22) over the white header composites to rgb(245,253,224), which
           measures 1.032:1 against this chip's own #f4f7ee - an RGB move of 15 out of a possible
           441. That is not a hover effect, it is a rounding error, and it is why the owner
           reported the menu icon as having none.

           WHY IT CANNOT SIMPLY BE MORE LIME. Lime is a LIGHT colour, so no lime fill can carry a
           state change on a near-white chip. Measured against #f4f7ee:
             rgba(209,244,112,.22)   1.03:1   (move 15)    <- what shipped
             solid #d1f470           1.15:1   (move 131)
             #1a3a2a                11.52:1  (move 349)
           Only an inversion produces a luminance step. Solid lime is a hue move: fine for most
           people, close to nothing for anyone with reduced colour discrimination.

           AND WHY NOT RECOLOUR THE CHEVRON ALONE, which was the narrower reading. On a chip this
           pale the glyph can only go to a colour that clears 3:1 on it - lime 1.15:1, amber
           1.88:1 and green 2.94:1 all fail, leaving blue 4.77:1, purple 4.35:1 or red 4.46:1.
           None of those mean anything in this palette and red reads as an error on a menu button,
           so a glyph-only colour change would have had to invent a hue. Inverting the chip lets
           the pairing that already exists - lime on dark green - do the work.

           The chip's resting border also firms up from #e3ecc9 (1.23:1 on white) to #cfe0a6, so
           the control reads as a button before it is touched; the fill is unchanged at 1.08:1,
           which is deliberate - this is chrome beside a wordmark, not a call to action.

           This icon-only iteration did not change the panel. The separate lime top border
           and rounded corners requested later live on .nav-menu below. */
        /* ROUND TWO: LIME FILL WITH A DARK EDGE, not a solid dark-green block.
           The inversion above was correct about the measurement and wrong about the mass. The
           owner's words on the shipped result were "on select too much green": filling all
           2116px² of a 46x46 chip with #1a3a2a makes the control the heaviest thing in a header
           whose other elements are a wordmark and text.

           Everything round one measured still holds and is why this is not a return to a tint.
           Against the #f4f7ee rest fill: rgba(209,244,112,.22) is 1.03:1 (RGB move 21/441) and
           solid #d1f470 is 1.15:1. A lime FILL cannot carry the state on its own.

           So the state is carried by the EDGE instead, and the fill is free to be lime - which is
           what "on" looks like everywhere else on this site. #1a3a2a against the resting #cfe0a6
           border measures 8.84:1, and it goes to 2px so the edge has weight to match the brighter
           fill. Three independent signals now say "open": the border darkens, the fill brightens,
           and the chevron rotates 45deg -> 225deg. Round one's objection to a hue-only move was
           that it says nothing to a visitor with reduced colour discrimination; a 8.84:1 edge and
           a rotation both survive that.

           Dark area drops from 2116px² to 352px², 16.6% of what shipped. The five options and
           their computed numbers are in docs/menu-icon-options.md, rendered by
           tools/browser/menuiconshots.js - this is G4.

           border-width IS transitioned. Without it the 1px -> 2px step snaps while the colours
           glide, which reads as two events. box-sizing is border-box (measured, not assumed:
           computed 46x46 outer at rest, hover and open), so the thicker border changes nothing
           outside the chip - the header stays 108px and the chip stays at x=210.34. */
        .nav-trigger:hover,.nav-trigger:focus-visible,.nav-trigger[aria-expanded='true']{
          background:var(--public-brand-lime);outline:none;
        }
        /* A TWO-TONE RING, because this control inverts on focus and a single-colour ring
           cannot work against both of its states.
           The ring was rgba(26,58,42,.2), which composites to rgb(200,209,199) over the
           header and measures 1.44:1 against it - under the 3:1 WCAG 1.4.11 asks of a focus
           indicator. Note the rule above also sets outline:none, so that faint shadow was
           the only ring present.
           Going opaque #1a3a2a alone does not fix it either: the :focus-visible rule above
           fills this chip with #1a3a2a, so a dark green ring drawn tight against a dark
           green chip has no edge at all - it just reads as a slightly bigger chip.
           So: a 2px white spacer first, then 3px of opaque #1a3a2a outside it. The white
           separates the ring from the inverted chip, and the dark green measures 12.48:1
           against the white header behind it. The same pair works if the chip is ever
           returned to its pale resting fill, which is what makes it the durable answer.
           The chip's own inversion still carries the state; this makes the ring carry it
           too, rather than relying on a colour change a low-vision visitor may not catch. */
        .nav-trigger:focus-visible{box-shadow:0 0 0 2px #fff,0 0 0 5px #1a3a2a}
        /* THE CHEVRON NO LONGER CHANGES COLOUR, and that is the simplification the lime fill
           buys. It had to flip to lime because the chip went dark underneath it; on a lime chip
           #1a3a2a measures 10.04:1, so the same dark glyph works in both states and there is one
           less thing moving. The rule that used to flip it to #d1f470 is gone rather than
           neutralised - a rule that sets a colour to the colour it already has is a thing the
           next reader has to work out. */
        /* 3px STROKES AND FULL OPACITY, because the previous "chunkier" change never rendered.
           The comment here used to say the strokes went from 2px to 2.5px so the arrow would stop
           reading as a hairline. MEASURED on the built page at devicePixelRatio 1:
           getComputedStyle(.nav-arrow).borderRightWidth was **2px**. A 2.5px border is rounded
           down to 2px on a 1x display, so the thickening existed only in the stylesheet and the
           glyph was still exactly the hairline it was meant to stop being. That is the likeliest
           reading of the owner's "menu icon is looking dull", and it is why this goes to a whole
           3px rather than nudging the fraction again - 3px cannot be rounded away.

           opacity:.85 is also gone. It was there to soften a dark glyph on a light ground, but it
           was softening the one element that carries the meaning; at full strength the chevron is
           11.52:1 on the resting chip and 10.04:1 on the lime one.

           NO LINES HERE, deliberately: a three-line burger was mocked in round one
           (docs/menu-mock/a4-three-lines.png) and the owner kept the chevron. */
        .nav-trigger-icon{display:block;width:27px;height:27px;margin:0;fill:#1a3a2a;transform:rotate(0deg);transition:transform .2s}
        .nav-trigger[aria-expanded='true'] .nav-trigger-icon{transform:rotate(180deg)}

        /* MEGA PANEL.
           WIDTH IS 760px, NOT THE PAGE MEASURE. It was first built at the site's
           1252px measure, which measured 1252x393 with its three columns only
           158/308/148px tall - a panel more than half empty, and it looked it. Twelve
           rows do not need the full page width. 760px is what the content asks for:
           the widest label, "Request Amendment" at 17px/600, needs ~210px of row, so
           three of those plus the 20px gutters and 14px padding comes to ~700px.
           Anchored left of the trigger rather than centred, because a narrow panel
           centred in the viewport under a left-aligned trigger reads as unrelated to
           it. min() against calc(100vw - 256px) is what stops the absolute
           positioning overflowing on a narrow window before the mobile rule takes
           over.

           DESKTOP WIDTH IS MEASURED FROM THE ACTUAL TRIGGER POSITION. Older versions
           subtracted a hard-coded 256px from 100vw to approximate the brand lockup plus
           trigger offset. That value broke whenever the lockup size changed. The component
           now writes --nav-menu-available-width from getBoundingClientRect(), keeps a 24px
           viewport gutter, and refreshes it while open on resize/header ResizeObserver.
           RTL measures from the opposite edge. The browser sweep still verifies that the
           resulting panel never leaves the viewport.

           max-height CLEARS THE WHATSAPP BUTTON GEOMETRICALLY, which is the only way
           to clear it. #wecarewa-widget is injected by an external script at
           z-index 2147483647, the maximum 32-bit integer, so nothing can ever be
           stacked above it - measured here, the full-height mobile panel ran straight
           through it and the green circle painted over the Customer service rows. The
           design contract records this for .wc-langbar; it applies to any floating
           panel. The measured footprint (60x60, 80px from the bottom) does not match
           the documented one (64x64, 120px), so the reserve clears the LARGER of the
           two plus a gap. overflow-y:auto is what keeps the rows reachable once the
           panel is capped.

           z-index is declared rather than left at auto. It cannot win against the
           widget above, but leaving it implicit meant the panel's stacking depended
           entirely on .hdr's context, which is fragile to reorder.

           Opening is driven ONLY by React state now. It used to also open on
           :hover and :focus-within, which meant the panel could be visible while
           aria-expanded was false - the arrow unrotated and a screen reader announcing
           it as collapsed. A mega panel appearing on an accidental mouse-over is also
           far more disruptive than a small dropdown was. */
        /* MAX-HEIGHT IS ANCHORED TO THE HEADER, and dvh rather than vh.
           It was calc(100vh - 320px). 320 corresponded to no element in this layout, and the
           failure needs a viewport that is WIDE and SHORT - rare on a phone or a laptop, and
           the normal shape of a folded-landscape device. Measured with the menu open:
             844x390  ->  70px of menu holding 700px of content
             880x360  ->  40px   (Z Flip 5, landscape)
             882x344  ->  24px   (Z Fold 5 cover, landscape)
             653x280  ->   0px   (Galaxy Fold folded, landscape) - the 32px box was padding
           Twenty links in a strip of chrome. 140 = the 108px header plus 32px of air, both
           nameable; dvh accounts for mobile browser chrome, the same unit fix index.tsx
           already made for .home-shell. Now: 280 -> 140px, 344 -> 204px, 360 -> 220px,
           390 -> 250px. See also the mobile override further down - BOTH carried a magic
           subtrahend and fixing only this one left the worst case untouched. */
        /* ANCHORED WITH A VARIABLE, for the specificity reason documented at length on
           .wc-langbar in SupportWidget.tsx. Short version: Lightning CSS rewrites any
           direction-conditional rule into a matched pair of :lang() rules, which adds a
           specificity class, so a logical inset here out-specified the mobile override below
           and pinned the panel to left:0 on phones where the media query asks for 16px.
           --nav-menu-inset is set once, overridden by the media query, and consumed by the
           two direction rules underneath.
           NO BACKTICKS IN THIS COMMENT: it sits inside a styled-jsx template literal, and a
           single backtick closes it - turning the rest of the stylesheet into JSX and failing
           the build hundreds of lines later with an unrelated-looking "Unexpected token". */
        /* Match the public checkout/auth card's rounded lime top accent without changing
           the menu's existing fill, shadow, positioning or scroll behavior. */
        .nav-menu{--nav-menu-inset:0px;position:absolute;top:calc(100% + 8px);left:var(--nav-menu-inset);right:auto;z-index:1002;width:min(760px,var(--nav-menu-available-width,760px));max-height:calc(100vh - 140px);max-height:calc(100dvh - 140px - var(--safe-bottom));overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;background:#fcfdfb;border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);border-radius:24px;padding:14px;opacity:0;visibility:hidden;transform:translateY(4px);transition:opacity .2s,transform .2s,visibility 0s linear .2s;box-shadow:0 8px 28px rgba(0,0,0,.10)}
        .nav-menu.open{opacity:1;visibility:visible;transform:translateY(0);transition:opacity .2s,transform .2s,visibility 0s}

        /* Search field. Sized off the language panel's input rather than a new set of
           numbers - same 42px row, same 10px radius, same focus ring - so the two
           search fields on the site are recognisably the same control. */
        /* THE SITE-WIDE SEARCH LOOK: borderless bottom hairline plus the shared lime voice mic. */
        .nav-search-field{position:relative;margin:0 0 12px}
        .nav-search{width:100%;margin:0;min-height:44px;box-sizing:border-box;border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;background:transparent;padding:0 44px 0 2px;font-size:16px;font-weight:400;line-height:1.3;color:var(--public-body);font-family:inherit;outline:none;transition:border-color .2s,box-shadow .2s}
        .nav-search::placeholder{color:rgba(0,0,0,.42)}
        .nav-search:focus-visible{border-bottom-color:var(--public-brand-green);box-shadow:0 1px 0 0 var(--public-brand-lime)}

        /* Three equal columns with minmax(0,1fr) rather than 1fr: a bare 1fr uses
           min-content as its floor, so "Request Amendment" would force its column
           wider than a third and push the others narrow. */
        .nav-cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px 20px;align-items:start}
        .nav-col{display:flex;flex-direction:column;gap:10px;min-width:0}
        .nav-results{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:2px 20px}

        /* 12px/500 muted, matching the language panel's group label. A heading over
           menu items must read as a category and not as a disabled item, which is why
           it is well below the 19px the items themselves use. */
        .nav-group{display:flex;flex-direction:column}
        /* Section labels read as headers, not as faint disabled rows. They were
           rgba(0,0,0,.42) grey, weight 500, text-transform:none - so "Products",
           "Legal Stuff" etc. blended into the item names below them. Now #1a3a2a
           (the brand's deep green, NOT the grassy #3da35a a first pass used - that
           bright green clashed with the palette), weight 700, UPPERCASE, with a
           touch more tracking so the caps stay legible. */
        .nav-group-label{display:flex;align-items:center;gap:7px;padding:6px 12px 4px;font-size:12px;font-weight:700;letter-spacing:.06em;color:var(--public-brand-green);text-transform:uppercase}
        /* One optical heading-icon rung. Custom SVGs fill their viewBox more tightly than
           Material Symbols, so both reserve 18px while the symbol itself renders at 20px.
           This makes neurology read at the same visual weight as Products, Request, Extras,
           Contact and Legal Stuff instead of looking undersized beside the label. */
        .nav-section-icon{width:18px;height:18px;flex:0 0 18px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
        .nav-section-icon-material{fill:currentColor;stroke:none}
        .nav-section-material-symbol{
          width:18px;height:18px;flex:0 0 18px;display:inline-flex;align-items:center;justify-content:center;
          font-family:'Material Symbols Rounded';font-size:20px;font-weight:400;line-height:1;
          letter-spacing:normal;text-transform:none;white-space:nowrap;
          font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 20;
        }

        /* PRODUCTS SCROLL. The catalogue is meant to reach 100+ entries, so Products
           keeps its own capped rail on desktop AND mobile. Desktop shows seven 46px rows;
           mobile shows seven 52px rows. On mobile the vertical scroll chain stays AUTO so a
           swipe can continue into the main menu after the Products rail reaches its end. */
        .nav-group-products{min-height:0}
        /* The heading stays PINNED above its own scrolling list. Sticky against the
           scroll container's top; the #fcfdfb backer stops list rows showing through the
           label as they pass under it. z-index clears the rows. */
        .nav-group-products .nav-group-label{position:sticky;top:0;z-index:2;background:#fcfdfb}
        .nav-products-scroll{
          /* Seven desktop rows. Mobile overrides only the row-height-derived ceiling
             (7 x 52px = 364px); the same overflow rail and continuation cue stay active. */
          max-height:322px;
          overflow-y:auto;
          -webkit-overflow-scrolling:touch;
          /* Contain the scroll chain so flicking the product list to its end does not
             then scroll the page behind the menu. */
          overscroll-behavior:contain;
          /* FULL COLUMN WIDTH so the lime scrollbar aligns with the right edge of the
             Home tab above it, plus a FAINT LIME TINT BOX so the bar reads as anchored to
             this list rather than floating in the empty space right of the short product
             names. The product labels are much narrower than the column, so a bare
             full-width bar looked detached; the tint (rgba(209,244,112,.08)) and the 10px
             radius give the scroll area a subtle surface the bar belongs to. This is the
             one place a background is used - it earns it because this is the only
             scrolling group; the static columns stay plain. */
          width:100%;
          padding:4px 8px 4px 0;
          background:rgba(209,244,112,.08);
          border-radius:10px;
          /* scrollbar-width STAYS and the colour does NOT. Gecko does not inherit
             scrollbar-width and the canonical block in src/styles/inner-ux.css declares it on
             html only, so dropping this line hands Firefox a system-default gutter inside the
             nav group. A LIME-THEMED SCROLLBAR WAS DELETED HERE: the Gecko half
             (scrollbar-color, a lime thumb on a transparent track) and the Blink half (four
             .nav-products-scroll::-webkit-scrollbar* rules, lime thumb, darker-lime hover,
             8px wide). A lime thumb is 1.18:1 on its own track, far under the 3:1 WCAG 1.4.11
             asks of a control boundary, and this nav mounts on every public page. The brand
             shows in the TRACK; the thumb is the --scrollbar-thumb token. Do not restore
             either half - src/test/ScrollbarDeclarations.test.ts pins the file set. */
          scrollbar-width:thin;
        }
        /* GOOGLE DOUBLE-DOWN CUE. The exact path comes from the Google Material icon supplied
           for this change. It lives in a dedicated row BELOW the scrolling list instead of
           floating over it, so product names can never sit underneath the affordance.
           The button keeps a 44px interaction target while the visible icon stays only 24px.
           There is no pill, circle, label or shadow: just the double chevron. */
        .nav-products-cue-row{height:46px;display:flex;align-items:center;justify-content:flex-end;flex:0 0 46px;margin-top:6px;padding-inline-end:4px;box-sizing:border-box}
        .nav-products-cue-row.is-hidden{visibility:hidden;pointer-events:none}
        .nav-products-more{display:flex;align-items:center;justify-content:center;width:46px;height:46px;min-width:46px;min-height:46px;padding:0;border:0;border-radius:50%;background:var(--public-brand-lime);color:#0f2a1d;cursor:pointer;transition:background-color .16s ease,transform .16s ease,box-shadow .16s ease}
        .nav-products-more:hover{background:#c5ed51;transform:translateY(-1px) scale(1.06);box-shadow:0 4px 12px rgba(26,58,42,.16)}
        .nav-products-more:focus-visible{outline:none;box-shadow:0 0 0 2px #fff,0 0 0 5px #1a3a2a}
        .nav-products-more-icon{display:block;width:31px;height:31px;fill:currentColor;transform:scaleX(1.08);transform-origin:center}
        /* The Customer service heading is a link, so it needs an affordance the plain
           headings do not have - without one it looks like the same inert label. */
        .nav-group-link{color:var(--public-brand-green);text-decoration:none;border-radius:8px}
        /* Split, same reason as .lgd-toc-link: this was one rule giving hover and
           focus-visible the same lime tint plus outline:none, so a keyboard user's only
           focus cue was a tint that composites to rgb(245,253,224) over white. The tint is
           a pointer affordance on hover; focus needs a ring that measures 3:1, and opaque
           #1a3a2a on the panel is 12.48:1. */
        .nav-group-link:hover{background:var(--public-lime-tint)}
        .nav-group-link:focus-visible{background:var(--public-lime-tint);outline:3px solid var(--public-brand-green);outline-offset:1px}
        .nav-empty{margin:0;padding:10px 12px 12px;font-size:14px;color:var(--public-muted)}
        .nav-search-status{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}

        /* 15px/46px was undersized against a 108px header and a 24px brand lockup,
           and it sat below the 16-17px the global .nav-item rules use for the same
           control elsewhere. 19px puts the type-to-row ratio at ~2.8, near the
           2.5-ish a notion-style menu sits at, and keeps a deliberate step down from
           the 24px brand lockup instead of near-matching it.
           Nothing global was fighting this: the styled-jsx rule carries a jsx class,
           so it beats Layout.css's plain .nav-item on specificity, and
           inner-pages.css's .layout .nav-item block is empty and out of scope for the
           public header anyway.
           The row is 46px here, not the 54px of the old single column: three columns
           of 19px rows at 54px made the panel taller than the Customer service list needs,
           and 46px still clears the 44px minimum touch target. */
        /* position:relative so the divider hairline and the animated sweep (::after /
           ::before below) can be absolutely positioned within each row. */
        .nav-item{position:relative;display:flex;align-items:center;gap:9px;min-height:46px;padding:0 12px;font-size:19px;font-weight:600;color:var(--public-brand-green);text-decoration:none;border-radius:8px}
        .nav-row-icon,.nav-sub-icon,.nav-row-chevron{fill:none;stroke:currentColor;stroke-linecap:round;stroke-linejoin:round}
        .nav-row-icon{width:20px;height:20px;flex:0 0 20px;stroke-width:1.9}
        .nav-row-icon-material{fill:currentColor;stroke:none}
        /* The location_on pin fills most of its 48px viewBox. A slight optical scale
           balances it with other 20px menu icons without moving the row label. */
        .nav-item[href="/contact/"] .nav-row-icon-material{transform:scale(1.15);transform-origin:center}
        .nav-row-material-symbol{
          width:20px;height:20px;flex:0 0 20px;display:inline-flex;align-items:center;justify-content:center;
          font-family:'Material Symbols Rounded';font-size:21px;font-weight:400;line-height:1;
          letter-spacing:normal;text-transform:none;white-space:nowrap;
          font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24;
        }
        .nav-sub-icon{width:17px;height:17px;flex:0 0 17px;stroke-width:1.8;opacity:.82}
        .nav-row-chevron{width:17px;height:17px;flex:0 0 17px;margin-inline-start:auto;stroke-width:1.9;opacity:.72}
        .nav-item-label{min-width:0;white-space:nowrap}
        /* ACTIVE AND HOVER MUST READ AS DIFFERENT STATES. They were both the same
           rgba(209,244,112,.22) pale tint, so the current page ("you are here") looked
           identical to whatever row the mouse was over - you could not tell which page
           you were on. Hover/focus is now a stronger-but-still-transparent tint (.38);
           the active row is SOLID #d1f470 with #0f2a1d type, which is the palette's
           own-surface treatment (.msg.sent, .tab.active) and unmistakably marks the
           current page. */
        /* Split, same reason. .38 is a stronger tint than the .22 above but still only
           reaches rgb(238,251,201) over white - darker than nothing, nowhere near 3:1, and
           outline:none removed the fallback. Tint on hover, opaque ring on focus. */
        .nav-item:not(.active):hover{background:rgba(209,244,112,.38)}
        .nav-item:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:1px}.nav-item:not(.active):focus-visible{background:rgba(209,244,112,.38)}
        .nav-item.active{font-weight:800;background:var(--public-brand-lime);color:#0f2a1d}
        /* DIVIDER LINE AFTER EACH ROW + a lime SWEEP on hover.
           ::after is the faint resting hairline (#f1f3ec - deliberately very light, so it
           separates rows without drawing attention). ::before is the lime accent that
           SWEEPS in on hover: scaleX(0)->(1) from the left, 0.2s, so a thin lime line
           draws left-to-right under the row. Inset 12px each side to line up with the row
           padding. Reduced-motion users get the end state with no transition. */
        /* inset-inline:12px collapses the symmetric pair. The ::before underline reveal grows
           with scaleX from transform-origin, which has no logical keyword, so the rtl case is
           stated explicitly - otherwise the underline would wipe in from the end of the line
           a right-to-left reader finishes on, reading as a retreat rather than a reveal. */
        .nav-item::after{content:'';position:absolute;inset-inline:12px;bottom:0;height:1px;background:linear-gradient(90deg,transparent 0,#e5eadc 12%,#e5eadc 88%,transparent 100%)}
        .nav-item::before{content:'';position:absolute;inset-inline:12px;bottom:0;height:2px;background:var(--public-brand-lime);opacity:0;transform:scaleX(.16);transform-origin:left center;transition:transform .22s cubic-bezier(.16,1,.3,1),opacity .14s ease}
        :global([dir='rtl']) .nav-item::before{transform-origin:right center}
        /* The desktop panel hangs off its trigger, so under rtl it has to hang off the other
           edge. Paired with the --nav-menu-inset base rule above. */
        :global([dir='rtl']) .nav-menu{left:auto;right:var(--nav-menu-inset)}
        .nav-item:not(.active):hover::before,.nav-item:not(.active):focus-visible::before{opacity:1;transform:scaleX(1)}
        /* The last row in a group has nothing after it, so no divider. */
        .nav-group > .nav-item:last-child::after,.nav-tree-item:last-child > .nav-item:last-child::after{display:none}
        @media(prefers-reduced-motion:reduce){.nav-item::before{transition:none}}
        /* Family children use the exact same 19px/600 navigation typography as their
           parent. Hierarchy is expressed by grouping and indentation, never smaller text. */
        .nav-tree-item.has-children + .nav-tree-item{margin-top:6px}
        .nav-family-label{cursor:default}
        .nav-child{font-size:19px;font-weight:600;min-height:46px;padding-inline-start:24px;gap:8px}

        /* The panel breaks to fewer columns before the columns get too narrow to hold
           "Request Amendment" on one line. Measured rather than guessed: at 19px/17px
           the widest label needs ~210px of row, so three columns stop fitting inside
           the 1252px measure once the viewport is under ~820px. */
        @media(max-width:1024px){.nav-cols,.nav-results{grid-template-columns:repeat(2,minmax(0,1fr))}}
        /* NOTE: .hdr-in must stay the first rule inside this media query - Header.test
           asserts the literal string "@media(max-width:767px){.hdr-in{height:96px".
           Below 768px the panel is a single scrolling column pinned to the viewport
           with a 16px gutter, sitting just under the 96px mobile header. max-height
           plus overflow-y is what stops twelve rows running off the bottom of a
           phone - the old six-item dropdown never needed it. */
        /* The mobile panel spans the viewport, so it sets BOTH insets rather than the
           variable - symmetric, therefore direction-neutral, therefore no rtl override
           needed. It still has to beat the base rule's compiled :lang() selector, which the
           extra .hdr-in ancestor class does. */
        @media(max-width:767px){.hdr-in{height:96px;padding:14px 16px}.logo-nav{gap:8px}.hdr-in .nav-menu{position:fixed;top:100px;left:max(16px,var(--safe-left));right:max(16px,var(--safe-right));width:calc(100vw - max(16px,var(--safe-left)) - max(16px,var(--safe-right)));max-width:none;box-sizing:border-box;max-height:calc(100vh - 140px);max-height:calc(100dvh - 140px - var(--safe-bottom))}.nav-cols,.nav-results{grid-template-columns:minmax(0,1fr)}.nav-item,.nav-child{font-size:20px;font-weight:600;min-height:52px}.nav-products-scroll{max-height:364px;overflow-y:auto;overscroll-behavior:auto}.nav-products-cue-row{height:44px;flex-basis:44px;margin-top:4px}.nav-products-more{width:44px;height:44px;min-width:44px;min-height:44px}}

        /* ROOM FOR THE SHOPPING BAG ON THE NARROWEST DEVICE THAT SHIPS, derived rather than
           nudged. Measured on the built header at 280px (Galaxy Fold, folded) before the bag
           existed: the 16px gutter leaves a 248px content box, and .logo-nav occupies 212.8px of
           it, so 35.2px remained - 8.8px short of the 44px tap target devicecheck.js enforces on
           every header control.
           10px of gutter returns 12px and a 6px .logo-nav gap returns 2px, giving 49.2px: a 44px
           chip with 5.2px of air beside the menu trigger. Neither height moves, and the trigger
           stays 46x46 at border-box - both re-measured after this change.
           340px is RotatingHero's own narrow rung, reused so the site has one narrow breakpoint
           rather than a new one invented for the header. 344px (Z Fold cover) is above it and
           keeps the full 16px gutter, which is why the ceiling is 340 and not 360.
           padding-inline is symmetric, so Lightning CSS emits a plain left/right pair with no
           :lang() specificity class - it cannot out-specify the 767px rule above it, which is the
           trap documented on .nav-menu. */
        @media(max-width:340px){
          .hdr-in{padding-inline:10px}
          .logo-nav{gap:6px}
          /* Keep every destination on one line at the narrow Fold width. The row icon is
             decorative; dropping it here returns the width to the label instead of wrapping
             a navigation destination into two lines. 17px preserves the hierarchy while
             fitting the longest current label. */
          .nav-row-icon,.nav-row-material-symbol,.nav-sub-icon{display:none}
          .nav-item,.nav-child{font-size:18px;padding-inline:10px}
        }

        @media(prefers-reduced-motion:reduce){
          .nav-menu{transition:none}
          .nav-trigger-icon{transition:none}
          .nav-products-more{transition:none}
        }
      `}</style>
    </header>
  );
};

export default Header;