import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import RotatingHero, { type CycleWord } from './RotatingHero';
import Breadcrumbs from './Breadcrumbs';
import BlogSearch from './BlogSearch';
import { cycle } from '../content/products';
import { type ShopListing } from '../content/shopProducts';

/**
 * The /shop/ listing, one page of it.
 *
 * WHY THIS IS A COMPONENT AND NOT src/pages/shop/index.tsx. Two routes render this exact page -
 * /shop/ for the first six listings and /shop/page/N/ for the rest - and they must not be two
 * copies of the markup and the styles. Both pages are thin: they slice and hand the slice here.
 * Same arrangement, and same reason, as components/BlogIndexView.tsx.
 *
 * WHAT CHANGED AND WHY. This listing was a PageTopBand heading over a three-up auto-fill grid of
 * the eight visible Wix rows. It is now the home page's own animated headline (RotatingHero,
 * mounted directly under the header), the blog listing's exact search box, and the blog's card
 * look laid out in a SINGLE HORIZONTAL ROW THAT SCROLLS sideways - a rotating hue spine on each
 * card, over the whole shelf, every product the site sells, from src/content/shopProducts.ts.
 *
 * THE PAGER IS THE PERSPECTIVES PANEL'S, not a numbered Previous/Next. Owner instruction: match
 * the product-page blog panel (components/ProductBlogPanel.tsx) - a lime progress bar plus two
 * circular arrow buttons, NO page numbers. The arrows scroll the horizontal card row left/right
 * by one viewport and the bar tracks the scroll position. The whole shelf renders in the row (not
 * this route's six), so the arrows reach every product without a page navigation.
 *
 * NO "CATALOGUE READ ON ..." LINE. Owner instruction: the as-of date is removed from the page.
 * The catalogue is still frozen at build time by output: 'export'; the date is simply not printed.
 *
 * THE SERVER ROUTES ARE UNTOUCHED. /shop/ and /shop/page/N/ still prerender their own slices, so a
 * crawler with no JavaScript reaches every product through real links and the sitemap is unchanged
 * (SEO rule). The single-rail-of-everything is the rendered experience; the paginated HTML remains
 * the crawl surface. Moving off PageTopBand is free:
 * src/test/PublicPageHero.test.tsx lists src/pages/shop/[slug].tsx in BAND_PAGE_FILES and
 * never this listing.
 *
 * NO NEW COLOUR ENTERS THE SITE. The hero rotates the four cycle() pairs from
 * src/content/products.ts and the card spines rotate the three accent hues .home-flow-list
 * already uses. The home page's fifth pair (#fee2e2/#dc2626) is NOT used: red is retired from
 * these surfaces and PublicPageHero.test.tsx enforces its absence on the neighbouring shop
 * files.
 *
 * SEARCH FILTERS THE WHOLE SHELF, NOT THIS PAGE'S SIX, and it needs no fetched index to do it.
 * The blog lazily fetches a 301 kB search index because 864 posts cannot ship in the page; the
 * shop's whole list is roughly 2 kB of __NEXT_DATA__ against the 128 kB threshold blogcheck
 * enforces, so both routes pass it in as `allListings`. There is nothing here that can fail, so
 * there is no 'loading' state, no 'failed' state and no .blog-degraded recovery notice.
 */

/**
 * The hero rotation. Four words held close in length - 8, 9, 8, 8 characters - because the pill
 * animates to each word's MEASURED width and the spread is how far the line's tail travels every
 * tick. Tints are the four cycle() pairs, reused verbatim.
 */
export const SHOP_HERO_WORDS: CycleWord[] = cycle( 'services', 'documents', 'products', 'journeys' );

/** Bound on a String.prototype.includes over a 15-item list, not a security control. */
const MAX_QUERY = 100;

interface ShopListingViewProps {
  /** This page's slice, in order. */
  listings: ShopListing[];
  /** The whole shelf, for the search box's denominator and for filtering. */
  allListings: ShopListing[];
  /** 1-based. Page 1 is /shop/; every other page is /shop/page/N/. */
  page: number;
  totalPages: number;
}

const ShopListingView: React.FC<ShopListingViewProps> = ( { allListings } ) => {
  /**
   * READ ?q= ON FIRST RENDER, because BlogSearch's no-JavaScript path is a GET form that
   * navigates to /shop/?q=... and because a search result page should be linkable. Done in a
   * lazy initialiser rather than an effect so the filtered list is correct on the FIRST paint
   * instead of flashing cards and then narrowing. `window` is guarded because this same
   * initialiser runs during the static export, where there is no location.
   *
   * VALIDATION IS A TRUNCATION, NOT A REJECTION. There is no sensible error to show a reader for
   * a long search term, and the value never reaches a regex, dangerouslySetInnerHTML, a URL or a
   * network call - it is one lowercased includes() over a handful of strings - so there is no
   * injection and no ReDoS surface to defend.
   */
  const [ query, setQuery ] = useState( () => {
    if ( typeof window === 'undefined' ) return '';
    const raw = new URLSearchParams( window.location.search ).get( 'q' );
    return raw === null ? '' : String( raw ).slice( 0, MAX_QUERY ).trim();
  } );

  const filtering = Boolean( query.trim() );

  /**
   * THE WHOLE SHELF IS THE ROW. The rendered experience is one horizontal rail the reader scrolls
   * or swipes through, so cards are always drawn from `allListings` (every product the site
   * sells) rather than this route's six-item slice. The prerendered /shop/page/N/ HTML still
   * exists for a no-JS crawler; this is the interactive surface.
   */
  const visible = useMemo( () => {
    if ( !filtering ) return allListings;
    const q = query.trim().toLowerCase();
    /*
     * THE FIELDS ARE JOINED WITH A NEWLINE, NOT A SPACE, and that is copied deliberately from
     * BlogIndexView rather than simplified. Joining with a space lets a query match a phrase made
     * only of the end of one field and the start of the next - "Anew" plus "A considered..." gives
     * "anew a considered", which contains "anew a", a phrase no product has. A newline cannot
     * appear in a typed query, so it is a boundary a search term cannot cross, while spaces inside
     * one field still match normally.
     */
    return allListings.filter( listing => (
      [ listing.name, listing.blurb ].join( '\n' ).toLowerCase().includes( q )
    ) );
  }, [ filtering, query, allListings ] );

  /**
   * THE PERSPECTIVES-STYLE PAGER, driving the horizontal card row (components/ProductBlogPanel's
   * arrows + progress bar, no numbers). `rowRef` is the scrolling .shop-grid; the arrows scroll it
   * by ~one viewport, and `progress` (0..1) is read back from scrollLeft so the lime bar tracks
   * position. All SSR-safe: the state is 0 until the first client scroll/measure.
   */
  const rowRef = useRef<HTMLDivElement | null>( null );
  const [ progress, setProgress ] = useState( 0 );
  const [ atStart, setAtStart ] = useState( true );
  const [ atEnd, setAtEnd ] = useState( false );

  const measure = useCallback( (): void => {
    const el = rowRef.current;
    if ( !el ) return;
    const max = el.scrollWidth - el.clientWidth;
    // No overflow (every card fits) means there is nothing to page: full bar, both arrows off.
    if ( max <= 1 ) { setProgress( 1 ); setAtStart( true ); setAtEnd( true ); return; }
    const left = el.scrollLeft;
    setProgress( Math.min( 1, Math.max( 0, left / max ) ) );
    setAtStart( left <= 1 );
    setAtEnd( left >= max - 1 );
  }, [] );

  // Re-measure when the result set changes (a search narrows the row) and on mount. scrollTo is
  // feature-detected: jsdom does not implement it, and some older in-app WebViews lack the
  // options form, so fall back to setting scrollLeft directly rather than throwing.
  useEffect( () => {
    const el = rowRef.current;
    if ( el ) {
      if ( typeof el.scrollTo === 'function' ) el.scrollTo( { left: 0, behavior: 'auto' } );
      else el.scrollLeft = 0;
    }
    measure();
  }, [ visible, measure ] );

  // Keep the bar honest when the viewport resizes (orientation change, foldable unfold, zoom).
  useEffect( () => {
    if ( typeof window === 'undefined' ) return;
    window.addEventListener( 'resize', measure );
    return () => window.removeEventListener( 'resize', measure );
  }, [ measure ] );

  const prefersReduced = (): boolean =>
    typeof window !== 'undefined' && !!window.matchMedia
    && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;

  const scrollByPage = useCallback( ( dir: 1 | -1 ): void => {
    const el = rowRef.current;
    if ( !el ) return;
    // One viewport-worth, minus a card so the next page keeps a card of context, like a swipe.
    const step = Math.max( el.clientWidth * 0.9, 280 );
    // Feature-detect scrollBy for the same reason as scrollTo above (jsdom / older WebViews).
    if ( typeof el.scrollBy === 'function' ) {
      el.scrollBy( { left: dir * step, behavior: prefersReduced() ? 'auto' : 'smooth' } );
    } else {
      el.scrollLeft += dir * step;
    }
    measure();
  }, [ measure ] );

  // Overflow is only known on the client; render the control, but it is inert (full bar, disabled
  // arrows) until there is something to scroll, which `measure` settles on mount.
  const showPager = visible.length > 0;

  return (
    <RotatingHero
      frame="A shop for"
      words={ SHOP_HERO_WORDS }
      sub="Every WECARE.DIGITAL product and service on one page, each with its own page to open."
      ariaLabel="WECARE.DIGITAL shop"
    >
      <div className="shop-in">
        <Breadcrumbs
          items={ [ { label: 'Home', href: '/' }, { label: 'Shop' } ] }
        />

        {/* Live mode, and the count's denominator is the WHOLE shelf: "3 of 15" is the true
            answer about what was searched. The five strings are the only thing that differs from
            the blog's box. */}
        <BlogSearch
          value={ query }
          onChange={ setQuery }
          resultCount={ visible.length }
          totalCount={ allListings.length }
          action="/shop/"
          inputId="shop-q"
          label="Search the shop"
          placeholder="Search products"
          noun="products"
        />

        {/* THE PAGER, MATCHING THE PERSPECTIVES PANEL: two circular arrow buttons on the right,
            no numbers, with a lime progress bar below. The arrows scroll the card row; the bar
            tracks the scroll position. Hidden when a search returns nothing. */}
        { showPager && (
          <div className="shop-pager" aria-label="Catalogue pager">
            <div className="shop-pager-row">
              <div className="shop-arrows">
                <button
                  type="button"
                  className="shop-arrow"
                  aria-label="Scroll products left"
                  disabled={ atStart }
                  onClick={ () => scrollByPage( -1 ) }
                >‹</button>
                <button
                  type="button"
                  className="shop-arrow"
                  aria-label="Scroll products right"
                  disabled={ atEnd }
                  onClick={ () => scrollByPage( 1 ) }
                >›</button>
              </div>
            </div>
            <div
              className="shop-progress-track"
              role="progressbar"
              aria-label="Position through the catalogue"
              aria-valuemin={ 0 }
              aria-valuemax={ 100 }
              aria-valuenow={ Math.round( progress * 100 ) }
            >
              <div className="shop-progress-fill" style={ { width: `${Math.max( progress * 100, 4 )}%` } } />
            </div>
          </div>
        ) }

        { visible.length > 0 ? (
          <section
            className="shop-grid"
            aria-label={ filtering ? 'Matching products' : 'Catalogue' }
            ref={ rowRef }
            onScroll={ measure }
          >
            { visible.map( listing => (
              <Link key={ listing.slug } className="shop-card" href={ listing.href }>
                <span className="shop-card-name">{ listing.name }</span>
                <span className="shop-card-tag">{ listing.blurb }</span>
                { ( listing.formattedPrice || listing.inStock === false ) && (
                  <span className="shop-card-foot">
                    { listing.formattedPrice && (
                      <span className="shop-card-price" data-wc-no-translate="true">{ listing.formattedPrice }</span>
                    ) }
                    { listing.inStock === false && (
                      <span className="shop-card-oos">Not available right now</span>
                    ) }
                  </span>
                ) }
              </Link>
            ) ) }
          </section>
        ) : (
          <div className="shop-empty">No products match that search.</div>
        ) }

        <style jsx>{`
          /* NO TOP PADDING AND NO MAX-WIDTH: RotatingHero owns the header clearance, the 1300px
             measure, the gutter and the typeface through .rh-shell / .rh-layout. This div sets
             only the stack between the hero and the list, which is its own job. */
          .shop-in{width:100%;display:flex;flex-direction:column;gap:28px}

          /* THE PERSPECTIVES-PANEL PAGER, borrowed rung for rung from components/ProductBlogPanel
             (pbp-arrows / pbp-progress-track). Two circular arrows pinned to the right, no page
             numbers, with a slim lime progress bar below them. These are plain <button>s on real
             DOM tags in this file, so styled-jsx scopes them without :global(). */
          .shop-pager{display:flex;flex-direction:column;gap:12px;margin:0}
          .shop-pager-row{display:flex;align-items:center;justify-content:flex-end}
          .shop-arrows{display:flex;align-items:center;gap:8px}
          /* Lime-themed, matching the pill language: dark-green 2px edge at rest (2px means
             hoverable), full lime on hover like the CTA. 44x44 is the WCAG 2.5.8 touch floor, so
             the arrows are reliably tappable on phones and in-app browsers, not just clickable. */
          .shop-arrow{
            display:inline-flex;align-items:center;justify-content:center;
            width:44px;height:44px;flex:0 0 auto;
            border:2px solid #1a3a2a;border-radius:50%;background:#fff;
            color:#1a3a2a;font-size:20px;line-height:1;font-family:inherit;cursor:pointer;
            transition:background-color .2s,border-color .2s,opacity .2s;
          }
          .shop-arrow:hover:not(:disabled){background:#d1f470}
          .shop-arrow:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
          .shop-arrow:disabled{opacity:.3;cursor:default;border-color:#cfd4d9;color:rgba(0,0,0,.4)}
          /* The position bar: hairline track, lime fill, no numbers - the one place lime marks
             progress rather than action, fine as a thin bar. The fill width is set inline from
             the scroll position; a 4% floor keeps a sliver visible at the very start. */
          .shop-progress-track{
            width:100%;height:6px;border-radius:50px;background:#eef0f2;overflow:hidden;
          }
          .shop-progress-fill{
            height:100%;border-radius:50px;background:#d1f470;transition:width .2s ease;
          }

          /* ONE HORIZONTAL ROW THAT SCROLLS - the brief: blog-style cards, laid out in a single
             row, the rest reached by scrolling sideways rather than wrapping down the page.
             A flex row with overflow-x:auto is the whole mechanism: the cards never wrap
             (flex-wrap:nowrap), each keeps a fixed width (set on .shop-card below) so it does not
             squash as more are added, and the row scrolls horizontally past the viewport edge.
             scroll-snap-type keeps a card aligned to the start edge after a flick on touch, and
             -webkit-overflow-scrolling:touch gives momentum on iOS. The gap matches the blog
             grid's. padding-bottom leaves room for the scrollbar so it does not sit on the cards,
             and the small negative/positive inline padding lets the first and last card breathe
             against the measure's gutter without clipping the hover lift. */
          .shop-grid{
            display:flex;flex-wrap:nowrap;gap:24px;margin:0;padding:4px 2px 16px;
            overflow-x:auto;overflow-y:hidden;
            scroll-snap-type:x proximity;-webkit-overflow-scrolling:touch;
            scrollbar-width:thin;
          }
          /* A visible but quiet scrollbar so a reader can tell the row scrolls. The HEIGHT is set
             here (8px, a size, not a colour); the COLOUR is deliberately NOT declared locally -
             the canonical block in src/styles/inner-ux.css colours every scroller from the
             --scrollbar-* tokens, and ScrollbarDeclarations.test.ts forbids a second colour
             declaration in a component because Gecko reads scrollbar-color while Blink reads
             ::-webkit-scrollbar-thumb, so a local colour is invisible in one engine. */
          .shop-grid::-webkit-scrollbar{height:8px}

          /* :global() IS MANDATORY ON EVERY .shop-card RULE - styled-jsx attaches its scoping
             class only to the lowercase DOM tags it can see in this file, and <Link> is a
             capitalised component, so a bare .shop-card rule would match nothing and the cards
             would render as plain blue underlined links. It is the same trap Pager.tsx documents
             at length for .pager-step. Scoped inside .shop-in, which IS a div in this file and
             does carry the hash, so these cannot leak out of the component.
             Do not "simplify" them to bare selectors, and do not swap <Link> for <a> to avoid the
             wrapper: the link keeps client-side navigation, and an inner span carrying the class
             would move it off the focusable element and break the focus ring. */
          /* THE SPINE IS THE ROTATING HUE, and three hues rather than four is a measured
             constraint. Green, blue and purple are the site's only accent spine motif, taken from
             .home-flow-list, and AMBER WAS MEASURED AT 2.04:1 AND REJECTED for a 3px stroke - see
             the identical note in BlogIndexView. The four-pair cycle() set is used where it
             belongs, in the hero pill, where the colour is a large tint behind dark type rather
             than a hairline. The cards are the direct children of section.shop-grid, so
             nth-child counts cards and nothing else. */
          .shop-in :global(.shop-card){
            /* A FIXED-WIDTH FLEX CHILD so the cards sit side by side in the scrolling row and
               keep their shape no matter how many there are. 320px is the blog card's natural
               three-up width at the 1300px measure; flex:0 0 means never grow and never shrink,
               which is what stops the row collapsing the cards to fit. scroll-snap-align:start
               pairs with the row's scroll-snap-type so a card settles against the left edge. */
            flex:0 0 320px;scroll-snap-align:start;
            display:flex;flex-direction:column;gap:10px;
            padding:26px;background:#fff;
            border:1px solid #e5e7eb;border-radius:14px;
            border-inline-start:3px solid #3da35a;
            overflow:hidden;text-decoration:none;color:inherit;
            transition:border-color .2s,transform .2s,box-shadow .2s;
          }
          .shop-in :global(.shop-card:nth-child(3n+2)){border-inline-start-color:#2563eb}
          .shop-in :global(.shop-card:nth-child(3n+3)){border-inline-start-color:#9849e8}
          /* The home CTA's treatment, and the only shadow this design language allows. */
          .shop-in :global(.shop-card:hover){
            border-color:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
          }
          /* Opaque, because the translucent ring failed WCAG 1.4.11 at 1.51:1 on white. */
          .shop-in :global(.shop-card:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px}

          /* The one card-heading rung, 22px/700/1.27/-.25px on solid black, and the one body
             rung, 20px/400/1.4/-.125px at rgba(0,0,0,.898) - the same two the blog listing and
             the home page's cards use. The blurb is clamped so a long tagline does not set the
             height of its row. */
          .shop-in :global(.shop-card-name){
            font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;color:#000;
          }
          .shop-in :global(.shop-card-tag){
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);
            display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
          }
          .shop-in :global(.shop-card-foot){display:flex;align-items:baseline;gap:12px;margin-top:4px}
          /* Dark green, not lime: lime means actionable on this site and the actionable surface
             is the button on the product page, not the price on a listing card. Tabular figures,
             like the product page. Rendered only where a live catalogue row supplies the string -
             a ProductDef entry carries no price, so this page never prints a number nobody
             quoted. */
          .shop-in :global(.shop-card-price){
            font-size:18px;font-weight:700;line-height:1.3;color:#1a3a2a;
            font-variant-numeric:tabular-nums;
          }
          .shop-in :global(.shop-card-oos){
            font-size:14px;font-weight:700;line-height:1.3;color:rgba(0,0,0,.54);
          }

          /* The honest miss, on the blog listing's own empty-state rung. */
          .shop-empty{
            border:1px dashed #d1d5db;border-radius:14px;padding:40px;text-align:center;
            font-size:20px;line-height:1.4;letter-spacing:-.125px;color:rgba(0,0,0,.54);
          }

          /* 767px is the home page's narrow step, which RotatingHero above also breaks at. The
             row still scrolls horizontally; the card just narrows so a reader sees most of one
             card plus a hint of the next, which is the cue that the row scrolls. The body rung
             steps down and the clamp opens, the same pair of moves the blog listing makes. */
          @media(max-width:767px){
            .shop-in :global(.shop-card){flex-basis:82vw;padding:22px}
            .shop-in :global(.shop-card-tag){font-size:18px;-webkit-line-clamp:4}
          }
          /* A shadow appearing under a card is the same "something moved" cue as the lift, and the
             progress fill / arrow tints stop animating under reduced-motion too. */
          @media(prefers-reduced-motion:reduce){
            .shop-in :global(.shop-card){transition:none}
            .shop-in :global(.shop-card:hover){transform:none;box-shadow:none}
            .shop-arrow,.shop-progress-fill{transition:none}
          }
        `}</style>
      </div>
    </RotatingHero>
  );
};

export default ShopListingView;
