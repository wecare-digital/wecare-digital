import { describe, expect, it } from 'vitest';
import fs from 'fs';
import path from 'path';

import census from './fixtures/control-skin-census.json';

// Census regenerated after retiring the unused RichTextEditor stylesheet and
// previously retired pay-link page: 62 select rules across20files,27geometry rules.
// Checkbox/radio rules are unchanged; the no-new-skins gate remains enforced.

/**
 * INVARIANT 4 — the chevron is declared in exactly one file, and no NEW file starts skinning a
 * select, in any of the three authoring mechanisms.
 *
 * WHAT THIS IS AND IS NOT. It is a NO-NEW-SKINS gate, not a uniqueness claim, and the
 * difference is the whole point. 28 files skinned a select before batch 1.3a and 21 of them
 * still do: retiring `select` from the rule sets that remain — scoped to single workspace pages
 * no harness can load — is a consolidation with its own risk budget and its own sign-off. A
 * test asserting uniqueness would have to be written to fail or written to lie. What it can
 * honestly do is fail the moment a TWENTY-THIRD file joins — which is the mechanism that
 * produced six competing scrollbar declarations, one file at a time.
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
 * ONE COMMAND, BOTH ELEMENT SETS. `--json` emits the select census under the top-level keys and
 * the checkbox/radio census under `checkboxRadio`, because the fixture is one committed file and
 * two scans written separately would drift apart. That is also why assertion 10 reads this
 * fixture rather than getting a scanner of its own: it shares assertion 3's producer, so a count
 * that moves means a RULE moved and not that two scanners disagree.
 *
 * A real change then shows up as a fixture diff AND a failing literal, which is a reviewable
 * pair rather than an integer nobody can re-derive. LINE NUMBERS IN THE FIXTURE ARE NOT
 * ASSERTED — they move whenever any of these 22 files is edited, and asserting them would make
 * this suite fail for reasons that have nothing to do with control skinning.
 *
 * THE FIGURES WERE 85/43 PRE-1.3a, 83/41 POST-1.3a, AND ARE 67/29 POST-LAYER-2. All three are
 * recorded because the arithmetic between them is the only thing that makes the current numbers
 * checkable.
 *
 * 1.3a: the pre-batch inventory was 85 rule sets / 43 geometry (A-global 44 in 8 files,
 * B-styledjsx 38 in 18, C-injected 3 in 2). That batch removed `select` from six counted rule
 * sets (tokens.css base/:hover/:focus, inner-ux.css base/:hover/:focus), deleted a seventh in
 * full (the chevron block), and added form-controls.css as a ninth mechanism-A file contributing
 * five — so 85 - 7 + 5 = 83, and 43 - 3 + 1 = 41 geometry.
 *
 * LAYER 2 (batches 2b-2f) then migrated 159 native selects onto `ui/Select`, and the fixture was
 * NOT regenerated during those batches — deliberately, because each of them changed call sites
 * rather than stylesheets, and regenerating inside one of them would have meant editing this
 * gate's frozen numbers for a reason that is about elements. It was regenerated once, on the
 * finished tree, by the cross-batch integration pass, and 16 rule sets in 10 files dropped out:
 *
 *   83 - 16 = 67 rule sets, 29 - 7 = 22 files, B-styledjsx 38 - 16 = 22 in 18 - 7 = 11 files.
 *   41 - 12 = 29 geometry — only 12 of the 16 set a box property; the other four
 *   (`.cart-option:focus-visible`, `.ui-pay-in:focus`, `.sms-search:focus`, `.waba-select:hover`)
 *   are state rules that set none.
 *
 * ALL 16 ARE A MIGRATION CONSEQUENCE RATHER THAN A CSS EDIT, AND THE DISTINCTION IS WHAT MAKES
 * THE DROP SAFE TO ACCEPT. Fifteen are mode-`class` hits counted only because a `<select>` wore
 * the class — `classnames_on_select()` matches `<select` literally, so the rule stops being a
 * select skin the moment the element becomes a `<button role="combobox">`, whether or not the
 * rule itself was touched. The sixteenth, `.shopd-options select`, is a `select`-token rule that
 * batch 2e deleted outright with the control it dressed. MECHANISM A DID NOT MOVE AT ALL:
 * A-global is 42 rule sets in 9 files before and after, form-controls.css still contributes
 * exactly 5, `pairings` is still 21, and the whole checkbox/radio census is unchanged at 29/10.
 * So the global stylesheets — the only mechanism whose rules can actually win the cascade — are
 * byte-for-byte the set 1.3a froze.
 *
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
    // 21 of these 22 are pre-existing and stay; form-controls.css is the one 1.3a added.
    // AddressFields.tsx and cart.tsx are still here because 1.3a rewrote their rule sets onto
    // the tokens rather than retiring them, and the `input,select` selector list survives with
    // an unreached `select` arm — retiring an arm from a shared list is its own consolidation.
    // SEVEN FILES LEFT THIS LIST IN LAYER 2, and all seven left because their select became a
    // `<button role="combobox">`, not because their CSS was edited: TemplateSender.tsx,
    // engage/automation, engage/broadcast, engage/content, engage/inbox, engage/scheduled, and
    // shop/[slug].tsx — the last of which did delete its rule, with the control, in batch 2e.
    expect( census.files ).toEqual( [
      'src/components/AddressFields.tsx',
      'src/components/dashboard/tabs/AppBuilderTab.tsx',
      'src/pages/cart.tsx',
      'src/pages/workspace/engage/logs/index.tsx',
      'src/pages/workspace/engage/push/index.tsx',
      'src/pages/workspace/engage/sms/index.tsx',
      'src/pages/workspace/engage/whatsapp/migration.tsx',
      'src/pages/workspace/engage/whatsapp/templates.tsx',
      'src/pages/workspace/engage/whatsapp/waba-dashboard.tsx',
      'src/pages/workspace/forms/responses.tsx',
      'src/pages/workspace/pay/records.tsx',
      'src/pages/workspace/task/index.tsx',
      'src/styles/Dashboard.css',
      'src/styles/Layout.css',
      'src/styles/MCPConnections.module.css',
      'src/styles/Pages.css',
      'src/styles/form-controls.css',
      'src/styles/inner-pages.css',
      'src/styles/inner-ux.css',
      'src/styles/tokens.css',
    ] );

    // The counts are asserted SEPARATELY from the file set, so a new rule added to an
    // already-allowed file is caught as well as a new file. The arithmetic from 1.3a's frozen
    // 83/41/29 to these figures is in this file's header, property by property.
    expect( census.summary.ruleSets ).toBe( 62 );
    expect( census.summary.files ).toBe( 20 );
    expect( census.summary.geometryRuleSets ).toBe( 27 );
    // A-global, A-module and C-injected are UNCHANGED from 1.3a. Only mechanism B moved, and
    // only because elements moved - so a regression in the global stylesheets still fails here.
    expect( census.summary.mechanisms[ 'A-global' ] ).toMatchObject( { ruleSets: 40, files: 8 } );
    expect( census.summary.mechanisms[ 'A-module' ] ).toMatchObject( { ruleSets: 0, files: 0 } );
    expect( census.summary.mechanisms[ 'B-styledjsx' ] ).toMatchObject( { ruleSets: 19, files: 10 } );
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

  it( '6. the tap-target floor is declared in the <=768px block and nowhere else', () => {
    // A NEGATIVE PAIRED WITH A POSITIVE, and each one passes without the other, which is why
    // both halves are here. The negative alone passes on a file that simply dropped the phone
    // floor; the positive alone says nothing about a stray desktop min-height. And the hazards
    // are different in kind: a top-level min-height renders a 44px tile at 1280px, while a
    // missing media-block one leaves the phone box at Layout.css:127's 32px.
    //
    // THIS RESTORES A FLOOR RATHER THAN PRESERVING ONE. Layout.css:127's `min-height: 32px`
    // and tokens.css:576's `min-height: 44px` are BOTH (0,1,1) on the checkbox compound, and
    // tokens.css arrives through Layout.css:8's @import, so Layout.css is later in source order
    // and 32px wins at every viewport - phones included. tokens.css:581's min-width is
    // unopposed, so the phone box today is 44 wide by 32 high.
    const blocks = formControlsCode.split( /@media[^{]*\{/ );
    const topLevel = blocks[ 0 ];
    expect( topLevel ).not.toMatch( /input\[type="checkbox"\][^{]*\{[^}]*min-(height|width)/ );
    expect( topLevel ).not.toMatch( /input\[type="radio"\][^{]*\{[^}]*min-(height|width)/ );

    // The positive, scoped to the <=768px block. There is exactly one media block in this file
    // and it is the floor; if a second is ever added, this locates the right one by its query.
    const phone = /@media\s*\(\s*max-width:\s*768px\s*\)\s*\{([\s\S]*)$/.exec( formControlsCode )?.[ 1 ] || '';
    expect( phone, 'the <=768px block must exist' ).not.toBe( '' );
    expect( phone ).toMatch( /input\[type="checkbox"\][^{]*\{[^}]*min-height/ );
    expect( phone ).toMatch( /input\[type="checkbox"\][^{]*\{[^}]*min-width/ );
    expect( phone ).toMatch( /min-height:\s*var\(--tap-target\)/ );
    expect( phone ).toMatch( /min-width:\s*var\(--tap-target\)/ );
  } );

  it( '7. the current pairing count is 19', () => {
    // A pairing rule is a geometry rule whose selector list names BOTH an input and a select, so
    // form-controls.css reaches one half of it and not the other - which is the criterion the
    // design uses to decide rewrite-versus-accept. It was 22 before this batch; tokens.css's
    // `input, select, textarea` base and inner-ux.css's `.inner-page` base both lost `select`
    // (-2) and form-controls.css's own base rule is a new one (+1), so 21.
    // LAYER 2 DID NOT MOVE IT. All 16 rule sets that left the census in 2b-2f are mechanism-B
    // class hits plus one deleted styled-jsx rule, and a pairing needs a selector list naming
    // both an input and a select - which none of those 16 was. AddressFields' `input,select` is
    // still a pairing, and still counted, because the input half is live.
    // A TWENTY-SECOND means a new pairing exists whose accept-versus-rewrite decision has not
    // been taken rather than inherited.
    expect( census.summary.pairings ).toBe( 19 );
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
    };
    const RADIUS_EXCEPT: Record<string, string[]> = {
      'src/styles/Dashboard.css': [ 'var(--radius-sm)' ],
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

  it( '10. the set of files skinning a checkbox or a radio is exactly the frozen allow-list', () => {
    // WHY THIS EXISTS AT ALL. Until batch 1.3c nothing inventoried the 53 checkboxes and 18
    // radios: the scanner was hardcoded to <select>, so a twenty-ninth file skinning a select
    // failed this suite while a twenty-first file skinning a checkbox landed unnoticed. That
    // asymmetry is what left 71 controls without an inventory for five revisions. Assertion 10
    // now shares assertion 3's PRODUCER - the same committed Python, run with
    // `--elements checkbox,radio` - rather than getting a second scanner that could disagree
    // with it. Regenerate the fixture with the single command in this file's header; --json
    // emits both element sets from one invocation for exactly that reason.
    //
    // THE COUNTING RULE, same sentence with the element set substituted: one rule set = one
    // {...} block, counted once regardless of how many compounds its selector list holds or
    // how many at-rules it is nested inside; a block counts when its selector names
    // input[type="checkbox"] or input[type="radio"] as a whole token, OR names a class worn by
    // one, AND its body sets at least one box property.
    //
    // ONE DELIBERATE WIDENING, scoped to this element set and recorded because it is the only
    // place 1.3c touches how the scan counts. `display`, `width` and `margin` count as skinning
    // a checkbox or radio and nothing else. The two visually-hidden native controls in the tree
    // are hidden with `display: none` (voice-in/index.tsx:823) and sized away with
    // `width: auto; margin: 0` (engage/sms/index.tsx:591), and neither property was in the
    // select-era set - so without the widening the census reports 18 in 8 files and is blind to
    // the two rules this batch most needs to see, because our appearance:none box would be
    // drawn on top of a control a call site deliberately hid. Adding `width` to the shared set
    // instead would make `.inner-page select { width: 100% }` a counted rule and move the
    // select total to 84, which is the "edit the expected value instead of fixing the bug"
    // failure this fixture exists to prevent.
    //
    // THE PRE-BATCH FIGURE WAS 20 RULE SETS IN 9 FILES (A 12 in 6, B+C 8 in 3; 15 matched on
    // the element token, 5 on a resolved class), reproduced exactly on the tree before this
    // batch wrote a line of CSS. AND THE 20 IS NOT 20 RULES ON A CHECKBOX: it is 16 rules on the
    // control plus FOUR sibling-combinator rules keyed on `.bc-radio` that style the `+`
    // sibling `.bc-choice-face` rather than the radio itself. Those four are what a user of
    // /post/<slug>/ actually sees, they are untouched by this batch, and they are counted
    // because the counting rule matches on the selector naming a class worn by a radio - which
    // is the right behaviour, since a rule keyed on a control's class is exactly the kind of
    // thing a later edit could turn into a competitor.
    //
    // STATED BLIND SPOT, carried here rather than left in the design: a BARE `input` selector
    // is invisible to this counting rule and reaches every type. Seven matter and are pinned by
    // LINE rather than by this scan - tokens.css:420, :434, :440, inner-pages.css:279, :1999,
    // :2021 and MCPConnections.module.css:14 (design.md 1.14c's second table; line numbers are
    // that document's, taken before batches 1.1-1.3a moved them). tokens.css:420 is the one
    // that forces form-controls.css to declare `padding: 0` on the checkbox, and
    // inner-pages.css:279 and :2021 are the two that already paint a 0.3-alpha focus ring on
    // every workspace checkbox - which is why the focus rule targets :focus and not
    // :focus-visible. A census presented as exhaustive is how the select half went wrong twice.
    const cbr = census.checkboxRadio;

    // BLOGCONTRIBUTION.TSX LEFT THIS LIST ON 2026-10-10, AND IT LEFT BY LOSING ITS RADIO RATHER
    // THAN BY HAVING ITS CSS EDITED - the same kind of migration consequence the select half
    // records above, so the figures below are an arithmetic consequence and not a loosened gate.
    // Owner instruction turned the blog contribution block into a single WhatsApp anchor: the
    // ₹250 amount pill went, and with it the visually-hidden `.bc-radio`, its `data-ui-raw`
    // opt-out and all five of the rule sets keyed on that class (the hidden control itself plus
    // the four sibling-combinator rules that drew the `.bc-choice-face` pill). There is no
    // checkbox or radio anywhere in that component now, so nothing in it can compete with the
    // shared skin.
    //
    //   29 - 5 = 24 rule sets, 10 - 1 = 9 files, B-styledjsx 8 - 5 = 3 in 3 - 1 = 2 files,
    //   16 - 1 = 15 geometry (only `.bc-radio` itself set a box property; the other four are
    //   state rules on the sibling), and class-resolved 5 - 5 = 0.
    //
    // MECHANISM A DID NOT MOVE: A-global is still 21 rule sets in 7 files and form-controls.css
    // still contributes exactly 9, so the global stylesheets - the only mechanism whose rules
    // can actually win the cascade - are byte-for-byte the set 1.3c froze.
    //
    // 8 of these 9 are pre-existing and stay. form-controls.css is 1.3c's own - and it has to
    // be allow-listed, because without it this assertion fails the moment that batch writes the
    // very file it exists to protect.
    expect( cbr.files ).toEqual( [
      'src/pages/workspace/engage/sms/index.tsx',
      'src/pages/workspace/engage/voice-in/index.tsx',
      'src/styles/Dashboard.css',
      'src/styles/Layout.css',
      'src/styles/Pages.css',
      'src/styles/form-controls.css',
      'src/styles/inner-pages.css',
      'src/styles/inner-ux.css',
      'src/styles/tokens.css',
    ] );

    // Counts asserted separately from the file set, so a new rule in an already-allowed file is
    // caught as well as a new file. 20 pre-1.3c + form-controls.css's own 9 = 29, then - 5 with
    // BlogContribution's radio = 24. form-controls.css's 9 are: the shared drawn box, the
    // checkbox radius, the radio radius, :hover, checkbox :checked, radio :checked,
    // :indeterminate, :focus, and the <=768px floor.
    expect( cbr.summary.ruleSets ).toBe( 24 );
    expect( cbr.summary.files ).toBe( 9 );
    expect( cbr.summary.geometryRuleSets ).toBe( 15 );
    expect( cbr.summary.mechanisms[ 'A-global' ] ).toMatchObject( { ruleSets: 21, files: 7 } );
    expect( cbr.summary.mechanisms[ 'A-module' ] ).toMatchObject( { ruleSets: 0, files: 0 } );
    expect( cbr.summary.mechanisms[ 'B-styledjsx' ] ).toMatchObject( { ruleSets: 3, files: 2 } );
    expect( cbr.summary.mechanisms[ 'C-injected' ] ).toMatchObject( { ruleSets: 0, files: 0 } );
    // NO class-resolved hits left: all five were BlogContribution's `.bc-radio` rules, which went
    // with the amount pill. If this moves off 0, a class worn by a checkbox or radio gained a
    // skin somewhere - which is the signal the mode split exists to give.
    expect( cbr.summary.matchModes ).toMatchObject( { element: 24, class: 0 } );
    expect( cbr.hits.filter( h => h.file === 'src/components/BlogContribution.tsx' ) ).toHaveLength( 0 );
    expect( cbr.hits.filter( h => h.file === 'src/styles/form-controls.css' ) ).toHaveLength( 9 );
  } );

  it( '11. no :checked and no :indeterminate rule in form-controls.css sets box-shadow', () => {
    // A NEGATIVE, and the only mechanical guard against a collision inside this file's own
    // contract. box-shadow MEANS focus ring here and carries !important; the radio's checked
    // dot and the indeterminate dash are background-images for that reason. Draw an indicator
    // with `box-shadow: inset 0 0 0 4px` instead and it sits at the same (0,5,1) with one
    // pseudo-class as the focus rule, loses to its !important, and a keyboard-focused checked
    // radio renders as a solid accent disc with no dot.
    //
    // THE NEGATIVE IS THE HALF THAT EARNS ITS PLACE. The positive it pairs with - that the
    // focus rule declares `box-shadow: var(--focus-ring) !important` - passes whether or not
    // the collision exists, which is precisely how the defect shipped in a previous revision of
    // the design with everything else green.
    const offenders: string[] = [];
    for ( const m of formControlsCode.matchAll( /([^{}]+)\{([^}]*)\}/g ) ) {
      const selector = m[ 1 ].replace( /\s+/g, ' ' ).trim();
      if ( !/:checked|:indeterminate/.test( selector ) ) continue;
      if ( /box-shadow/.test( m[ 2 ] ) ) offenders.push( selector );
    }
    expect( offenders ).toEqual( [] );

    // And the paired positive, so a file that simply deleted the indicator rules cannot pass.
    // Three state rules exist and each one draws with background-image, not box-shadow.
    const stateRules = [ ...formControlsCode.matchAll( /([^{}]+)\{([^}]*)\}/g ) ]
      .filter( m => /:checked|:indeterminate/.test( m[ 1 ] ) );
    expect( stateRules ).toHaveLength( 3 );
    for ( const m of stateRules ) {
      expect( m[ 2 ], `${m[ 1 ].trim()} must draw with background-image` ).toMatch( /background-image:\s*var\(--control-(tick|dot|dash)\)/ );
      // :indeterminate MUST set the fill as well as the mark, or it is a white dash on a white
      // box - an empty box, which is the "looks permanently unchecked" failure this batch is for.
      expect( m[ 2 ], `${m[ 1 ].trim()} must set the accent fill` ).toMatch( /background-color:\s*var\(--accent\)/ );
    }
    expect( formControlsCode ).toMatch(
      /input\[type="checkbox"\][^{]*:indeterminate\s*\{[^}]*background-color:\s*var\(--accent\)/
    );
  } );

  it( '12. all four data-URI assets are pinned by content', () => {
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

    // The radio's dot. A FILL rather than a stroke, and r='5' of a 24-unit viewBox so the disc
    // lands at about 5px inside the 12px indicator box - the same optical weight as the 4px
    // inset ring an earlier revision drew with box-shadow, which is the mechanism assertion 11
    // now forbids.
    const dot = /--control-dot:\s*url\("data:image\/svg\+xml[^"]*"\)/.exec( tokens )?.[ 0 ] || '';
    expect( dot ).toContain( 'fill=\'%23ffffff\'' );
    expect( dot ).toContain( 'r=\'5\'' );

    // The indeterminate dash. Its one consumer in the tree is DataTab.tsx:182's tri-state
    // select-all checkbox.
    const dash = /--control-dash:\s*url\("data:image\/svg\+xml[^"]*"\)/.exec( tokens )?.[ 0 ] || '';
    expect( dash ).toContain( 'stroke=\'%23ffffff\'' );
    expect( dash ).toContain( 'M6 12h12' );

    // Each one is marked with the batch that declared it. An earlier revision of the design
    // claimed "two data URIs" while needing a third that no token held, so an implementer had
    // to invent an asset the suite could not see. Pinning all four is what makes the count of
    // four a fact rather than a sentence.
    expect( tokens ).toMatch( /\/\* 1\.3a \*\/\s*\n\s*--control-arrow:/ );
    expect( tokens ).toMatch( /\/\* 1\.3a \*\/\s*\n\s*--control-tick:/ );
    expect( tokens ).toMatch( /\/\* 1\.3c \*\/\s*\n\s*--control-dot:/ );
    expect( tokens ).toMatch( /\/\* 1\.3c \*\/\s*\n\s*--control-dash:/ );

    // And all four are consumed, so none of them is surface area no test can see.
    for ( const token of [ 'arrow', 'tick', 'dot', 'dash' ] ) {
      expect( formControlsCode, `--control-${token} must have a consumer` )
        .toMatch( new RegExp( `var\\(--control-${token}\\)` ) );
    }
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
