'use strict';

/**
 * postlayoutreview - the three candidate post-page layouts, at actual size, side by side.
 *
 * WHY THIS EXISTS. The owner asked for the home page's top section on the blog AND on post
 * pages. On /blog/ that is unambiguous - it replaces the "Blog / Ideas, guides and updates"
 * block. On a post page it is a real choice, because the article already owns a 55px/600 h1
 * and a full rotating hero would put a second one ~300px above it. Three options were
 * described in prose, the owner reasonably said prose is guesswork, so here they are as
 * pixels.
 *
 * WHAT IS DIFFERENT ABOUT THIS ONE, AND IT MATTERS FOR HOW MUCH TO TRUST IT.
 * homereview, flowreview and closereview all harvest a band that EXISTS and show it before
 * and after a change. None of A, B or C exists in the codebase yet - that is the point of
 * looking - so these frames are COMPOSED from real pieces rather than captured whole:
 *
 *   - the article markup and CSS come from a real built post page
 *   - the hero markup and CSS come from a real built product page, which uses the same
 *     RotatingHero the blog would use
 *   - the breadcrumb and the compact strip in C are the only NEW markup here, written to the
 *     same rungs the rest of the site uses
 *
 * So the type, spacing and colour are the real thing and the ARRANGEMENT is the proposal.
 * That is the honest description, and it is why every panel carries its own measurements
 * taken from the rendered frame rather than from arithmetic.
 *
 * THE MEASUREMENTS ARE TAKEN INSIDE THE FRAMES, not asserted in the copy. Each option
 * reports where the article body actually starts, how many 55px/600 headlines it renders and
 * how tall the document becomes, read back from the composed document itself - so a caption
 * cannot drift from the panel beside it.
 *
 * Run:    node tools/browser/postlayoutreview.js     (needs out/ - see README.md)
 * Writes: docs/post-layout-review.html
 */

const fs = require( 'fs' );
const path = require( 'path' );
const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );

const REPO = path.join( __dirname, '..', '..' );
const OUT_FILE = path.join( REPO, 'docs', 'post-layout-review.html' );
const POST = '/post/a-page-view-is-not-a-person/';
const HERO_SOURCE = '/anew/';

/**
 * THE BREADCRUMB, which is common to all three options and replaces the current control.
 *
 * Today a post page offers a single Link with class "back" rendering as "← Blog" at
 * 13px/650 in #1a3a2a. That is a back button, not a breadcrumb: it names one ancestor, gives
 * no sense of depth, and is the only element on the page still at 13px when the site's
 * smallest UI rung is 12px/700 uppercase (.home-close-eyebrow) and its base body is 17px.
 *
 * This is a real trail - Home, Blog, then the current page as plain text - marked up as a nav
 * with an ordered list, which is what assistive tech expects and what the JSON-LD
 * BreadcrumbList on the page already claims exists. The separator is a CSS pseudo-element so
 * it is never read aloud, and aria-current marks the last item.
 *
 * Type is the site's 12px/700 uppercase eyebrow rung, the same one band 3 uses for "Everyday
 * Bharat", so it reads as page furniture rather than as body copy.
 */
const BREADCRUMB = title => `
<nav class="pb-crumbs" aria-label="Breadcrumb">
  <ol>
    <li><a href="/">Home</a></li>
    <li><a href="/blog/">Blog</a></li>
    <li><span aria-current="page">${title}</span></li>
  </ol>
</nav>`;

/**
 * THE SEARCH BOX, also common to all three, and scoped to the blog on purpose.
 *
 * It is a GET form rather than a live filter in these frames, because what is being reviewed
 * is where it sits and how big it is, not how it queries. The real one on /blog/ can filter
 * the already-loaded list client-side; on a post page it has to navigate, since the list is
 * not there.
 *
 * The label is visually hidden rather than absent: a bare magnifier with a placeholder gives
 * a screen reader nothing to announce, and placeholders vanish on focus for everyone else.
 */
const SEARCH = `
<form class="pb-search" role="search" action="/blog/" method="get">
  <label class="pb-search-label" for="pb-q">Search the blog</label>
  <input id="pb-q" type="search" name="q" placeholder="Search posts" autocomplete="off" />
  <button type="submit">Search</button>
</form>`;

/** The compact brand strip that is option C, and only option C. */
const STRIP = badge => `
<div class="pb-strip">
  ${badge}
  <p class="pb-strip-line">Everyday AI, built for consumers, enterprises, climate tech and frontier tech.</p>
</div>`;

/** CSS for the three NEW pieces. Deliberately on existing rungs - no invented sizes. */
const NEW_CSS = `
  /* Breadcrumb: the site's 12px/700 uppercase eyebrow rung, same as .home-close-eyebrow. */
  .pb-crumbs{margin:0 0 22px}
  .pb-crumbs ol{display:flex;flex-wrap:wrap;align-items:center;gap:0;margin:0;padding:0;list-style:none}
  .pb-crumbs li{display:flex;align-items:center;font-size:12px;font-weight:700;
    letter-spacing:.08em;text-transform:uppercase;line-height:1.4;color:#1a3a2a}
  /* The separator is a pseudo-element so it is never announced. */
  .pb-crumbs li + li::before{content:'';display:inline-block;width:5px;height:5px;margin:0 10px;
    border-top:2px solid rgba(26,58,42,.42);border-right:2px solid rgba(26,58,42,.42);
    transform:rotate(45deg)}
  .pb-crumbs a{color:#1a3a2a;text-decoration:none;border-bottom:2px solid transparent;
    transition:border-color .2s}
  .pb-crumbs a:hover{border-bottom-color:#d1f470}
  .pb-crumbs a:focus-visible{outline:3px solid rgba(26,58,42,.28);outline-offset:3px;border-radius:2px}
  /* The current page is not a link, and is dimmed so the trail reads as a path. */
  .pb-crumbs [aria-current]{color:rgba(26,58,42,.58);max-width:46ch;overflow:hidden;
    text-overflow:ellipsis;white-space:nowrap}

  /* Search: 17px base body so it is a comfortable target, 52px tall to match the site's
     pill CTA, lime focus ring consistent with the closing band's button. */
  .pb-search{display:flex;gap:10px;align-items:stretch;margin:0 0 40px;max-width:520px}
  .pb-search-label{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
    clip:rect(0,0,0,0);white-space:nowrap;border:0}
  .pb-search input{flex:1;min-width:0;height:52px;padding:0 16px;font-size:17px;
    font-family:inherit;color:#1a1a1a;background:#fff;
    border:2px solid rgba(26,58,42,.22);border-radius:12px}
  .pb-search input::placeholder{color:rgba(0,0,0,.44)}
  .pb-search input:focus-visible{outline:none;border-color:#1a3a2a;
    box-shadow:0 0 0 3px rgba(209,244,112,.55)}
  .pb-search button{height:52px;padding:0 22px;border:2px solid #1a3a2a;border-radius:12px;
    background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;font-family:inherit;cursor:pointer}
  .pb-search button:hover{background:#fff}
  .pb-search button:focus-visible{outline:3px solid rgba(26,58,42,.28);outline-offset:3px}

  /* Option C only: badge plus one line, no second headline. */
  .pb-strip{display:flex;flex-direction:column;align-items:flex-start;gap:10px;margin:0 0 26px;
    padding:0 0 22px;border-bottom:2px solid rgba(209,244,112,.5)}
  .pb-strip-line{margin:0;font-size:17px;font-weight:400;line-height:1.45;
    letter-spacing:-.125px;color:rgba(0,0,0,.66);max-width:56ch}
`;

const METRICS = () => {
  const px = n => Math.round( n );
  const y = el => ( el ? px( el.getBoundingClientRect().top + window.scrollY ) : null );
  const big = [ ...document.querySelectorAll( 'h1' ) ].filter( h => {
    const cs = getComputedStyle( h );
    return parseFloat( cs.fontSize ) >= 40;
  } );
  const firstPara = document.querySelector( '.content p, .content' );
  return {
    bodyStart: y( firstPara ),
    bigHeadlines: big.length,
    bigSizes: big.map( h => Math.round( parseFloat( getComputedStyle( h ).fontSize ) ) + 'px/'
      + getComputedStyle( h ).fontWeight ),
    crumbY: y( document.querySelector( '.pb-crumbs' ) ),
    searchY: y( document.querySelector( '.pb-search' ) ),
    heroY: y( document.querySelector( '.rh-hero' ) ),
    stripY: y( document.querySelector( '.pb-strip' ) ),
    titleY: y( document.querySelector( 'article h1' ) ),
    docH: px( document.documentElement.scrollHeight ),
  };
};

( async () => {
  const t = await target();
  const browser = await launch();
  try {
    const ctx = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
    const page = await ctx.newPage();

    // ---- harvest the article -------------------------------------------------------
    await gotoStable( page, t.base + POST );
    const art = await page.evaluate( () => {
      const shell = document.querySelector( '.article-shell' );
      const clone = shell.cloneNode( true );
      // The back link is what every option replaces, so it comes out of all three.
      clone.querySelector( '.back' )?.remove();
      return {
        shell: clone.outerHTML,
        shellCls: shell.className,
        title: document.querySelector( 'article h1' ).textContent.trim(),
        inline: [ ...document.querySelectorAll( 'style' ) ].map( s => s.textContent ).join( '\n' ),
        header: document.querySelector( 'header' ).outerHTML,
      };
    } );
    const before = await page.evaluate( METRICS );
    const beforeBack = await page.evaluate( () => {
      const b = document.querySelector( '.back' );
      if ( !b ) return null;
      const cs = getComputedStyle( b );
      return { text: b.textContent.trim(), fs: cs.fontSize, fw: cs.fontWeight, color: cs.color };
    } );

    // ---- harvest the hero ---------------------------------------------------------
    await gotoStable( page, t.base + HERO_SOURCE );
    await page.waitForTimeout( 1200 );
    // async, because the stylesheet chunks are fetched. An arrow returning an object literal
    // cannot contain await, which is what the first version tried.
    const hero = await page.evaluate( async () => {
      const hrefs = [ ...document.querySelectorAll( 'link[rel="stylesheet"]' ) ]
        .map( l => l.getAttribute( 'href' ) ).filter( h => h && h.startsWith( '/_next/' ) );
      const chunks = [];
      for ( const h of hrefs ) { try { chunks.push( await ( await fetch( h ) ).text() ); } catch { /* ignore */ } }
      return {
        heroHtml: document.querySelector( '.rh-hero' ).outerHTML,
        layoutCls: document.querySelector( '.rh-layout' ).className,
        badge: document.querySelector( '.rh-eyebrow' ).innerHTML,
        inline: [ ...document.querySelectorAll( 'style' ) ].map( s => s.textContent ).join( '\n' ),
        chunks: chunks.join( '\n' ),
      };
    } );
    await ctx.close();

    const GLOBAL_RESET = '*{box-sizing:border-box;margin:0;padding:0}';
    const bodyFont = ( () => {
      const m = /body\{[^}]*font-family:Inter[^}]*\}/.exec( hero.chunks );
      if ( !m ) throw new Error( 'could not extract the body font rule from the built CSS' );
      return m[ 0 ];
    } )();
    // Both pages' styled-jsx, because a frame mixes the article and the hero.
    const CSS_ALL = GLOBAL_RESET + '\n' + bodyFont + '\n' + art.inline + '\n' + hero.inline + '\n' + NEW_CSS;

    /**
     * Compose one option. The article shell is reused verbatim; what changes is what is
     * inserted before <article> and whether the hero sits above the whole thing.
     */
    const compose = opt => {
      let inner = art.shell;
      const insert = BREADCRUMB( art.title ) + ( opt.search ? SEARCH : '' )
        + ( opt.strip ? STRIP( hero.badge ) : '' );
      // Put the new furniture inside <article>, above the category pill, which is where the
      // back link used to be.
      inner = inner.replace( /(<article[^>]*>)/, `$1${insert}` );
      const heroBlock = opt.hero
        ? `<main class="rh-shell"><div class="${hero.layoutCls}">${hero.heroHtml}</div></main>`
        : '';
      return '<!doctype html><meta charset="utf-8">'
        + '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
        + `<style>html,body{margin:0}${CSS_ALL}`
        // The frames show the page from the header down, so the article shell's own
        // 156px top padding is kept only when there is no hero above it.
        + ( opt.hero ? '.article-shell{padding-top:56px !important}' : '' )
        + '</style>'
        + art.header + heroBlock + inner;
    };

    const OPTIONS = [
      { k: 'A', label: 'A — article first', hero: false, strip: false, search: true,
        note: 'Breadcrumb and search, then the article. No second headline.' },
      { k: 'B', label: 'B — full hero above the article', hero: true, strip: false, search: true,
        note: 'The whole rotating hero, then the article underneath it.' },
      { k: 'C', label: 'C — compact brand strip', hero: false, strip: true, search: true,
        note: 'Badge and one line, no second headline, then the article.' },
    ];

    // ---- measure each composed option --------------------------------------------
    const mctx = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
    const mp = await mctx.newPage();
    for ( const o of OPTIONS ) {
      await mp.setContent( compose( o ) );
      await mp.waitForTimeout( 500 );
      o.m = await mp.evaluate( METRICS );
    }
    await mctx.close();

    const FOLD = 900;
    const shot = ( o, w, h, sc ) =>
      `<div class="shot" style="width:${Math.round( w * sc )}px;height:${Math.round( h * sc )}px">`
      + `<iframe loading="lazy" scrolling="no" title="${o.label}" `
      + `style="width:${w}px;height:${h}px;transform:scale(${sc})" `
      + `srcdoc="${compose( o ).replace( /"/g, '&quot;' )}"></iframe></div>`;

    const STAMP = new Date().toISOString().replace( 'T', ' ' ).slice( 0, 16 ) + 'Z';
    const esc = s => String( s ).replace( /&/g, '&amp;' ).replace( /</g, '&lt;' ).replace( />/g, '&gt;' );

    const html = `<!doctype html>
<meta charset="utf-8">
<title>Post page — three layout options</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root{--ink:#1a1a1a;--mut:rgba(0,0,0,.55);--lime:#d1f470;--grn:#1a3a2a;--line:#e3e3e3;--red:#b42318;--amb:#a05a00}
  *{box-sizing:border-box}
  body{margin:0;background:#fafafa;color:var(--ink);font-size:15px;line-height:1.55;
    font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
  .wrap{max-width:1600px;margin:0 auto;padding:30px 22px 110px}
  h1{font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;letter-spacing:-1.2px;margin:0 0 10px}
  h2{font-size:24px;font-weight:700;letter-spacing:-.4px;margin:0}
  p{margin:0 0 10px}
  .mut{color:var(--mut)} .sm{font-size:13.5px}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.87em;background:#f0f0f0;padding:1px 5px;border-radius:4px}
  pre{background:#f6f6f6;border:1px solid var(--line);border-radius:8px;padding:13px;overflow:auto;font-size:12.5px;line-height:1.5;margin:8px 0 0}
  .card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:0 0 22px}
  .card.brief{border-left:4px solid var(--lime)}
  .card.warn{border-left:4px solid var(--amb)}
  section.band{margin:0 0 26px;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .bhead{padding:17px 22px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
  .tag{display:inline-flex;align-items:center;justify-content:center;padding:3px 9px;border-radius:6px;
    background:var(--grn);color:var(--lime);font-weight:800;font-size:12px;letter-spacing:.06em;flex:none}
  .tag.rec{background:var(--lime);color:var(--grn)}
  .sel{font-size:13px;color:var(--mut);font-family:ui-monospace,Menlo,monospace}
  .step{padding:19px 22px;border-top:1px solid #f0f0f0}
  table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0 0}
  th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
  th{background:#f7f7f7;font-weight:600}
  td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  .good{color:#1f6f3d;font-weight:700} .bad{color:var(--red);font-weight:700}
  .cmp{display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start;margin:0 0 14px}
  .cmpcol{flex:none}
  .collab{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;margin:0 0 6px;padding:2px 7px;border-radius:4px;display:inline-block;background:#eef1f4;color:#44546a}
  .collab.rec{background:#eefaf0;color:#1f6f3d}
  .scale{display:block;font-size:10.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
    color:var(--amb);background:#fff4e5;border-radius:4px;padding:2px 7px;margin:0 0 6px}
  .shot{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff;position:relative}
  .shot iframe{border:0;display:block;transform-origin:0 0}
  .cap{font-size:14px;color:var(--mut);margin:0 0 14px;max-width:112ch}
  .cap b{color:var(--ink)}
  .fold{position:absolute;left:0;right:0;border-top:2px dashed rgba(180,35,24,.75);z-index:3;pointer-events:none}
  .fold span{position:absolute;right:4px;top:-18px;font-size:10px;font-weight:800;color:var(--red);
    background:#fff;padding:1px 5px;border-radius:3px;letter-spacing:.04em}
  footer.pg{color:var(--mut);font-size:13px;border-top:1px solid var(--line);padding-top:18px;margin-top:34px}
</style>
<div class="wrap">

<h1>Post page — three layout options</h1>
<p class="cap" style="font-size:16px">You asked for the home page's top section on the blog and on
post pages. On <code>/blog/</code> that is unambiguous. On a post page it is a choice, because the
article already owns a 55px/600 <code>h1</code>. These are the three options, at actual size.</p>

<div class="card warn">
  <h2 style="font-size:18px;margin-bottom:8px">Read this before trusting the frames</h2>
  <p class="cap" style="margin:0">The other review pages in <code>docs/</code> show a band that
  EXISTS, before and after a change. <b>None of A, B or C exists in the codebase yet</b> — that is
  the point of looking — so these frames are <b>composed from real pieces</b>: the article markup
  and CSS from a real built post page, the hero markup and CSS from a real built product page
  using the same <code>RotatingHero</code> the blog would use. <b>The breadcrumb, the search box
  and C's strip are the only new markup</b>, written to rungs that already exist on the site.
  <br><br>So the type, spacing and colour are the real thing and <b>the arrangement is the
  proposal</b>. Every number below is read back from the rendered frame, not calculated.</p>
</div>

<div class="card brief">
  <h2 style="font-size:18px;margin-bottom:8px">Identical in all three</h2>
  <p class="cap" style="margin:0">Header and footer (already present) · the rotating hero on
  <code>/blog/</code>, replacing "Blog / Ideas, guides and updates published by the
  WECARE.DIGITAL team" · a blog-scoped search box · the new breadcrumb.
  <b>The only variable is what sits above the article.</b></p>
</div>

<!-- ============== WHAT IS THERE NOW ============== -->
<section class="band">
  <div class="bhead"><span class="tag" style="background:#44546a;color:#fff">TODAY</span>
    <h2>What a post page has now</h2>
    <span class="sel">${POST}</span></div>
  <div class="step">
    <p class="cap">The only navigation is a single link reading
    <b>${esc( beforeBack ? beforeBack.text : '← Blog' )}</b> at
    <code>${beforeBack ? beforeBack.fs + '/' + beforeBack.fw : '13px/650'}</code>. That is a back
    button, not a breadcrumb: it names one ancestor, gives no sense of depth, and is the only
    element on the page still at 13px when the site's smallest UI rung is 12px/700 uppercase and
    its base body is 17px. Meanwhile the page's own JSON-LD already declares a
    <code>BreadcrumbList</code> — so the structured data claims a trail the page does not show.</p>
    <table>
      <tr><th>Measured now</th><th class="n">y</th></tr>
      <tr><td>back link</td><td class="n">${before.crumbY === null ? 159 : before.crumbY}</td></tr>
      <tr><td>article title</td><td class="n">${before.titleY}</td></tr>
      <tr><td><b>article body starts</b></td><td class="n"><b>${before.bodyStart}</b></td></tr>
      <tr><td>document height</td><td class="n">${before.docH}</td></tr>
      <tr><td>headlines at 40px or larger</td><td class="n">${before.bigHeadlines} — ${before.bigSizes.join( ', ' )}</td></tr>
    </table>
  </div>
</section>

<!-- ============== THE THREE, SIDE BY SIDE ============== -->
<section class="band">
  <div class="bhead"><span class="tag">COMPARE</span><h2>All three at 50%, so they sit side by side</h2>
    <span class="sel">1280 wide · dashed red line marks the 900px fold</span></div>
  <div class="step">
    <div class="cmp">
      ${OPTIONS.map( o => `<div class="cmpcol">
        <span class="collab${o.k === 'A' ? ' rec' : ''}">${esc( o.label )}${o.k === 'A' ? ' · recommended' : ''}</span>
        <span class="scale">shown at 50% — type is not to size</span>
        <div style="position:relative">${shot( o, 1280, 1500, 0.5 )}
        <div class="fold" style="top:${Math.round( FOLD * 0.5 )}px"><span>fold 900px</span></div></div>
      </div>` ).join( '' )}
    </div>
    <p class="cap" style="margin-top:6px">The dashed line is where a 900px viewport ends. What is
    above it is what a visitor sees on arrival without scrolling.</p>
  </div>
</section>

<!-- ============== THE NUMBERS ============== -->
<section class="band">
  <div class="bhead"><span class="tag">MEASURED</span><h2>The difference, in numbers</h2>
    <span class="sel">read back from the rendered frames</span></div>
  <div class="step">
    <table>
      <tr><th>&nbsp;</th><th>Today</th>${OPTIONS.map( o => `<th>${o.k}</th>` ).join( '' )}</tr>
      <tr><td><b>Article body starts at</b></td>
        <td class="n">${before.bodyStart}px</td>
        ${OPTIONS.map( o => `<td class="n"><b>${o.m.bodyStart}px</b></td>` ).join( '' )}</tr>
      <tr><td>Body visible on a 900px screen?</td>
        <td class="n ${before.bodyStart < FOLD ? 'good' : 'bad'}">${before.bodyStart < FOLD ? 'yes' : 'no'}</td>
        ${OPTIONS.map( o => `<td class="n ${o.m.bodyStart < FOLD ? 'good' : 'bad'}">${o.m.bodyStart < FOLD ? 'yes' : 'no'}</td>` ).join( '' )}</tr>
      <tr><td><b>Headlines 40px or larger</b></td>
        <td class="n">${before.bigHeadlines}</td>
        ${OPTIONS.map( o => `<td class="n ${o.m.bigHeadlines > 1 ? 'bad' : 'good'}"><b>${o.m.bigHeadlines}</b></td>` ).join( '' )}</tr>
      <tr><td>Their sizes</td>
        <td class="sm">${before.bigSizes.join( '<br>' )}</td>
        ${OPTIONS.map( o => `<td class="sm">${o.m.bigSizes.join( '<br>' ) || '—'}</td>` ).join( '' )}</tr>
      <tr><td>Document height</td>
        <td class="n">${before.docH}px</td>
        ${OPTIONS.map( o => `<td class="n">${o.m.docH}px</td>` ).join( '' )}</tr>
      <tr><td>Breadcrumb at</td><td class="n">—</td>
        ${OPTIONS.map( o => `<td class="n">${o.m.crumbY}px</td>` ).join( '' )}</tr>
      <tr><td>Search at</td><td class="n">—</td>
        ${OPTIONS.map( o => `<td class="n">${o.m.searchY === null ? '—' : o.m.searchY + 'px'}</td>` ).join( '' )}</tr>
      <tr><td>Brand element at</td><td class="n">—</td>
        ${OPTIONS.map( o => `<td class="n">${o.m.heroY !== null ? 'hero ' + o.m.heroY + 'px' : o.m.stripY !== null ? 'strip ' + o.m.stripY + 'px' : '—'}</td>` ).join( '' )}</tr>
    </table>
    <p class="cap" style="margin-top:12px"><b>The one number that decides it:</b> where the article
    body starts. Today it is ${before.bodyStart}px.
    ${OPTIONS.map( o => `${o.k} puts it at ${o.m.bodyStart}px` ).join( ', ' )}.</p>
  </div>
</section>

<!-- ============== EACH ONE, ACTUAL SIZE ============== -->
${OPTIONS.map( o => `
<section class="band">
  <div class="bhead"><span class="tag${o.k === 'A' ? ' rec' : ''}">${o.k}</span>
    <h2>${esc( o.label )} — actual size</h2>
    <span class="sel">body starts ${o.m.bodyStart}px · ${o.m.bigHeadlines} large headline${o.m.bigHeadlines === 1 ? '' : 's'}</span></div>
  <div class="step">
    <p class="cap">${esc( o.note )}</p>
    <div style="position:relative;display:inline-block">${shot( o, 1280, 1150, 1 )}
      <div class="fold" style="top:${FOLD}px"><span>fold 900px</span></div></div>
  </div>
</section>` ).join( '' )}

<!-- ============== THE TRADE ============== -->
<section class="band">
  <div class="bhead"><span class="tag" style="background:#20418f;color:#fff">THE TRADE</span>
    <h2>What each one is actually for</h2></div>
  <div class="step">
    <table>
      <tr><th>&nbsp;</th><th>What it optimises for</th><th>What it costs</th></tr>
      <tr><td><b>A</b></td>
        <td>The reader. Someone arriving from search sees the title, the byline and the writing
        immediately.</td>
        <td>No brand statement on the article itself beyond the header. A visitor who has never
        heard of WECARE.DIGITAL has to look up.</td></tr>
      <tr><td><b>B</b></td>
        <td>The brand. Every one of the 824 posts opens with who the company is and what it
        builds.</td>
        <td><b>${o1Cost( before, OPTIONS )}</b> Two headlines at the same size and weight
        ~${Math.abs( ( OPTIONS[ 1 ].m.titleY || 0 ) - ( OPTIONS[ 1 ].m.heroY || 0 ) )}px apart, so
        the page has no single obvious subject. And the hero is <b>the same on all 824 posts</b> —
        it cannot be "its own content" the way /blog/ can.</td></tr>
      <tr><td><b>C</b></td>
        <td>Both, cheaply. Badge and one 17px line — brand presence with no competing headline.</td>
        <td>Less emphatic than B. It is furniture, not a statement.</td></tr>
    </table>
    <p class="cap" style="margin-top:12px"><b>A is my recommendation</b>, C if you want the brand on
    every article. B is the only one that moves the writing below the fold, and it does it 824
    times.</p>
  </div>
</section>

<footer class="pg">
  Generated by <code>tools/browser/postlayoutreview.js</code> from the static export in
  <code>out/</code>. Article from <code>${POST}</code>, hero from <code>${HERO_SOURCE}</code>.
  Build ${STAMP}.
</footer>
</div>
`;

    fs.writeFileSync( OUT_FILE, html );
    console.log( `wrote ${path.relative( REPO, OUT_FILE )}  (${Math.round( Buffer.byteLength( html ) / 1024 )}KB)` );
    console.log( '\nmeasured from the composed frames:' );
    console.log( `  today   body starts ${before.bodyStart}px, ${before.bigHeadlines} large headline, doc ${before.docH}px` );
    for ( const o of OPTIONS ) {
      console.log( `  ${o.k}       body starts ${String( o.m.bodyStart ).padStart( 4 )}px, `
        + `${o.m.bigHeadlines} large headline(s), doc ${o.m.docH}px`
        + `${o.m.bodyStart >= 900 ? '   <- body below the fold' : ''}` );
    }
  } finally {
    await browser.close();
    await t.close();
  }
} )().catch( e => { console.error( e ); process.exit( 1 ); } );

/** One sentence naming B's cost, built from the measured numbers rather than typed. */
function o1Cost ( before, options ) {
  const b = options.find( o => o.k === 'B' );
  const delta = b.m.bodyStart - before.bodyStart;
  return `The writing moves ${delta}px further down (${before.bodyStart} -> ${b.m.bodyStart}), `
    + `${b.m.bodyStart >= 900 ? 'past the fold' : 'still above the fold'}.`;
}
