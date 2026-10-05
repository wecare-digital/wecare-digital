import fs from 'fs';
import path from 'path';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { readCart, toLineItems } from '../lib/cart';
import { CONTRIBUTION_CHOICES } from '../config/contribution';
import ShopProductPage from '../pages/shop/[slug]';
import { shopProductSchema } from '../components/ShopProductHead';
import {
  SHOP_PRODUCTS, shopProductBySlug, shopMetaDescription, shopPageTitle, shopProductPath,
  toParagraphs, catalogReadOn, CATALOG_FETCHED_AT,
  CONTRIBUTION_CONFIGURED, CONTRIBUTION_PRODUCT, CONTRIBUTION_PRODUCT_ID, CONTRIBUTION_RAW,
  CONTRIBUTION_SLUG, projectForTest,
  WIX_TEMPLATE_SAMPLE_PRODUCT_IDS, WIX_TEMPLATE_SAMPLE_SLUGS,
} from '../content/shop';
import { getStaticPaths } from '../pages/shop/[slug]';
import type { ShopProduct } from '../content/shop';
// The RAW snapshot, so the assertions below can compare the projection against its own source
// instead of against a literal copied out of it. A literal is a per-product hand edit, and
// `.github/workflows/catalogue-sync.yml` rewrites this file on a schedule.
import catalog from '../content/wix-catalog.json';

/**
 * The /shop/ catalogue: the snapshot reader, and the two pages built on it.
 *
 * WHAT IS WORTH ASSERTING HERE AND WHAT IS NOT. The layout is measured in the browser -
 * tools/browser/seocheck.js, sectioncheck.js, devicecheck.js, lhcheck.js and pageaudit.js all
 * carry /shop/ and /shop/kiosk/, and a jsdom test cannot read a computed style, which is the trap
 * the mega-menu documents: 112 browser assertions passed while every row was unstyled.
 *
 * So this file asserts the things that are TRUE OR FALSE rather than visual: that the snapshot is
 * read correctly, that the derived strings stay inside the bounds seocheck enforces, that
 * merchant-authored HTML never reaches the DOM as HTML, and that the out-of-stock branch renders -
 * which nothing else can check, because all seven items in the committed snapshot are in stock.
 */

/** A product that is not in the snapshot, so the assertions below cannot be satisfied by luck. */
const SYNTHETIC: ShopProduct = {
  id: 'synthetic',
  name: 'Sold Out Thing',
  slug: 'sold-out-thing',
  formattedPrice: '₹1,234.00',
  price: '1234.00',
  currency: 'INR',
  inStock: false,
  tagline: 'A thing nobody can buy today.',
  body: [ 'One paragraph of body copy.' ],
};

/**
 * Narrow one JSON-LD node for assertion. A schema.org graph is heterogeneous, so the builder types
 * it as Record<string, unknown>; this keeps the reads explicit without reaching for `any`.
 */
const ld = ( value: unknown ): Record<string, unknown> => value as Record<string, unknown>;

/** The raw snapshot row for one slug, with every field read as a string. */
const rawRow = ( slug: string ): Record<string, string> => {
  const rows = ( catalog.products as unknown as Record<string, unknown>[] );
  const row = rows.find( r => r.slug === slug );
  expect( row, `${slug} is in SHOP_PRODUCTS but not in the snapshot` ).toBeDefined();
  const out: Record<string, string> = {};
  for ( const [ key, value ] of Object.entries( row as Record<string, unknown> ) ) {
    out[ key ] = typeof value === 'string' ? value : String( value );
  }
  return out;
};

describe( 'the Wix snapshot is read correctly', () => {
  it( 'requires a merchandise variant and keeps distinct sizes in distinct cart lines', () => {
    window.localStorage.clear();
    const merchandise = shopProductBySlug( 'merchandise' )!;
    render( <ShopProductPage product={ merchandise } /> );
    const button = screen.getByRole( 'button', { name: 'Add Merchandise to cart' } );
    expect( button ).toBeDisabled();
    const variants = merchandise.variants!;
    fireEvent.change( screen.getByRole( 'combobox' ), { target: { value: variants[0].id } } );
    fireEvent.click( button );
    fireEvent.change( screen.getByRole( 'combobox' ), { target: { value: variants[1].id } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Add Merchandise to cart' } ) );
    expect( readCart() ).toHaveLength( 2 );
    expect( readCart().map( item => item.name ) ).toEqual( [
      `Merchandise (${variants[0].label})`, `Merchandise (${variants[1].label})`,
    ] );
    expect( toLineItems().map( item => item.catalogReference.options?.variantId ) ).toEqual( [ variants[0].id, variants[1].id ] );
    expect( JSON.stringify( toLineItems() ) ).not.toMatch( /price|amount|formattedPrice/ );
    window.localStorage.clear();
  } );
  it( 'reads the visible non-contribution products the snapshot holds', () => {
    /*
     * ASSERTS THE PROPERTY, NOT THE SPELLING - changed 2026-10-04 for catalogue auto-sync.
     *
     * This used to pin an explicit eight-slug list, and the reason given was a good one: a check
     * derived from the file would agree with whatever the file said, INCLUDING AN EMPTY ARRAY,
     * which is how a catalogue page ships blank.
     *
     * But a literal slug list is a PER-SLUG ALLOWLIST, and `.github/workflows/catalogue-sync.yml`
     * now commits a refreshed snapshot on its own every six hours. Adding one product in Wix would
     * turn this green test red with no code change behind it, and a human would have to hand-edit
     * a list - which is the exact manual step B2 exists to remove. Everything else on the /shop/
     * path is already prefix-based (getStaticPaths enumerates SHOP_PRODUCTS, the sitemap carries
     * the '/shop/' PREFIX, _app.tsx keys on the '/shop/[slug]' PATTERN), so this list was the only
     * place a new product needed a hand edit.
     *
     * THE BLANK-CATALOGUE PROTECTION IS KEPT, and it is what the floor is for. A derived check
     * cannot be satisfied by an empty array while `FLOOR` must also hold, so the failure the old
     * comment was defending against still fails. The floor is a LOWER BOUND, which a new product
     * cannot cross; only a product being REMOVED from Wix can, and that is a change worth a human
     * reading the diff.
     */
    const FLOOR = 6;
    const rows = ( catalog.products as { slug?: string; visible?: boolean; name?: string }[] );
    const expected = rows
      .filter( r => r.visible !== false && !!r.slug && !!r.name )
      .filter( r => r.slug !== CONTRIBUTION_SLUG )
      // The Wix template's twelve sample products, excluded by owner decision 2026-10-05. Derived
      // from the exported list rather than named here, so this stays the prefix-based check the
      // comment above argues for: a product the owner decides to sell is published by deleting one
      // line in shop.ts, with no edit to this test.
      .filter( r => !WIX_TEMPLATE_SAMPLE_SLUGS.includes( String( r.slug ) ) )
      .map( r => r.slug as string )
      .sort();
    expect( SHOP_PRODUCTS.length ).toBeGreaterThanOrEqual( FLOOR );
    expect( [ ...SHOP_PRODUCTS.map( p => p.slug ) ].sort() ).toEqual( expected );
    // Every slug is route-safe, because the slug IS the path segment of its page. A slug Wix would
    // accept but a URL would not (a space, an uppercase letter, a slash) must fail here rather
    // than produce a page nobody can reach.
    for ( const product of SHOP_PRODUCTS ) {
      expect( product.slug, `${product.slug} is not a route-safe slug` )
        .toMatch( /^[a-z0-9]+(?:-[a-z0-9]+)*$/ );
    }
    // No duplicates: two rows sharing a slug would collide on one static path.
    expect( new Set( SHOP_PRODUCTS.map( p => p.slug ) ).size ).toBe( SHOP_PRODUCTS.length );
  } );

  it( 'sorts by name, because the snapshot offers no other order', () => {
    const names = SHOP_PRODUCTS.map( p => p.name );
    expect( names ).toEqual( [ ...names ].sort( ( a, b ) => a.localeCompare( b ) ) );
  } );

  it( 'passes Wix\'s own formatted price through rather than rebuilding it', () => {
    /*
     * The rule the whole commerce architecture rests on: a price rendered here must be the string
     * Wix would quote, not a locally formatted version of the number beside it. A reimplemented
     * formatter is a second opinion about the amount.
     *
     * ASSERTED AGAINST THE SNAPSHOT ROW, not against a literal - changed 2026-10-04 with
     * catalogue auto-sync. A hardcoded '₹24,999.00' tests a PRICE, which the owner may change in
     * Wix at any moment and the scheduled sync will then commit. Comparing the projection to the
     * raw row tests the PASS-THROUGH, which is the property that must never change, and it holds
     * for every product rather than for one.
     */
    for ( const product of SHOP_PRODUCTS ) {
      const raw = rawRow( product.slug );
      expect( product.formattedPrice, `${product.slug} reformats the price` )
        .toBe( raw.formattedPrice );
      expect( product.price, `${product.slug} alters the decimal amount` ).toBe( raw.price );
      // INR only, compared explicitly and never inferred from the amount.
      expect( product.currency, `${product.slug} is not priced in INR` ).toBe( 'INR' );
    }
  } );

  it( 'splits the description into a tagline and body paragraphs', () => {
    // Derived from each row's own descriptionHtml rather than pinning one product's copy: the
    // owner edits this text in Wix and the scheduled catalogue sync commits the edit, so a literal
    // sentence here would fail on a legitimate content change. `toParagraphs` has its own
    // exhaustive unit tests below; this asserts the PROJECTION uses it.
    for ( const product of SHOP_PRODUCTS ) {
      const raw = rawRow( product.slug );
      const paragraphs = toParagraphs( raw.descriptionHtml || '' );
      if ( paragraphs.length ) {
        expect( product.tagline, `${product.slug} does not lead with its own first paragraph` )
          .toBe( paragraphs[ 0 ] );
      }
      // Every product has a tagline and at least one body paragraph, so neither the card nor the
      // detail page can render an empty lead. A product authored in Wix with NO description
      // reaches the synthesised fallback in shop.ts rather than an empty string - which is what
      // lets a brand-new product render a complete page before anybody writes copy for it.
      expect( product.tagline.length, `${product.slug} has no tagline` ).toBeGreaterThan( 0 );
      expect( product.body.length, `${product.slug} has no body copy` ).toBeGreaterThan( 0 );
    }
  } );

  it( 'returns null for a slug that is not in the catalogue', () => {
    expect( shopProductBySlug( 'not-a-product' ) ).toBeNull();
    expect( shopProductBySlug( '' ) ).toBeNull();
  } );

  it( 'renders the fetch date in UTC, so the build cannot produce two answers', () => {
    // The snapshot timestamp is UTC. Resolving it in the visitor's zone would print a different
    // date either side of midnight for one build, which is a hydration mismatch as well as a wrong
    // answer. The catalogue is auto-synced from Wix (every sync rewrites fetchedAt), so this test
    // pins the SHAPE and UTC-stability rather than a frozen date: a hardcoded date would break on
    // every legitimate refresh.
    expect( CATALOG_FETCHED_AT ).toMatch( /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/ );
    // catalogReadOn() must render that same UTC instant deterministically, in the
    // "D Month YYYY" form, with no dependence on the host timezone.
    const utcExpected = new Date( CATALOG_FETCHED_AT ).toLocaleDateString( 'en-GB', {
      day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
    } );
    expect( catalogReadOn() ).toBe( utcExpected );
  } );
} );

describe( 'toParagraphs turns merchant rich text into plain paragraphs', () => {
  it( 'breaks on </p> and <br> and drops every other tag', () => {
    expect( toParagraphs( '<p>One</p><p>Two</p>' ) ).toEqual( [ 'One', 'Two' ] );
    expect( toParagraphs( 'One<br>Two<br/>Three' ) ).toEqual( [ 'One', 'Two', 'Three' ] );
    expect( toParagraphs( '<p><span style="font-weight: 700">Bold</span></p>' ) ).toEqual( [ 'Bold' ] );
  } );

  it( 'collapses whitespace per line rather than across the whole string', () => {
    // The ordering is load-bearing. Collapsing before the split would eat the newlines the
    // replacements just created; a near-identical helper in this repo trimmed at every recursion
    // instead and produced "2 tbsptoastedsesame oil" - words fused at a tag boundary.
    expect( toParagraphs( '<p>  a   b  </p>\n<p>\tc\n\nd</p>' ) ).toEqual( [ 'a b', 'c d' ] );
  } );

  it( 'decodes &amp; last, so a double-encoded entity is not decoded twice', () => {
    // "&amp;lt;" is a literal "&lt;" in the source. Decoding &amp; first would turn it into "<".
    expect( toParagraphs( '<p>&amp;lt;</p>' ) ).toEqual( [ '&lt;' ] );
    expect( toParagraphs( '<p>Tom &amp; Jerry</p>' ) ).toEqual( [ 'Tom & Jerry' ] );
    expect( toParagraphs( '<p>&nbsp;a&#39;b&quot;c&nbsp;</p>' ) ).toEqual( [ 'a\'b"c' ] );
  } );

  it( 'drops empty paragraphs instead of rendering blank lines', () => {
    expect( toParagraphs( '<p></p><p>a</p><p>   </p>' ) ).toEqual( [ 'a' ] );
    expect( toParagraphs( '' ) ).toEqual( [] );
  } );

  it( 'leaves no tag delimiter behind, terminated or not', () => {
    /*
     * THE CodeQL FINDING, AS A TEST. It was a high-severity
     * js/incomplete-multi-character-sanitization on this file and a real defect, not a false
     * positive: the assertion further down that no `<span` reaches the DOM could have passed while
     * the text still carried `<script`.
     *
     * Two residues, both measured rather than assumed:
     *
     *   UNTERMINATED. `/<[^>]*>/` needs a closing bracket, so `<script` with none never matched and
     *     passed through whole. This is the one CodeQL named.
     *
     *   NESTED. `a<scr<script>ipt>b` consumes `<scr<script>` - `[^>]*` happily eats the inner `<` -
     *     and strands the leftover `>` in `aipt>b`.
     *
     * The loop plus the final delimiter sweep removes both. Hostile input comes out mangled, which
     * is the correct outcome for markup debris; readable copy is unaffected.
     */
    expect( toParagraphs( '<p>a<script</p>' ) ).toEqual( [ 'ascript' ] );
    expect( toParagraphs( '<p>a<scr<script>ipt>b</p>' ) ).toEqual( [ 'aiptb' ] );
    expect( toParagraphs( '<p>x<a<b>c>y</p>' ) ).toEqual( [ 'xcy' ] );
    expect( toParagraphs( '<<>>' ) ).toEqual( [] );
    expect( toParagraphs( '<p>q<<<<x>>>>r</p>' ) ).toEqual( [ 'qr' ] );
  } );

  it( 'never lets a raw delimiter out of any real description', () => {
    // The property, swept over the whole committed catalogue rather than over invented input. Only
    // a bracket that arrived entity-encoded may appear, and none of the seven contains one.
    for ( const product of SHOP_PRODUCTS ) {
      for ( const paragraph of [ product.tagline, ...product.body ] ) {
        expect( paragraph, product.slug ).not.toMatch( /[<>]/ );
      }
    }
  } );

  it( 'leaves a decoded angle bracket as text, because the output is not markup', () => {
    // Entities decode LAST, so `&lt;b&gt;` becomes the literal characters `<b>`. That is correct:
    // this is display text for React children, which escapes on render, so the reader sees what the
    // merchant typed. Stripping again after decoding would delete legitimate copy - `a < b > c`
    // is tag-shaped and would become `a  c`.
    expect( toParagraphs( '<p>a &lt; b &gt; c</p>' ) ).toEqual( [ 'a < b > c' ] );
  } );
} );

describe( 'the derived head strings stay inside the bounds seocheck enforces', () => {
  /*
   * tools/browser/seocheck.js fails a title outside 15-75 characters or a description outside
   * 50-170. Those are browser assertions against the built export, so they only run after a build;
   * these run on every push and name the product that broke the bound.
   */
  it( 'keeps every product title within 15-75 characters', () => {
    for ( const product of SHOP_PRODUCTS ) {
      const title = shopPageTitle( product );
      expect( title.length, `${product.slug}: "${title}"` ).toBeGreaterThanOrEqual( 15 );
      expect( title.length, `${product.slug}: "${title}"` ).toBeLessThanOrEqual( 75 );
      expect( title.endsWith( '| WECARE.DIGITAL' ), `${product.slug} drops the brand suffix` ).toBe( true );
    }
  } );

  it( 'keeps every product description within 50-170 characters', () => {
    for ( const product of SHOP_PRODUCTS ) {
      const description = shopMetaDescription( product );
      expect( description.length, `${product.slug}: "${description}"` ).toBeGreaterThanOrEqual( 50 );
      expect( description.length, `${product.slug}: "${description}"` ).toBeLessThanOrEqual( 170 );
    }
  } );

  it( 'never cuts a sentence in half to fit the budget', () => {
    // The whole point of joining whole paragraphs rather than truncating: the description is the
    // owner's sentences, entire, or it is not used. Measured lengths across the seven: 54 to 159.
    for ( const product of SHOP_PRODUCTS ) {
      const description = shopMetaDescription( product );
      expect( description ).not.toContain( '…' );
      expect( description.startsWith( product.tagline ), `${product.slug} does not open with its tagline` ).toBe( true );
      // Every character of it comes from a whole paragraph, in order.
      const whole = [ product.tagline, ...product.body ].join( ' ' );
      expect( whole.startsWith( description ) ).toBe( true );
    }
  } );

  it( 'gives every product a distinct title and description', () => {
    // seocheck asserts uniqueness across all 24 public routes; this is the half of it that is
    // this file's responsibility.
    const titles = SHOP_PRODUCTS.map( shopPageTitle );
    const descriptions = SHOP_PRODUCTS.map( shopMetaDescription );
    expect( new Set( titles ).size ).toBe( titles.length );
    expect( new Set( descriptions ).size ).toBe( descriptions.length );
  } );

  it( 'builds a product path with the trailing slash the canonical form needs', () => {
    // trailingSlash is set in next.config.js, so the slashless spelling 308s. A canonical or a
    // breadcrumb item pointing at it names a URL that redirects.
    expect( shopProductPath( SYNTHETIC ) ).toBe( '/shop/sold-out-thing/' );
    for ( const product of SHOP_PRODUCTS ) {
      expect( shopProductPath( product ) ).toMatch( /^\/shop\/[a-z0-9-]+\/$/ );
    }
  } );
} );

/**
 * THE TRAILING SLASH IS ABSENT IN jsdom, AND THAT IS THE ROUTER RATHER THAN THE PAGE.
 *
 * next/link puts href through resolveHref, which calls normalizePathTrailingSlash - and that
 * REMOVES a trailing slash unless `trailingSlash` is true. The flag lives in next.config.js, which
 * a vitest run does not load, so a Link given '/contact/' renders href="/contact" here and
 * href="/contact/" in the export.
 *
 * Measured on the built export rather than assumed:
 *   out/shop/kiosk/index.html  href="/contact/"  href="/"
 *
 * So these tests assert the path the PAGE hands to Link, normalised the way this environment
 * normalises it. The canonical form of the built URL is seocheck.js's assertion, against the
 * export, where the real config applies. Hard-coding the slashless string instead would hide which
 * of the two is being checked.
 *
 * The out/shop/index.html line above was removed on 2026-10-04 along with the file: the owner
 * withdrew the catalogue index, so there is no listing document in the export any more. The
 * `describe( 'the listing page' )` block that followed - five its covering the product links,
 * the formatted price, the boundary copy and both stock branches - went with it, because the
 * component it rendered no longer exists. Every property it asserted that is still reachable is
 * asserted against the product page below: formatted price, boundary copy, and both stock
 * branches all have equivalents in `describe( 'the product page' )`.
 */
const asRendered = ( path: string ): string => path.replace( /\/$/, '' ) || '/';

describe( 'the product page', () => {
  it( 'renders the name as the only h1 and the description as text', () => {
    const kiosk = shopProductBySlug( 'kiosk' ) as ShopProduct;
    const { container } = render( <ShopProductPage product={ kiosk } /> );
    const h1s = container.querySelectorAll( 'h1' );
    expect( h1s ).toHaveLength( 1 );
    expect( h1s[ 0 ].textContent ).toBe( 'Kiosk' );
    expect( screen.getByText( kiosk.tagline ) ).toBeTruthy();
    expect( container.querySelectorAll( 'p.shopd-p' ) ).toHaveLength( kiosk.body.length );
  } );

  it( 'renders a hostile description as inert text, creating no element', () => {
    /*
     * THE PROPERTY THAT ACTUALLY MATTERS, asserted against the DOM.
     *
     * The hostile input goes through toParagraphs FIRST, because that is the real pipeline - the
     * page renders `product.body`, which is already this function's output. An earlier version of
     * this test handed raw entity-encoded HTML straight to `body` and so tested nothing but React's
     * escaping of an already-safe string.
     */
    const paragraphs = toParagraphs(
      '<p>Safe opening line.</p><p><script>alert(1)</script></p>'
      + '<p>&lt;img src=x onerror=alert(1)&gt;</p>',
    );
    const hostile: ShopProduct = {
      ...SYNTHETIC, tagline: paragraphs[ 0 ], body: paragraphs.slice( 1 ),
    };
    const { container } = render( <ShopProductPage product={ hostile } /> );
    expect( container.querySelectorAll( 'script' ) ).toHaveLength( 0 );
    expect( container.querySelectorAll( 'img' ) ).toHaveLength( 0 );
    expect( container.querySelector( '[onerror]' ) ).toBeNull();
    // The script TAGS are gone and only their inner text survives.
    expect( screen.getByText( 'alert(1)' ) ).toBeTruthy();
    // The entity-encoded one decodes to literal characters and React escapes them on render, so it
    // is readable text and not an element.
    expect( screen.getByText( '<img src=x onerror=alert(1)>' ) ).toBeTruthy();
  } );

  it( 'never puts merchant HTML into the DOM as HTML', () => {
    /*
     * THE ASSERTION THAT MATTERS MOST IN THIS FILE. descriptionHtml is rich text from a
     * third-party CMS; rendering it through dangerouslySetInnerHTML would make the storefront an
     * XSS surface that depends on Wix's sanitiser rather than ours. Every one of the seven
     * descriptions contains <span style="font-weight: 700">, so if the tags were passing through,
     * this would find them.
     */
    for ( const product of SHOP_PRODUCTS ) {
      const { container, unmount } = render( <ShopProductPage product={ product } /> );
      const about = container.querySelector( 'section.shopd-about' ) as HTMLElement;
      expect( about, `${product.slug} has no about section` ).toBeTruthy();
      expect( about.innerHTML, `${product.slug} leaked a Wix span` ).not.toContain( '<span' );
      expect( about.innerHTML, `${product.slug} leaked a style attribute` ).not.toContain( 'style=' );
      unmount();
    }
  } );

  it( 'offers an add-to-cart action rather than a contact link', () => {
    // The CTA is now the page's single lime surface: it adds the item to the browser cart. It is a
    // button (a client action) before anything is added, so there is no /contact/ link to find.
    const kiosk = shopProductBySlug( 'kiosk' ) as ShopProduct;
    render( <ShopProductPage product={ kiosk } /> );
    const cta = screen.getByRole( 'button', { name: 'Add Kiosk to cart' } );
    expect( cta ).toBeTruthy();
    expect( screen.queryByRole( 'link', { name: 'Ask about Kiosk' } ) ).toBeNull();
  } );

  it( 'stays truthful that payment is not live yet, without claiming it is not a checkout', () => {
    // The boundary statement is the honest part of shipping a priced catalogue while live payment
    // is off: the store confirms the amount, and proceeding prepares the order without charging.
    // It no longer claims "this page is not a checkout" now that a cart path exists.
    const kiosk = shopProductBySlug( 'kiosk' ) as ShopProduct;
    render( <ShopProductPage product={ kiosk } /> );
    expect( screen.getByText( /Review your final total in the cart before payment/ ) ).toBeTruthy();
    expect( screen.getByText( /before payment/ ) ).toBeTruthy();
    expect( screen.queryByText( /This page is not a checkout/ ) ).toBeNull();
  } );

  it( 'marks a product that is out of stock', () => {
    render( <ShopProductPage product={ SYNTHETIC } /> );
    expect( screen.getByText( 'Not available right now.' ) ).toBeTruthy();
  } );

  it( 'emits no Product node while the product has no image', () => {
    /*
     * Google requires name, image and offers on Product, and tools/audit/schemacheck.js enforces
     * exactly that list - it failed this branch seven times, once per page. All seven items report
     * mediaCount 0, so there is no image to send, and an incomplete Product is ineligible for the
     * rich result anyway. The node waits for the picture rather than borrowing the company logo.
     */
    for ( const product of SHOP_PRODUCTS ) {
      expect( product.image, `${product.slug} unexpectedly has an image` ).toBeUndefined();
    }
    for ( const product of SHOP_PRODUCTS ) {
      const types = shopProductSchema( product )[ '@graph' ]
        .map( node => ld( node )[ '@type' ] );
      expect( types, product.slug ).toEqual( [ 'ItemPage', 'BreadcrumbList' ] );
      // No dangling reference to the node that was not emitted: schemacheck also asserts
      // "no unresolved @id references", so an unconditional mainEntity would swap one failure
      // for another.
      expect( JSON.stringify( shopProductSchema( product ) ) ).not.toContain( '#product' );
    }
  } );

  it( 'emits Product with its Offer as soon as an image exists', () => {
    // The other half: the markup is written and gated, not missing. Populating `image` is the only
    // thing between this repo and complete Product data.
    const withImage: ShopProduct = {
      ...( shopProductBySlug( 'kiosk' ) as ShopProduct ),
      image: 'https://wecare.digital/get/o/stream/media/m/kiosk.png',
    };
    const graph = shopProductSchema( withImage )[ '@graph' ];
    const item = graph.find( n => ld( n )[ '@type' ] === 'ItemPage' );
    const productLd = graph.find( n => ld( n )[ '@type' ] === 'Product' );
    expect( productLd ).toBeTruthy();
    // The three properties Google requires, all present.
    expect( ld( productLd ).name ).toBe( 'Kiosk' );
    expect( ld( productLd ).image ).toBe( withImage.image );
    expect( ld( ld( productLd ).offers )[ '@type' ] ).toBe( 'Offer' );
    // The price in the markup is the same number the page prints, read from the same field.
    expect( ld( ld( productLd ).offers ).price ).toBe( '24999.00' );
    expect( ld( ld( productLd ).offers ).priceCurrency ).toBe( 'INR' );
    expect( ld( ld( productLd ).offers ).availability ).toBe( 'https://schema.org/InStock' );
    // And the page points at it, so the reference resolves.
    expect( ld( ld( item ).mainEntity )[ '@id' ] ).toBe( ld( productLd )[ '@id' ] );
  } );

  it( 'marks the offer out of stock when the product is', () => {
    const graph = shopProductSchema( { ...SYNTHETIC, image: 'https://wecare.digital/x.png' } )[ '@graph' ];
    const productLd = graph.find( n => ld( n )[ '@type' ] === 'Product' );
    expect( ld( ld( productLd ).offers ).availability ).toBe( 'https://schema.org/OutOfStock' );
  } );

  it( 'names the canonical URL in the graph, never the route pattern', () => {
    // The whole reason this component owns the head: PUBLIC_PAGE_META is keyed on router.pathname,
    // which for a dynamic route is '/shop/[slug]'.
    const json = JSON.stringify( shopProductSchema( shopProductBySlug( 'viveka' ) as ShopProduct ) );
    expect( json ).toContain( 'https://wecare.digital/shop/viveka/' );
    expect( json ).not.toContain( '[slug]' );
  } );

  it( 'offers a way out through a two-item breadcrumb, never back to the withdrawn listing', () => {
    /*
     * REWRITTEN 2026-10-04. This was `offers a way back to the listing` and asserted an
     * "All items in the shop" link pointing at /shop/. The owner withdrew the catalogue index, so
     * that link and the middle "Shop" breadcrumb both pointed at a URL that 301s to the home page -
     * and the trail's middle step redirected to its own first step.
     *
     * The crumb is REMOVED rather than left href-less: components/Breadcrumbs.tsx renders an
     * href-less item as <span aria-current="page">, so keeping it would announce two current pages.
     * That is why the negative half below checks for the absence of a /shop/ href AND the absence
     * of a second aria-current.
     */
    const kiosk = shopProductBySlug( 'kiosk' ) as ShopProduct;
    const { container } = render( <ShopProductPage product={ kiosk } /> );

    const trail = container.querySelector( 'nav[aria-label="Breadcrumb"]' ) as HTMLElement;
    expect( trail, 'the product page renders no breadcrumb trail' ).toBeTruthy();
    expect( trail.querySelectorAll( 'li' ) ).toHaveLength( 2 );
    expect( screen.getByRole( 'link', { name: 'Home' } ).getAttribute( 'href' ) )
      .toBe( asRendered( '/' ) );
    // Exactly one current page, and it is the product.
    const current = trail.querySelectorAll( '[aria-current="page"]' );
    expect( current ).toHaveLength( 1 );
    expect( current[ 0 ].textContent ).toBe( 'Kiosk' );

    // Nothing on the page points at the withdrawn index, in either spelling.
    const hrefs = Array.from( container.querySelectorAll( 'a' ) )
      .map( a => a.getAttribute( 'href' ) );
    expect( hrefs ).not.toContain( '/shop/' );
    expect( hrefs ).not.toContain( '/shop' );
    expect( screen.queryByRole( 'link', { name: 'All items in the shop' } ) ).toBeNull();
  } );
} );

describe( 'the contribution product is a payment vehicle, not a shop listing', () => {
  /**
   * T11, SPLIT BY SOURCE, and the split is the point rather than a formality.
   *
   * The contribution product MUST be visible in Wix, because the checkout refuses
   * `product.visible === false` - so `scripts/fetch-wix-catalog.js` picks it up and it would
   * otherwise appear at /shop/ with its own page and sitemap entry. The place to choose a
   * contribution is the "Contribute" block at the foot of a blog post, not a product page with an
   * "Amount" dropdown.
   *
   * `productType` and the three counts are read off the RAW snapshot entry, never off
   * `CONTRIBUTION_PRODUCT`: `interface ShopProduct` declares none of them, and `shop.ts`'s own
   * header records why the omission is deliberate - `productType` reads PHYSICAL on every product
   * in the snapshot, so surfacing it would put a false statement on five pages. The
   * `ShopProduct`-shaped assertions stay against the projection.
   *
   * WHAT THIS BLOCK STOPPED ASSERTING ON 2026-10-04, because it was pinning a retired assumption:
   * `raw.productType === 'DIGITAL'`, with a comment calling DIGITAL "what makes the checkout skip
   * the delivery address". The live `Contribute` product is PHYSICAL - a Wix digital product with
   * no downloadable file attached is not purchasable - and the delivery skip now keys on
   * contribution product IDENTITY in `checkout/handler.py:_v2_catalog_items`. Asserting the
   * product's Wix type would therefore fail against the real product AND push the next reader back
   * towards the rule that was removed. The identity-keyed property is asserted instead.
   */
  it( 'appears in neither SHOP_PRODUCTS nor the generated paths', async () => {
    expect( SHOP_PRODUCTS.some( product => product.slug === CONTRIBUTION_SLUG ) ).toBe( false );
    expect( shopProductBySlug( CONTRIBUTION_SLUG ) ).toBeNull();
    const result = await getStaticPaths( {} as never );
    const paths = ( result as unknown as { paths: { params: { slug: string } }[] } ).paths;
    expect( paths.some( entry => entry.params.slug === CONTRIBUTION_SLUG ) ).toBe( false );
    // `generate-sitemap.js` crawls the BUILT output tree, so removing the page removes the entry.
    // No sitemap change is needed and this is the concrete fact behind that.
    expect( paths.length ).toBe( SHOP_PRODUCTS.length );
  } );

  it( 'is excluded by PRODUCT ID, not only by slug', () => {
    // The id is the identity the server, the cart and `shop.ts` all key on, and it cannot be
    // edited in the Wix dashboard. The slug can, so a slug-only exclusion would put a
    // /shop/<renamed>/ page live the next time somebody tidied the product's URL.
    const shopSource = fs.readFileSync(
      path.resolve( __dirname, '../content/shop.ts' ), 'utf8' );
    expect( shopSource ).toMatch( /CONTRIBUTION_PRODUCT_ID/ );
    expect( SHOP_PRODUCTS.some( product => product.id === CONTRIBUTION_PRODUCT_ID ) ).toBe( false );
  } );

  it( 'projects through the SAME function the shop listings use', () => {
    // So the excluded entry is a real `ShopProduct` and not a raw snapshot row mislabelled as one.
    // Driven from an injected fixture row, because the committed snapshot may not carry the entry.
    const projected = projectForTest( {
      id: CONTRIBUTION_PRODUCT_ID,
      name: 'Contribute',
      slug: CONTRIBUTION_SLUG,
      formattedPrice: '\u20B9100.00',
      price: '100.00',
      currency: 'INR',
      inStock: true,
      visible: true,
      descriptionHtml: '<p>Support this work.</p><p>Thank you.</p>',
      variants: CONTRIBUTION_CHOICES.map( choice => ( {
        id: choice.variantId, label: `\u20B9${ choice.rupees }`, inStock: true } ) ),
    } );
    expect( projected.tagline ).toBe( 'Support this work.' );
    expect( projected.body ).toEqual( [ 'Thank you.' ] );
    expect( projected.variants ).toHaveLength( 3 );
    expect( projected.variants?.every( variant => variant.inStock ) ).toBe( true );
  } );

  it.skipIf( CONTRIBUTION_RAW !== null )(
    'is absent from the committed snapshot, which costs the feature nothing', () => {
      // SKIPPED-WITH-REASON once the snapshot carries the entry: this case and the next are two
      // halves of one question and exactly one of them is meaningful at a time.
      //
      // Absence is NOT a configuration problem any more, which is the change from the previous
      // revision: the product id and the three variant ids are committed constants in
      // src/config/contribution.ts, because `slim()` in scripts/fetch-wix-catalog.js emits no
      // `variants` array and so a refresh could never supply them. All the snapshot entry buys is
      // the /shop/ exclusion, which only matters once the entry exists.
      expect( CONTRIBUTION_RAW ).toBeNull();
      expect( CONTRIBUTION_PRODUCT ).toBeNull();
      expect( CONTRIBUTION_CONFIGURED ).toBe( true );
    } );

  it.skipIf( CONTRIBUTION_RAW === null )(
    'carries the invariant fields the checkout depends on', () => {
      const raw = CONTRIBUTION_RAW as Record<string, unknown>;
      expect( raw.visible ).toBe( true );
      // THE DELIVERY SKIP DOES NOT COME FROM `productType`, and this is where that is pinned.
      // The live product is PHYSICAL; what makes the checkout skip the address is the line's
      // product id being in the recognised contribution set. So the identity is asserted and the
      // Wix type deliberately is not - the server is free to see either one.
      expect( String( raw.id ).toLowerCase() ).toBe( CONTRIBUTION_PRODUCT_ID );
      // Three variants, one option, no modifiers: an invariant of THIS product, not of the
      // catalogue. The option is the "Amount" chooser and its three choices are the three prices,
      // which is why a contribution line MUST carry an explicit variantId - with three variants
      // there is no single-variant fallback and Wix answers "choose an available product option".
      expect( [ raw.variantCount, raw.optionCount, raw.modifierCount ] ).toEqual( [ 3, 1, 0 ] );
      // The cheapest and dearest choices, so a changed price in Wix is caught here rather than by
      // a customer. `price` is the minimum of the range and `priceMax` the maximum.
      expect( raw.price ).toBe( `${ CONTRIBUTION_CHOICES[ 0 ].rupees }.00` );
      expect( raw.priceMax ).toBe(
        `${ CONTRIBUTION_CHOICES[ CONTRIBUTION_CHOICES.length - 1 ].rupees }.00` );
    } );

  it( 'needs a product id AND three variant ids to count as configured', () => {
    // A product id with no variant id would mint a cart line that reaches
    // `normalized_catalog_items`' single-variant fallback -- the guess the explicit variant exists
    // to avoid -- and answers a 502 on this three-variant product.
    expect( CONTRIBUTION_CONFIGURED ).toBe(
      !!CONTRIBUTION_PRODUCT_ID
      && CONTRIBUTION_CHOICES.length > 0
      && CONTRIBUTION_CHOICES.every( choice => !!choice.variantId ) );
    expect( CONTRIBUTION_CONFIGURED ).toBe( true );
  } );
} );
describe( "the Wix template's own sample products are not this storefront", () => {
  /*
   * Owner decision, 2026-10-05. The migrated site c993128b was created from a store template and
   * came with twelve demo products already in its catalogue, so the refreshed snapshot carries 21
   * rows where the previous one carried 9. They are excluded from `SHOP_PRODUCTS` rather than
   * deleted from Wix or stripped from the snapshot, which is what makes the decision reversible:
   * publishing one is deleting a line from the list in shop.ts.
   *
   * This matters on a SCHEDULE, not just once: .github/workflows/catalogue-sync.yml rewrites
   * wix-catalog.json unattended, so an exclusion that lived in the snapshot would be undone by the
   * next sync without anybody looking. It lives in code for that reason.
   */
  it( 'keeps all twelve out of the shop, and out of the built routes', async () => {
    const result = await getStaticPaths( {} as never );
    const paths = ( result as unknown as { paths: { params: { slug: string } }[] } ).paths
      .map( entry => entry.params.slug );
    for ( const slug of WIX_TEMPLATE_SAMPLE_SLUGS ) {
      expect( SHOP_PRODUCTS.some( product => product.slug === slug ), slug ).toBe( false );
      expect( paths.includes( slug ), `${slug} would get a /shop/ page` ).toBe( false );
      expect( shopProductBySlug( slug ), slug ).toBeNull();
    }
    expect( WIX_TEMPLATE_SAMPLE_SLUGS ).toHaveLength( 12 );
    expect( WIX_TEMPLATE_SAMPLE_PRODUCT_IDS ).toHaveLength( 12 );
  } );
  it( 'excludes them by PRODUCT ID as well as by slug', () => {
    // Same reasoning as the contribution exclusion above: the slug is editable in the Wix
    // dashboard and the id is not, so a slug-only list would publish a demo product the next time
    // somebody renamed its URL.
    for ( const id of WIX_TEMPLATE_SAMPLE_PRODUCT_IDS ) {
      expect( SHOP_PRODUCTS.some( product => product.id.toLowerCase() === id ), id ).toBe( false );
    }
  } );
  it( 'still carries every one of them in the committed snapshot', () => {
    // The rows are NOT removed from wix-catalog.json. The snapshot stays a faithful read of the
    // live catalogue -- `scripts/fetch-wix-catalog.js` would re-add them anyway -- and the shop is
    // what filters. A test that passed by them being absent would pass for the wrong reason.
    const rows = ( catalog as { products?: { id?: string; slug?: string }[] } ).products || [];
    for ( const id of WIX_TEMPLATE_SAMPLE_PRODUCT_IDS ) {
      expect( rows.some( row => String( row.id ).toLowerCase() === id ), id ).toBe( true );
    }
  } );
  it( 'leaves the real listings and the contribution vehicle untouched', () => {
    // The seven services are PRESENT, asserted as a lower bound rather than as a closed list, for
    // the same reason the derived check above is derived: a closed list is a hand edit every time
    // the owner adds a product. What this pins is that the exclusion took out the template's
    // samples and nothing else.
    for ( const slug of [ 'file-assist', 'guided-resolution', 'kiosk', 'merchandise', 'paperwork',
      'referral-partner', 'viveka' ] ) {
      expect( SHOP_PRODUCTS.some( product => product.slug === slug ), slug ).toBe( true );
    }
    // Exactly the visible rows, less the contribution vehicle, less the twelve samples.
    const visible = ( ( catalog as { products?: { slug?: string; name?: string;
      visible?: boolean }[] } ).products || [] )
      .filter( row => row.visible !== false && !!row.slug && !!row.name );
    expect( SHOP_PRODUCTS.length ).toBe( visible.length - 1 - WIX_TEMPLATE_SAMPLE_SLUGS.length );
    expect( SHOP_PRODUCTS.some( product => product.slug === CONTRIBUTION_SLUG ) ).toBe( false );
    expect( CONTRIBUTION_PRODUCT?.slug ).toBe( CONTRIBUTION_SLUG );
  } );
} );
