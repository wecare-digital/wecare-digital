import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import BrandLockup from './BrandLockup';
import HeaderCart from './HeaderCart';
import { PRODUCTS } from '../content/products';

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
  href: string;
  /** router.pathname value that marks this link as the current page. */
  match?: string;
  /** True for absolute URLs off this app. Same tab either way. No nav row uses it now:
   *  the two that did pointed at www.wecare.digital paths that both 404. */
  external?: boolean;
}

interface NavSection {
  /** '' renders the links with no heading above them. */
  heading: string;
  /** When set, the heading itself is a link. Used by Customer service, which is both a
   *  real destination and the parent of the rows beneath it. */
  headingHref?: string;
  links: NavLink[];
}

/** One column of the mega menu. Columns may hold more than one section. */
interface NavColumn {
  sections: NavSection[];
}

// BOTH OF THESE USED TO BE ABSOLUTE URLS ON www.wecare.digital, AND BOTH RETURNED 404
// ON EVERY PUBLIC PAGE. Measured: [retired public path] -> 404 and /product-page/referral-partner
// -> 404, on both the apex and the www host. That domain serves THIS Next.js app, which
// has no [retired public path] route and no Wix /product-page/* routes - the Wix storefront those
// paths assumed is not published there. The referral-partner PRODUCT is real (it exists in
// the Wix catalog at 999.00); only the URL was wrong.
// They now point at routes that exist and return 200. [retired public path]/ and its three children are
// real exported pages that were simply never wired into this menu.

// EVERY ROW NOW HAS ITS OWN PAGE, and the placeholder that stood here is gone with the
// constants it defined.
//
// What it said: every Customer service child pointed at /contact/, chosen over href="#" or an
// invented path so that each row at least worked. The consequence, measured on the built
// home page, was six distinct labels - Submit Request, Request Amendment, Drop Docs, Leave
// Review, Refer & Earn and Contact us - resolving to one destination, on all 872 documents.
// The menu made six promises and kept one.
//
// That note also named the way out, and this is it: public pages, registered in
// PUBLIC_PAGE_META. Copy lives in src/content/customerservice.ts, layout in ProductPage.tsx -
// the same shape the seven product pages use, so twelve pages cannot drift apart. Contact us
// keeps /contact/, which is its real destination, so five pages were needed rather than six.
//
// STILL NOT [retired public path]/*, AND THAT PART OF THE OLD NOTE STANDS. Those routes exist and return
// 200, and an earlier pass wired these rows to them, which was wrong: service/index.tsx
// renders <Layout user onSignOut> and submit-request.tsx reads the requester from
// user?.signInDetails?.loginId. None is in PUBLIC_PAGE_META, so _app.tsx wraps them in the
// Authenticator and a public row pointing there shows an anonymous visitor a login wall.
// Measured: out/service/submit-request/index.html was 144,800 bytes of auth shell against
// 35,738 for public /contact/. The new pages touch neither Layout nor a session.
//
// The current mapping, for the record:
//   Submit Request     -> /submit-request/
//   Request Amendment  -> /request-amendment/
//   Orders             -> /orders/
//   Drop Docs          -> /drop-docs/
//   Leave Review       -> /leave-review/
//   Subscribe          -> /subscribe/
//   Refer & Earn       -> /refer-and-earn/
//   Contact us         -> /contact/
//
// Header.test.tsx asserts all eight rows exist, so a typo here cannot silently drop one.

// One structure, rendered as columns, rather than the single flat list this used to
// be. The Customer service group is why: seven children under one parent made a
// single-column dropdown roughly 700px tall, past the bottom of a laptop viewport.
//
// Trailing slashes are load-bearing on the static pages: next.config.js sets
// trailingSlash, so /vayulok would redirect before resolving. Staff access belongs
// inside /workspace/ and is deliberately absent from this public menu.
//
// The external entries carry no target, so they open in the SAME tab. That is the
// default for a plain anchor, so it is the ABSENCE of an attribute doing the work -
// do not "fix" it by adding target, and note rel="noopener" would be inert without
// one. They also carry no `match`: it is compared against router.pathname, which can
// never equal an absolute URL.
const COLUMNS: NavColumn[] = [
  {
    sections: [
      // HOME, in the unlabelled group at the top of the menu, because it is the one
      // whole-site destination rather than a member of a category.
      //
      // SHOP JOINS IT, DIRECTLY AFTER, by that same rule: /shop/ lists every product and every
      // service on one page, so it is an index ACROSS the categories rather than a member of one.
      // It is the 'start' group in STRUCTURAL too, beside /, /contact and /blog.
      // Not the Products group: that is generated from PRODUCTS, it scrolls, and an index sitting
      // inside one category reads as a product named Shop. Not the Request group either - Shop is
      // not a request action, and Header.test.tsx pins that group's exact label order as an owner
      // instruction.
      // The trailing slash on href is load-bearing (trailingSlash is set, so /shop 308s before
      // resolving); `match` is slashless because it is compared against router.pathname, and that
      // comparison is strict equality, so the row does not light up on /shop/[slug] or
      // /shop/page/[page] - which is how every other row in this menu behaves.
      { heading: '', links: [
        { label: 'Home', href: '/', match: '/' },
        { label: 'Shop', href: '/shop/', match: '/shop' },
      ] },
      {
        heading: 'Products',
        links: [
          { label: 'Grahak OS', href: '/grahak-os/', match: '/grahak-os' },
          { label: 'VayuLok', href: '/vayulok/', match: '/vayulok' },
          // Bharat Rx moved here from Customer service: it is a product, not one of the
          // request actions the Customer service column lists. It now has its own page, so it
          // is a local route with `match` rather than a PENDING_HREF placeholder - a
          // product listed beside Grahak OS and VayuLok that landed on a generic
          // marketing page was worse than not listing it.
          { label: 'Bharat Rx', href: '/bharat-rx/', match: '/bharat-rx' },
          // GENERATED FROM src/content/products.ts, not retyped. Eleven products across a
          // menu, a sitemap allowlist, a structured-data map and eight route files is four
          // places a name or a slug can disagree; mapping the same array means the menu
          // cannot list a product that has no page, or miss one that does. Hunar was added
          // by a single entry in that file and appeared here on its own.
          ...PRODUCTS.map( p => ( {
            label: p.name,
            href: `/${p.slug}/`,
            match: `/${p.slug}`,
          } ) ),
        ],
      },
    ],
  },
  {
    sections: [
      {
        // NO headingHref. "Customer service" is a group label now, not a destination - the
        // owner's instruction is that there is no Customer service page, only the items under
        // it. It previously linked to the external landing page, which made the heading
        // both a category and a link and gave a visitor two things to click for one idea.
        // Renamed from 'Customer service' on 2026-09-27 (owner instruction: remove the word
        // everywhere it is customer-visible). It named a portal that has no page at any
        // address - the in-repo [retired public path] route went in PR #47 on 2026-09-24 and nothing
        // replaced it, so the label promised a destination that did not exist. The only
        // [retired public path] route left is the ADMIN flow dashboard under /workspace/forms/.
        // 'Requests' described what the rows beneath it do; the owner's instruction (Section 1)
        // is the singular 'Request' as the exact customer-facing label, and never 'Get Help',
        // 'Customer-Service', 'Customer service' or 'Help Hub'. This is a label change only - no internal
        // `customerservice` identifier, config/public-pages.json group id, workspace route, provider
        // template, API or historical integration id is touched.
        heading: 'Request',
        links: [
          // ORDERS IS FIRST, on owner instruction - it is the row customers reach for
          // most, and it is the one real local page in this group (the others land on
          // /contact for now), so it leads. It carries `match` and lights up on its own
          // route. It REPLACES the old "Request Tracking" row - the two answer the
          // same question, and offering both sends one visitor to two places for one answer.
          //
          // RENAMED FROM "My Order" -> "Orders" AND [retired public path]/ -> /orders/, on owner
          // instruction, label and URL in the same change. `match` stays the slashless form
          // because it is compared against router.pathname; `href` keeps the trailing slash or
          // the static host 308s before resolving. The old path 301s here - see RETIRED in
          // scripts/provision_legacy_redirects.py.
          { label: 'Orders', href: '/orders/', match: '/orders' },
          // FAQ removed on request. The local [retired public path] page was already deleted; this
          // drops the menu row too, so there is no FAQ entry point left anywhere.
          // EACH ROW NOW HAS ITS OWN PAGE. These four, plus Refer & Earn below, used to
          // resolve to /contact/ - six labels, one destination, on every page of the site.
          // They are public pages registered in PUBLIC_PAGE_META, NOT the authenticated
          // [retired public path]/* routes: those render the dashboard Layout behind a Cognito session,
          // so a public row pointing there shows an anonymous visitor a login wall.
          { label: 'Submit Request', href: '/submit-request/', match: '/submit-request' },
          { label: 'Request Amendment', href: '/request-amendment/', match: '/request-amendment' },
          { label: 'Drop Docs', href: '/drop-docs/', match: '/drop-docs' },
          // VAULT SITS DIRECTLY BELOW DROP DOCS because it is the same door in the other
          // direction - Drop Docs sends paperwork in, Vault asks for a copy back out - and
          // the pair only reads that way when the rows are adjacent.
          //
          // IT HAD TO BE TYPED HERE, unlike the products above. This group's rows are
          // written out rather than mapped from src/content/customerservice.ts, so an entry in
          // that file alone gives Vault a page and a sitemap line but no way to reach it
          // from the menu. If Vault ever goes missing from the nav, this list is why.
          { label: 'Vault', href: '/vault/', match: '/vault' },
          // REQUEST PICKUP FOLLOWS VAULT, completing the paperwork trio: in, out, collected.
          // TYPED HERE BY HAND for the same reason as the row above - this group's rows are
          // written out rather than mapped from src/content/customerservice.ts, so the content
          // entry alone would give it a page and a sitemap line and no way to reach it from the
          // menu. If Request Pickup ever goes missing from the nav, this list is why.
          { label: 'Request Pickup', href: '/request-pickup/', match: '/request-pickup' },
          // SHIPMENTS SITS DIRECTLY ABOVE LEAVE REVIEW, on owner instruction: it is the single
          // place that gathers "track it, arrange it, keep it moving" for a request, delivery or
          // pickup, so it rounds out the request actions just before Leave Review (which was the
          // last row until Subscribe was added after it, below). THE ROUTE MOVED FROM /zip/ TO /shipments/ on owner instruction
          // (2026-10-02): the page was called "Zip" and the name is gone everywhere, not just on
          // the label. The earlier change renamed only this label and left the route, the
          // PUBLIC_PAGE_META `name` ('Zip') and the legal copy intact, which is why the owner kept
          // seeing "Zip" on the live site. The sitemap PUBLIC_EXACT entry,
          // config/public-pages.json, the PUBLIC_PAGE_META key and scripts/generate-public-pages.js
          // all moved with it. NOTE: /zip/ 404s at the origin until a CDN redirect
          // /zip/ -> /shipments/ is added in the Amplify Console - a static export cannot emit a
          // 301 (see the RETIRED URLS note in _app.tsx). It carries `match` and lights up on its
          // own route. It surfaces the real request routes (orders, request-amendment, drop-docs,
          // vault, leave-review) and renders anything with no backend (pickup/visit/
          // delivery-status) as a clearly non-transacting affordance.
          { label: 'Shipments', href: '/shipments/', match: '/shipments' },
          { label: 'Leave Review', href: '/leave-review/', match: '/leave-review' },
          // SUBSCRIBE SITS DIRECTLY AFTER LEAVE REVIEW AND IS NOW THE LAST ROW, on owner
          // instruction (2026-10-09). This supersedes the earlier rule that Leave Review stays
          // last. Route /subscribe/ is registered in PUBLIC_PAGE_META (_app.tsx), PUBLIC_EXACT
          // (scripts/generate-sitemap.js) and STRUCTURAL (scripts/generate-public-pages.js). Its
          // CTA goes to /contact/ until the subscription backend exists. `match` is slashless
          // because it is compared against router.pathname; `href` keeps the trailing slash.
          { label: 'Subscribe', href: '/subscribe/', match: '/subscribe' },
          // CONTACT MOVED OUT of Customer service into the third column (Work with us), on
          // owner instruction - the Customer service column is now the request ACTIONS only,
          // and Contact sits with Refer & Earn as a way to reach the company.
        ],
      },
    ],
  },
  {
    sections: [
      // "Work with us", NOT "Company" - that word was explicitly retired from this
      // menu, and restructuring into columns nearly reintroduced it. Not "Service"
      // either: that would sit one column away from "Customer service" and read as the
      // same category. This heading says who the column is for, which is the honest
      // distinction - Customer service is for existing customers, this is for prospective
      // referral partners.
      // "Refer & Earn", not "Partners", on instruction. It is also the better label: it says
      // what you get rather than what you become, and the destination is the referral-partner
      // product page.
      // Now a LOCAL page rather than an external link, so it carries `match` and lights up
      // on its own route like every other row.
      { heading: 'Work with us', links: [ { label: 'Refer & Earn', href: '/refer-and-earn/', match: '/refer-and-earn' } ] },
      // CONTACT HAS ITS OWN HEADING now, on owner instruction, rather than sitting as a
      // second row under Work with us. It is its own thing - a way to reach us - so it
      // gets its own labelled group in this column. Local page, so it carries `match`
      // and lights up on /contact; the trailing slash is load-bearing (trailingSlash is
      // set, so /contact would redirect before resolving).
      { heading: 'Contact', links: [ { label: 'Contact us', href: '/contact/', match: '/contact' } ] },
      // LEGAL STUFF LIVES HERE NOW, under Work with us. It moved out of the middle
      // column (where it sat beneath Customer service) on owner instruction, so the third
      // column carries the "about the company" rows - Refer & Earn plus the policies -
      // and the middle column is purely the Customer service actions.
      // EXTRAS SITS IMMEDIATELY ABOVE LEGAL STUFF, on owner instruction (Section 4). The GROUP
      // HEADING is the category ("Extras"); the ROW is the page's own name, "Perks".
      // THE ROW READ "Extras" UNDER A HEADING THAT ALSO READ "Extras" — the word printed twice,
      // one directly beneath the other, which the owner reported as looking broken (2026-10-02).
      // An earlier instruction had renamed the page Perks -> Extras; the owner has reversed that,
      // so the page's customer-facing name is "Perks" again and the row says "Perks".
      // The ROUTE/URL stays /perks/ (src/pages/perks.tsx keeps its filename, so the live URL, the
      // sitemap PUBLIC_EXACT, config/public-pages.json, PUBLIC_PAGE_META and the gift-card CTAs in
      // the WhatsApp/AI/SEO handlers that point at https://wecare.digital/perks/ all keep resolving
      // — and the route already matches the name "Perks", so there is nothing to rename there).
      // The group once carried three ANCHOR rows into /perks (Gift Cards -> #gift-cards, Rewards ->
      // #rewards, Offers -> #offers). The owner then asked to REMOVE those gift-card / offers /
      // rewards sections from the page, so those anchors no longer exist. Rather than leave nav
      // rows pointing at dead #gift-cards/#rewards/#offers anchors, the group is collapsed to a
      // single link to the /perks/ page itself. The several systems that link customers to a
      // gift-card URL already point at https://wecare.digital/perks/ (the page, not an anchor), so
      // they still resolve. No third-party gift-card provider name ('Gift Up'/'GiftUp'/any vendor)
      // appears here or on the page. The /perks page is a home-styled, non-transacting landing
      // page; it carries no working-looking buy/redeem/check-balance control.
      {
        heading: 'Extras',
        links: [
          { label: 'Perks', href: '/perks/', match: '/perks' },
        ],
      },
      {
        heading: 'Legal Stuff',
        links: [
          { label: 'Terms', href: '/terms/', match: '/terms' },
          { label: 'Privacy', href: '/privacy/', match: '/privacy' },
        ],
      },
      // ACCOUNT / SIGN IN REMOVED from the public menu on owner instruction. That "Sign
      // in" pointed at [retired public path], which is the INTERNAL staff dashboard login (Cognito) -
      // it does not belong in the public navigation. A fresh, customer-facing login
      // (WhatsApp OTP, SMS/email fallback) will live on the /orders page instead, so
      // there is deliberately no sign-in row here now.
    ],
  },
];

const Header: React.FC = () => {
  const [ open, setOpen ] = useState( false );
  const [ query, setQuery ] = useState( '' );
  const router = useRouter();
  const rootRef = useRef<HTMLDivElement | null>( null );
  const triggerRef = useRef<HTMLButtonElement | null>( null );
  const hasOpened = useRef( false );

  const term = query.trim().toLocaleLowerCase();
  const searching = term.length > 0;

  // Flattened once, from the same structure the columns render, so a link can never
  // exist in the menu but be missing from search.
  const allLinks = useMemo( () => COLUMNS.flatMap( column => column.sections.flatMap( section => (
    section.headingHref
      ? [ { label: section.heading, href: section.headingHref, external: true }, ...section.links ]
      : section.links
  ) ) ), [] );

  const filtered = useMemo( () => (
    searching ? allLinks.filter( link => link.label.toLocaleLowerCase().includes( term ) ) : allLinks
  ), [ allLinks, searching, term ] );

  const close = () => { setOpen( false ); setQuery( '' ); };

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
  }, [ open ] );

  // Focus returns to the trigger on close, so a keyboard user is not dropped onto
  // <body> and made to tab from the top of the document again.
  useEffect( () => {
    if ( open ) { hasOpened.current = true; return; }
    if ( hasOpened.current ) triggerRef.current?.focus();
  }, [ open ] );

  // Driven off router.pathname, which carries no trailing slash even though the
  // hrefs do - hence the separate `match` field.
  //
  // This returns a BOOLEAN, and className is written inline on each anchor, on
  // purpose. Returning a props object and spreading it silently broke the whole
  // menu: styled-jsx appends its own className attribute AFTER a spread, so the
  // spread's className lost and every anchor exported as class="jsx-hash" with no
  // nav-item on it at all - no padding, no row height, no hover, no active weight.
  // The 33 unit tests still passed, because they assert role, name and href and
  // never look at classes. Only reading the built HTML caught it.
  const isActive = ( link: NavLink ) => link.match !== undefined && router.pathname === link.match;

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
  // megamenu.js now asserts computed font-size, weight and the active background so
  // this cannot recur silently.

  return (
    <header className="hdr">
      <div className="hdr-in">
        <div className="logo-nav">
          {/* Plain <a>, not next/link, for the same styled-jsx reason as Footer's lockup:
              styled-jsx does not scope capitalised components, so `<Link className="logo">`
              renders with no styles at all. Recorded in
              `.kiro/steering/grahak-os-design.md`. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/" className="logo" aria-label="WECARE.DIGITAL home">
            <BrandLockup />
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
              onClick={ () => { setOpen( value => !value ); setQuery( '' ); } }
            >
              <span className="nav-arrow" aria-hidden="true" />
            </button>
            <nav className={ `nav-menu ${open ? 'open' : ''}` } aria-label="Public navigation">
              {/* Not autofocused. The language panel autofocuses its search because
                  searching is the only way to use it, but this menu is readable at a
                  glance - popping the on-screen keyboard over the whole catalogue on a
                  phone would cost more than it saves. */}
              <input
                className="nav-search"
                type="search"
                value={ query }
                placeholder="Search"
                aria-label="Search navigation"
                onChange={ event => setQuery( event.target.value ) }
                onKeyDown={ event => { if ( event.key === 'Escape' ) close(); } }
              />

              {/* Flat results while searching: column headings over a filtered list
                  describe categories that are no longer all present, which reads as
                  missing items rather than as a narrowed list. */}
              { searching && (
                <div className="nav-results">
                  { filtered.map( link => (
                    <a
                      key={ link.label + link.href }
                      href={ link.href }
                      className={ `nav-item ${isActive( link ) ? 'active' : ''}`.trim() }
                      aria-current={ isActive( link ) ? 'page' : undefined }
                      onClick={ close }
                    >{ link.label }</a>
                  ) ) }
                  { !filtered.length && <p className="nav-empty">No matching page.</p> }
                </div>
              ) }

              { !searching && (
                <div className="nav-cols">
                  { COLUMNS.map( ( column, columnIndex ) => (
                    <div key={ columnIndex } className="nav-col">
                      { column.sections.map( ( section, sectionIndex ) => {
                        // The PRODUCTS section is the one that grows without bound - it is
                        // generated from src/content/products.ts and is meant to hold 100+
                        // entries eventually. So ONLY this section gets a capped, scrollable
                        // list with a pinned heading; every other section renders exactly as
                        // before. Matched by heading text rather than index so reordering the
                        // columns cannot silently move the scroll onto the wrong group.
                        const isProducts = section.heading === 'Products';
                        const label = section.heading && ( section.headingHref
                          ? (
                            // The heading is the parent destination as well as a label, so
                            // it is a link. Styled as a heading rather than as a row so the
                            // hierarchy still reads.
                            <a
                              href={ section.headingHref }
                              className="nav-group-label nav-group-link"
                              onClick={ close }
                            >{ section.heading }</a>
                          )
                          : <span className="nav-group-label">{ section.heading }</span>
                        );
                        const items = section.links.map( link => (
                          <a
                            key={ link.label + link.href }
                            href={ link.href }
                            className={ `nav-item ${section.headingHref ? 'nav-sub' : ''} ${isActive( link ) ? 'active' : ''}`.trim() }
                            aria-current={ isActive( link ) ? 'page' : undefined }
                            onClick={ close }
                          >{ link.label }</a>
                        ) );
                        return (
                          <div key={ section.heading || sectionIndex } className={ `nav-group ${isProducts ? 'nav-group-products' : ''}`.trim() }>
                            { label }
                            { isProducts
                              ? <div className="nav-products-scroll">{ items }</div>
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
        .hdr-in{max-width:1300px;margin:0 auto;padding:18px 24px;display:flex;align-items:center;box-sizing:border-box;height:108px}
        .logo{display:flex;align-items:center;text-decoration:none}
        .logo-nav{display:flex;align-items:center;gap:10px}
        .nav-dropdown{position:relative}
        /* SOFT NEUTRAL CHIP at rest, not a bare invisible button. It was
           background:none, so the chevron floated with no target - it read as
           decoration rather than a control. A soft #f4f7ee fill with a #e3ecc9
           hairline gives it a visible, tappable chip while staying quieter than the
           lime hover state below it. Hover/focus/expanded still brighten to the lime
           tint, so the interaction feedback is unchanged. */
        .nav-trigger{min-width:46px;min-height:46px;background:#f4f7ee;border:1px solid #e3ecc9;border-radius:10px;cursor:pointer;padding:8px;display:flex;align-items:center;justify-content:center;
          transition:background-color .18s ease,border-color .18s ease,border-width .18s ease}
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

           NOTHING ABOUT THE PANEL CHANGES. Its radius, fill and shadow are untouched: the owner's
           instruction was the icon only. */
        .nav-trigger{border-color:#cfe0a6}
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
          background:#d1f470;border-color:#1a3a2a;border-width:2px;outline:none;
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
        .nav-arrow{width:8px;height:8px;box-sizing:border-box;margin:0;border-right:3px solid #1a3a2a;border-bottom:3px solid #1a3a2a;opacity:1;transform:translateY(-2px) rotate(45deg);transition:transform .2s,border-color .18s ease,opacity .18s ease}
        .nav-trigger[aria-expanded='true'] .nav-arrow{transform:translateY(2px) rotate(225deg)}

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

           THAT 256 IS COUPLED TO THE BRAND LOCKUP'S WIDTH, and it has now been wrong
           twice. The panel's left edge is wherever the lockup plus the trigger ends:
           a first attempt reserved 176px from a guessed 152px offset and overflowed
           by 4px at 900px wide; measuring gave 180px, so it became 208; then the logo
           was sized up from 60px to 68px, the offset moved to 225px, and 208 overflowed
           again at 768-960px. 225 + 24px of gutter is 249, taken to 256.
           So: if BrandLockup's logo height or type size changes, THIS NUMBER MOVES.
           Re-measure it, do not nudge it - the width sweep in megamenu.js is what
           catches it, and it caught both of these.

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
        .nav-menu{--nav-menu-inset:0px;position:absolute;top:calc(100% + 8px);left:var(--nav-menu-inset);right:auto;z-index:1002;width:min(760px,calc(100vw - 256px));max-height:calc(100dvh - 140px);overflow-y:auto;-webkit-overflow-scrolling:touch;background:#fcfdfb;border:1px solid #e5e7eb;border-top:3px solid #d1f470;border-radius:14px;padding:14px;opacity:0;visibility:hidden;transform:translateY(4px);transition:opacity .2s,transform .2s,visibility 0s linear .2s;box-shadow:0 8px 28px rgba(0,0,0,.10)}
        .nav-menu.open{opacity:1;visibility:visible;transform:translateY(0);transition:opacity .2s,transform .2s,visibility 0s}

        /* Search field. Sized off the language panel's input rather than a new set of
           numbers - same 42px row, same 10px radius, same focus ring - so the two
           search fields on the site are recognisably the same control. */
        /* THE SITE-WIDE SEARCH LOOK: borderless, bottom hairline only, no icon, no box. The same
           field as the blog search (BlogSearch) and the Anew blog panel (ProductBlogPanel), so
           every search a visitor meets reads as one control. Transparent fill, 1px bottom
           hairline, and on focus the hairline darkens with a lime underline (WCAG 1.4.11 without
           a box). */
        .nav-search{width:100%;margin:0 0 12px;min-height:44px;box-sizing:border-box;border:0;border-bottom:1px solid #e5e7eb;border-radius:0;background:transparent;padding:0 2px;font-size:16px;font-weight:400;line-height:1.3;color:rgba(0,0,0,.898);font-family:inherit;outline:none;transition:border-color .2s,box-shadow .2s}
        .nav-search::placeholder{color:rgba(0,0,0,.42)}
        .nav-search:focus-visible{border-bottom-color:#1a3a2a;box-shadow:0 1px 0 0 #d1f470}

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
        .nav-group-label{display:block;padding:6px 12px 4px;font-size:12px;font-weight:700;letter-spacing:.06em;color:#1a3a2a;text-transform:uppercase}

        /* PRODUCTS SCROLL. Only the Products group. The catalogue is meant to reach 100+
           entries, so its list is capped and scrolls rather than making the whole panel
           grow past the viewport. With today's ~10 products it never scrolls - max-height
           is a ceiling, not a fixed height - so nothing changes until the list is long.
           Cap is ~6 rows (6 x 46px = 276px), kept deliberately short so the open menu
           stays compact. */
        .nav-group-products{min-height:0}
        /* The heading stays PINNED above its own scrolling list. Sticky against the
           scroll container's top; the #fcfdfb backer stops list rows showing through the
           label as they pass under it. z-index clears the rows. */
        .nav-group-products .nav-group-label{position:sticky;top:0;z-index:2;background:#fcfdfb}
        .nav-products-scroll{
          /* 5 rows. 5 x 46px = 230px, on owner instruction to keep the open menu short.
             This is a CEILING, not a fixed height: with fewer than 5 products the group
             is only as tall as its list and does not scroll. With today's ten products it
             does scroll, which is the accepted trade-off for a compact menu. */
          max-height:230px;
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
        /* The Customer service heading is a link, so it needs an affordance the plain
           headings do not have - without one it looks like the same inert label. */
        .nav-group-link{color:#1a3a2a;text-decoration:none;border-radius:8px}
        /* Split, same reason as .lgd-toc-link: this was one rule giving hover and
           focus-visible the same lime tint plus outline:none, so a keyboard user's only
           focus cue was a tint that composites to rgb(245,253,224) over white. The tint is
           a pointer affordance on hover; focus needs a ring that measures 3:1, and opaque
           #1a3a2a on the panel is 12.48:1. */
        .nav-group-link:hover{background:rgba(209,244,112,.22)}
        .nav-group-link:focus-visible{background:rgba(209,244,112,.22);outline:3px solid #1a3a2a;outline-offset:1px}
        .nav-empty{margin:0;padding:10px 12px 12px;font-size:14px;color:rgba(0,0,0,.54)}

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
        .nav-item{position:relative;display:flex;align-items:center;min-height:46px;padding:0 12px;font-size:19px;font-weight:600;color:#1a3a2a;text-decoration:none;border-radius:8px}
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
        .nav-item:hover{background:rgba(209,244,112,.38)}
        .nav-item:focus-visible{background:rgba(209,244,112,.38);outline:3px solid #1a3a2a;outline-offset:1px}
        .nav-item.active{font-weight:800;background:#d1f470;color:#0f2a1d}
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
        .nav-item::after{content:'';position:absolute;inset-inline:12px;bottom:0;height:1px;background:#f1f3ec}
        .nav-item::before{content:'';position:absolute;inset-inline:12px;bottom:0;height:2px;background:#d1f470;transform:scaleX(0);transform-origin:left center;transition:transform .2s cubic-bezier(.16,1,.3,1)}
        :global([dir='rtl']) .nav-item::before{transform-origin:right center}
        /* The desktop panel hangs off its trigger, so under rtl it has to hang off the other
           edge. Paired with the --nav-menu-inset base rule above. */
        :global([dir='rtl']) .nav-menu{left:auto;right:var(--nav-menu-inset)}
        .nav-item:hover::before,.nav-item:focus-visible::before{transform:scaleX(1)}
        /* The last row in a group has nothing after it, so no divider. */
        .nav-group .nav-item:last-child::after,.nav-products-scroll .nav-item:last-child::after{display:none}
        @media(prefers-reduced-motion:reduce){.nav-item::before{transition:none}}
        /* Children of a linked heading step down to 17px. Same weight and colour, so
           they read as the same kind of thing at a lower level rather than as a
           different control - and the size difference is what carries the hierarchy
           now that indentation alone would be ambiguous inside a column. */
        .nav-sub{font-size:17px;min-height:42px}

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
        @media(max-width:767px){.hdr-in{height:96px;padding:14px 16px}.logo-nav{gap:8px}.hdr-in .nav-menu{position:fixed;top:100px;left:16px;right:16px;width:auto;max-height:calc(100dvh - 140px)}.nav-cols,.nav-results{grid-template-columns:minmax(0,1fr)}.nav-item{font-size:19px;min-height:52px}.nav-sub{font-size:17px;min-height:46px}}

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
        @media(max-width:340px){.hdr-in{padding-inline:10px}.logo-nav{gap:6px}}

        @media(prefers-reduced-motion:reduce){
          .nav-menu{transition:none}
          .nav-arrow{transition:none}
        }
      `}</style>
    </header>
  );
};

export default Header;
