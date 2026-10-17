import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Read one CSS rule by selector without pinning declaration order. Public-page style tests
 * should guard the properties that define the visual contract, not the byte-for-byte
 * serialization of an entire styled-jsx rule.
 */
function cssRuleFor( source: string, selector: string ): string {
  const clean = source.replace( /\/\*[\s\S]*?\*\//g, '' );
  const marker = selector + '{';
  const start = clean.indexOf( marker );
  if ( start < 0 ) return '';
  const bodyStart = start + marker.length;
  const end = clean.indexOf( '}', bodyStart );
  return end < 0 ? '' : clean.slice( bodyStart, end );
}
describe( 'Grahak OS five approved visual fixes', () => {
  const pagePath = resolve( process.cwd(), 'src/pages/grahak-os/index.tsx' );
  const source = readFileSync( pagePath, 'utf8' );

  it( 'drops the three hero stat cards and their dead CSS', () => {
    // Removed by design decision: the hero leads on the rotating channel pill,
    // so the stat row was redundant. Markup and styles both go.
    expect( source ).not.toContain( '<span>4 Channels</span>' );
    expect( source ).not.toContain( 'hero-stats' );
    expect( source ).not.toContain( '.stat{' );
    expect( source ).not.toContain( '.stat span{' );
    expect( source ).not.toContain( '.stat small{' );
    // the hero now uses the same shared RotatingHero band as every other product/request page.
    expect( source ).toContain( '<RotatingHero' );
    expect( source ).toContain( 'insideMain' );
  } );

  it( 'uses the approved WECARE.DIGITAL color system and canonical logo avatar', () => {
    // Header teal darkened from #128c7e to #0a7265 so the white .contact-name clears the
    // 4.5:1 WCAG AA contrast floor (white on #0a7265 is 5.82:1; on #128c7e it was 4.14:1,
    // the axe-core failure that held /grahak-os/ at accessibility 95). #0a7265 is a
    // non-retired WhatsApp header green; the #075e54 negative assertion below still holds.
    expect( source ).toContain( '.phone-header{background:#0a7265' );

    // The phone mock now uses the canonical WECARE.DIGITAL mark as a real contact-photo DP.
    // Guard the semantic pieces independently so harmless CSS reordering or added declarations
    // cannot break the suite the way the retired exact-string assertion did.
    const avatarRule = cssRuleFor( source, '.avatar' );
    expect( avatarRule ).toContain( 'width:40px' );
    expect( avatarRule ).toContain( 'height:40px' );
    expect( avatarRule ).toContain( 'background:#d1f470' );
    expect( avatarRule ).toContain( 'border-radius:50%' );
    expect( avatarRule ).toContain( 'overflow:hidden' );
    expect( avatarRule ).toContain( 'box-shadow:0 0 0 2px rgba(255,255,255,.6)' );

    const avatarImageRule = cssRuleFor( source, '.avatar-img' );
    // Logo fills 90% of the disc (was 84%) so the DP mark reads larger and crisper.
    expect( avatarImageRule ).toContain( 'width:90%' );
    expect( avatarImageRule ).toContain( 'height:90%' );
    expect( avatarImageRule ).toContain( 'object-fit:contain' );

    const avatarMarkup = source.match( /<div className="avatar">([\s\S]*?)<\/div>/ )?.[ 1 ] || '';
    expect( avatarMarkup ).toContain( 'className="avatar-img"' );
    expect( avatarMarkup ).toContain( 'src="https://wecare.digital/get/o/stream/media/m/wecaredigital.png"' );
    expect( avatarMarkup ).toContain( 'alt=""' );
    expect( avatarMarkup ).toContain( 'aria-hidden="true"' );
    expect( avatarMarkup ).not.toContain( '>W<' );

    expect( source ).toContain( '.verified-badge{width:18px;height:18px;background:#25d366' );
    expect( source ).toContain( '.msg.sent{background:#d9fdd3' );
    // Renamed .tab -> .pp-tab so the page owns the control outright: the bare .tab
    // class is declared unscoped in Pages.css and Layout.css, which were supplying
    // min-height, box-shadow, font-family and five more properties this page never
    // asked for. The lime pair being guarded here is unchanged.
    expect( source ).toContain( '.pp-tab.active{background:#d1f470;color:#1a3a2a' );
    // The class must stay pp- prefixed. Reverting it to .tab silently reopens the leak.
    expect( source ).toContain( 'className={`pp-tab ' );
    // The "Trusted by Meta" section was removed on owner instruction, so the Meta
    // card and all its trust-* markup/CSS are gone from this page.
    expect( source ).not.toContain( '.trust-card{' );
    expect( source ).not.toContain( '#2f6b52' );
    expect( source ).not.toContain( '.verified-badge{width:22px;height:22px;background:#075e54' );
    expect( source ).not.toContain( '.meta-panel{background:#d9fbf2' );
    expect( source ).not.toContain( '.whatsapp-panel{background:#25d366' );
  } );

  it( 'removes both added CTA buttons', () => {
    expect( source ).not.toContain( '>Start with WhatsApp<' );
    expect( source ).not.toContain( '>Talk to us<' );
    expect( source ).not.toContain( 'className="cta-actions"' );
  } );

  it( 'removes the entire "Trusted by Meta" section (owner instruction)', () => {
    // The whole trust-strip block - the Meta lockup card and the channel pills beside
    // it - was removed on owner instruction. Guard that neither its markup, its CSS, nor
    // its wording survives anywhere in the page source.
    expect( source ).not.toContain( 'trust-strip' );
    expect( source ).not.toContain( 'trust-grid' );
    expect( source ).not.toContain( '.trust-card{' );
    expect( source ).not.toContain( 'trust-logo' );
    expect( source ).not.toContain( 'trust-wordmark' );
    expect( source ).not.toContain( 'trust-divider' );
    expect( source ).not.toContain( 'trust-caption' );
    expect( source ).not.toContain( 'trust-heading' );
    expect( source ).not.toContain( 'trust-subtext' );
    expect( source ).not.toContain( 'trust-pills' );
    expect( source ).not.toContain( 'Trusted by Meta' );
    expect( source ).not.toContain( 'meta-mark' );
    // meta-icon.svg went with the card: the page no longer references the Meta mark.
    expect( source ).not.toContain( 'meta-icon.svg' );
  } );

  it( 'leaves no temporary design-review markup behind', () => {
    expect( source ).not.toContain( 'VARIANT' );
    expect( source ).not.toContain( 'tv-label' );
    expect( source ).not.toContain( 'tv-code' );
    expect( source ).not.toContain( 'TEMP DESIGN REVIEW' );
  } );
} );

/**
 * The owner-approved numbered 1-2-3 step block that replaced the old .api-info copy in
 * the "Built for your stack" section (<section id="api"> / .api-grid). The step block is
 * the LEFT column; the code panel (.api-demo) stays the RIGHT column, unchanged. These
 * assertions pin the new truth exactly - heading, three numbered steps (DRAFT copy),
 * checkout + demo buttons wired to the EXISTING mechanism/price/SKU/demo link, and the
 * imported shipping/cancellation/refund disclaimer. Do not loosen to vague matchers.
 */
describe( 'Grahak OS: numbered 1-2-3 step block in the Built-for-your-stack section', () => {
  const pagePath = resolve( process.cwd(), 'src/pages/grahak-os/index.tsx' );
  const source = readFileSync( pagePath, 'utf8' );

  it( 'carries the owner-approved consulting heading on the .api-info h2 rung', () => {
    // Exact owner-approved heading theme. The old left-column heading is gone.
    expect( source ).toContain( '<h2>Deploy an ecosystem of AI agents to own Enterprise Outcomes</h2>' );
    expect( source ).not.toContain( '<h2>Built for your stack</h2>' );
    // The LEFT column is still .api-info (so it keeps the h2 type rung) and now also
    // carries .api-steps.
    expect( source ).toContain( 'className="api-info api-steps"' );
  } );

  it( 'renders three numbered steps 1-2-3 in the /anew/ pattern with DRAFT copy', () => {
    expect( source ).toContain( 'className="api-steps-list"' );
    // Visible step numbers 1, 2, 3, each aria-hidden (the ordered list carries order).
    expect( source ).toContain( '<span className="api-step-num" aria-hidden="true">1</span>' );
    expect( source ).toContain( '<span className="api-step-num" aria-hidden="true">2</span>' );
    expect( source ).toContain( '<span className="api-step-num" aria-hidden="true">3</span>' );
    // Each step has a short title + one supporting line.
    expect( source ).toContain( '<h3 className="api-step-title">Map your outcomes</h3>' );
    expect( source ).toContain( '<h3 className="api-step-title">Deploy the agent ecosystem</h3>' );
    expect( source ).toContain( '<h3 className="api-step-title">Own the result</h3>' );
    // Copy is clearly marked DRAFT placeholder - final wording pending owner approval.
    const stepLines = source.match( /className="api-step-line">DRAFT: /g ) || [];
    expect( stepLines.length ).toBe( 3 );
  } );

  // Scope assertions to the steps-block CTA container so the single-button truth is
  // pinned to this section, not to the whole page (the closer carries its own CTA).
  const stepsCtas = source.match( /className="api-steps-ctas">([\s\S]*?)<\/div>/ )?.[ 1 ] || '';

  it( 'keeps the single WhatsApp CTA and attaches the fresh catalog checkout', () => {
    // The existing WhatsApp door stays exactly once in this steps block, while the fresh
    // catalog checkout is mounted separately without duplicating the visible ₹899 price.
    expect( source ).toContain( 'className="api-steps-ctas"' );
    expect( source ).toContain( '<a className="gos-wa-cta" href="https://wa.me/message/APDM5HUWH26SG1" target="_blank" rel="noopener noreferrer">Get Started on WhatsApp &#8594;</a>' );
    // The steps block now carries EXACTLY ONE WhatsApp CTA: "Get Started on WhatsApp".
    // The redundant second "See it on WhatsApp" pill here was removed on owner
    // instruction; the demo button lives only in the closer now.
    const stepsCtaCount = ( stepsCtas.match( /className="gos-wa-cta"/g ) || [] ).length;
    expect( stepsCtaCount ).toBe( 1 );
    expect( stepsCtas ).toContain( 'Get Started on WhatsApp' );
    expect( stepsCtas ).not.toContain( 'See it on WhatsApp' );
    expect( source ).toContain( "import ProductBuyBox from '../../components/ProductBuyBox';" );
    expect( source ).toContain( '<ProductBuyBox slug="grahak-os" showPrice={ false } />' );
    // The existing ₹899 price with its exact caption is surfaced in the step block.
    expect( source ).toContain( '&#8377;899<span className="gos-price-unit"> · Grahak OS · consulting solution</span>' );
  } );

  it( 'has removed the redundant "See it on WhatsApp" demo button FROM THE STEPS BLOCK', () => {
    // UNIFIED CTA STYLE (owner instruction): the lighter .api-action-link text-link that
    // used to carry "See it on WhatsApp" here is long gone (do not reintroduce it).
    const codeNoComments = source.replace( /\/\*[\s\S]*?\*\//g, '' ).replace( /^\s*\/\/.*$/gm, '' );
    expect( codeNoComments ).not.toContain( 'api-action-link' );
    // Owner instruction: the second steps-block WhatsApp pill ("See it on WhatsApp") was
    // REMOVED - the steps block now carries only "Get Started on WhatsApp". The demo
    // "See it on WhatsApp" button survives ONLY in the closer (asserted in its own suite).
    expect( stepsCtas ).not.toContain( 'See it on WhatsApp' );
    // The page as a whole still has exactly one "See it on WhatsApp" link, in the closer.
    const seeItCount = ( source.match( />See it on WhatsApp</g ) || [] ).length;
    expect( seeItCount ).toBe( 1 );
    // The single remaining steps-block CTA keeps the standard new-tab attributes.
    expect( stepsCtas ).toContain( 'target="_blank"' );
    expect( stepsCtas ).toContain( 'rel="noopener noreferrer"' );
  } );

  it( 'surfaces the existing SKU and disclaimer from the imported constants, not retyped', () => {
    // SKU via the imported map; policy via the imported title/text constants.
    expect( source ).toContain( "PRODUCT_SKU_BY_SLUG['grahak-os']" );
    expect( source ).toContain( '<strong>{ PRODUCT_POLICY_TITLE }:</strong> { PRODUCT_POLICY_TEXT }' );
    // The imports are present at the top of the file.
    expect( source ).toContain( "import { PRODUCT_POLICY_TEXT, PRODUCT_POLICY_TITLE, PRODUCT_SKU_BY_SLUG } from '../../content/productCommerce';" );
  } );

  it( 'uses only existing design tokens for the step block and introduces no new palette', () => {
    const code = source.replace( /\/\*[\s\S]*?\*\//g, '' );
    // Lime disc + dark-green text, the page's own tokens.
    expect( code ).toContain( '.api-step-num{' );
    expect( code ).toContain( 'background:#d1f470;color:#1a3a2a' );
    // Supporting line uses the muted body token.
    expect( code ).toContain( '.api-step-line{' );
    expect( code ).toContain( 'color:rgba(0,0,0,.6)' );
    // No retired colours leak into the step block CSS.
    expect( code ).not.toContain( '#2f6b52' );
    expect( code ).not.toContain( '#075e54' );
    expect( code ).not.toContain( '#1e293b' );
    expect( code ).not.toContain( '#4b5563' );
  } );

  it( 'stacks the step block FIRST above the code panel at <=767px', () => {
    const code = source.replace( /\/\*[\s\S]*?\*\//g, '' );
    // Step block ordered before the code panel when the grid stacks.
    expect( code ).toContain( '.api-steps{order:0}' );
    expect( code ).toContain( '.api-demo{order:1' );
  } );
} );

/**
 * The closer section (<section id="gos-closer">) was STRIPPED on owner instruction down to
 * a single unified WhatsApp CTA. The closing heading ("Transform customer engagement with
 * Grahak OS"), the ₹899 price line and the SKU/policy disclaimer block were all removed
 * from this section; the only control left is one .gos-wa-cta pill labelled exactly
 * "See it on WhatsApp". The price/SKU/policy still live in the api-steps block above, so
 * these assertions pin the closer-specific removals and the single remaining button, not a
 * page-wide absence.
 */
describe( 'Grahak OS: closer stripped to a single unified WhatsApp CTA', () => {
  const pagePath = resolve( process.cwd(), 'src/pages/grahak-os/index.tsx' );
  const source = readFileSync( pagePath, 'utf8' );
  const code = source.replace( /\/\*[\s\S]*?\*\//g, '' );
  // Isolate just the closer section's markup so assertions are scoped to it, not the page.
  const closer = source.match( /id="gos-closer">([\s\S]*?)<\/section>/ )?.[ 1 ] || '';

  it( 'removes the "Transform customer engagement with Grahak OS" heading and its CSS', () => {
    expect( code ).not.toContain( 'Transform customer' );
    expect( code ).not.toContain( 'gos-closer-head' );
  } );

  it( 'removes the price line and the SKU/policy disclaimer FROM THE CLOSER', () => {
    // Scoped to the closer: the closer no longer renders a price or the commerce block.
    expect( closer ).not.toContain( 'gos-price' );
    expect( closer ).not.toContain( 'gos-commerce' );
    expect( closer ).not.toContain( 'PRODUCT_SKU_BY_SLUG' );
    expect( closer ).not.toContain( 'PRODUCT_POLICY_TITLE' );
  } );

  it( 'keeps exactly one WhatsApp button, labelled "See it on WhatsApp", in the unified pill style', () => {
    // The closer contains a single .gos-wa-cta pill, a real link, with the exact label.
    const closerCtas = closer.match( /className="gos-wa-cta"/g ) || [];
    expect( closerCtas.length ).toBe( 1 );
    expect( closer ).toContain( '<a className="gos-wa-cta" href="https://wa.me/message/APDM5HUWH26SG1" target="_blank" rel="noopener noreferrer">See it on WhatsApp</a>' );
    // No price, heading or disclaimer markup survives in the closer.
    expect( closer ).not.toContain( '<h2' );
    expect( closer ).not.toContain( '<p' );
  } );
} );

/**
 * The accessibility and head defects found by measuring the built export, not the source.
 *
 * Every assertion here exists because the page passed all five browser harness suites
 * (typecheck 3/3, animcheck 18/18, rtlcheck 6523/6523, uicheck 96/96, seocheck 11/11)
 * while carrying the defect. Each suite measures one settled state - JS running, motion
 * allowed, viewport fixed - so none of them entered the state that was broken.
 */
/**
 * The "Every touchpoint" section (<section id="touchpoint">) renders six use-case pills.
 * They used to be six identical grey outlines (.pp-pill with a single #e5e7eb border on
 * white). They now carry SIX DISTINCT HUES drawn from the HOMEPAGE subject palette
 * (src/pages/index.tsx CYCLE_WORDS amber/purple/green/red dot hues), the homepage blue
 * border #2563eb, and this page's brand lime #d1f470 - no invented colours. Each hue is a
 * thin COLOURED BORDER on a WHITE background (the earlier filled tint fills were dropped on
 * owner instruction). The pill text stays dark so every pill clears WCAG AA. These
 * assertions pin the exact per-pill border-only CSS and the data-driven mapping so a revert
 * to either the monochrome treatment or the filled tints fails here.
 */
describe( 'Grahak OS: "Every touchpoint" pills carry multiple homepage hues', () => {
  const pagePath = resolve( process.cwd(), 'src/pages/grahak-os/index.tsx' );
  const source = readFileSync( pagePath, 'utf8' );
  const code = source.replace( /\/\*[\s\S]*?\*\//g, '' );

  it( 'keeps the heading, sub-line and the six use-case titles/order unchanged', () => {
    expect( source ).toContain( '<h2>Every touchpoint<br/>One seamless experience</h2>' );
    expect( source ).toContain( 'Engage, support, and convert customers across their entire journey' );
    // The six touchpoints, in order, now carry a hue each - titles and order are frozen.
    expect( source ).toContain( "{ title: 'Promotional', hue: 'amber' }" );
    expect( source ).toContain( "{ title: 'Transactional', hue: 'blue' }" );
    expect( source ).toContain( "{ title: 'Appointments', hue: 'green' }" );
    expect( source ).toContain( "{ title: 'OTPs', hue: 'purple' }" );
    expect( source ).toContain( "{ title: 'Orders', hue: 'red' }" );
    expect( source ).toContain( "{ title: 'Surveys', hue: 'lime' }" );
  } );

  it( 'renders each pill with a data-driven per-hue modifier class', () => {
    expect( source ).toContain( 'className={`pp-pill pp-pill--${hue}`}' );
  } );

  it( 'pins each pill to its exact homepage hue (border-only on white), keeping text dark/AA', () => {
    // Base geometry keeps the pinned 17px type and the dark body text.
    expect( code ).toContain( '.pp-pill{' );
    expect( code ).toContain( 'font-size:17px' );
    expect( code ).toContain( 'color:rgba(0,0,0,.898)' );
    // Six hues from the homepage palette, now each a thin COLOURED BORDER on a WHITE
    // background - amber/green dot hues used only as border (they fail as TEXT), blue as
    // a border on white, lime as the brand pair. The earlier filled tint backgrounds were
    // dropped on owner instruction, so every pill is border-only on #fff.
    expect( code ).toContain( '.pp-pill--amber{border-color:#f0a818;background:#fff}' );
    expect( code ).toContain( '.pp-pill--blue{border-color:#2563eb;background:#fff}' );
    expect( code ).toContain( '.pp-pill--green{border-color:#3da35a;background:#fff}' );
    expect( code ).toContain( '.pp-pill--purple{border-color:#9849e8;background:#fff}' );
    expect( code ).toContain( '.pp-pill--red{border-color:#dc2626;background:#fff}' );
    expect( code ).toContain( '.pp-pill--lime{border-color:#d1f470;background:#fff;color:#1a3a2a}' );
    // The dropped tint fills must NOT appear on the pill rules (scoped to the pill
    // selectors so a legitimate use of the hex elsewhere on the page is not caught).
    expect( code ).not.toContain( '.pp-pill--amber{border-color:#f0a818;background:#fef3c7}' );
    expect( code ).not.toContain( '.pp-pill--green{border-color:#3da35a;background:#e0f7c8}' );
    expect( code ).not.toContain( '.pp-pill--purple{border-color:#9849e8;background:#ede9fe}' );
    expect( code ).not.toContain( '.pp-pill--red{border-color:#dc2626;background:#fee2e2}' );
    // Hover keeps each pill's own hue (no more forcing every pill to the lime border);
    // it only lifts and casts the existing shadow.
    expect( code ).toContain( '.pp-pill:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}' );
  } );

  it( 'introduces no retired colour via the new pill hues', () => {
    // The homepage hues are all NON-retired; guard the retired set does not creep in here.
    expect( code ).not.toContain( '#2f6b52' );
    expect( code ).not.toContain( '#075e54' );
    expect( code ).not.toContain( '#1e293b' );
    expect( code ).not.toContain( '#4b5563' );
    expect( code ).not.toContain( '#0f172a' );
    expect( code ).not.toContain( '#94a3b8' );
  } );
} );

describe( 'Grahak OS: states the harness suites do not enter', () => {
  const pagePath = resolve( process.cwd(), 'src/pages/grahak-os/index.tsx' );
  const source = readFileSync( pagePath, 'utf8' );

  /**
   * Comments stripped for the negative assertions, for the reason BrandAssets.test.ts
   * already records: the fixes below are each documented AT the rule they changed, and
   * those comments necessarily quote the defective value they replaced. A substring
   * search cannot tell an explanation from a usage, and the first version of this block
   * failed on exactly that - `.anim{opacity:0}` and `img.icons8.com` both appear in the
   * notes explaining why they are gone.
   *
   * Stripping is the honest fix. The alternative is deleting the explanation to make the
   * suite green, which loses the reason the rule exists.
   */
  const code = source
    .replace( /\/\*[\s\S]*?\*\//g, '' )
    .replace( /^\s*\/\/.*$/gm, '' )
    .replace( /\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '' );

  it( 'ships the finished state in CSS, so the page is visible without JavaScript', () => {
    // THE DEFECT: .anim{opacity:0} was the base state and .show was added by an
    // IntersectionObserver in a useEffect. Measured against out/ with
    // javaScriptEnabled:false, all six sections reported op=0 - the entire page was
    // blank. It survived review because opacity does not remove text from the DOM, so
    // the no-JS body-text count stayed at ~2,086 chars and read as healthy.
    //
    // The base rule must show the section. This is the assertion to keep: a revert to
    // opacity:0 on .anim reopens the blank page.
    expect( source ).toContain( '.anim{opacity:1;transform:none}' );
    expect( code ).not.toContain( '.anim{opacity:0' );
    // Hiding is opt-in, and only the armed state hides.
    expect( source ).toContain( '.anim.is-armed{opacity:0;transform:translateY(30px)' );
    expect( source ).toContain( '.anim.is-armed.show{opacity:1;transform:translateY(0)}' );
    // Reduced motion has to match BOTH selectors now that the transition moved onto
    // .is-armed; matching .anim alone would leave armed sections transitioning.
    expect( source ).toContain( '.anim,.anim.is-armed{transition:none}' );
  } );

  it( 'arms the reveal only after confirming it can animate, and seeds the fold', () => {
    // Capability detection, not user-agent sniffing: if IntersectionObserver is absent
    // the effect returns before arming and the finished state stands.
    expect( source ).toContain( "if (typeof IntersectionObserver === 'undefined') return;" );
    expect( source ).toContain( 'setArmed(true);' );
    // And the anti-flash half, which is the reason this is not simply "add a class on
    // mount". Arming hides everything; without seeding what is already on screen in the
    // SAME batch, the hero paints visible -> hidden -> animated-in on every load.
    expect( source ).toContain( 'const onScreenNow = sections' );
    expect( source ).toContain( 'setVisible((p) => new Set([...p, ...onScreenNow]));' );
  } );

  it( 'has removed the capabilities strip section, its data and all its CSS', () => {
    // OWNER INSTRUCTION: the six-item capabilities strip (Customer Data Platform / Custom
    // Data Modeling / Multichannel Orchestration / Smart Personalization / Enterprise
    // Infrastructure / Predictive Analytics) was removed entirely - markup, the
    // `capabilities` data array and every .pp-strip* / #capabilities CSS rule. Comments
    // are stripped from `code`, so these negative assertions guard real markup/CSS/data
    // and a revert that re-adds the section fails here.
    expect( code ).not.toContain( 'const capabilities' );
    expect( code ).not.toContain( 'id="capabilities"' );
    expect( code ).not.toContain( 'pp-strip' );
    expect( code ).not.toContain( "title: 'Customer Data Platform'" );
    expect( code ).not.toContain( "title: 'Predictive Analytics'" );
    // The shared full-bleed selector keeps #touchpoint but drops #capabilities.
    expect( code ).toContain( '#touchpoint{max-width:none;width:100vw' );
    expect( code ).not.toContain( '#touchpoint,#capabilities' );
  } );

  it( 'clears the 44px touch-target floor on the only controls inside main', () => {
    // THE DEFECT: the three code-language tabs measured 91.6x43.3, 117.5x43.3 and
    // 78x43.3 - short of the WCAG 2.5.8 minimum by 0.7px. They are the only interactive
    // elements inside this page's <main>, which has zero links.
    // min-height, not extra padding: the tab is already an inline-flex with centred
    // content, so the box grows without moving the label.
    expect( source ).toContain( 'padding:10px 20px;min-height:44px' );
  } );

  it( 'carries no connection hint for an origin it never calls', () => {
    // THE DEFECT: a preconnect AND a dns-prefetch to img.icons8.com, against zero
    // icons8 requests on the route. Every glyph here is drawn - six inline
    // data:image/svg+xml URIs plus meta-icon.svg from our own media host - so the
    // handshakes were opened for nothing and competed with real requests.
    expect( code ).not.toContain( 'img.icons8.com' );
  } );
} );
