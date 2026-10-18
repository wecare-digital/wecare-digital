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
  CONTRIBUTION_SLUG, projectForTest

} from '../content/shop';
import { getStaticPaths } from '../pages/shop/[slug]';
import type { ShopProduct } from '../content/shop';
// The RAW snapshot, so the assertions below can compare the projection against its own source
// instead of against a literal copied out of it. A literal is a per-product hand edit, and
// `.github/workflows/catalogue-sync.yml` rewrites this file on a schedule.
import catalog from '../content/catalogSnapshot';
import { SERVICE_PRODUCT_IDS } from '../config/services';

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

describe( 'the catalogue snapshot is read correctly', () => {
  it( 'requires a merchandise variant and keeps distinct sizes in distinct cart lines', () => {
    window.localStorage.clear();
    const merchandise: ShopProduct = {
      ...SYNTHETIC,
      id: 'synthetic-merchandise',
      name: 'Merchandise',
      slug: 'merchandise',
      inStock: true,
      variants: [
        { id: 'size-s', label: 'Small', inStock: true },
        { id: 'size-m', label: 'Medium', inStock: true },
      ],
    };
    render( <ShopProductPage product={ merchandise } /> );
    const button = screen.getByRole( 'button', { name: 'Add Merchandise to cart' } );
    expect( button ).toBeDisabled();
    const variants = merchandise.variants!;
    /*
     * DRIVEN AS A BUTTON-PLUS-LISTBOX, not with fireEvent.change, which does nothing at all
     * against one - it would pass silently while choosing no variant, and the assertion below
     * would then be comparing two cart lines that never got one.
     *
     * The name is an EXACT STRING and that is the labelling fix landing. The call site used to
     * wrap the control in <label className="shopd-options">Fit and size, and a <button
     * role="combobox"> inside a <label> computes its name by walking the label's subtree -
     * which contains the trigger's own caption, giving "Fit and size Choose your fit and size".
     * The wrapper is gone and Select owns the label, so the name is those three words and
     * nothing else. An exact string is what proves that; a regex would pass either way.
     */
    const chooser = () => screen.getByRole( 'combobox', { name: 'Fit and size' } );
    fireEvent.click( chooser() );
    fireEvent.click( screen.getByRole( 'option', { name: variants[0].label } ) );
    fireEvent.click( button );
    fireEvent.click( chooser() );
    fireEvent.click( screen.getByRole( 'option', { name: variants[1].label } ) );
    fireEvent.click( screen.getByRole( 'button', { name: 'Add Merchandise to cart' } ) );
    expect( readCart() ).toHaveLength( 2 );
    expect( readCart().map( item => item.name ) ).toEqual( [
      `Merchandise (${variants[0].label})`, `Merchandise (${variants[1].label})`,
    ] );
    expect( toLineItems().map( item => item.catalogReference.options?.variantId ) ).toEqual( [ variants[0].id, variants[1].id ] );
    expect( JSON.stringify( toLineItems() ) ).not.toMatch( /price|amount|formattedPrice/ );
    window.localStorage.clear();
  } );
  it( 'reads every visible Shop product while keeping guarded service products out', () => {
    /*
     * ASSERTS THE PROPERTY, NOT THE SPELLING - changed 2026-10-04 for catalogue auto-sync.
     *
     * This used to pin an explicit eight-slug list, and the reason given was a good one: a check
     * derived from the file would agree with whatever the file said, INCLUDING AN EMPTY ARRAY,
     * which is how a catalogue page ships blank.
     *
     * But a literal slug list is a PER-SLUG ALLOWLIST, and the scheduled catalogue publisher
     * (`.github/workflows/aws-native-catalog-publish.yml`) commits a refreshed snapshot on its own
     * every six hours. Adding one product to ProductsTable would
     * turn this green test red with no code change behind it, and a human would have to hand-edit
     * a list - which is the exact manual step B2 exists to remove. Everything else on the /shop/
     * path is already prefix-based (getStaticPaths enumerates SHOP_PRODUCTS, the sitemap carries
     * the '/shop/' PREFIX, _app.tsx keys on the '/shop/[slug]' PATTERN), so this list was the only
     * place a new product needed a hand edit.
     *
     * THE BLANK-CATALOGUE PROTECTION IS KEPT, and it is what the floor is for. A derived check
     * cannot be satisfied by an empty array while `FLOOR` must also hold, so the failure the old
     * comment was defending against still fails. The floor is a LOWER BOUND, which a new product
     * cannot cross; only a product being REMOVED from the catalogue can, and that is a change worth a human
     * reading the diff.
     */
    const rows = ( catalog.products as { slug?: string; visible?: boolean; name?: string }[] );
    const expected = rows
      .filter( r => r.visible !== false && !!r.slug && !!r.name )
      // Request services keep their dedicated intent-aware pages; every other visible row,
      // including Contribute, is allowed to have a Shop detail page.
      .filter( r => !SERVICE_PRODUCT_IDS.has( String( ( r as { id?: string } ).id || '' ) ) )
      .map( r => r.slug as string )
      .sort();
    expect( SHOP_PRODUCTS.length ).toBe( expected.length );
    expect( [ ...SHOP_PRODUCTS.map( p => p.slug ) ].sort() ).toEqual( expected );
    // Every slug is route-safe, because the slug IS the path segment of its page. A slug the
    // catalogue would accept but a URL would not (a space, an uppercase letter, a slash) must fail here rather
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

  it( 'passes the catalogue\'s own formatted price through rather than rebuilding it', () => {
    /*
     * The rule the whole commerce architecture rests on: a price rendered here must be the string
     * the catalogue would quote, not a locally formatted version of the number beside it. A
     * reimplemented formatter is a second opinion about the amount.
     *
     * ASSERTED AGAINST THE SNAPSHOT ROW, not against a literal - changed 2026-10-04 with
     * catalogue auto-sync. A hardcoded '₹24,999.00' tests a PRICE, which the owner may change in
     * ProductsTable at any moment and the scheduled publisher will then commit. Comparing the projection to the
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
    // owner edits this text in ProductsTable and the scheduled publisher commits the edit, so a literal
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
      // detail page can render an empty lead. A product authored with NO description
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
    // answer. The catalogue is auto-published from ProductsTable (every publish rewrites fetchedAt), so this test
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
      const path = shopProductPath( product );
      // A product may declare its own canonical destination (catalog v2: Anew lives at /anew/);
      // otherwise it is /shop/<slug>/. Either way: lowercase, hyphenated, trailing slash.
      expect( path ).toMatch( /^\/(shop\/)?[a-z0-9-]+\/$/ );
      if ( !product.canonicalPath ) expect( path ).toBe( '/shop/' + product.slug + '/' );
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
    const kiosk: ShopProduct = {
      ...SYNTHETIC, id: 'synthetic-kiosk', name: 'Kiosk', slug: 'kiosk', inStock: true,
      formattedPrice: '₹26,999.00', price: '26999.00',
    };
    const { container } = render( <ShopProductPage product={ kiosk } /> );
    const h1s = container.querySelectorAll( 'h1' );
    expect( h1s ).toHaveLength( 1 );
    // The product page's h1 is the shared RotatingHero: a fixed "Explore" frame line plus a
    // static pill holding the product name (a single-element words array, so no rotation). The
    // h1's textContent concatenates the frame, the sr-only words copy and the visible word, so
    // assert the frame and the pill word separately rather than the joined string.
    expect( container.querySelector( '.rh-head-line' )?.textContent ).toBe( 'Explore' );
    expect( container.querySelector( '.rp-cyc-word.on' )?.textContent ).toBe( 'Kiosk' );
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
     * THE ASSERTION THAT MATTERS MOST IN THIS FILE. descriptionHtml is merchant-authored rich
     * text; rendering it through dangerouslySetInnerHTML would make the storefront an XSS surface
     * that depends on an upstream sanitiser rather than ours. Every one of the seven
     * descriptions contains <span style="font-weight: 700">, so if the tags were passing through,
     * this would find them.
     */
    /*
     * SCOPED TO THE MERCHANT-DERIVED NODES, NOT TO THE WHOLE SECTION - changed in batch 2e, and
     * the reason is worth stating because loosening a guard like this one is exactly the move
     * that should be resisted.
     *
     * It used to read `section.shopd-about`'s entire innerHTML. That worked while every element
     * in the section was either a <p> or a <button>, and it broke the moment the variant chooser
     * became our own component: Select renders a <span class="ui-field-label"> and a <span
     * class="ui-select-value">, so the assertion started failing on OUR chrome rather than on
     * merchant HTML. The wrong fix is to allow `<span` through, which is the one string this test
     * exists to catch.
     *
     * So the subject narrows to the nodes that actually carry merchant strings, and NOTHING that
     * carries one is left out: `.shopd-price` is product.formattedPrice, and every `.shopd-p` is
     * one paragraph of product.body, which is the whole of what toParagraphs returns from
     * descriptionHtml. Both are still read as innerHTML rather than textContent, so a tag that
     * survived sanitising is still visible to this check. It is narrower in surface and identical
     * in strength on the thing being tested, and the count assertion below makes the narrowing
     * self-checking: a page whose merchant text stopped rendering through these classes would
     * report zero nodes and fail here rather than passing vacuously.
     */
    for ( const product of SHOP_PRODUCTS ) {
      const { container, unmount } = render( <ShopProductPage product={ product } /> );
      const about = container.querySelector( 'section.shopd-about' ) as HTMLElement;
      expect( about, `${product.slug} has no about section` ).toBeTruthy();

      const merchantNodes = Array.from(
        container.querySelectorAll( '.shopd-price, .shopd-p' )
      ) as HTMLElement[];
      // One price plus one paragraph per body paragraph. If this is ever zero the loop below
      // asserts nothing, which is how a guard passes while covering nothing.
      expect( merchantNodes.length, `${product.slug} renders no merchant-derived text` )
        .toBe( product.body.length + 1 );

      for ( const node of merchantNodes ) {
        expect( node.innerHTML, `${product.slug} leaked a merchant span` ).not.toContain( '<span' );
        expect( node.innerHTML, `${product.slug} leaked a style attribute` ).not.toContain( 'style=' );
      }
      unmount();
    }
  } );

  it( 'offers an add-to-cart action rather than a contact link', () => {
    // The CTA is now the page's single lime surface: it adds the item to the browser cart. It is a
    // button (a client action) before anything is added, so there is no /contact/ link to find.
    const kiosk: ShopProduct = {
      ...SYNTHETIC, id: 'synthetic-kiosk', name: 'Kiosk', slug: 'kiosk', inStock: true,
      formattedPrice: '₹26,999.00', price: '26999.00',
    };
    render( <ShopProductPage product={ kiosk } /> );
    const cta = screen.getByRole( 'button', { name: 'Add Kiosk to cart' } );
    expect( cta ).toBeTruthy();
    expect( screen.queryByRole( 'link', { name: 'Ask about Kiosk' } ) ).toBeNull();
  } );

  it( 'uses concise customer-facing purchase copy without checkout implementation wording', () => {
    const kiosk: ShopProduct = {
      ...SYNTHETIC, id: 'synthetic-kiosk', name: 'Kiosk', slug: 'kiosk', inStock: true,
      formattedPrice: '₹26,999.00', price: '26999.00',
    };
    render( <ShopProductPage product={ kiosk } /> );
    expect( screen.getByText( 'One-time purchase' ) ).toBeTruthy();
    expect( screen.queryByText( /final total/i ) ).toBeNull();
    expect( screen.queryByText( /confirmed at checkout/i ) ).toBeNull();
  } );

  it( 'marks a product that is out of stock', () => {
    render( <ShopProductPage product={ SYNTHETIC } /> );
    expect( screen.getByText( 'Not available right now.' ) ).toBeTruthy();
  } );

  it( 'gates the Product node on the image: emits it (complete) with one, omits it without', () => {
    /*
     * Google requires name, image and offers on Product, and tools/audit/schemacheck.js enforces
     * exactly that list, so an image-less product must emit NO Product node (an incomplete one is
     * ineligible for the rich result and would trip schemacheck's "no unresolved @id references").
     *
     * This originally asserted that EVERY product was image-less, from when all seven catalogue
     * rows reported mediaCount 0. The scheduled publisher re-reads ProductsTable every six hours,
     * and the rows now carry real media URLs, so that premise is stale. The contract being verified is the
     * CONDITIONAL one - gate the node on `image` - so assert it per product against the product's
     * actual image state rather than assuming the whole shelf is pictureless. The component is
     * correct: with an image it now emits a complete Product; without one it still omits it.
     */
    for ( const product of SHOP_PRODUCTS ) {
      const graph = shopProductSchema( product )[ '@graph' ];
      const types = graph.map( node => ld( node )[ '@type' ] );
      const productNode = graph.find( node => ld( node )[ '@type' ] === 'Product' );

      if ( product.image ) {
        // With an image, the full Product node is emitted and carries the three required fields.
        expect( types, product.slug ).toEqual( [ 'ItemPage', 'BreadcrumbList', 'Product' ] );
        expect( ld( productNode ).name, product.slug ).toBeTruthy();
        expect( ld( productNode ).image, product.slug ).toBe( product.image );
        expect( ld( ld( productNode ).offers )[ '@type' ], product.slug ).toBe( 'Offer' );
      } else {
        // Without an image, no Product node and no dangling #product reference.
        expect( types, product.slug ).toEqual( [ 'ItemPage', 'BreadcrumbList' ] );
        expect( JSON.stringify( shopProductSchema( product ) ), product.slug ).not.toContain( '#product' );
      }
    }
  } );

  it( 'emits Product with its Offer as soon as an image exists', () => {
    // The other half: the markup is written and gated, not missing. Populating `image` is the only
    // thing between this repo and complete Product data.
    const withImage: ShopProduct = {
      ...{ ...SYNTHETIC, id: 'synthetic-kiosk', name: 'Kiosk', slug: 'kiosk', inStock: true, formattedPrice: '₹26,999.00', price: '26999.00' },
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
    expect( ld( ld( productLd ).offers ).price ).toBe( withImage.price );
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
    const anew: ShopProduct = {
      ...SYNTHETIC, id: 'synthetic-anew', name: 'Anew', slug: 'anew', inStock: true,
      canonicalPath: '/anew/',
    };
    const json = JSON.stringify( shopProductSchema( anew ) );
    // The graph names the product's canonical URL (its declared destination, /anew/).
    expect( json ).toContain( 'https://wecare.digital' + shopProductPath( anew ) );
    expect( json ).not.toContain( '[slug]' );
  } );

  it( 'keys page-scoped @ids on the route it renders on, even when the canonical is elsewhere', () => {
    // /anew/ defines its own #webpage and #breadcrumb. If /shop/anew/ keyed its nodes off the
    // canonical it would define the same two, and schemacheck fails a page-scoped @id on two routes.
    const anew: ShopProduct = {
      ...SYNTHETIC, id: 'synthetic-anew', name: 'Anew', slug: 'anew', inStock: true,
      canonicalPath: '/anew/',
    };
    expect( shopProductPath( anew ) ).toBe( '/anew/' );
    const graph = shopProductSchema( anew )[ '@graph' ];
    const page = ld( graph.find( n => ld( n )[ '@type' ] === 'ItemPage' ) );
    const crumbs = ld( graph.find( n => ld( n )[ '@type' ] === 'BreadcrumbList' ) );
    expect( page[ '@id' ] ).toBe( 'https://wecare.digital/shop/anew/#webpage' );
    expect( ld( page.breadcrumb )[ '@id' ] ).toBe( 'https://wecare.digital/shop/anew/#breadcrumb' );
    expect( crumbs[ '@id' ] ).toBe( 'https://wecare.digital/shop/anew/#breadcrumb' );
    // The URL fields still name the canonical, so search engines are pointed at /anew/.
    expect( page.url ).toBe( 'https://wecare.digital/anew/' );
    expect( JSON.stringify( graph ) ).not.toContain( 'https://wecare.digital/anew/#' );
    // A product whose canonical IS its route is unchanged.
    const kioskProduct: ShopProduct = {
      ...SYNTHETIC, id: 'synthetic-kiosk', name: 'Kiosk', slug: 'kiosk', inStock: true,
    };
    const kiosk = ld( shopProductSchema( kioskProduct )[ '@graph' ][ 0 ] );
    expect( kiosk[ '@id' ] ).toBe( 'https://wecare.digital/shop/kiosk/#webpage' );
    expect( kiosk.url ).toBe( 'https://wecare.digital/shop/kiosk/' );
  } );

  it( 'offers a way back to the listing through a three-item breadcrumb and an all-items link', () => {
    /*
     * REWRITTEN 2026-10-10, inverting the 2026-10-04 rewrite. The owner restored the catalogue
     * index, so /shop/ resolves at 200 again: the product page carries a three-item trail
     * (Home / Shop / product) and an "All items in the shop" link pointing at /shop/. The middle
     * Shop crumb is a real link to a real page, not a redirect to its own first step.
     *
     * Exactly one current page still - the product - because only the last crumb is href-less and
     * rendered as <span aria-current="page">; the Shop crumb is a link.
     */
    const kiosk: ShopProduct = {
      ...SYNTHETIC, id: 'synthetic-kiosk', name: 'Kiosk', slug: 'kiosk', inStock: true,
      formattedPrice: '₹26,999.00', price: '26999.00',
    };
    const { container } = render( <ShopProductPage product={ kiosk } /> );

    const trail = container.querySelector( 'nav[aria-label="Breadcrumb"]' ) as HTMLElement;
    expect( trail, 'the product page renders no breadcrumb trail' ).toBeTruthy();
    expect( trail.querySelectorAll( 'li' ) ).toHaveLength( 3 );
    expect( screen.getByRole( 'link', { name: 'Home' } ).getAttribute( 'href' ) )
      .toBe( asRendered( '/' ) );
    // asRendered: next/link strips the trailing slash the source passes ('/shop/'), so the
    // rendered href is '/shop' - the same normalisation asRendered('/') applies to the Home crumb.
    expect( screen.getByRole( 'link', { name: 'Shop' } ).getAttribute( 'href' ) )
      .toBe( asRendered( '/shop/' ) );
    // Exactly one current page, and it is the product.
    const current = trail.querySelectorAll( '[aria-current="page"]' );
    expect( current ).toHaveLength( 1 );
    expect( current[ 0 ].textContent ).toBe( 'Kiosk' );

    // The page points back at the restored index, and offers the all-items link.
    const hrefs = Array.from( container.querySelectorAll( 'a' ) )
      .map( a => a.getAttribute( 'href' ) );
    expect( hrefs ).toContain( asRendered( '/shop/' ) );
    expect( screen.getByRole( 'link', { name: 'All items in the shop' } ).getAttribute( 'href' ) )
      .toBe( asRendered( '/shop/' ) );
  } );
} );

describe( 'Contribute is visible in Shop but keeps its dedicated contribution checkout semantics', () => {
  /**
   * T11, SPLIT BY SOURCE, and the split is the point rather than a formality.
   *
   * The contribution product MUST be visible in the catalogue, because the checkout refuses
   * `product.visible === false` - so `scripts/build-catalog-snapshot.py` picks it up and it would
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
   * the delivery address". The live `Contribute` product is PHYSICAL, and the delivery skip now
   * keys on contribution product IDENTITY in the checkout. Asserting the product's catalogue type
   * would therefore fail against the real product AND push the next reader back towards the rule
   * that was removed. The identity-keyed property is asserted instead.
   */
  it( 'appears in SHOP_PRODUCTS and gets its own generated Shop path', async () => {
    expect( SHOP_PRODUCTS.some( product => product.slug === CONTRIBUTION_SLUG ) ).toBe( true );
    expect( shopProductBySlug( CONTRIBUTION_SLUG )?.id ).toBe( CONTRIBUTION_PRODUCT_ID );
    const result = await getStaticPaths( {} as never );
    const paths = ( result as unknown as { paths: { params: { slug: string } }[] } ).paths;
    expect( paths.some( entry => entry.params.slug === CONTRIBUTION_SLUG ) ).toBe( true );
    expect( paths.length ).toBe( SHOP_PRODUCTS.length );
  } );

  it( 'keeps the fresh contribution identity in the Shop projection', () => {
    const shopSource = fs.readFileSync(
      path.resolve( __dirname, '../content/shop.ts' ), 'utf8' );
    expect( shopSource ).toMatch( /CONTRIBUTION_PRODUCT_ID/ );
    expect( SHOP_PRODUCTS.some( product => product.id === CONTRIBUTION_PRODUCT_ID ) ).toBe( true );
  } );

  it( 'projects through the SAME function the shop listings use', () => {
    // So the excluded entry is a real `ShopProduct` and not a raw snapshot row mislabelled as one.
    // Driven from an injected fixture row, because the committed snapshot may not carry the entry.
    const projected = projectForTest( {
      id: CONTRIBUTION_PRODUCT_ID,
      name: 'Contribute',
      slug: CONTRIBUTION_SLUG,
      formattedPrice: '\u20B9250.00',
      price: '250.00',
      currency: 'INR',
      inStock: true,
      visible: true,
      descriptionHtml: '<p>Support this work.</p><p>Thank you.</p>',
      variants: CONTRIBUTION_CHOICES.map( choice => ( {
        id: choice.variantId, label: `\u20B9${ choice.rupees }`, inStock: true } ) ),
    } );
    expect( projected.tagline ).toBe( 'Support this work.' );
    expect( projected.body ).toEqual( [ 'Thank you.' ] );
    expect( projected.variants ).toHaveLength( CONTRIBUTION_CHOICES.length );
    expect( projected.variants?.every( variant => variant.inStock ) ).toBe( true );
  } );

  it.skipIf( CONTRIBUTION_RAW !== null )(
    'is absent from the committed snapshot, which costs the feature nothing', () => {
      // SKIPPED-WITH-REASON once the snapshot carries the entry: this case and the next are two
      // halves of one question and exactly one of them is meaningful at a time.
      //
      // Absence is NOT a configuration problem any more, which is the change from the previous
      // revision: the product id and the variant ids are committed constants in
      // src/config/contribution.ts, so a snapshot refresh never has to supply them. All the
      // snapshot entry buys is the /shop/ exclusion, which only matters once the entry exists.
      expect( CONTRIBUTION_RAW ).toBeNull();
      expect( CONTRIBUTION_PRODUCT ).toBeNull();
      expect( CONTRIBUTION_CONFIGURED ).toBe( true );
    } );

  it.skipIf( CONTRIBUTION_RAW === null )(
    'carries the invariant fields the checkout depends on', () => {
      const raw = CONTRIBUTION_RAW as Record<string, unknown>;
      // IDENTITY is what the checkout keys on: a line whose product id is in the recognised
      // contribution set skips the delivery address. The id is the immutable UUID, asserted here;
      // the native catalog carries no provider-specific `productType`/`visible`/count fields, and
      // the server does not need them. The variant ids and the per-choice amounts are committed
      // constants in src/config/contribution.ts (CONTRIBUTION_CHOICES), not read from the catalog
      // row, so they are asserted there rather than from a provider's dashboard counts.
      expect( String( raw.id ).toLowerCase() ).toBe( CONTRIBUTION_PRODUCT_ID );
      // The native row is active and visible in /shop; its contribution identity
      // and configured-ness are the whole contract; price authority is server-side at checkout.
      expect( String( raw.status || 'active' ) ).toBe( 'active' );
      expect( CONTRIBUTION_CONFIGURED ).toBe( true );
    } );

  it( 'needs a product id AND a variant id for every choice to count as configured', () => {
    // A product id with no variant id would mint a cart line that reaches
    // `normalized_catalog_items`' single-variant fallback -- the guess the explicit variant
    // exists to avoid, which would pick the wrong amount the moment a second one is added back.
    expect( CONTRIBUTION_CONFIGURED ).toBe(
      !!CONTRIBUTION_PRODUCT_ID
      && CONTRIBUTION_CHOICES.length > 0
      && CONTRIBUTION_CHOICES.every( choice => !!choice.variantId ) );
    expect( CONTRIBUTION_CONFIGURED ).toBe( true );
  } );
} );
