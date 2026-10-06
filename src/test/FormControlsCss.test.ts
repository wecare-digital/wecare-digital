import { describe, expect, it } from 'vitest';
import fs from 'fs';
import path from 'path';

import census from './fixtures/control-skin-census.json';

/**
 * INVARIANT 4 — the chevron is declared in exactly one file, and no NEW file starts skinning a
 * select, in any of the three authoring mechanisms.
 *
 * WHAT THIS IS AND IS NOT. It is a NO-NEW-SKINS gate, not a uniqueness claim, and the
 * difference is the whole point. 28 files skinned a select before batch 1.3a and 26 of them
 * still do: retiring `select` from 83 rule sets scoped to single workspace pages no harness can
 * load is a consolidation with its own risk budget and its own sign-off. A test asserting
 * uniqueness would have to be written to fail or written to lie. What it can honestly do is
 * fail the moment a THIRTIETH file joins — which is the mechanism that produced six competing
 * scrollbar declarations, one file at a time.
 *
 * WHY IT READS A FIXTURE INSTEAD OF SCANNING. The producer of these figures is
 * `scripts/census_control_skins.py`, and it is deliberately NOT re-implemented here. Its
 * counting rule is not restatable from the design tables, a defensible reimplementation lands
 * on 84 or 87, and the first thing that happens then is that the expected number gets edited
 * instead of the bug fixed. So the scanner is committed, `--json` writes
 * `src/test/fixtures/control-skin-census.json` on the finished tree, and this suite asserts the
 * fixture against literals. Regenerate with:
 *
 *   .venv/bin/python scripts/census_control_skins.py --json > src/test/fixtures/control-skin-census.json
 *
 * A real change then shows up as a fixture diff AND a failing literal, which is a reviewable
 * pair rather than an integer nobody can re-derive. LINE NUMBERS IN THE FIXTURE ARE NOT
 * ASSERTED — they move whenever any of these 29 files is edited, and asserting them would make
 * this suite fail for reasons that have nothing to do with control skinning.
 *
 * THE 83/41 FIGURES ARE POST-1.3a. The pre-batch inventory was 85 rule sets / 43 geometry
 * (A-global 44 in 8 files, B-styledjsx 38 in 18, C-injected 3 in 2). This batch removed `select`
 * from six counted rule sets (tokens.css base/:hover/:focus, inner-ux.css base/:hover/:focus),
 * deleted a seventh in full (the chevron block), and added form-controls.css as a ninth
 * mechanism-A file contributing five — so 85 - 7 + 5 = 83, and 43 - 3 + 1 = 41 geometry.
 * `.inner-page select { width: 100% }` adds no rule set to either count: `width` is not a box
 * property, which is exactly why assertion 4 has to watch that line separately.
 */
describe( 'form-controls.css — invariant 4', () => {
  const STYLES = path.join( __dirname, '..', 'styles' );
  const read = ( f: string ) => fs.readFileSync( path.join( STYLES, f ), 'utf8' );

  /**
   * Comment-stripping is load-bearing, for the reason `ScrollbarDeclarations.test.ts` records:
   * the notes that explain a retirement necessarily contain the declarations being searched
   * for. The note left in `inner-ux.css` where the chevron block used to be says what moved and
   * why, so a raw-text search would find the words it is looking for inside the explanation of
   * their own absence.
   */
  const stripComments = ( css: string ) =>
    css.replace( /\/\*[\s\S]*?\*\//g, '' ).replace( /^\s*\/\/.*$/gm, '' );

  const formControls = read( 'form-controls.css' );
  const formControlsCode = stripComments( formControls );
  const innerUx = read( 'inner-ux.css' );
  const innerUxCode = stripComments( innerUx );
  const tokens = read( 'tokens.css' );
  const innerPages = read( 'inner-pages.css' );

  it( '1. the chevron block is gone from inner-ux.css', () => {
    expect( innerUxCode ).not.toMatch( /appearance:\s*none\s*!important/ );
    expect( innerUxCode ).not.toMatch( /data:image\/svg\+xml[^"]*M6 9l6 6 6-6/ );
    // And it is now declared exactly once, in the shared file, via the token.
    expect( formControlsCode ).toMatch( /background-image:\s*var\(--control-arrow\)\s*!important/ );
  } );

  it( '2. the scrollbar did not follow the controls into the new file', () => {
    expect( formControls ).not.toMatch( /::-webkit-scrollbar/ );
  } );

  it( '3. the set of files skinning a select is exactly the frozen allow-list', () => {
    // 26 of these 29 are pre-existing and stay. form-controls.css is the new one; cart.tsx,
    // shop/[slug].tsx and AddressFields.tsx were rewritten onto the tokens rather than retired.
    expect( census.files ).toEqual( [
      'src/components/AddressFields.tsx',
      'src/components/TemplateSender.tsx',
      'src/components/dashboard/tabs/AppBuilderTab.tsx',
      'src/pages/cart.tsx',
      'src/pages/shop/[slug].tsx',
      'src/pages/workspace/engage/automation/index.tsx',
      'src/pages/workspace/engage/broadcast/index.tsx',
      'src/pages/workspace/engage/content/index.tsx',
      'src/pages/workspace/engage/inbox/index.tsx',
      'src/pages/workspace/engage/logs/index.tsx',
      'src/pages/workspace/engage/push/index.tsx',
      'src/pages/workspace/engage/scheduled/index.tsx',
      'src/pages/workspace/engage/sms/index.tsx',
      'src/pages/workspace/engage/whatsapp/migration.tsx',
      'src/pages/workspace/engage/whatsapp/templates.tsx',
      'src/pages/workspace/engage/whatsapp/waba-dashboard.tsx',
      'src/pages/workspace/forms/responses.tsx',
      'src/pages/workspace/pay/link/index.tsx',
      'src/pages/workspace/pay/records.tsx',
      'src/pages/workspace/task/index.tsx',
      'src/styles/Dashboard.css',
      'src/styles/Layout.css',
      'src/styles/MCPConnections.module.css',
      'src/styles/Pages.css',
      'src/styles/RichTextEditor.module.css',
      'src/styles/form-controls.css',
      'src/styles/inner-pages.css',
      'src/styles/inner-ux.css',
      'src/styles/tokens.css',
    ] );

    // The counts are asserted SEPARATELY from the file set, so a new rule added to an
    // already-allowed file is caught as well as a new file.
    expect( census.summary.ruleSets ).toBe( 83 );
    expect( census.summary.files ).toBe( 29 );
    expect( census.summary.geometryRuleSets ).toBe( 41 );
    expect( census.summary.mechanisms[ 'A-global' ] ).toMatchObject( { ruleSets: 42, files: 9 } );
    expect( census.summary.mechanisms[ 'A-module' ] ).toMatchObject( { ruleSets: 0, files: 0 } );
    expect( census.summary.mechanisms[ 'B-styledjsx' ] ).toMatchObject( { ruleSets: 38, files: 18 } );
    expect( census.summary.mechanisms[ 'C-injected' ] ).toMatchObject( { ruleSets: 3, files: 2 } );

    // The allow-list entry for tokens.css no longer covers its `input, textarea` base rule, and
    // the one for inner-ux.css no longer covers the .inner-page base/:hover/:focus lists, so
    // restoring `select` to either fails on the counts above. Named here so the failure message
    // points at the cause.
    expect( census.hits.filter( h => h.file === 'src/styles/tokens.css' ) ).toHaveLength( 3 );
    expect( census.hits.filter( h => h.file === 'src/styles/inner-ux.css' ) ).toHaveLength( 5 );
    expect( census.hits.filter( h => h.file === 'src/styles/form-controls.css' ) ).toHaveLength( 5 );
  } );

  it( '4. inner-ux.css still declares the select width', () => {
    // A test for a line that must EXIST, which is unusual and is here because deleting it is the
    // cheap mistake. form-controls.css declares no `width` at all - layout belongs to the call
    // site - so this rule is the only thing keeping ~50 workspace pages from shrinking every
    // select to its intrinsic content width. That would be a bigger visible change than anything
    // else in Layer 1, arrived at by deleting a line nobody was looking at.
    expect( innerUxCode ).toMatch( /\.inner-page\s+select\s*\{\s*width:\s*100%\s*;?\s*\}/ );
  } );

  it( '5. form-controls.css declares a transition', () => {
    // The second declaration the retirement must not lose, and the second must-exist assertion
    // here. `select` left tokens.css:420 and inner-ux.css:550, which both carried a transition,
    // so a shared file without one makes ~140 workspace selects and all three public ones snap
    // where they ease today - and makes a date input ease while the select beside it snaps,
    // because only `select` left those rules. Deliberately the weak form: pinning the exact
    // property list would fail on a legitimate later addition; what cannot be allowed is the
    // property going missing entirely.
    expect( formControlsCode ).toMatch( /transition:/ );
  } );

  it( '6. no checkbox or radio rule sets min-height or min-width outside a media block', () => {
    // THE TOP-LEVEL NEGATIVE ONLY. The paired positive - that the <=768px block DOES set both -
    // belongs to batch 1.3c, which is what writes the checkbox and radio rules; asserting it now
    // would be asserting a rule that does not exist yet. The negative is live from this batch
    // because the hazard it guards is permanent: a top-level `min-height: !important` on a
    // checkbox renders a 44px tile at 1280px, and a media-scoped one cannot, because the block
    // does not exist above 768px.
    const topLevel = formControlsCode.split( /@media[^{]*\{/ )[ 0 ];
    expect( topLevel ).not.toMatch( /input\[type="checkbox"\][^{]*\{[^}]*min-(height|width)/ );
    expect( topLevel ).not.toMatch( /input\[type="radio"\][^{]*\{[^}]*min-(height|width)/ );
  } );

  it( '7. the pairing count is 21', () => {
    // A pairing rule is a geometry rule whose selector list names BOTH an input and a select, so
    // form-controls.css reaches one half of it and not the other - which is the criterion the
    // design uses to decide rewrite-versus-accept. It was 22 before this batch; tokens.css's
    // `input, select, textarea` base and inner-ux.css's `.inner-page` base both lost `select`
    // (-2) and form-controls.css's own base rule is a new one (+1), so 21.
    // A TWENTY-SECOND means a new pairing exists whose accept-versus-rewrite decision has not
    // been taken rather than inherited.
    expect( census.summary.pairings ).toBe( 21 );
  } );

  it( '8. every global rule setting a border width or radius on a select sets 2px and 13px', () => {
    // This is what turns "whichever rule wins, the result is identical" from an observation into
    // an invariant. Scoped to mechanism A (the global stylesheets), which is where the exception
    // table below was measured and where the rules that can actually win live: every styled-jsx
    // and injected rule is (0,1,1) or lower and loses outright to form-controls.css's (0,4,1),
    // so their authored 1px values are already dead and normalising them is a separate job.
    //
    // THE EXCEPTIONS ARE PER PROPERTY, NOT PER FILE, and that matters: Pages.css is a
    // border-width exception and a media-query-only radius one - its base radius reads
    // var(--btn-radius), a Pages.css-local property equal to 13px, so it AGREES with us - and
    // MCPConnections.module.css declares a literal 13px and is not a radius exception at all.
    // Keeping the list per-property is what stops a real exception being widened into a
    // fictional one. Each entry is out-RANKED by !important, not agreed with.
    const WIDTH_OK = [ '2px', 'var(--control-border-w)' ];
    const RADIUS_OK = [ '13px', 'var(--radius-md)', 'var(--control-radius)', 'var(--btn-radius)' ];
    const WIDTH_EXCEPT: Record<string, string[]> = {
      'src/styles/Pages.css': [ '1.5px' ],
      'src/styles/Dashboard.css': [ '1px' ],
      'src/styles/MCPConnections.module.css': [ '1px' ],
      'src/styles/RichTextEditor.module.css': [ '1px' ],
    };
    const RADIUS_EXCEPT: Record<string, string[]> = {
      'src/styles/Dashboard.css': [ 'var(--radius-sm)' ],
      'src/styles/RichTextEditor.module.css': [ '6px' ],
      // Both are inside @media (max-width: 768px); the base rule at :876 is 13px and agrees.
      'src/styles/Pages.css': [ '12px', '10px' ],
    };

    const failures: string[] = [];
    for ( const hit of census.hits ) {
      if ( hit.mech !== 'A-global' ) continue;
      const where = `${hit.file}:${hit.line}`;

      for ( const m of hit.decls.matchAll( /(?:^|[;{\s])border(?:-width)?\s*:\s*([^;]+)/g ) ) {
        const width = m[ 1 ].trim().split( /\s+/ )[ 0 ];
        if ( WIDTH_OK.includes( width ) ) continue;
        if ( ( WIDTH_EXCEPT[ hit.file ] || [] ).includes( width ) ) continue;
        failures.push( `${where} border width ${width} (expected 2px)` );
      }

      for ( const m of hit.decls.matchAll( /(?:^|[;{\s])border-radius\s*:\s*([^;]+)/g ) ) {
        const radius = m[ 1 ].trim().split( /\s+/ )[ 0 ];
        if ( RADIUS_OK.includes( radius ) ) continue;
        if ( ( RADIUS_EXCEPT[ hit.file ] || [] ).includes( radius ) ) continue;
        failures.push( `${where} radius ${radius} (expected 13px)` );
      }
    }
    expect( failures ).toEqual( [] );
  } );

  it( '9. the scan finds the planted sample', () => {
    // The scanner is tested before it is trusted, the same way ScrollbarDeclarations.test.ts
    // plants a sample. A scanner with a parsing bug reports FEWER files than exist, which reads
    // as "the gate passed" - and that is precisely how an earlier inventory came to be a quarter
    // of the real number. A gate that can fail silently in the safe-looking direction is worse
    // than no gate.
    const selfTest = census.selfTest;
    // An interpolated ${...} must not be read as CSS braces: if it were, the declarations AFTER
    // it would be lost and the rule would look like a one-property rule.
    expect( selfTest.interpolated_rule_keeps_later_declarations ).toBe( true );
    // A class-only selector, naming no `select` anywhere, must still be reported.
    expect( selfTest.class_only_selector_reported ).toBe( true );
    // And a rule that sets no box property must NOT be reported, or the count means nothing.
    expect( selfTest.non_box_rule_ignored ).toBe( true );
    expect( selfTest.reported.map( r => r.sel ) ).toEqual( [ '.ui-planted', '.ui-planted:focus' ] );
  } );

  it( '12. the two data-URI assets this batch declares are pinned by content', () => {
    // A data URI cannot read a custom property, so the hue inside one is the single hardcoded
    // colour in the FORM CONTROLS block. Pinning the assets is what makes the count a fact
    // rather than a sentence: an earlier revision declared two and needed three, so an
    // implementer had to invent an asset the suite could not see.
    const arrow = /--control-arrow:\s*url\("data:image\/svg\+xml[^"]*"\)/.exec( tokens )?.[ 0 ] || '';
    expect( arrow ).toContain( 'stroke=\'%231a3a2a\'' );   // --accent
    expect( arrow ).toContain( 'M6 9l6 6 6-6' );

    const tick = /--control-tick:\s*url\("data:image\/svg\+xml[^"]*"\)/.exec( tokens )?.[ 0 ] || '';
    expect( tick ).toContain( 'stroke=\'%23ffffff\'' );
    expect( tick ).toContain( 'M20 6L9 17l-5-5' );

    // Both are marked as this batch's.
    expect( tokens ).toMatch( /\/\* 1\.3a \*\/\s*\n\s*--control-arrow:/ );
    expect( tokens ).toMatch( /\/\* 1\.3a \*\/\s*\n\s*--control-tick:/ );

    // --control-dot and --control-dash are the other two of the four. They belong to batch 1.3c
    // with the checkbox and radio rules that consume them, and a token whose consumer does not
    // exist is surface area no test can see. This assertion inverts when 1.3c lands.
    expect( tokens ).not.toMatch( /--control-dot:/ );
    expect( tokens ).not.toMatch( /--control-dash:/ );
  } );

  /**
   * The carried checks. None of them is about the scan, which is why none is numbered.
   */
  it( 'declares no font-size at all, and leaves the three existing claimants alone', () => {
    // Layout.css:132-154 is a 23-line comment recording the incident this would re-create: an
    // !important font-size is a FLOOR THAT CANNOT BE EXCEEDED, and it painted four components'
    // deliberate 17px at 16px. The floor also already holds without any help from this file.
    // Asserted on the comment-stripped text, for the reason the stripper exists: the policy
    // note in form-controls.css has to NAME the property it refuses to declare, or the next
    // reader adds it back. Prose explaining an absence cannot be allowed to count as the thing.
    expect( formControlsCode ).not.toMatch( /font-size/ );

    // Both <=768px iOS-zoom blocks, which beat even an inline fontSize.
    // Two blocks, and they are spelled differently - `@media (max-width: 768px)` and
    // `@media screen and (max-width: 768px)` - so the query is matched loosely on purpose.
    const zoomBlocks = tokens.match( /@media[^{]*max-width:\s*768px[\s\S]*?font-size:\s*16px\s*!important/g );
    expect( zoomBlocks?.length ).toBe( 2 );

    // And the third claimant, which is NOT inside a media query and so already pins every
    // workspace select at 16px at every viewport. It is cited as the reason the workspace needs
    // nothing from form-controls.css, so it has to still be there for the reason to hold.
    expect( innerPages ).toMatch(
      /\.layout \.main-content select:not\(\[data-public-ui\]\)\s*\{\s*font-size:\s*16px\s*!important/
    );
  } );

  it( 'mirrors the chevron for RTL with an attribute-keyed override', () => {
    // background-position-x is not a logical property, so the one physical edge in the file
    // needs one override. [dir="rtl"] rather than :dir(rtl) because `dir` is declared on <html>
    // in the exported HTML and rtlcheck.js fails the build if it is absent.
    expect( formControlsCode ).toMatch( /\[dir="rtl"\]\s*select[^{]*\{[^}]*background-position:\s*left/ );
  } );

  it( 'is imported LAST in _app.tsx', () => {
    // The whole mechanism rests on this. A ninth import after button.css arrives after every
    // rule in the inventory, including Layout.css's own @import of tokens.css - so a per-page
    // rule that ties us on specificity loses on source order instead of winning.
    const app = fs.readFileSync( path.join( __dirname, '..', 'pages', '_app.tsx' ), 'utf8' );
    const imports = [ ...app.matchAll( /^import\s+'\.\.\/styles\/([\w.-]+\.css)';/gm ) ].map( m => m[ 1 ] );
    expect( imports[ imports.length - 1 ] ).toBe( 'form-controls.css' );
    expect( imports[ imports.length - 2 ] ).toBe( 'button.css' );
  } );

  it( 'keeps the !important policy the design table specifies', () => {
    // The three carve-outs exist to let a call site keep something it legitimately owns, and
    // each one is the kind of line that gets "tidied" by someone making the file look
    // consistent. They are asserted so tidying fails.
    const base = /^select:not\(\[data-ui-raw\][\s\S]*?\{([\s\S]*?)\}/m.exec( formControlsCode )?.[ 1 ] || '';
    expect( base ).not.toBe( '' );

    // Owned, and therefore important: these are the properties the 101 inline styles must lose.
    for ( const prop of [
      'appearance', '-webkit-appearance', '-moz-appearance',
      'border-width', 'border-style', 'border-radius',
      'padding-block', 'padding-inline-start', 'padding-inline-end',
      'min-height', 'color',
    ] ) {
      expect( base, `${prop} must be !important` )
        .toMatch( new RegExp( `${prop.replace( /[-]/g, '\\-' )}:[^;]*!important` ) );
    }

    // border-color is NOT important, so engage/appointments' inline #dc2626 past-date error on a
    // date input still shows inside our geometry. This is also why the border is written as
    // longhands: an !important `border` shorthand would set the colour too and erase it.
    expect( base ).toMatch( /border-color:\s*var\(--control-border\)\s*;/ );
    expect( base ).not.toMatch( /border-color:[^;]*!important/ );
    expect( base ).not.toMatch( /(?:^|[;\s])border:\s/ );

    // background-color is NOT important: 12 call sites set a background shorthand for a state
    // tint and ours is the fallback.
    expect( base ).not.toMatch( /background-color:[^;]*!important/ );

    // No width and no layout property, ever: that belongs to the call site.
    for ( const prop of [ 'width', 'max-width', 'min-width', 'flex', 'margin' ] ) {
      expect( base, `${prop} is layout and must not be declared here` )
        .not.toMatch( new RegExp( `(?:^|[;\\s])${prop}:` ) );
    }
  } );

  it( 'declares the focus ring important and the outline reset NOT important', () => {
    // The outline row is the one place in this file where dropping an !important is the correct
    // act. The focus rule is (0,5,1) and cart.tsx's and AddressFields' call-site outlines are
    // (0,2,0) and (0,0,1), so importance is the ONLY axis on which they can win - and if this
    // reset were important, a 3px 11.85:1 dark-green outline on the checkout page would be
    // silently replaced by a lime ring.
    const focus = /^select:not\(\[data-ui-raw\][\s\S]*?:focus,[\s\S]*?\{([\s\S]*?)\}/m
      .exec( formControlsCode )?.[ 1 ] || '';
    expect( focus ).toMatch( /box-shadow:\s*var\(--focus-ring\)\s*!important/ );
    expect( focus ).toMatch( /outline:\s*none\s*;/ );
    expect( focus ).not.toMatch( /outline:[^;]*!important/ );
    // :focus, not :focus-visible. All twenty existing focus rules on a select in this tree
    // target :focus, and a rule on :focus-visible does not suppress one on :focus - so mixing
    // the two shows a different ring depending on whether the control was clicked or tabbed to.
    expect( formControlsCode ).not.toMatch( /select[^{,]*:focus-visible/ );
  } );
} );
