import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = process.cwd();
const read = ( relative: string ): string =>
  fs.readFileSync( path.join( ROOT, relative ), 'utf8' );

/**
 * Step 3 public-hero contract.
 *
 * Home stays the frozen reference surface and keeps its inline home hero. Every other
 * public HTML route must reach the shared RotatingHero either directly or through one
 * of the approved shared page views below. The marker is intentionally the component
 * boundary rather than page copy, so each route remains free to own its own title,
 * subtitle, rotating words and visual/content.
 */
const CANONICAL_ROUTES: Array<[ string, string, string ]> = [
  [ '/', 'src/pages/index.tsx', 'RotatingPill' ],
  [ '/contact/', 'src/pages/contact.tsx', '<RotatingHero' ],
  [ '/blog/', 'src/pages/blog/index.tsx', 'BlogIndexView' ],
  [ '/shop/', 'src/pages/shop/index.tsx', 'ShopListingView' ],
  [ '/orders/', 'src/pages/orders.tsx', 'OrdersPage' ],
  [ '/grahak-os/', 'src/pages/grahak-os/index.tsx', '<RotatingHero' ],
  [ '/vayulok/', 'src/pages/vayulok/index.tsx', '<RotatingHero' ],
  [ '/bharat-rx/', 'src/pages/bharat-rx.tsx', '<RotatingHero' ],
  [ '/elsewhere/visa/', 'src/pages/elsewhere/visa.tsx', 'ProductPage' ],
  [ '/elsewhere/trip/', 'src/pages/elsewhere/trip.tsx', 'ProductPage' ],
  [ '/elsewhere/activities/', 'src/pages/elsewhere/activities.tsx', 'ProductPage' ],
  [ '/dastavez/drafting/', 'src/pages/dastavez/drafting.tsx', 'ProductPage' ],
  [ '/dastavez/registration/', 'src/pages/dastavez/registration.tsx', 'ProductPage' ],
  [ '/dastavez/legal-reference/', 'src/pages/dastavez/legal-reference.tsx', 'ProductPage' ],
  [ '/ritual-guru/ritva/', 'src/pages/ritual-guru/ritva.tsx', 'ProductPage' ],
  [ '/ritual-guru/puja-guidance/', 'src/pages/ritual-guru/puja-guidance.tsx', 'ProductPage' ],
  [ '/ritual-guru/diy-puja-kit/', 'src/pages/ritual-guru/diy-puja-kit.tsx', 'ProductPage' ],
  [ '/hunar/kaushal/', 'src/pages/hunar/kaushal.tsx', 'ProductPage' ],
  [ '/hunar/prastuti/', 'src/pages/hunar/prastuti.tsx', 'ProductPage' ],
  [ '/shipments/track/', 'src/pages/shipments/track.tsx', 'ProductPage' ],
  [ '/expo-week/', 'src/pages/expo-week.tsx', 'ProductPage' ],
  [ '/anew/', 'src/pages/anew.tsx', 'ProductPage' ],
  [ '/niji-setu/', 'src/pages/niji-setu.tsx', 'ProductPage' ],
  [ '/submit-request/', 'src/pages/submit-request.tsx', 'ProductPage' ],
  [ '/request-amendment/', 'src/pages/request-amendment.tsx', 'ProductPage' ],
  [ '/drop-docs/', 'src/pages/drop-docs.tsx', 'ProductPage' ],
  [ '/vault/', 'src/pages/vault.tsx', 'ProductPage' ],
  [ '/request-pickup/', 'src/pages/request-pickup.tsx', 'ProductPage' ],
  [ '/leave-review/', 'src/pages/leave-review.tsx', 'ProductPage' ],
  [ '/privacy/', 'src/pages/privacy.tsx', '<RotatingHero' ],
  [ '/terms/', 'src/pages/terms.tsx', '<RotatingHero' ],
];

const SHARED_FAMILIES: Array<[ string, string, string ]> = [
  [ '/post/<slug>/', 'src/pages/post/[slug].tsx', '<RotatingHero' ],
  [ '/blog/page/<page>/', 'src/pages/blog/page/[page].tsx', 'BlogIndexView' ],
  [ '/blog/topic/<topic>/', 'src/pages/blog/topic/[topic].tsx', 'BlogIndexView' ],
  [ '/blog/topic/<topic>/page/<page>/', 'src/pages/blog/topic/[topic]/page/[page].tsx', 'BlogIndexView' ],
  [ '/shop/page/<page>/', 'src/pages/shop/page/[page].tsx', 'ShopListingView' ],
  [ '/shop/<slug>/', 'src/pages/shop/[slug].tsx', '<RotatingHero' ],
  [ '/account/sign-in/', 'src/pages/account/sign-in.tsx', 'SignInPage' ],
  [ '/cart/', 'src/pages/cart.tsx', 'CartPage' ],
  [ '/checkout/status/', 'src/pages/checkout/status.tsx', '<RotatingHero' ],
  [ '/checkout/success/', 'src/pages/checkout/success.tsx', '<RotatingHero' ],
  [ '/get/', 'src/pages/get.tsx', 'GetPage' ],
];

const SHARED_HERO_OWNERS = [
  'src/components/ProductPage.tsx',
  'src/components/BlogIndexView.tsx',
  'src/components/ShopListingView.tsx',
  'src/components/orders/OrdersPage.tsx',
  'src/components/cart/CartPage.tsx',
  'src/components/account/SignInPage.tsx',
  'src/components/get/GetPage.tsx',
];

describe( 'Step 3 public hero route matrix', () => {
  it( 'keeps the canonical route inventory complete', () => {
    expect( CANONICAL_ROUTES ).toHaveLength( 31 );
  } );

  it.each( CANONICAL_ROUTES )( '%s reaches the intended hero owner', ( route, file, marker ) => {
    expect( read( file ), `${route} must keep its hero owner` ).toContain( marker );
  } );

  it.each( SHARED_FAMILIES )( '%s reaches the intended shared hero owner', ( route, file, marker ) => {
    expect( read( file ), `${route} must keep its hero owner` ).toContain( marker );
  } );

  it.each( SHARED_HERO_OWNERS )( '%s mounts RotatingHero', file => {
    expect( read( file ) ).toContain( '<RotatingHero' );
  } );

  it( 'keeps Home frozen as the inline reference rather than migrating it into RotatingHero', () => {
    const home = read( 'src/pages/index.tsx' );
    expect( home ).toContain( '<RotatingPill' );
    expect( home ).not.toContain( '<RotatingHero' );
  } );

  it( 'keeps Grahak OS on the shared hero without removing its bespoke visual', () => {
    const grahak = read( 'src/pages/grahak-os/index.tsx' );
    expect( grahak ).toContain( '<RotatingHero' );
    expect( grahak ).toContain( 'insideMain' );
    expect( grahak ).toContain( 'visual={' );
  } );

  it( 'gives the post family page-specific hero supporting copy', () => {
    const post = read( 'src/pages/post/[slug].tsx' );
    expect( post ).toContain( "const description = post.metaDescription || post.excerpt || '';" );
    expect( post ).toContain( 'sub={ description }' );
    expect( post ).toContain( 'ariaLabel={ post.title }' );
  } );
} );
