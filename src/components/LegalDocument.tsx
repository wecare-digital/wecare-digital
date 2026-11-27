import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { LegalSection } from '../content/legal/types';
import { normalizeNavigationText, rankNavigation, contentSearchText } from '../lib/navigationSearch';
import VoiceSearchMic from './VoiceSearchMic';
import SearchClearButton from './SearchClearButton';
import { CONTENTS_ICON, CONTENTS_ICON_VIEW_BOX, ROW_CHEVRON_PATH, ROW_CHEVRON_VIEW_BOX, SUBNAV_ICON_PATH, SUBNAV_DOT_PATH, SUBNAV_ICON_VIEW_BOX } from '../lib/publicNavigationIcons';

/**
 * Renders a long legal document on the site's own type system.
 *
 * SELF-STYLING, like BrandBadge, RotatingHero and WorkflowTerminal: styled-jsx cannot
 * scope a composite component from its parent, so this owns every rule it needs.
 *
 * Classes are lgd- prefixed. The globally imported src/styles/*.css declares unscoped
 * rules for generic names and styled-jsx does not shield a page from them.
 *
 * The TABLE OF CONTENTS is not decoration. Terms is 57 sections and Privacy is 39; a
 * flat wall of numbered prose is unusable on a phone, which is where a privacy policy
 * actually gets opened. Native disclosure groups make nested sections reachable
 * without flattening every sub-clause into a long menu. The operative text stays visible.
 *
 * TYPE COMES OFF THE DESIGN CONTRACT, with one deliberate exception. The contract pins
 * exactly one body level at 20px/400 for marketing pages. That is too large for 42,000
 * characters of clauses: at 20px this document runs to a scroll depth nobody reaches.
 * Body here is 17px on a 68-character measure, which is inside the 45-75 the rest of
 * the site holds to. Headings still use the contract's rungs, so the page reads as part
 * of the same family. This is the one place a smaller body level is justified and it is
 * confined to this component.
 */

interface LegalDocumentProps {
  sections: LegalSection[];
  intro: string[];
  /** Optional customer-facing guidance above the contents. */
  notice?: React.ReactNode;
}

/** Turns bare /terms/ and /privacy/ references in the text into real links. */
const withLinks = ( text: string, keyBase: string ): React.ReactNode => {
  const parts = text.split( /(\/terms\/|\/privacy\/)/g );
  if ( parts.length === 1 ) return text;
  return parts.map( ( part, i ) => (
    part === '/terms/' || part === '/privacy/'
      ? <a key={ `${keyBase}-${i}` } className="lgd-inline-link" href={ part }>{ part === '/terms/' ? 'Terms of Service' : 'Privacy Policy' }</a>
      : <React.Fragment key={ `${keyBase}-${i}` }>{ part }</React.Fragment>
  ) );
};



const LegalDocument: React.FC<LegalDocumentProps> = ( { sections, intro, notice } ) => {
  const topLevel = sections.filter( s => !s.number.includes( '.' ) );
  const tocRef = useRef<HTMLDetailsElement>( null );
  const navRef = useRef<HTMLElement>( null );
  const searchId = useId();
  const [ activeId, setActiveId ] = useState( '' );
  const [ sectionQuery, setSectionQuery ] = useState( '' );
  const [ showContentsShortcut, setShowContentsShortcut ] = useState( false );
  const applySectionQuery = ( value: string ) => {
    if ( tocRef.current ) tocRef.current.open = true;
    setSectionQuery( value.slice( 0, 120 ) );
  };
  const searchTerm = normalizeNavigationText( sectionQuery );
  const sectionIndex = useMemo( () => sections.map( section => ( {
    section, label: section.heading,
    searchText: contentSearchText( [ section.number, section.heading, ...section.paragraphs ] ),
  } ) ), [ sections ] );
  const matches = useMemo( () => {
    if ( !searchTerm ) return [];
    // Clause numbers and fragment IDs are exact identifiers, not fuzzy words.
    const raw = sectionQuery.trim();
    const exactNumber = raw.match( /^(?:(?:section|clause)\s+)?(\d+(?:\.\d+)*)\.?$/i )?.[1];
    if ( exactNumber ) return sectionIndex.filter( item => item.section.number === exactNumber || item.section.number.startsWith( exactNumber + '.' ) ).map( item => item.section );
    const exactId = sectionIndex.find( item => item.section.id === raw.replace( /^#/, '' ) );
    if ( exactId ) return [ exactId.section ];
    return rankNavigation( sectionIndex, sectionQuery ).map( item => item.section );
  }, [ searchTerm, sectionQuery, sectionIndex ] );
  const activeGroup = sections.find( section => section.id === activeId )?.number.split( '.' )[0];
  const lastScrollGroup = useRef( '' );

  // Establish the default only on mount or at a breakpoint crossing; parent
  // rerenders and fragment changes must not undo the reader's disclosure choice.
  useEffect( () => {
    const wide = window.matchMedia( '(min-width: 1100px)' );
    const syncLayout = () => {
      if ( tocRef.current ) tocRef.current.open = wide.matches;
    };
    syncLayout();
    wide.addEventListener( 'change', syncLayout );
    return () => wide.removeEventListener( 'change', syncLayout );
  }, [] );

  // Reveal the relevant subsection group without reopening a closed mobile panel.
  useEffect( () => {
    const revealDeepLink = () => {
      const id = window.location.hash.slice( 1 );
      const section = sections.find( item => item.id === id );
      setActiveId( section?.id ?? '' );
      if ( !section ) return;
      const parentNumber = section.number.split( '.' )[ 0 ];
      const parent = sections.find( item => item.number === parentNumber );
      if ( !parent ) return;
      const group = document.getElementById( `lgd-toc-group-${parent.id}` );
      if ( group instanceof HTMLDetailsElement ) group.open = true;
    };
    revealDeepLink();
    window.addEventListener( 'hashchange', revealDeepLink );
    return () => window.removeEventListener( 'hashchange', revealDeepLink );
  }, [ sections ] );

  // Track the visible reading line; never change the URL or scroll the article.
  useEffect( () => {
    let frame = 0;
    lastScrollGroup.current = '';
    const update = () => {
      frame = 0;
      const readingLine = 150;
      let current: LegalSection | undefined;
      for ( const section of sections ) {
        const element = document.getElementById( section.id );
        if ( element && element.getBoundingClientRect().top <= readingLine ) current = section;
        else if ( element ) break;
      }
      const last = sections[ sections.length - 1 ];
      const articleEnd = last ? document.getElementById( last.id )?.getBoundingClientRect().bottom : undefined;
      setShowContentsShortcut( !!navRef.current && navRef.current.getBoundingClientRect().bottom < 128 && ( articleEnd ?? 0 ) > readingLine );
      if ( !current ) { setActiveId( '' ); return; }
      setActiveId( current.id );
      const groupNumber = current.number.split( '.' )[0];
      if ( groupNumber !== lastScrollGroup.current ) {
        lastScrollGroup.current = groupNumber;
        const parent = sections.find( section => section.number === groupNumber );
        const group = parent && document.getElementById( `lgd-toc-group-${parent.id}` );
        if ( group instanceof HTMLDetailsElement && ( window.matchMedia( '(min-width: 1100px)' ).matches || !tocRef.current?.open ) ) group.open = true;
      }
    };
    const schedule = () => { if ( !frame ) frame = window.requestAnimationFrame( update ); };
    window.addEventListener( 'scroll', schedule, { passive: true } );
    window.addEventListener( 'resize', schedule );
    schedule();
    return () => {
      window.cancelAnimationFrame( frame );
      window.removeEventListener( 'scroll', schedule );
      window.removeEventListener( 'resize', schedule );
    };
  }, [ sections, searchTerm ] );

  const selectSection = ( event: React.MouseEvent<HTMLAnchorElement>, id: string ) => {
    // Keep native fragment history and modifier-click semantics.
    if ( event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ) return;
    setActiveId( id );
    if ( !window.matchMedia( '(min-width: 1100px)' ).matches && tocRef.current ) {
      // Close before native fragment scrolling, so the target is not shifted up
      // afterwards by the collapse of a long list above it.
      tocRef.current.open = false;
    }
  };

  /**
   * HOW MANY ROWS THE CONTENTS RAIL HAS TO SPAN, counted from the children that actually
   * land in column 1.
   *
   * The rail used to declare grid-row:1/-1 in CSS, which looks right and is not. Line -1
   * resolves against the EXPLICIT row grid, and .lgd only ever declares
   * grid-template-columns - so the explicit row grid has a single line, -1 resolves back
   * to line 1, and "1 / -1" collapses to a one-row span. The rail then sat in row 1 and
   * its 740px height inflated that row, leaving "Last updated" alone at the top of it and
   * a measured 719px hole above the first paragraph. Every assertion still passed, because
   * the suite checked the reading column width and the deep-link offset but never the
   * vertical distance between two children.
   *
   * Counted rather than given a large magic span so it stays exact if the document grows:
   * one row per intro paragraph, the optional notice, and one row per section.
   *
   * THE LEADING +1 WAS THE "LAST UPDATED" LINE and went when that line did. Leaving it
   * would have spanned the rail one row further than the flow actually occupies, which is
   * the same off-by-one that produced the 719px hole in the first place - so the gap
   * assertion in legalcheck.js is the thing that proves this count is right, not reading it.
   */
  const columnOneRows =
    intro.length
    + ( notice ? 1 : 0 )
    + sections.length;

  return (
    <div className="lgd">
      { /* NO "LAST UPDATED" LINE, on instruction. The revision dates still exist as
           TERMS_UPDATED and PRIVACY_UPDATED in src/content/legal/ for engineering
           reference; they are simply not rendered, and the prop that carried them here
           was removed rather than left accepting a value nobody displays.
           Worth knowing what this costs, once: an effective date is the normal way a
           reader, an app store reviewer or a regulator establishes WHICH version of a
           contract they are looking at, and without one a later dispute has nothing to
           anchor to. The owner's call, and reversible in one line. */ }
      { intro.map( ( paragraph, i ) => (
        <p key={ `intro-${i}` } className="lgd-intro">{ withLinks( paragraph, `intro-${i}` ) }</p>
      ) ) }

      { notice && <div className="lgd-notice">{ notice }</div> }

      { /* gridRow is inline because it depends on the document's length, which CSS cannot
           count. Harmless below 1100px, where .lgd is not a grid and the property is
           ignored. */ }
      <nav ref={ navRef } className="lgd-toc" aria-label="Legal sections" style={ { gridRow: `1 / span ${columnOneRows}` } }>
        {/* Search is a sibling of the native disclosure, never nested inside its
            interactive summary. It remains available while the clause list is closed. */}
        <div className="lgd-toc-search">
          <label className="lgd-search-icon" htmlFor={ searchId }>
            <svg className="lgd-contents-icon" viewBox={ CONTENTS_ICON_VIEW_BOX } aria-hidden="true" focusable="false"><path d={ CONTENTS_ICON } /></svg>
          </label>
          <div className="lgd-search-field" data-public-search-field="compact">
            <input id={ searchId } type="search" value={ sectionQuery } maxLength={ 120 } placeholder="Search" aria-label="Find a legal clause"
              onFocus={ () => { if ( tocRef.current ) tocRef.current.open = true; } }
              onChange={ event => applySectionQuery( event.target.value ) }
              onKeyDown={ event => { if ( event.nativeEvent.isComposing ) return; if ( event.key === 'Escape' && sectionQuery ) { event.preventDefault(); applySectionQuery( '' ); } } } />
            <SearchClearButton query={ sectionQuery } onClear={ () => applySectionQuery( '' ) } />
            <VoiceSearchMic onTranscript={ applySectionQuery } />
          </div>
        </div>
        <details className="lgd-contents" ref={ tocRef } open>
          <summary className="lgd-toc-summary" aria-label="Toggle legal section list" title="Toggle legal section list">
            <svg className="lgd-contents-chevron" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true" focusable="false"><path d={ ROW_CHEVRON_PATH } /></svg>
          </summary>
          { searchTerm && <p className="lgd-toc-status" role="status">{ matches.length } { matches.length === 1 ? 'clause' : 'clauses' } found</p> }
          { searchTerm ? <ol className="lgd-toc-list" aria-label="Matching clauses">
            { matches.map( section => <li key={ section.id }><a className="lgd-toc-link" href={ `#${section.id}` } aria-current={ activeId === section.id ? 'location' : undefined } onClick={ event => selectSection( event, section.id ) }>
              { section.number.includes( '.' ) ? <>
                <svg className="lgd-sub-icon" viewBox={ SUBNAV_ICON_VIEW_BOX } aria-hidden="true" focusable="false"><path d={ SUBNAV_ICON_PATH } /><path className="lgd-sub-dots" d={ SUBNAV_DOT_PATH } /></svg>
                <span className="lgd-toc-label"><span className="lgd-toc-num">{ section.number }</span>{ ' ' }{ section.heading }</span>
              </> : <>
                <span className="lgd-toc-num">{ section.number }</span><span className="lgd-toc-label">{ section.heading }</span>
              </> }
            </a></li> ) }
            { !matches.length && <li className="lgd-toc-empty">No matching clauses. Try a related word, such as payment or privacy, or a clause number.</li> }
          </ol> : <ol className="lgd-toc-list">
            { topLevel.map( section => {
              const children = sections.filter( child => child.number.startsWith( `${section.number}.` ) );
              return (
                <li key={ section.id }>
                  { children.length ? (
                    <details id={ `lgd-toc-group-${section.id}` } className="lgd-toc-group">
                      <summary className={ `lgd-toc-group-summary ${activeGroup === section.number ? 'is-current' : ''}`.trim() }>
                        <span className="lgd-toc-num">{ section.number }</span>
                        <span className="lgd-toc-label">{ section.heading }</span>
                        <svg className="lgd-group-chevron" viewBox={ ROW_CHEVRON_VIEW_BOX } aria-hidden="true" focusable="false"><path d={ ROW_CHEVRON_PATH } /></svg>
                      </summary>
                      <ol className="lgd-toc-children" aria-label={ `Section ${section.number} subsections` }>
                        <li><a href={ `#${section.id}` } className="lgd-toc-link lgd-child-link" aria-current={ activeId === section.id ? 'location' : undefined } onClick={ event => selectSection( event, section.id ) }>
                          <svg className="lgd-sub-icon" viewBox={ SUBNAV_ICON_VIEW_BOX } aria-hidden="true" focusable="false"><path d={ SUBNAV_ICON_PATH } /><path className="lgd-sub-dots" d={ SUBNAV_DOT_PATH } /></svg>
                          <span className="lgd-toc-label">Section { section.number } overview</span>
                        </a></li>
                        { children.map( child => (
                          <li key={ child.id }>
                            <a href={ `#${child.id}` } className="lgd-toc-link lgd-child-link" aria-current={ activeId === child.id ? 'location' : undefined } onClick={ event => selectSection( event, child.id ) }>
                              <svg className="lgd-sub-icon" viewBox={ SUBNAV_ICON_VIEW_BOX } aria-hidden="true" focusable="false"><path d={ SUBNAV_ICON_PATH } /><path className="lgd-sub-dots" d={ SUBNAV_DOT_PATH } /></svg>
                              <span className="lgd-toc-label"><span className="lgd-toc-num">{ child.number }</span>{ ' ' }{ child.heading }</span>
                            </a>
                          </li>
                        ) ) }
                      </ol>
                    </details>
                  ) : (
                    <a href={ `#${section.id}` } className="lgd-toc-link" aria-current={ activeId === section.id ? 'location' : undefined } onClick={ event => selectSection( event, section.id ) }>
                      <span className="lgd-toc-num">{ section.number }</span>
                      <span className="lgd-toc-label">{ section.heading }</span>
                    </a>
                  ) }
                </li>
              );
            } ) }
          </ol> }
        </details>
      </nav>

      { showContentsShortcut && <button type="button" className="lgd-return-to-contents" aria-label="Open legal section search" title="Open legal section search" onClick={ () => {
        if ( tocRef.current ) {
          tocRef.current.open = true;
          const parent = sections.find( section => section.number === activeGroup );
          const group = parent && document.getElementById( `lgd-toc-group-${parent.id}` );
          if ( group instanceof HTMLDetailsElement ) group.open = true;
          tocRef.current.querySelector<HTMLElement>( 'summary' )?.focus( { preventScroll: true } );
          navRef.current?.scrollIntoView( { block: 'start', behavior: 'auto' } );
        }
      } }>
        <svg viewBox={ CONTENTS_ICON_VIEW_BOX } aria-hidden="true" focusable="false"><path d={ CONTENTS_ICON } /></svg>
      </button> }

      { sections.map( section => {
        const sub = section.number.includes( '.' );
        return (
          <section key={ section.id } id={ section.id } className={ `lgd-section ${sub ? 'is-sub' : ''}`.trim() }>
            { sub
              ? <h3 className="lgd-h3"><span className="lgd-num">{ section.number }</span>{ ' ' }<span className="lgd-heading-text">{ section.heading }</span></h3>
              : <h2 className="lgd-h2"><span className="lgd-num">{ section.number }</span>{ ' ' }<span className="lgd-heading-text">{ section.heading }</span></h2> }
            { section.paragraphs.map( ( paragraph, i ) => (
              <p key={ `${section.id}-${i}` } className="lgd-p">{ withLinks( paragraph, `${section.id}-${i}` ) }</p>
            ) ) }
          </section>
        );
      } ) }

      <style jsx>{`
        /* TWO COLUMNS ON A WIDE SCREEN: a 720px reading column and a sticky contents
           rail beside it.
           The reading column is 720px because at 17px that is ~68 characters a line,
           inside the 45-75 the rest of the site holds to - the full 1300px measure
           would run to ~150 characters and be unreadable for this much prose. But
           capping it there left 556px of dead white space to the right of a
           45-section document, which looked broken and wasted the one thing a long
           legal document actually needs: navigation that stays put.
           The rail goes on the RIGHT, not the conventional left, so the reading column
           stays aligned with the hero headline directly above it. Moving it left would
           indent the prose away from the h1 and break that vertical line.
           Below 1100px it collapses to one column and the contents return inline above
           the document as a compact native disclosure on phones and tablets. */
        .lgd{font-family:var(--font-sans)}
        /* Single column below the grid breakpoint. */
        @media(max-width:1099px){
          .lgd{max-width:720px}
        }
        @media(min-width:1100px){
          .lgd{
            display:grid;
            grid-template-columns:minmax(0,720px) minmax(260px,1fr);
            column-gap:56px;
            align-items:start;
          }
          /* EVERY child goes in column 1, and the rail is pulled into column 2 spanning
             all rows. The first attempt used grid-template-areas with grid-column on
             individual children, which left the areas and the auto-placement disagreeing
             - children landed in fresh rows sized by the rail, opening a measured 417px
             hole between "Last updated" and the first paragraph. Placing the flow
             explicitly and letting the rail span 1/-1 removes the ambiguity. */
          .lgd > *{grid-column:1}
          /* Child combinator on BOTH rules, deliberately. styled-jsx appends its scoping
             class to every compound in a selector, so the column-1 rule above compiles to
             two classes plus a universal and outranks a bare single-class .lgd-toc - the
             rail stayed in column one and the 556px of dead space came straight back.
             Matching the shape of the rule it has to beat is what fixes it. */
          /* Sticky at 128px, the same offset the sections use for scroll-margin, so the
             rail sits level with whatever heading a contents link just jumped to.
             The row span comes from an inline style, not from here - see columnOneRows in
             the component. It has to cover every row so the rail's grid area is the full
             document height, which is what gives sticky something to travel inside.
             max-height keeps 45 entries reachable on a short laptop screen rather than
             running off the bottom unscrollable. */
          .lgd > .lgd-toc{
            grid-column:2;
            position:sticky;top:128px;
            margin:0;
            /* Only the clause list scrolls. Search and its toggle stay visible. */
          }
          .lgd-toc-list{
            max-height:max(80px,calc(100vh - 270px));
            max-height:max(80px,calc(100dvh - 270px));
            overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;
          }
        }

        .lgd-intro{margin:0 0 16px;font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-body)}

        /* The one lime surface on the page. A legal document should not be decorated,
           but the "this is not advice" note has to be found before the clauses are
           read, so it takes the .22 transient tint and a solid lime edge - the same
           pairing the sign-in card uses - rather than a warning colour this site does
           not have. */
        .lgd-notice{
          margin:28px 0 36px;padding:16px 18px;
          background:var(--public-lime-tint);border-inline-start:4px solid var(--public-brand-lime);border-radius:8px;
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-muted);
        }

        /* One search-led toolbar: view_list at the start, the same underline-only
           search treatment as Header, and a native double_arrow disclosure at the end.
           The search field is never hidden or trapped inside an interactive summary. */
        .lgd-toc{
          --lgd-toc-pad-block:12px;--lgd-toc-pad-inline:16px;
          position:relative;margin:0 0 48px;padding:var(--lgd-toc-pad-block) var(--lgd-toc-pad-inline);
          border:1px solid var(--public-hairline);border-radius:14px;min-width:0;scroll-margin-top:128px;
        }
        .lgd-contents{min-width:0}
        .lgd-toc-search{
          display:flex;align-items:center;gap:8px;min-height:var(--tap-min);
          padding-inline-end:calc(var(--tap-min) + 8px);margin:0;
        }
        .lgd-search-icon{display:flex;align-items:center;justify-content:center;flex:0 0 var(--tap-min);min-height:var(--tap-min);color:var(--public-brand-green);cursor:text}
        .lgd-search-field{position:relative;flex:1;min-width:0}
        @media(max-width:279px){.lgd-toc-search{padding-inline-end:0;gap:4px;flex-wrap:wrap}.lgd-search-field{flex:1 1 96px}}
        .lgd-toc-search input{
          display:block;min-width:0;width:100%;margin:0;min-height:max(var(--tap-min),var(--public-search-compact-height));box-sizing:border-box;
          appearance:none;-webkit-appearance:none;
          border:0;border-bottom:2px solid var(--public-search-underline);border-radius:0;background:transparent;
          padding:0 2px;padding-inline-end:46px;padding-inline-end:var(--public-search-end-padding,46px);font-size:16px;font-weight:400;line-height:1.3;color:var(--public-body);
          font-family:inherit;outline:none;transition:border-color .2s,box-shadow .2s;
        }
        .lgd-toc-search input::-webkit-search-cancel-button,.lgd-toc-search input::-webkit-search-decoration{display:none;-webkit-appearance:none}
        .lgd-toc-search input::-ms-clear{display:none}
        .lgd-toc-search input:not(:placeholder-shown){padding-inline-end:90px;padding-inline-end:var(--public-search-end-padding,90px)}
        .lgd-toc-search input::placeholder{color:var(--public-muted)}
        .lgd-toc-search input:focus-visible{border-bottom-color:var(--public-search-underline);box-shadow:var(--public-search-focus-shadow)}
        .lgd-toc-status,.lgd-toc-empty{font-size:var(--public-meta-size);color:var(--public-muted);margin:10px 0}
        .lgd-return-to-contents{display:none}
        @media(max-width:1099px){
          .lgd-return-to-contents{
            display:flex;align-items:center;justify-content:center;position:fixed;
            inset-inline-start:max(12px,var(--safe-left));bottom:calc(16px + var(--safe-bottom));z-index:20;
            min-width:var(--tap-min);min-height:var(--tap-min);padding:8px;
            border:1px solid var(--public-hairline);border-radius:var(--public-nav-radius);
            box-shadow:var(--public-lift-shadow);background:var(--public-bg);color:var(--public-brand-green);cursor:pointer;
          }
          .lgd-return-to-contents svg{width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);fill:currentColor}
        }
        .lgd-toc-summary,.lgd-toc-group-summary{
          display:flex;align-items:center;gap:10px;min-height:var(--tap-min);box-sizing:border-box;
          cursor:pointer;list-style:none;color:var(--public-brand-green);border-radius:var(--public-nav-radius);
        }
        .lgd-toc-summary::-webkit-details-marker,.lgd-toc-group-summary::-webkit-details-marker{display:none}
        .lgd-toc-summary::marker,.lgd-toc-group-summary::marker{content:''}
        .lgd-toc-summary{
          position:absolute;inset-block-start:var(--lgd-toc-pad-block);inset-inline-end:var(--lgd-toc-pad-inline);
          width:var(--tap-min);height:var(--tap-min);justify-content:center;padding:0;
        }
        .lgd-toc-label{flex:1;min-width:0;overflow-wrap:anywhere}
        .lgd-contents-icon,.lgd-contents-chevron,.lgd-group-chevron{
          display:block;width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);flex:0 0 var(--public-nav-icon-size);fill:currentColor;
        }
        .lgd-contents-chevron,.lgd-group-chevron{color:var(--public-nav-arrow);transition:transform .18s ease}
        .lgd-sub-icon{display:block;width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);flex:0 0 var(--public-nav-icon-size);margin-top:2px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;color:var(--public-nav-arrow)}
        .lgd-sub-icon path{vector-effect:non-scaling-stroke}
        .lgd-sub-icon .lgd-sub-dots{fill:currentColor;stroke:none}
        :global([dir='rtl']) .lgd-sub-icon{transform:scaleX(-1)}
        .lgd-contents[open]>.lgd-toc-summary .lgd-contents-chevron,
        .lgd-toc-group[open]>.lgd-toc-group-summary .lgd-group-chevron{transform:rotate(90deg)}
        :global([dir='rtl']) .lgd-contents:not([open])>.lgd-toc-summary .lgd-contents-chevron,
        :global([dir='rtl']) .lgd-toc-group:not([open])>.lgd-toc-group-summary .lgd-group-chevron{transform:scaleX(-1)}
        .lgd-toc-list,.lgd-toc-children{margin:0;padding:0;list-style:none}
        .lgd-toc-list{margin-top:8px;padding-top:4px}
        .lgd-toc-list li{margin:0 0 2px;min-width:0}
        /* Match the document's actual Inter body type, including mobile. Clause
           numbers remain muted; the blue from both legal heroes marks reading
           position, while the established lime tint is reserved for hover/focus. */
        .lgd-toc-link,.lgd-toc-group-summary{
          display:flex;align-items:flex-start;gap:8px;min-height:max(44px,var(--tap-min));
          box-sizing:border-box;padding:8px;border-radius:var(--public-nav-radius);
          font-family:inherit;font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-body);text-decoration:none;
        }
        .lgd-toc-group-summary{font-weight:600}
        .lgd-toc-group-summary.is-current{background:var(--public-accent-blue-tint)}
        .lgd-toc-link[aria-current="location"]{
          background:var(--public-accent-blue-tint);font-weight:600;
          border-inline-start:3px solid var(--public-accent-blue);padding-inline-start:5px;
        }
        .lgd-toc-children{margin:2px 0 8px 12px;padding-inline-start:8px;border-inline-start:2px solid var(--public-hairline)}
        .lgd-child-link{padding-block:8px}
        .lgd-toc-link:not([aria-current="location"]):hover,.lgd-toc-summary:hover,.lgd-toc-group-summary:not(.is-current):hover{background:var(--public-nav-hover)}
        .lgd-toc-link:focus-visible,.lgd-toc-summary:focus-visible,.lgd-toc-group-summary:focus-visible,.lgd-return-to-contents:focus-visible{
          outline:var(--public-focus-ring) solid var(--public-brand-green);outline-offset:-2px;
        }
        .lgd-toc-num{flex:0 0 auto;min-width:22px;font-weight:600;color:var(--public-muted)}
        @media(prefers-reduced-motion:reduce){
          .lgd-contents-chevron,.lgd-group-chevron,.lgd-toc-search input{transition:none}
        }

        /* scroll-margin-top clears the fixed 108px header. Without it, following a
           contents link puts the heading underneath the header and the reader lands
           mid-paragraph with no idea which section they are in. */
        .lgd-section{margin:0 0 34px;scroll-margin-top:128px}
        .lgd-section.is-sub{margin-inline-start:0}

        /* Legal sections use the same public hierarchy as the rest of the site: section H2,
           then card/subsection H3. Density is handled by the reading measure and spacing, not
           by inventing a second type ladder for these two routes. */
        /* A word longer than the column breaks instead of pushing the page sideways at 280px. */
        .lgd-h2{margin:0 0 12px;font-size:var(--public-section-size);font-weight:var(--public-section-weight);line-height:var(--public-section-leading);letter-spacing:var(--public-section-tracking);color:var(--public-heading);overflow-wrap:anywhere}
        .lgd-h3{margin:0 0 10px;font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-heading)}
        /* Separate the number and title into aligned columns; a real gap remains
           even for longer clause numbers, and wrapped titles keep their alignment. */
        .lgd-h2,.lgd-h3{
          display:grid;grid-template-columns:3.5rem minmax(0,1fr);
          column-gap:12px;align-items:baseline;text-align:start;font-style:normal;
          transform:none;
        }
        .lgd-num{
          display:block;white-space:nowrap;letter-spacing:normal;font-variant-numeric:tabular-nums;
          color:var(--public-muted);font-weight:600;font-style:normal;
        }
        .lgd-heading-text{min-width:0;overflow-wrap:anywhere;font-style:normal}

        .lgd-p{margin:0 0 12px;font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-body)}
        .lgd-p:last-child{margin-bottom:0}

        .lgd-inline-link{color:var(--public-brand-green);font-weight:600;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
        .lgd-inline-link:hover{background:var(--public-lime-tint)}

        @media(max-width:767px){
          .lgd-toc{--lgd-toc-pad-block:8px;--lgd-toc-pad-inline:10px;margin-bottom:36px}
          .lgd-toc-children{margin-inline-start:10px;padding-inline-start:6px}
          .lgd-section{scroll-margin-top:112px}
          .lgd-h2{font-size:var(--public-mobile-section-size)}
          .lgd-h3{font-size:var(--public-mobile-card-size)}
          .lgd-h2,.lgd-h3{grid-template-columns:3rem minmax(0,1fr);column-gap:8px}
        }
      `}</style>
    </div>
  );
};

export default LegalDocument;
