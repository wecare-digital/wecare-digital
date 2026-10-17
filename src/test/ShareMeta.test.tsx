import { CONTRIBUTE_CTA_HREF } from '../config/contribution';
import PublicShare from '../components/PublicShare';
import fs from 'fs';
import path from 'path';
import React from 'react';
import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import BlogIndex from '../pages/blog/index';
import BlogPostPage from '../pages/post/[slug]';
import {
  MEDIA_BASE, SOCIAL_CARD_URL, SOCIAL_CARD_W, SOCIAL_CARD_H, SHARE_CARD_TYPE, whatsappShareHref,
} from '../config/share';
import { toBlogCard, type PublicBlogPost } from '../lib/public-blog';

/**
 * LINK PREVIEWS, AND THE SHARE CONTROLS.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * /blog/ and /post/<slug>/ shipped no og:image at all, and the post page asked for the small
 * twitter card. Measured on the live site before the change:
 *
 *   /                 og:image present   twitter:card summary_large_image
 *   /blog/            og:image MISSING   twitter:card MISSING
 *   /post/<slug>/     og:image MISSING   twitter:card summary   twitter:image MISSING
 *
 * The cause is the `!isContentPublic` gate in pages/_app.tsx, which suppresses the sitewide Head
 * for the five content routes because they declare their own - and theirs declared no image. It
 * is the same gate that once swallowed the favicon, which is why this is asserted rather than
 * left to a comment: the next route added to that gate will have the same hole.
 *
 * The head is rendered through a mocked next/head so the tags land in the container, the way
 * BlogDesign.test.tsx already does it.
 */

vi.mock( 'next/head', () => ( { default: ( { children }: { children: React.ReactNode } ) => <>{ children }</> } ) );

const samplePost: PublicBlogPost = {
  id: 'post-1',
  title: 'A Clear Question Can Change the Work',
  slug: 'a-clear-question-can-change-the-work',
  excerpt: 'A short excerpt.',
  url: '/post/a-clear-question-can-change-the-work',
  category: 'Conversations',
  tags: [ 'Practice' ],
  authorName: 'Anew by WECARE.DIGITAL',
  publishedDate: '2026-09-27T00:00:00Z',
  seoTitle: 'A Clear Question Can Change the Work | WECARE.DIGITAL',
  metaDescription: 'A meta description.',
  robots: 'index, follow',
};

const card = toBlogCard( samplePost );

/**
 * READ FROM THE DOCUMENT, NOT THE RENDER CONTAINER - and that is React 19, not a mistake.
 *
 * React 19 hoists document metadata: a meta, title or link rendered anywhere in a tree is moved
 * into document.head. So with next/head mocked out to render its children inline, these tags do
 * not stay in the container the way the JSON-LD script tags do - scripts without async are not
 * hoisted, which is why asserting on those from the container works and this does not.
 *
 * Querying the document is therefore correct rather than lax. The risk it carries is a tag
 * lingering between cases, and the og:type assertions are what cover it: the blog index must say
 * "website" and the post must say "article", so a leaked tag from either test fails the other.
 */
const metaOf = ( _container: HTMLElement, key: string ) =>
  document.querySelector( `meta[property="${key}"]` )?.getAttribute( 'content' )
  ?? document.querySelector( `meta[name="${key}"]` )?.getAttribute( 'content' )
  ?? null;

/** The tag set every shareable public surface has to carry. */
const expectShareCard = ( container: HTMLElement ) => {
  expect( metaOf( container, 'og:image' ) ).toBe( SOCIAL_CARD_URL );
  expect( metaOf( container, 'og:image:secure_url' ) ).toBe( SOCIAL_CARD_URL );
  expect( metaOf( container, 'og:image:width' ) ).toBe( SOCIAL_CARD_W );
  expect( metaOf( container, 'og:image:height' ) ).toBe( SOCIAL_CARD_H );
  expect( metaOf( container, 'og:image:type' ) ).toBe( 'image/png' );
  expect( metaOf( container, 'og:image:alt' ) ).toBeTruthy();
  expect( metaOf( container, 'og:site_name' ) ).toBe( 'WECARE.DIGITAL' );
  // The card type comes from the same module as the image, because the two have to agree about
  // shape: "summary" frames a 1:1 image, summary_large_image centre-crops it.
  expect( metaOf( container, 'twitter:card' ) ).toBe( SHARE_CARD_TYPE );
  expect( metaOf( container, 'twitter:image' ) ).toBe( SOCIAL_CARD_URL );
};

describe( 'Share previews', () => {
  it( 'gives the blog index a full link-preview card, which it had none of', () => {
    const { container } = render(
      <BlogIndex posts={ [ card ] } page={ 1 } totalPages={ 1 } totalPosts={ 1 }
        categories={ [ 'Conversations' ] } categoryCounts={ { Conversations: 1 } }
        activeCategory="Conversations" defaultCategory="Conversations" />
    );
    expectShareCard( container );
    expect( metaOf( container, 'og:type' ) ).toBe( 'website' );
  } );

  it( 'gives a post the same card, and declares itself an article', () => {
    const { container } = render( <BlogPostPage post={ samplePost } /> );
    expectShareCard( container );
    expect( metaOf( container, 'og:type' ) ).toBe( 'article' );
    // og:url has to be the canonical, not a path: a share target handed a relative URL shares
    // nothing, and a crawler resolves it against whatever page it found the link on.
    expect( metaOf( container, 'og:url' ) ).toBe( `https://wecare.digital/post/${samplePost.slug}/` );
  } );

  /**
   * THE DRIFT GUARD config/share.ts PROMISES.
   *
   * pages/_app.tsx keeps its own copies of these literals because BrandAssets.test.ts pins them
   * to that file by source string, and moving them would mean rewriting six assertions for no
   * behavioural gain. The cost of that decision is two declarations of one value, so this holds
   * them equal - if someone repoints the card in one place the other fails here rather than
   * silently serving two different images to two halves of the site.
   */
  it( 'keeps the card in config/share.ts identical to the copy in _app.tsx', () => {
    const app = fs.readFileSync(
      path.join( __dirname, '..', 'pages', '_app.tsx' ), 'utf8'
    );
    expect( app ).toContain( `const MEDIA_BASE = '${MEDIA_BASE}'` );
    // _app.tsx aliases its share image to LOGO_URL rather than restating the filename, so there is
    // one place in that file where the asset is named.
    expect( app ).toContain( 'const SOCIAL_CARD_URL = LOGO_URL;' );
    expect( app ).toContain( 'const LOGO_URL = `${MEDIA_BASE}/wecare-digital.png`' );
    expect( app ).toContain( `const SOCIAL_CARD_W = '${SOCIAL_CARD_W}'` );
    expect( app ).toContain( `const SOCIAL_CARD_H = '${SOCIAL_CARD_H}'` );
    // And the shared module resolves to the same absolute URL the marketing branch emits.
    expect( SOCIAL_CARD_URL ).toBe( 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png' );
  } );

  /**
   * THE PAIRING INVARIANT, which is the thing that actually prevents a broken preview.
   *
   * The share image and the Twitter card type have to agree about shape. A 1:1 image in a
   * summary_large_image slot is centre-cropped top and bottom - that is what once cut the ends off
   * this mark - and a 1.91:1 image in a "summary" slot is squeezed into a small square instead of
   * getting the wide frame it was designed for. Either mistake is one careless edit away, because
   * the two values look unrelated.
   *
   * So this asserts the RELATIONSHIP rather than the values: if the declared image is square the
   * card must be "summary", and if it is not square the card must be the large one. Swapping the
   * asset later is then a change this test either accepts or explains.
   */
  it( 'keeps the card type agreeing with the share image shape', () => {
    const square = SOCIAL_CARD_W === SOCIAL_CARD_H;
    expect( SHARE_CARD_TYPE ).toBe( square ? 'summary' : 'summary_large_image' );

    // And whatever the shape, it stays inside WhatsApp's stated limits: at least 300px wide, and
    // an aspect ratio no wider than 4:1.
    const w = Number( SOCIAL_CARD_W );
    const h = Number( SOCIAL_CARD_H );
    expect( w ).toBeGreaterThanOrEqual( 300 );
    expect( w / h ).toBeLessThanOrEqual( 4 );
  } );

  /**
   * THE STAGED WIDE CARD STAYS FIT FOR PURPOSE, even though nothing currently points at it.
   *
   * docs/brand/wd-brand-16x9.png is the 1200x675 / 273 KB re-export of the designed card - mark,
   * wordmark and tagline - kept as the documented way back to a wide preview if the S3 upload is
   * ever done. It is a fallback, not the live asset: the share image is the square icon, which
   * needs no upload.
   *
   * This used to assert the file's pixels equalled SOCIAL_CARD_W/H. That coupling is now wrong and
   * was removed - tying the live declaration to an asset the site does not use would fail the
   * moment the icon was adopted, which is exactly what happened. What is still worth holding is
   * that the staged file remains VALID, so whoever picks it up later is not inheriting a broken
   * one: a real PNG, inside both weight ceilings, past the minimum width, under the aspect limit,
   * and opaque.
   *
   * Parsed by hand rather than with an image library: a PNG's IHDR is the first chunk after the
   * 8-byte signature and width and height are big-endian uint32s at offsets 16 and 20. No
   * dependency for four bytes.
   */
  it( 'keeps the staged wide-card fallback valid, opaque and inside WhatsApp limits', () => {
    const file = path.join( __dirname, '..', '..', 'docs', 'brand', 'wd-brand-16x9.png' );
    const bytes = fs.readFileSync( file );

    expect( bytes.subarray( 0, 8 ).toString( 'hex' ) ).toBe( '89504e470d0a1a0a' ); // PNG signature
    expect( bytes.subarray( 12, 16 ).toString( 'ascii' ) ).toBe( 'IHDR' );
    const width = bytes.readUInt32BE( 16 );
    const height = bytes.readUInt32BE( 20 );

    // Meta's documented ceiling, and the working one that accounts for a silent drop.
    expect( bytes.length ).toBeLessThan( 600 * 1024 );
    expect( bytes.length ).toBeLessThan( 300 * 1024 );
    // Their stated minimum width, and the 4:1 aspect ceiling.
    expect( width ).toBeGreaterThanOrEqual( 300 );
    expect( width / height ).toBeLessThanOrEqual( 4 );
    // It is the WIDE one - if this ever became square it would no longer be the thing the README
    // describes, and adopting it would need the card type changed as well.
    expect( width ).toBeGreaterThan( height );

    // OPAQUE. The binding rule for anything handed to a renderer we do not control is that it must
    // not rely on alpha - Apple and the preview services flatten it to black and the mark is
    // light. A palette PNG carries transparency in a tRNS chunk, so its absence is the check.
    expect( bytes.includes( Buffer.from( 'tRNS', 'ascii' ) ) ).toBe( false );
  } );
} );

describe( 'Share controls', () => {
  /**
   * api.whatsapp.com, NOT wa.me. wa.me is built around wa.me/<number> and serves an error page
   * when called without one - and a share button cannot know the recipient, which is the whole
   * reason the reader is being shown a contact picker. Asserted because the two hosts look
   * interchangeable and only one of them works for this job.
   */
  it( 'builds a WhatsApp link that opens a contact picker rather than an error page', () => {
    const href = whatsappShareHref( 'A & B', 'https://wecare.digital/post/x/' );
    expect( href.startsWith( 'https://api.whatsapp.com/send?text=' ) ).toBe( true );
    expect( href ).not.toContain( 'wa.me' );
    // One encoded text field, because WhatsApp has one message body - there is no url parameter.
    expect( href ).toContain( encodeURIComponent( 'A & B' ) );
    expect( href ).toContain( encodeURIComponent( 'https://wecare.digital/post/x/' ) );
    // The ampersand must not survive raw, or it ends the parameter and truncates the message.
    expect( href.split( '?text=' )[ 1 ] ).not.toContain( '&' );
  } );

} );

// The retired ShareLinks implementation is gone; keep its useful behavior coverage on PublicShare.
describe( 'current shared action dock', () => {
  afterEach( () => { vi.unstubAllGlobals(); } );

  it( 'opens a WhatsApp contact picker and labels every available share action', () => {
    const { container } = render( <PublicShare url="https://wecare.digital/post/x/" title="A Post" /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Share this page' } ) );
    const whatsapp = screen.getByRole( 'link', { name: 'Share this page on WhatsApp' } );
    expect( whatsapp ).toHaveAttribute( 'href', whatsappShareHref( 'A Post', 'https://wecare.digital/post/x/' ) );
    expect( whatsapp.getAttribute( 'rel' ) ).toContain( 'noopener' );
    for ( const action of container.querySelectorAll( 'button' ) ) {
      expect( action.getAttribute( 'aria-label' ) ).toBeTruthy();
    }
  } );

  it( 'keeps WhatsApp contribution live and refuses an unpriced website checkout path', () => {
    render( <PublicShare url="https://wecare.digital/post/x/" title="A Post" /> );
    expect( screen.getByText( /Contribute ₹250/ ) ).toBeInTheDocument();
    fireEvent.click( screen.getByRole( 'button', { name: /Contribute ₹/ } ) );
    expect( screen.getByRole( 'link', { name: 'Contribute on WhatsApp' } ) )
      .toHaveAttribute( 'href', CONTRIBUTE_CTA_HREF );
    const website = screen.getByLabelText( 'Website contribution checkout unavailable' );
    expect( website ).toHaveAttribute( 'aria-disabled', 'true' );
    expect( website.textContent ).toContain( 'contribution SKU is live' );
  } );

  it( 'uses the native share sheet and clipboard only when supported', async () => {
    const share = vi.fn( async () => undefined );
    const writeText = vi.fn( async () => undefined );
    vi.stubGlobal( 'isSecureContext', true );
    vi.stubGlobal( 'navigator', Object.create( navigator, {
      share: { value: share, configurable: true },
      canShare: { value: () => true, configurable: true },
      clipboard: { value: { writeText }, configurable: true },
    } ) );
    render( <PublicShare url="https://wecare.digital/post/x/" title="A Post" /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Share this page' } ) );
    fireEvent.click( screen.getByRole( 'button', { name: 'Share this page using another app' } ) );
    expect( share ).toHaveBeenCalledWith( expect.objectContaining( { url: 'https://wecare.digital/post/x/', title: 'A Post' } ) );
    fireEvent.click( screen.getByRole( 'button', { name: 'Share this page' } ) );
    fireEvent.click( screen.getByRole( 'button', { name: 'Copy link to this page' } ) );
    await waitFor( () => expect( screen.getByRole( 'button', { name: 'Link copied' } ) ).toBeInTheDocument() );
    expect( writeText ).toHaveBeenCalledWith( 'https://wecare.digital/post/x/' );
  } );
} );
