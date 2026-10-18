import React from 'react';
import type { LegalSection } from '../content/legal/types';

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
 * actually gets opened. Top-level sections only - listing 14.1 through 14.12 as well
 * would make the contents as long as the document.
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
  /** Rendered above the contents, for the "not legal advice" style note. */
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
  const hasSummaries = sections.some( s => s.inShort );

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
   * one row per intro paragraph, the notice, the summaries disclaimer, and one row per
   * section.
   *
   * THE LEADING +1 WAS THE "LAST UPDATED" LINE and went when that line did. Leaving it
   * would have spanned the rail one row further than the flow actually occupies, which is
   * the same off-by-one that produced the 719px hole in the first place - so the gap
   * assertion in legalcheck.js is the thing that proves this count is right, not reading it.
   */
  const columnOneRows =
    intro.length
    + ( notice ? 1 : 0 )
    + ( hasSummaries ? 1 : 0 )
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

      {/* THE COMPONENT OWNS THIS DISCLAIMER, not the page, so it cannot be forgotten on a
          document that has summaries. Rendered only when there are summaries to
          disclaim. A plain-language summary above a binding clause is a real
          improvement, but only if the reader is told which of the two governs - without
          that line the summaries quietly become representations about the contract. */}
      { hasSummaries && (
        <p className="lgd-disclaimer">
          The &ldquo;In short&rdquo; lines are plain-language summaries to help you find
          the part you need. They are not part of the agreement and do not change it. Where
          a summary and the numbered text below it differ, the numbered text is what applies.
        </p>
      ) }

      { /* gridRow is inline because it depends on the document's length, which CSS cannot
           count. Harmless below 1100px, where .lgd is not a grid and the property is
           ignored. */ }
      <nav className="lgd-toc" aria-label="Contents" style={ { gridRow: `1 / span ${columnOneRows}` } }>
        <h2 className="lgd-toc-title">Contents</h2>
        <ol className="lgd-toc-list">
          { topLevel.map( s => (
            <li key={ s.id }>
              <a href={ `#${s.id}` } className="lgd-toc-link">
                <span className="lgd-toc-num">{ s.number }</span>
                <span>{ s.heading }</span>
              </a>
            </li>
          ) ) }
        </ol>
      </nav>

      { sections.map( section => {
        const sub = section.number.includes( '.' );
        return (
          <section key={ section.id } id={ section.id } className={ `lgd-section ${sub ? 'is-sub' : ''}`.trim() }>
            { sub
              ? <h3 className="lgd-h3"><span className="lgd-num">{ section.number }</span>{ section.heading }</h3>
              : <h2 className="lgd-h2"><span className="lgd-num">{ section.number }</span>{ section.heading }</h2> }
            { section.inShort && (
              <p className="lgd-short">
                <span className="lgd-short-tag">In short</span>
                { section.inShort }
              </p>
            ) }
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
           the document, which is where they have to be on a phone. */
        .lgd{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
        /* Single column below the grid breakpoint. */
        @media(max-width:1099px){
          .lgd{max-width:720px}
        }
        @media(min-width:1100px){
          .lgd{
            display:grid;
            grid-template-columns:720px minmax(0,1fr);
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
            max-height:calc(100vh - 160px);
            overflow-y:auto;
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
          background:var(--public-lime-tint);border-left:4px solid var(--public-brand-lime);border-radius:8px;
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-muted);
        }

        /* Deliberately quiet - it sits directly under the lime notice and must not
           compete with it for the same glance. Muted body colour at the intro size. */
        .lgd-disclaimer{margin:0 0 36px;font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-muted)}

        /* SUMMARIES USE NEUTRALS ONLY. Lime is already spoken for on this page: the
           notice block owns it, and it means "read this before the clauses". Repeating
           that treatment 45 times would spend the accent on every section and leave the
           notice indistinguishable from ordinary body copy.
           A 2px hairline rule plus muted text is enough separation because the summary
           is doing the opposite job to the notice - it wants to be skimmed past once the
           reader has found their section, not fixated on. Every value here is already
           in the palette. */
        .lgd-short{margin:0 0 14px;padding:0 0 0 14px;border-left:2px solid var(--public-hairline);font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-muted)}
        /* display:block puts the tag on its own line so the summary text stays a clean
           rectangle - inline, the first line was indented by the tag width and the
           result read as a hanging indent rather than a label. */
        /* rgba(0,0,0,.54), not .42. All three of these carry real content - a clause number
           and a section tag - and .42 composites to rgb(148,148,148) over white, measuring
           3.04:1 where 4.5:1 is required for normal text. .54 measures 4.59:1 and is the
           value the design contract already names as the palette's muted level, so this is
           a correction onto an existing token rather than a new one. Lighthouse's axe pass
           flagged four instances on /terms/; the focus-ring sweep never looked at these
           because they are neither indicators nor named labels. */
        .lgd-short-tag{display:block;margin-bottom:3px;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--public-muted)}

        .lgd-toc{margin:0 0 48px;padding:22px 24px;border:1px solid var(--public-hairline);border-radius:14px}
        .lgd-toc-title{margin:0 0 14px;font-size:14px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--public-muted)}
        /* ONE column is the base, and two columns are opted into only for the inline
           layout between 768 and 1099px, where the contents sit above the document at
           full width and 45 entries in a single column would be a very long scroll.
           Declared this way round on purpose: the base rule used to be columns:2 with a
           columns:1 override inside the min-width:1100px block, and because that block
           appears EARLIER in this stylesheet the later base rule won and the rail
           rendered two ~19-character columns. Media queries beating base rules depends
           on source order, which the design contract already records as a trap - so the
           narrower case is the exception here, not the default.
           list-style is off because the number is rendered explicitly: the document's
           own numbering is authoritative and must not be renumbered by the browser if a
           section is ever added or removed. */
        .lgd-toc-list{margin:0;padding:0;list-style:none;columns:1;column-gap:32px}
        @media(min-width:768px) and (max-width:1099px){
          .lgd-toc-list{columns:2}
        }
        .lgd-toc-list li{break-inside:avoid;margin:0 0 2px}
        .lgd-toc-link{display:flex;gap:10px;padding:6px 8px;margin:0 -8px;border-radius:7px;font-size:15px;line-height:1.45;color:var(--public-brand-green);text-decoration:none}
        /* HOVER AND FOCUS ARE SPLIT, because one rule cannot serve both here.
           This was a single declaration: hover and focus-visible shared the lime tint AND
           outline:none. So a keyboard user's only focus indicator was that tint, which
           composites to rgb(245,253,224) over white - the design contract's own words for
           this value are "a wash that reads as barely-not-white". Measured across the two
           legal pages: 71 contents links (47 on /terms/, 24 on /privacy/) with NO detectable
           focus indicator, because outline:none had removed the browser default too.
           The tint stays on hover, where it is a pointer affordance and does not need to
           carry 3:1. Focus gets an opaque #1a3a2a ring at 12.48:1 on white. Keeping the tint
           on focus as well is deliberate - the two states then look related rather than
           unrelated - but the ring is what makes focus perceivable.
           Do not re-merge these selectors. */
        .lgd-toc-link:hover{background:var(--public-lime-tint)}
        .lgd-toc-link:focus-visible{background:var(--public-lime-tint);outline:3px solid var(--public-brand-green);outline-offset:1px}
        .lgd-toc-num{flex:0 0 auto;min-width:22px;font-weight:600;color:var(--public-muted)}

        /* scroll-margin-top clears the fixed 108px header. Without it, following a
           contents link puts the heading underneath the header and the reader lands
           mid-paragraph with no idea which section they are in. */
        .lgd-section{margin:0 0 34px;scroll-margin-top:128px}
        .lgd-section.is-sub{margin-left:0}

        /* Legal sections use the same public hierarchy as the rest of the site: section H2,
           then card/subsection H3. Density is handled by the reading measure and spacing, not
           by inventing a second type ladder for these two routes. */
        .lgd-h2{margin:0 0 12px;font-size:var(--public-section-size);font-weight:var(--public-section-weight);line-height:var(--public-section-leading);letter-spacing:var(--public-section-tracking);color:var(--public-heading)}
        .lgd-h3{margin:0 0 10px;font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);color:var(--public-heading)}
        /* The clause number sits in the left margin on a wide screen so headings align
           on their text rather than stepping right as numbers get wider. */
        .lgd-num{display:inline-block;min-width:44px;color:var(--public-muted);font-weight:600}

        .lgd-p{margin:0 0 12px;font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-body)}
        .lgd-p:last-child{margin-bottom:0}

        .lgd-inline-link{color:var(--public-brand-green);font-weight:600;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
        .lgd-inline-link:hover{background:var(--public-lime-tint)}

        @media(max-width:767px){
          /* One column: two columns of contents on a phone gives ~20 characters a line. */
          .lgd-toc-list{columns:1}
          .lgd-toc{padding:18px 16px;margin-bottom:36px}
          .lgd-section{scroll-margin-top:112px}
          /* Keep the shared type ladder intact on narrow screens; only geometry changes. */
          .lgd-short{padding-left:12px}
          /* Numbers move inline: a 44px gutter on a 320px screen costs 14% of the width. */
          .lgd-num{min-width:0;margin-right:8px}
        }
      `}</style>
    </div>
  );
};

export default LegalDocument;
