import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = ( relative: string ) =>
  fs.readFileSync( path.resolve( process.cwd(), relative ), 'utf8' );

const ruleFor = ( source: string, selector: string ) => {
  const start = source.indexOf( selector );
  expect( start ).toBeGreaterThanOrEqual( 0 );
  const open = source.indexOf( '{', start );
  const close = source.indexOf( '}', open );
  expect( open ).toBeGreaterThan( start );
  expect( close ).toBeGreaterThan( open );
  return source.slice( start, close + 1 ).replace( /\s+/g, '' );
};

describe( 'WhatsApp subscribe CTA design', () => {
  /**
   * _app owns the one global PublicShare block. The post template owns neither the old inline
   * Subscribe pill nor a direct PublicShare mount; this also holds the shared dock's button contract.
   */
  it( 'removes the post page own Subscribe pill and keeps the contract on the global PublicShare', () => {
    const page = read( 'src/pages/post/[slug].tsx' );

    // The old inline Subscribe pill is gone, markup and CSS both.
    expect( page ).not.toContain( 'className="blog-wa-subscribe"' );
    expect( page ).not.toContain( '.blog-wa-subscribe{' );
    expect( page ).not.toContain( '<span>Subscribe</span>' );
    // The page does not mount the global block; _app does.
    expect( page ).not.toContain( '<PublicShare' );
    const app = read( 'src/pages/_app.tsx' );
    expect( app ).toContain( '<PublicShare />' );

    // Subscribe now shares the compact 48px circular action contract with Contribute and Share.
    const share = read( 'src/components/PublicShare.tsx' );
    const action = ruleFor( share, '.ps-action{' );
    const subscribe = ruleFor( share, '.ps-subscribe{' );
    expect( share ).toContain( 'aria-label="Subscribe on WhatsApp"' );

    expect( action ).toContain( 'width:48px' );
    expect( action ).toContain( 'height:48px' );
    expect( action ).toContain( 'border-radius:50%' );
    expect( action ).toContain( 'display:inline-flex' );
    expect( action ).toContain( 'align-items:center' );
    expect( action ).toContain( 'justify-content:center' );

    expect( subscribe ).toContain( 'background:var(--public-brand-lime)' );
    expect( subscribe ).toContain( 'border-color:var(--public-brand-green)' );
    expect( share ).toContain( '.ps-subscribe:hover{background:#fff}' );
    expect( share ).toContain(
      '.ps-action:focus-visible,.ps-menu-item:focus-visible{'
    );
  } );


  it( 'keeps the global Stay connected and share menus on the app-first readable type scale', () => {
    const share = read( 'src/components/PublicShare.tsx' );

    expect( ruleFor( share, '.ps-kicker{' ) ).toContain( 'font-size:17px' );
    expect( ruleFor( share, '.ps-tip{' ) ).toContain( 'font-size:14px' );
    expect( ruleFor( share, '.ps-menu-title{' ) ).toContain( 'font-size:18px' );
    expect( ruleFor( share, '.ps-menu-sub{' ) ).toContain( 'font-size:15px' );
    expect( ruleFor( share, '.ps-menu-name{' ) ).toContain( 'font-size:17px' );
    expect( ruleFor( share, '.ps-menu-note{' ) ).toContain( 'font-size:15px' );
  } );


  it( 'gives the contribution Checkout the shared Option B interaction states', () => {
    const share = read( 'src/components/PublicShare.tsx' );
    const checkout = ruleFor( share, '.contribute-link-btn{' );
    const hover = ruleFor( share, '.contribute-link-btn:hover:not(:disabled){' );
    const active = ruleFor( share, '.contribute-link-btn:active:not(:disabled){' );

    expect( share ).toContain( '<span className="ps-material">shopping_cart_checkout</span>' );
    expect( checkout ).toContain( 'border:2pxsolidtransparent' );
    expect( checkout ).toContain( 'border-radius:11px' );
    expect( checkout ).toContain( 'background:var(--public-accent-amber)' );
    expect( share ).toContain( '.contribute-link-btn .ps-menu-icon{background:transparent}' );
    expect( hover ).toContain( 'background:#fff' );
    expect( hover ).toContain( 'border-color:var(--public-accent-amber)' );
    expect( hover ).toContain( 'transform:translateY(-1px)' );
    expect( hover ).toContain( 'box-shadow:05px14pxrgba(240,168,24,.18),02px5pxrgba(26,58,42,.08)' );
    expect( active ).toContain( 'background:var(--public-accent-amber-tint)' );
    expect( active ).toContain( 'border-color:var(--public-accent-amber)' );
    expect( active ).toContain( 'box-shadow:none' );
    expect( share ).toContain( '.ps-action:focus-visible,.ps-menu-item:focus-visible{' );
  } );

  it( 'keeps the global action dock on the shared font, translation and RTL contracts', () => {
    const share = read( 'src/components/PublicShare.tsx' );
    const shell = ruleFor( share, '.public-share{' );
    const menu = ruleFor( share, '.ps-menu{' );
    const item = ruleFor( share, '.ps-menu-item{' );

    expect( shell ).toContain( 'font-family:var(--font-sans)' );
    expect( share ).not.toContain( 'className="ps-menu-title contribute-label" data-wc-no-translate="true"' );
    expect( menu ).toContain( 'inset-inline-start:0' );
    expect( item ).toContain( 'text-align:start' );
    expect( share ).toContain( 'inset-inline-start:50%' );
    expect( share ).toContain( '.ps-contribute-menu::before{inset-inline-start:18px}' );
    expect( share ).toContain( '.ps-share-menu::before{inset-inline-start:78px}' );
    expect( share ).toContain( '.ps-share-menu.has-contribute::before{inset-inline-start:138px}' );
    expect( share ).toContain( '.ps-chevron{display:inline-block;font-size:20px;color:rgba(26,58,42,.55);transform:scaleX(1);transform-origin:center}' );
    expect( share ).toContain( "html[dir='rtl'] .public-share .ps-chevron{transform:scaleX(-1)}" );
    expect( share ).toContain( '<style jsx global>{`' );
  } );


  it( 'keeps Subscribe, Contribute and Share out of the VayuLok Air card', () => {
    const source = read( 'src/components/VayuLokLive.tsx' );

    expect( source ).not.toContain( 'vl-live-air-subscribe' );
    expect( source ).not.toContain( 'SUBSCRIBE_CTA_HREF' );
    expect( source ).not.toContain( '<BlogContribution' );
    expect( source ).not.toContain( '<ShareLinks' );
    expect( source ).not.toContain( 'vl-live-air-extras' );
  } );

} );
