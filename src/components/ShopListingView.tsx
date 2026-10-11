import React, { useMemo, useState } from 'react';
import Link from 'next/link';
import RotatingHero, { type CycleWord } from './RotatingHero';
import Breadcrumbs from './Breadcrumbs';
import BlogSearch from './BlogSearch';
import Pager from './Pager';
import { cycle } from '../content/products';
import { catalogReadOn } from '../content/shop';
import { shopListingPageHref, type ShopListing } from '../content/shopProducts';

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
 * mounted directly under the header), the blog listing's exact search box and exact paginator,
 * and the blog's card look laid out in a SINGLE HORIZONTAL ROW THAT SCROLLS sideways - a rotating
 * hue spine on each card, over the whole shelf, every product the site sells, from
 * src/content/shopProducts.ts. Moving off PageTopBand is free:
 * src/test/PublicPageTopBand.test.tsx lists src/pages/shop/[slug].tsx in BAND_PAGE_FILES and
 * never this listing.
 *
 * NO NEW COLOUR ENTERS THE SITE. The hero rotates the four cycle() pairs from
 * src/content/products.ts and the card spines rotate the three accent hues .home-flow-list
 * already uses. The home page's fifth pair (#fee2e2/#dc2626) is NOT used: red is retired from
 * these surfaces and PublicPageTopBand.test.tsx enforces its absence on the neighbouring shop
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

const ShopListingView: React.FC<ShopListingViewProps> = ( { listings, allListings, page, totalPages } ) => {
  /**
   * READ ?q= ON FIRST RENDER, because BlogSearch's no-JavaScript path is a GET form that
   * navigates to /shop/?q=... and because a search result page should be linkable. Done in a
   * lazy initialiser rather than an effect so the filtered list is correct on the FIRST paint
   * instead of flashing six cards and then narrowing. `window` is guarded because this same
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

  const visible = useMemo( () => {
    if ( !filtering ) return listings;
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
  }, [ filtering, query, listings, allListings ] );

  return (
    <RotatingHero
      frame="A shop for"
      words={ SHOP_HERO_WORDS }
      sub="Every WECARE.DIGITAL product and service on one page, each with its own page to open."
      ariaLabel="WECARE.DIGITAL shop"
    >
      <div className="shop-in">
        <Breadcrumbs
          items={ page > 1
            ? [ { label: 'Home', href: '/' }, { label: 'Shop', href: '/shop/' }, { label: `Page ${page}` } ]
            : [ { label: 'Home', href: '/' }, { label: 'Shop' } ] }
        />

        {/* Live mode, and the count's denominator is the WHOLE shelf rather than this page's six:
            "3 of 15" is the true answer about what was searched. The five strings are the only
            thing that differs from the blog's box. */}
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

        { visible.length > 0 ? (
          <section className="shop-grid" aria-label={ filtering ? 'Matching products' : 'Catalogue' }>
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

        {/* THE PAGINATOR IS HIDDEN WHILE FILTERING, and every match is listed. A filtered list is
            already a narrowing of the whole shelf; paging it as well puts two narrowings between
            a reader and one product. Same rule as the blog listing.
            Previous / Next rather than the blog's Newer / Older: this order is declaration order
            and then name order, so "Older" would be a claim about a sort nobody performed. */}
        { !filtering && totalPages > 1 && (
          <Pager
            page={ page }
            totalPages={ totalPages }
            hrefFor={ shopListingPageHref }
            ariaLabel="Shop pages"
            prevLabel="Previous"
            nextLabel="Next"
          />
        ) }

        {/* HOW FRESH THE WIX HALF IS, stated rather than assumed. output: 'export' means the
            catalogue is frozen into this HTML at build time, so the honest thing is to print the
            date the snapshot was read. catalogReadOn() is UTC-pinned, so it cannot render a
            different date either side of midnight for the same build. It renders on every page,
            because the Wix half is on every page. */}
        <p className="shop-asof">Catalogue read on { catalogReadOn() }</p>

        <style jsx>{`
          /* NO TOP PADDING AND NO MAX-WIDTH: RotatingHero owns the header clearance, the 1300px
             measure, the gutter and the typeface through .rh-shell / .rh-layout. This div sets
             only the stack between the hero and the list, which is its own job. */
          .shop-in{width:100%;display:flex;flex-direction:column;gap:28px}

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
          /* A visible but quiet scrollbar track, so a reader can tell the row scrolls. */
          .shop-grid::-webkit-scrollbar{height:8px}
          .shop-grid::-webkit-scrollbar-thumb{background:#d1d5db;border-radius:999px}
          .shop-grid::-webkit-scrollbar-track{background:transparent}

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

          /* The as-of line. The quieter of the two treatments the repo's comments describe for
             this class name, because it is an aside and not a read-this-first notice: the dim
             rung at rgba(0,0,0,.54) on the page's own surface, with no box of its own. */
          .shop-asof{margin:28px 0 0;font-size:16px;line-height:1.55;color:rgba(0,0,0,.54)}

          /* 767px is the home page's narrow step, which RotatingHero above also breaks at. The
             row still scrolls horizontally; the card just narrows so a reader sees most of one
             card plus a hint of the next, which is the cue that the row scrolls. The body rung
             steps down and the clamp opens, the same pair of moves the blog listing makes. */
          @media(max-width:767px){
            .shop-in :global(.shop-card){flex-basis:82vw;padding:22px}
            .shop-in :global(.shop-card-tag){font-size:18px;-webkit-line-clamp:4}
          }
          /* A shadow appearing under a card is the same "something moved" cue as the lift. */
          @media(prefers-reduced-motion:reduce){
            .shop-in :global(.shop-card){transition:none}
            .shop-in :global(.shop-card:hover){transform:none;box-shadow:none}
          }
        `}</style>
      </div>
    </RotatingHero>
  );
};

export default ShopListingView;
