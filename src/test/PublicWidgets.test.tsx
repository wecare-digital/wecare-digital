import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe( 'support widget wiring', () => {
  const app = readFileSync( resolve( process.cwd(), 'src/pages/_app.tsx' ), 'utf8' );
  const widget = readFileSync( resolve( process.cwd(), 'src/components/SupportWidget.tsx' ), 'utf8' );
  /* AuthGate - the sign-in screen, and the third surface the mount count below is about -
     lives here rather than in _app.tsx since @aws-amplify/ui-react was split out of the
     shared bundle. See the note at that assertion. */
  const authShell = readFileSync( resolve( process.cwd(), 'src/components/AuthShell.tsx' ), 'utf8' );

  /**
   * The same source with comments removed, for NEGATIVE assertions only.
   *
   * This has now bitten five times in this suite, always the same way: a construct is
   * removed, the removal is explained in a comment, and the comment necessarily names the
   * construct - so the guard fires on the note recording the fix. Individually pinning each
   * assertion to a code-shaped form worked but had to be re-derived every time, and the
   * fifth failure was `not.toContain( '<select' )` catching a comment that says the native
   * select was replaced.
   *
   * Stripping first removes the whole class of false alarm. POSITIVE assertions deliberately
   * keep using the raw source: matching a real declaration in the raw text is stricter, and
   * a positive match cannot be fooled by prose in the way an absence check can.
   */
  const widgetCode = widget
    .replace( /\/\*[\s\S]*?\*\//g, '' )
    .replace( /\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '' )
    .replace( /^\s*\/\/.*$/gm, '' );

  it( 'renders one combined widget and no longer loads the external WhatsApp script', () => {
    // WHAT CHANGED. The WhatsApp button used to be injected by a third-party script,
    // wecare-wa-widget.js on app.wecare.digital, gated behind a showPublicWhatsApp flag.
    // That put a green 56px circle at z-index 2147483647 - the maximum 32-bit integer -
    // which nothing could be stacked above, so this repo's own language panel had to be
    // shoved sideways to avoid being punched through. It was also the only off-palette
    // colour on every public page, and its size and icon were not ours to change.
    expect( app ).toContain( "import SupportWidget from '../components/SupportWidget'" );
    expect( app ).toContain( '<SupportWidget />' );

    // ASSERTED AGAINST CODE, NOT PROSE. A bare not.toContain('wecare-wa-widget.js') was
    // the first version and it failed on this file's own comments, which explain why the
    // script was retired - the guard cannot be allowed to fire on the note recording the
    // decision. So these pin the constructs that would actually load or gate it.
    expect( app ).not.toContain( 'src="https://wecare.digital/get/o/stream/code/wecare-wa-widget.js"' );
    expect( app ).not.toContain( 'id="wecare-wa-widget"' );
    expect( app ).not.toContain( 'const showPublicWhatsApp' );
    expect( app ).not.toContain( '{ showPublicWhatsApp && (' );

    // The old component name must be gone, not merely unused.
    expect( existsSync( resolve( process.cwd(), 'src/components/LanguageBar.tsx' ) ) ).toBe( false );
    expect( app ).not.toContain( '<LanguageBar' );
  } );

  it( 'sends WhatsApp through the short link, which resolves to the original destination', () => {
    // THE DESTINATION HAS NOT MOVED, ONLY THE URL THAT NAMES IT. wecare.digital/r/wa answers
    // 302 to https://wa.me/message/APDM5HUWH26SG1 - the URL that used to be hardcoded here,
    // itself read out of the retired wecare-wa-widget.js rather than invented. Verified by
    // request before the swap, not assumed.
    // Asserting the short link rather than the wa.me URL is the point: the destination becomes
    // editable without a deploy, and this button now matches the link the voice handlers read
    // out to callers instead of duplicating it.
    expect( widget ).toContain( 'href="https://wecare.digital/r/wa"' );
    // And no wa.me URL may be the HREF any more, or both would ship and the indirection would
    // be decorative. Scoped to href= rather than the bare string on purpose: the component's
    // comment names the wa.me URL to record what the short link resolves to, and this file is
    // read as SOURCE, so a blanket not.toContain would fail on the documentation explaining
    // the change. That is precisely what it did first time.
    expect( widget ).not.toContain( 'href="https://wa.me/' );
    // An anchor, not a button with an onClick: it leaves the site, so it has to be
    // middle-clickable and copyable like any other link.
    expect( widget ).toContain( 'className="wc-wa"' );
    expect( widget ).toContain( 'rel="noopener noreferrer"' );
  } );

  it( 'presents both actions as one pill, in the site lime and smaller than before', () => {
    // One container holding both controls - previously two unrelated floating circles
    // with no shared colour, shape or container.
    expect( widget ).toContain( '.wc-pill{position:relative;overflow:hidden;display:inline-flex' );
    expect( widget ).toContain( 'border:1.5px solid #d1f470' );
    // WhatsApp takes the palette's own-surface pairing, NOT WhatsApp green.
    expect( widget ).toContain( 'background:#d1f470;color:#1a3a2a' );
    expect( widget ).not.toContain( '#25D366' );
    // 40px controls, down from the 56px pair they replace.
    expect( widget ).toContain( '.wc-wa{width:40px;height:40px' );
    expect( widget ).toContain( 'height:40px' );
  } );

  it( 'uses a searchable panel, and owns the keyboard that the native select used to give free', () => {
    // WHAT CHANGED, AND WHY THIS TEST IS NOW THE OPPOSITE OF WHAT IT WAS. This asserted the
    // presence of a native <select>, which had replaced an earlier custom panel precisely
    // because the platform supplies keyboard navigation, screen-reader announcement and the
    // phone's OS picker for nothing. That trade has been reversed on instruction, and the
    // reason it is defensible is that the native picker showed the provider's raw catalogue -
    // 76 entries, two thirds of them irrelevant, unsearchable on desktop.
    //
    // The cost of reversing it is the ARIA and keyboard wiring below. Every one of these is
    // something the <select> did for free, so every one is something that can now silently
    // break. A broken keyboard is invisible in a screenshot, which is why it is pinned here
    // rather than left to review.
    expect( widget ).toContain( 'role="combobox"' );
    expect( widget ).toContain( 'aria-autocomplete="list"' );
    expect( widget ).toContain( 'aria-activedescendant={' );
    expect( widget ).toContain( 'role="listbox"' );
    expect( widget ).toContain( 'role="option"' );
    expect( widget ).toContain( 'aria-haspopup="listbox"' );
    for ( const key of [ 'ArrowDown', 'ArrowUp', 'Enter', 'Escape', 'Tab' ] ) {
      expect( widget, `the panel must handle ${key}` ).toContain( `'${key}'` );
    }
    // Focus must come back to the chip on close. Without it, Escape sends a keyboard user to
    // the top of the document - a page-length punishment for changing their mind.
    expect( widget ).toContain( 'chipRef.current?.focus()' );

    // aria-disabled, NOT the disabled attribute. A disabled element cannot hold focus, so
    // disabling the chip the moment a language is applied dropped focus to the body every
    // time. Caught by driving the keyboard, not by looking.
    expect( widget ).toContain( 'aria-disabled={ busy }' );
    // Matched with a leading-whitespace boundary, not as a bare substring: 'aria-disabled={
    // busy }' CONTAINS 'disabled={ busy }', so the naive negative assertion failed against
    // the very fix it was written to protect.
    expect(
      /\sdisabled=\{/.test( widgetCode ),
      'the chip must not use the disabled attribute - a disabled element cannot hold focus, '
      + 'so applying a language dropped focus to the body every time. Use aria-disabled.'
    ).toBe( false );

    // The native control is gone, not merely unused. Checked against comment-stripped source:
    // the note above this test explains what the select was replaced by, and therefore names
    // it.
    expect( widgetCode ).not.toContain( '<select' );

    // 16px on the search field is not cosmetic: iOS Safari zooms the viewport when a focused
    // form control is smaller than that, and does not zoom back out on blur.
    expect( widget ).toContain( 'font-size:16px' );
  } );

  it( 'trims the catalogue on arrival, including an entry that is not a language', () => {
    // 'auto' is a SOURCE-language sentinel the provider ships in the same list as real
    // destinations. Selecting it sent targetLanguage: "auto" to /translate. It was offered to
    // every visitor, indistinguishable from a real choice.
    // ASSERTED AGAINST THE SET LITERAL, not against the file. The first version of this test
    // checked that the source contained "'auto'" anywhere - and it passed after 'auto' was
    // removed from DROP_CODES, because the comment above the constant quotes it while
    // explaining why it is dropped. Proved by deliberately re-introducing the bug: the guard
    // stayed green. Reading the Set's own contents is the only form that cannot be satisfied
    // by prose.
    expect( widgetCode ).toContain( 'DROP_CODES.has( row.code )' );
    const dropSet = /const DROP_CODES = new Set\(([^)]*)\)/.exec( widgetCode );
    expect( dropSet, 'DROP_CODES declaration not found' ).not.toBeNull();
    for ( const code of [ 'auto', 'fr-CA', 'zh-TW', 'es-MX', 'pt-PT' ] ) {
      expect(
        dropSet![ 1 ],
        `'${code}' must be in DROP_CODES. ${code === 'auto'
          ? "'auto' is a source-language sentinel, not a destination - offering it sends targetLanguage: \"auto\""
          : 'it is a multi-word region variant of a base language that stays in the list'}`
      ).toContain( `'${code}'` );
    }
    // Haitian Creole is renamed rather than dropped: it has no base-language twin.
    expect( widget ).toContain( "ht: 'Creole'" );
  } );

  it( 'ranks an exact code match first', () => {
    // A REAL DEFECT CAUGHT IN THE MOCKUP. Rows are sorted alphabetically, so typing 'ta'
    // listed Tagalog above Tamil - Tagalog wins on spelling - while 'ta' is Tamil's own ISO
    // code. For an audience in Bharat the most likely language sat second behind one almost
    // nobody here will want. Same shape for 'ml', where Malayalam was behind Malay and
    // Maltese.
    expect( widget ).toContain( 'function searchLanguages' );
    expect( widget ).toContain( 'if ( code === q ) rank = 0' );
    // The native name is matched too, so a reader typing in their own script finds their own
    // language - the only route in from an Indic keyboard.
    expect( widget ).toMatch( /native\.startsWith\( q \)/ );
    // Five rows is the measured worst case for a two-letter query across the whole
    // catalogue, so the panel has a fixed height. Not a truncation that usually works.
    expect( widget ).toContain( 'const MAX_ROWS = 5' );
  } );

  it( 'labels every row in English, while still matching native script', () => {
    // Changed on instruction from native script for eleven languages plus English for the
    // other sixty, to one uniform English list. Asserted because it is a decision, not a
    // default: the argument for native script is that a reader scans for their own script,
    // and the argument against is a list that reads two ways at once.
    expect( widget ).toContain( '<span className="wc-row-name">{ lang.name }</span>' );
    // The native names are unrendered, NOT deleted: search still matches them, so a reader on
    // an Indic keyboard typing தம finds Tamil. Dropping the data would remove that route in
    // for no visible saving.
    expect( widget ).toContain( 'const NATIVE' );
    expect( widget ).toMatch( /native\.startsWith\( q \)/ );
  } );

  it( 'never re-translates a page nobody asked it to translate', () => {
    /**
     * THE LARGEST COST REDUCTION AVAILABLE ON THE CLIENT, and it is an absence.
     *
     * The chosen language used to be written to localStorage and re-applied on load, so a
     * visitor who once chose Hindi had every subsequent page re-translated in full, silently,
     * with nothing on screen to say it was happening. Translation is billed per character and
     * the DynamoDB cache only helps where the same strings recur, so each new page was paid
     * for again.
     *
     * The page now always arrives in English and translates only on request. The cost of that
     * is real - a Hindi reader must choose Hindi on each page - and it is the right trade
     * while the endpoint is billed per character.
     */
    expect(
      /localStorage/.test( widgetCode ),
      'the widget must not persist the chosen language. Restoring it re-translated every '
      + 'later page load unasked, and translation is billed per character.'
    ).toBe( false );
    // The ref that existed only to let the restore call applyLanguage should be gone with it.
    expect( widgetCode ).not.toContain( 'applyLanguageRef' );
    // And nothing should auto-apply a language during the catalogue fetch.
    expect( widgetCode ).not.toContain( 'savedLang' );
  } );

  it( 'has no hover tint on the chip', () => {
    // Removed on instruction, and correct for a reason worth keeping: the same tint marks the
    // ACTIVE ROW inside the panel, so using it on the trigger meant one colour saying two
    // different things a few pixels apart. The chip now signals only real state.
    expect( widget ).not.toMatch( /\.wc-chip:hover/ );
    // Focus-visible only, so a mouse click does not leave a ring behind.
    expect( widget ).toContain( '.wc-chip:focus-visible' );
  } );

  it( 'neutralises the global input styling inside the panel', () => {
    // MEASURED, NOT GUESSED. tokens.css styles every bare input: a 3px lime box-shadow on
    // focus, min-height 44px, and a border-radius. With the search field focused for the
    // whole time the panel is open, the glow drew a heavy lime rounded box around it - the
    // most visible thing in the panel and not designed - and min-height pushed the panel from
    // ~230px to 302px. Anything NOT named in the reset silently keeps the global value, which
    // is exactly how all three arrived.
    expect( widget ).toMatch( /\.wc-search input\{[^}]*box-shadow:none/ );
    expect( widget ).toMatch( /\.wc-search input\{[^}]*min-height:0/ );
    expect( widget ).toMatch( /\.wc-search input\{[^}]*border-radius:0/ );
    // And the row height is declared rather than inherited from a global button rule, which
    // is how the WhatsApp circle previously ended up a 44x40 oval.
    expect( widget ).toMatch( /\.wc-row\{[^}]*min-height:44px/ );
  } );

  it( 'signals translating with lime motion, not a dark inversion', () => {
    // The chip used to flip to a #1a3a2a fill while working, which put the darkest object
    // on the page into the corner of every translation and read as an error rather than
    // as progress. The busy state is now lime-only and stays on the light surface: a
    // pulsing ring on the chip plus a sweep along the pill's bottom edge.
    expect( widget ).toContain( '@keyframes wc-ring' );
    expect( widget ).toContain( '@keyframes wc-sweep' );
    expect( widget ).toContain( '.wc-chip.is-busy{background:rgba(209,244,112,.38)' );
    // Specifically NOT the dark fill it used to take while busy.
    expect( widget ).not.toContain( "is-busy{background:#1a3a2a" );
    expect( widget ).not.toContain( "[aria-expanded='true']{background:#1a3a2a" );
    // Motion is slowed under reduced motion, never stopped: it is the only indication
    // that batches are still in flight, so freezing it would misreport a live translation
    // as a stalled one.
    expect( widget ).toContain( '@media(prefers-reduced-motion:reduce)' );
  } );

  it( 'has no read-aloud path left', () => {
    // READ-ALOUD IS REMOVED DELIBERATELY. Amazon Polly has no voice for Tamil, Telugu,
    // Bengali, Marathi, Gujarati, Kannada, Malayalam or Punjabi - its entire Indic
    // coverage is Hindi and Indian English - so the button was hidden for almost every
    // language this product serves. /tts responses were also never cached, making it the
    // largest cost line in the feature, and pre-generating audio is impossible for the
    // blog, /orders and /get, which are dynamic.
    // PINNED ON CODE, NOT PROSE, for the same reason as the panel assertions above: the
    // header comment explains why /tts was dropped, so a bare not.toContain('/tts') fired
    // on the explanation. These match the fetch template and the JSX/identifier forms.
    expect( widget ).not.toContain( '${API_BASE}/tts' );
    expect( widget ).not.toContain( '${API_BASE}/voices' );
    expect( widget ).not.toContain( 'listen-btn' );
    expect( widget ).not.toContain( 'audioRef' );
    expect( widget ).not.toContain( 'new Audio(' );
    // `canSpeak` likewise survives only in the header comment recording why speech went,
    // so this pins the property access and the interface field rather than the bare word.
    expect( widget ).not.toContain( 'canSpeak:' );
    expect( widget ).not.toContain( '.canSpeak' );
    expect( widget ).not.toContain( 'setSpeaking' );
  } );

  it( 'mounts on every surface a visitor can land on', () => {
    // THREE MOUNTS, not two. _app.tsx has two route branches - public and authenticated -
    // but three places a human actually sees a page, and the third is easy to miss because
    // it is not a route: AuthGate, the sign-in screen. Every visitor without a session who
    // opens a staff URL lands there, and so does every mistyped path, since anything
    // outside the allowlist falls through to that branch.
    //
    // The gap that was fixed: AuthGate had Header and Footer but no SupportWidget, so the
    // one screen that tells somebody they cannot get in was also the one screen with no way
    // to contact us. Counting to 3 is what keeps it mounted there.
    //
    // Counted on the JSX tag. The comments in _app.tsx deliberately refer to "the
    // SupportWidget component" in prose rather than writing the tag, precisely so this
    // count measures mounts and not explanatory text.
    //
    // COUNTED ACROSS TWO FILES NOW, and the reason matters more than the arithmetic.
    // `AuthGate` moved out of _app.tsx into components/AuthShell.tsx, because it calls
    // `useAuthenticator` and keeping it in _app kept @aws-amplify/ui-react's 450 kB chunk in
    // the shared bundle - i.e. on every public page, for a sign-in card they never render.
    // The invariant this test protects is unchanged: three SURFACES, not three occurrences
    // in one file. Summing the two files keeps it measuring surfaces, where pinning it to
    // _app.tsx alone would have turned a bundle split into a test failure and invited
    // someone to "fix" it by deleting a mount.
    const mounts = ( app.split( '<SupportWidget />' ).length - 1 )
      + ( authShell.split( '<SupportWidget />' ).length - 1 );
    expect(
      mounts,
      'SupportWidget must be mounted in all three places a visitor can land: the public '
      + 'branch and the authenticated branch (_app.tsx), and AuthGate, the sign-in screen '
      + '(components/AuthShell.tsx)'
    ).toBe( 3 );
  } );

  it( 'cannot machine-translate customer data on the dashboard', () => {
    // THE HAZARD THIS PINS. The translator replaces text nodes in place. On the dashboard
    // those nodes are customer names, phone numbers, message bodies and invoice amounts -
    // translating them corrupts what an operator is reading and afterwards cannot be told
    // apart from real data. It is why the widget was previously kept off these screens.
    //
    // Two things make the mount safe, and BOTH have to hold:
    //   1. Layout marks the dashboard content container as no-translate. The walk rejects
    //      a node if any ancestor up to the root carries the attribute, so this exempts
    //      every dashboard page's content in one place.
    //   2. The widget starts its walk at `.layout`, above the sidebar, so navigation still
    //      translates - the half that actually helps an operator.
    const layout = readFileSync( resolve( process.cwd(), 'src/components/Layout.tsx' ), 'utf8' );
    expect(
      layout,
      'Layout.tsx must mark .main-content as no-translate, or the dashboard mount lets an '
      + 'operator machine-translate live customer data'
    ).toContain( 'className="main-content" data-wc-no-translate="true"' );
    expect( widget ).toContain( "document.querySelector( '.layout' )" );
    expect( widget ).toContain( "el.dataset.wcNoTranslate === 'true'" );
  } );

  it( 'survives the translation service being unavailable', () => {
    // THE REGRESSION THIS GUARDS. The component used to `return null` when fewer than two
    // languages loaded. Now that it also owns the WhatsApp button, that early return would
    // have taken customer support down with the translation API - so the catalogue failing
    // must hide the language chip only.
    expect( widget ).toContain( 'const canTranslate = langs.length >= 2' );
    expect( widget ).not.toContain( 'if ( langs.length < 2 ) return null' );
    // And it no longer hides itself on the home page, the most visited route.
    expect( widget ).not.toContain( "window.location.pathname === '/' ) return null" );
  } );
} );
