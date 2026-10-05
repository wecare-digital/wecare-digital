import React, { useEffect, useState } from 'react';
import { findDialCode, nationalLengthHint } from '../lib/dialCodes';

/**
 * ONE FIELD, DIVIDED: a country-code segment and a number segment inside a single rounded outline.
 *
 * WHAT THE OWNER ASKED FOR, AND THE HISTORY BEHIND IT. This control has been through both extremes.
 * It started as a separate <select> sitting BESIDE a national-number input - two boxes, visibly two
 * fields. The owner then asked for "phone numbr and whatsapp ountrycode hsod in one feid", so it
 * became a single <input> where the shopper typed "+91 9876543210" and the page parsed it. The
 * instruction now is "countcode + number should bin same dived divide and rounded corner": one
 * field, but divided, with rounded corners. That is the international-phone pattern - a single
 * outlined container, split by a hairline, holding two controls.
 *
 * It resolves the tension in the middle version rather than reverting it. Typing your own country
 * code is work, and getting it wrong was punished with an error message; a segment that always
 * carries a code removes both. The guarantee that mattered survives untouched: the country code is
 * SHOWN rather than inferred (see DEFAULT_DIAL_CODE), so nobody is quietly signed in as Indian.
 *
 * MATERIAL 3, AND WHERE THIS DEPARTS FROM IT. Anatomy follows the M3 outlined text field: an
 * outlined container, a label above, supporting text below, and a leading section inside the
 * container. Two deliberate departures, both named so neither looks like an oversight:
 *
 *   1. CORNER RADIUS. The M3 default is `--md-sys-shape-corner-extra-small` = 4px. This uses 10px,
 *      which is the radius every other field on this site already has. Site consistency wins over
 *      importing a framework default into a page that is not otherwise M3, and 10px is the more
 *      "rounded corner" of the two, which is what was asked for.
 *   2. THE DIVIDER IS NOT AN M3 FEATURE. M3 offers `prefix-text` for static in-field context (the
 *      "$" in a currency field) and leading/trailing icon slots. It has no interactive leading
 *      segment and no divider inside a text field, so there is no token to follow. The rule here is
 *      the site's own 1px #e5e7eb hairline, used as a segment separator on owner instruction.
 *
 * WHICH M3 REPO IS AUTHORITATIVE, because they disagree and the answer changed.
 *
 * Google's material-components/material-web is the original and is where the component docs still
 * live, but its own README is now carried forward by material-esm/material, a fork that states the
 * upstream project "seems to be on hold". The fork is the maintained one, so it is the reference of
 * record here. Both are cited: the doc prose is still only in Google's repo, the current code is in
 * the fork.
 *
 *   - Fork (maintained, code):  https://github.com/material-esm/material
 *   - Google (docs prose):      https://github.com/material-components/material-web/blob/main/docs/components/text-field.md
 *
 * WHAT THE FORK CHANGED, read from text/text-field.js rather than assumed:
 *   - ONE ELEMENT, NOT TWO. `<md-text-field color="outlined">` replaces `<md-outlined-text-field>`,
 *     so the token is `--md-text-field-container-shape`, NOT the `--md-outlined-text-field-...`
 *     spelling an earlier version of this comment named. That older name is simply wrong against the
 *     maintained library, which is why it is corrected rather than left as a second-best citation.
 *   - THE 4px DEFAULT SURVIVED. It still resolves
 *     `var(--md-text-field-container-shape, var(--md-sys-shape-corner-extra-small, 4px))`, so
 *     departure (1) above is still a real departure and the 10px here is still a deliberate choice,
 *     not a stale number.
 *   - PER-CORNER LOGICAL SHAPE TOKENS: container-shape-start-start / start-end / end-end /
 *     end-start. Worth recording because that is exactly the shape of what .pf-code and .pf-num do
 *     by hand below - square against the divider, 9px on the outside, spelled logically so the two
 *     segments swap in RTL. The approach matches the library's own, arrived at independently.
 *
 * NOTHING IS INSTALLED FROM EITHER REPO, and that is deliberate. Both ship Lit web components; this
 * site is Next.js with styled-jsx and has no Lit dependency, so adopting them would mean a runtime,
 * a custom-element registry and a second styling system on a page that currently has none of the
 * three. M3 is used here as a SPEC to measure against, not as a dependency.
 *
 * FOCUS IS PER SEGMENT, NOT PER CONTAINER, AND THAT IS AN ACCESSIBILITY DECISION. The obvious way to
 * keep the one-field illusion is `:focus-within` on the container - but there are TWO focusable
 * controls inside it, so a ring around the whole box tells a keyboard user that focus is somewhere
 * in there without saying which half. That fails what WCAG 2.4.7 is for. Each segment therefore
 * draws its own ring, INSET (outline-offset:-3px) so it sits inside the container's outline instead
 * of drawing a second box around it. The field still reads as one control; the focused half is
 * unambiguous.
 *
 * NO RED, on standing owner instruction. The invalid state is carried by aria-invalid and the
 * message the page renders beneath - not by a colour. A control that only says "wrong" in red says
 * nothing to a colour-blind shopper either way.
 */

export interface PhoneFieldProps {
  /** id of the NUMBER input, so a visible <label htmlFor> outside this component can point at it. */
  id: string;
  /** The selected dial code, with its plus, e.g. "+91". */
  dialCode: string;
  onDialCodeChange: ( next: string ) => void;
  /** The national number, exactly as typed. Never normalised here. */
  number: string;
  onNumberChange: ( next: string ) => void;
  disabled?: boolean;
  /** Mirrors aria-invalid on both segments: the field is wrong as a whole, not one half of it. */
  invalid?: boolean;
  /** id list for aria-describedby - the hint, plus the error when there is one. */
  describedBy?: string;
  placeholder?: string;
  /**
   * The number has been verified server-side (OTP answered). Draws the lime accent and a check.
   *
   * COLOUR IS NOT THE ONLY SIGNAL. The tick glyph and the aria-live status text carry the meaning
   * too, so the state survives forced-colors, a colour-blind reader and a screen reader - the lime
   * is confirmation for people who can see it, not the message itself.
   */
  verified?: boolean;
  /**
   * Fires when the browser's own constraint validation refuses the number segment.
   *
   * KEPT FROM THE UPSTREAM FIX, THOUGH `required` IS NOW GONE - see the note on the input below.
   * Upstream added this hook so a consumer could mirror a native refusal into its own error
   * region, on the reasoning that the native affordance should be kept AND the programmatic
   * association added, rather than one traded for the other. That reasoning is sound in general;
   * it lost here only because the owner reported the native bubble itself as the defect (it is
   * unthemeable and contradicts the standing no-red instruction), so the trade had to go the
   * other way.
   *
   * The prop stays rather than being deleted: it is the correct escape hatch if any constraint
   * attribute is ever added back (pattern, minLength, type=email on a sibling), it keeps the
   * existing consumer wiring compiling, and it costs nothing while unused. With no constraints on
   * the input it simply never fires, and emptiness is caught by the consumer's submit path.
   */
  onInvalid?: ( event: React.FormEvent<HTMLInputElement> ) => void;
}

/**
 * A FORMAT MASK, NOT A SPECIMEN NUMBER, and the distinction is the whole point.
 *
 * This was `9876543210` - ten digits starting with 9, which is a structurally valid Indian
 * mobile number. Rendered in placeholder grey beside a segment already reading "+91 India",
 * it reads as a number that is ALREADY IN THE FIELD. A shopper who believes the field is
 * filled presses the CTA, the `required` constraint refuses an empty input, and the browser
 * answers "Please fill out this field." about a field that visibly contains a number. That
 * is the shape of the reported sign-in failure.
 *
 * Zeros in two groups cannot be mistaken for a value: an Indian mobile number never begins
 * with 0, and the grouping reads as a mask. It is also LANGUAGE-NEUTRAL, which a worded hint
 * would not be - placeholder text is an attribute, and SupportWidget's translation walker
 * rewrites text nodes only (the same cost recorded on the country-code aria-label below), so
 * "10-digit number" would stay English for every non-English shopper.
 *
 * The consumer may still override it; this is the default, not a constraint.
 */
export const NUMBER_FORMAT_HINT = '00000 00000';

const normaliseDialSearch = ( raw: string ): string => {
  const digits = raw.replace( /\D/g, '' ).slice( 0, 3 );
  return digits ? `+${ digits }` : '';
};

const PhoneField: React.FC<PhoneFieldProps> = ( {
  id, dialCode, onDialCodeChange, number, onNumberChange,
  disabled, invalid, describedBy, placeholder, verified, onInvalid,
} ) => {
  /*
   * THE DIAL-CODE SEGMENT'S EDIT BUFFER LIVES HERE, IN THE SAME COMPONENT AS THE <style jsx>,
   * AND THAT IS THE WHOLE POINT OF THIS SHAPE.
   *
   * It used to live in a `DialCodeSearch` child component declared just above, which read
   * tidily and was SILENTLY BROKEN IN PRODUCTION. styled-jsx only stamps its scoping hash
   * onto JSX that appears in the same return tree as the <style jsx> element, so the child's
   * <input className="pf-code"> shipped as class="pf-code" with NO hash while every rule for
   * it compiled to `.pf-code.jsx-972b1368ee20e676{...}` - a selector that can never match.
   * Measured in the built export at out/account/sign-in/index.html, where .pf-num carried the
   * hash and .pf-code did not.
   *
   * Everything the segment declares was therefore dead, and the browser fell through to the
   * global `input` skin: 13px radius instead of the 999px leading pill, a 2px box on all four
   * sides instead of `border:0` plus the one inline-end hairline, 50px instead of 52px, 16px
   * type instead of 17px, no min-inline-size, and no `::-webkit-search-cancel-button{display:none}`
   * so the native clear glyph showed inside the field. The "one field, divided" control the
   * owner asked for rendered as TWO BOXES of different heights and different corner radii, on
   * /account/sign-in/, /get/, /cart/ and the blog subscribe block. That is the reported
   * "phone field does not match home design".
   *
   * THIS REPO HAD ALREADY PAID FOR THIS LESSON TWICE. PillButton's docblock records the same
   * failure on its two segments and says in terms: "do not extract them into a helper or a
   * child component: either reintroduces the bug". RotatingHero records it costing "a full
   * debugging round on the mega menu, where a renderLink() helper left the rules behind".
   * A child component is a helper. Do not split this input out again.
   *
   * src/test/PhoneFieldScoping.test.tsx asserts the property - .pf-code carries the SAME
   * jsx- hash as .pf-num - rather than pinning today's hash, so it survives any edit to the
   * CSS and fails only if the scoping is lost again.
   */
  const [ query, setQuery ] = useState( dialCode );

  useEffect( () => {
    setQuery( dialCode );
  }, [ dialCode ] );

  const commitIfSupported = ( raw: string ) => {
    const candidate = normaliseDialSearch( raw );
    setQuery( candidate );
    if ( findDialCode( candidate ) ) onDialCodeChange( candidate );
  };

  const unresolved = Boolean( query ) && !findDialCode( query );

  return (
  <div className={ `pf${ verified ? ' pf-verified' : '' }` }>
    <input
      className="pf-code"
      type="search"
      inputMode="tel"
      autoComplete="off"
      autoCorrect="off"
      spellCheck={ false }
      enterKeyHint="next"
      aria-label="Calling code"
      aria-invalid={ invalid || unresolved ? 'true' : undefined }
      value={ query }
      maxLength={ 4 }
      placeholder="+91"
      disabled={ disabled }
      onFocus={ event => event.currentTarget.select() }
      onChange={ event => commitIfSupported( event.target.value ) }
      onBlur={ () => {
        if ( !findDialCode( query ) ) setQuery( dialCode );
      } }
      onKeyDown={ event => {
        if ( event.key === 'Enter' ) {
          event.preventDefault();
          if ( findDialCode( query ) ) event.currentTarget.blur();
        }
      } }
    />

    <input
      id={ id }
      className="pf-num"
      type="tel"
      inputMode="tel"
      /*
       * tel-national, NOT tel. The browser is filling the number segment only - the country code is
       * the select's job - and offering a full international number here would land a "+91" inside
       * a field that already has one beside it.
       */
      autoComplete="tel-national"
      /*
       * THE PLACEHOLDER NAMES THE EXPECTED LENGTH, from the selected country's own rule:
       * "10-digit WhatsApp number" for India, "8- or 9-digit WhatsApp number" for the UAE. It is
       * the owner's requested resting-state wording, and because it is derived from the same table
       * the validation reads it can never contradict what the field accepts. A caller may override.
       *
       * THIS ALSO SATISFIES THE UPSTREAM FINDING, which was the better diagnosis of the reported
       * bug and is worth keeping on the record. Upstream replaced the old `9876543210` with a
       * grouped-zeros FORMAT MASK, on the reasoning that ten digits beginning with 9 is a
       * structurally valid Indian mobile number, so in placeholder grey beside a segment reading
       * "+91 India" it reads as a number ALREADY IN THE FIELD - the shopper submits, the `required`
       * constraint refuses an empty input, and the browser objects about a field that visibly
       * contains a number. That is the shape of the failure the owner photographed.
       * A WORDED hint cannot be mistaken for a value either, so the root cause is closed the same
       * way; the wording is kept because the owner specified it explicitly and because it states
       * the expected LENGTH, which a mask only implies. The mask's language-neutrality is the one
       * thing given up, and the string is translatable by the site's walker, which offsets it.
       */
      placeholder={ placeholder
        ?? `${ nationalLengthHint( dialCode ) } WhatsApp number`.trim() }
      /*
       * `required` IS DELIBERATELY ABSENT, and removing it was a fix - this is the one place this
       * merge deliberately overrides the upstream decision rather than combining with it.
       *
       * Upstream kept `required` and added the onInvalid hook above so a consumer could mirror the
       * native refusal into its own error region, keeping the native affordance AND adding the
       * programmatic association. Sound in the general case. It loses here because the owner
       * reported the native bubble ITSELF as the defect: "Please fill out this field." with an
       * orange warning icon, photographed on the live sign-in page. That bubble cannot be themed,
       * cannot be translated by this site's text walker, and contradicts the standing no-red
       * instruction that stripped #fee2e2/#ef4444/#7f1d1d from these very surfaces.
       *
       * Nothing is lost by removing it. With no constraint the browser no longer blocks submit, so
       * the consumer's own onSubmit runs, composeE164() rejects an empty number, and the message
       * lands in the in-page error treatment (lime state tint, role=alert) wired to this input by
       * aria-invalid + aria-describedby - themed, translatable, announced once, and still on
       * screen after a native bubble would have dismissed itself.
       */
      onInvalid={ onInvalid }
      /*
       * aria-required, NOT `required` - this is how upstream's concern is met rather than traded.
       *
       * Upstream's objection to dropping `required` was specific and fair: removing the attribute
       * also removes the "required" a screen reader announces from it, so a message would have
       * been bought at the cost of a real semantic. aria-required="true" restores exactly that
       * announcement - it is the ARIA equivalent of the native attribute - WITHOUT engaging the
       * browser's constraint validation, which is the part that renders the unthemeable orange
       * bubble the owner reported. Assistive technology hears "required" either way; the browser
       * no longer blocks submit or draws its own UI.
       *
       * So neither half is given up: the semantic comes from ARIA, and the message comes from the
       * page's own error region via onSubmit, aria-invalid and aria-describedby.
       */
      aria-required="true"
      value={ number }
      onChange={ e => onNumberChange( e.target.value ) }
      disabled={ disabled }
      aria-invalid={ invalid ? 'true' : undefined }
      aria-describedby={ describedBy }
    />

    {/*
      * THE VERIFIED MARK, inside the field on the trailing edge - the owner's "small check/icon +
      * lime accent rather than changing the whole field into a button".
      * aria-hidden on the glyph plus a role=status sibling: the tick is decoration, the status text
      * is what a screen reader announces, and it announces once rather than on every keystroke.
      */}
    { verified && (
      <span className="pf-tick">
        <span aria-hidden="true">✓</span>
        <span className="pf-tick-sr" role="status">Number verified</span>
      </span>
    ) }

    <style jsx>{`
      /* THE ONE FIELD. The outline, the radius and the height live here, on the container, and the
         two segments inside carry none of their own - that is what makes it read as a single
         control rather than two boxes that happen to touch.
         52px matches the CTA this field feeds and every other input on the site. 10px is the site's
         field radius; see the note above for why it is not M3's 4px default.
         overflow:hidden so neither segment's own background can square off the rounded corners. */
      .pf{
        display:flex;align-items:stretch;
        min-height:52px;box-sizing:border-box;
        border:1px solid #e5e7eb;border-radius:999px;background:#fff;
        margin-bottom:20px;overflow:hidden;
      }

      /* THE DIVIDER, as a logical inline-end border on the leading segment rather than a separate
         element: one declaration, and it mirrors on its own in an RTL document, where the code
         segment moves to the right and the hairline has to move with it. border-inline-end is why
         this does not need an rtlcheck exception. */
      .pf-code{
        flex:0 0 auto;
        border:0;border-inline-end:1px solid #e5e7eb;
        padding-inline:12px;
        min-inline-size:78px;max-inline-size:86px;
        background:#fff;color:#1a1a1a;
        font-family:inherit;font-size:17px;font-weight:600;
        cursor:text;
        /* Match the Home pill silhouette while keeping the divider square internally. */
        border-start-start-radius:999px;border-end-start-radius:999px;
        border-start-end-radius:0;border-end-end-radius:0;
      }
      /* Search input only: no native country dropdown, no flag, no country name. The segment shows
         the explicit calling code (+91, +971, +44...) and accepts digits with or without "+". */
      .pf-code::-webkit-search-cancel-button{display:none}

      /* The number segment takes the rest. min-inline-size:0 because a flex item's default
         min-width:auto lets a long value push the container wider than its parent. */
      .pf-num{
        flex:1 1 auto;min-inline-size:0;
        border:0;padding-inline:16px;
        background:#fff;color:#1a1a1a;
        font-family:inherit;font-size:17px;
        /* scroll-margin-top CLEARS THE FIXED 108px HEADER, and it is on the INPUT rather
           than on .pf because the input is what the browser scrolls to.
           MEASURED, not precautionary. When the browser reveals this control - on focus,
           on autofocus, or as part of refusing an empty required field - it scrolls it
           to the top of the scrollport, and the scrollport's top is UNDER the fixed
           header. At 320x568 the field landed 36px behind the header and at 390x400 (the
           height a phone has left with its keyboard open) 50px behind it, so the shopper
           could not see the number they were typing. With this declaration both measure
           0px covered.
           128px/112px are the site's existing clearance constants for this exact header,
           used the same way by .lgd-section and .cl in LegalDocument and ContactLocation.
           WHY NOT html{scroll-padding-top}, which is the tidier-looking fix: those two
           components already carry their own scroll-margin-top, and scroll-padding on the
           scrollport ADDS to scroll-margin on the target - so a document-level inset would
           silently double their anchor clearance to 256px. Measured both ways; this one
           fixes the field without touching anything else. */
        scroll-margin-top:128px;
        /* Mirror the Home pill end on the number segment. */
        border-start-start-radius:0;border-end-start-radius:0;
        border-start-end-radius:999px;border-end-end-radius:999px;
      }

      /* INSET RINGS, one per segment. outline-offset:-3px draws the ring inside the segment, so the
         container's own rounded outline stays whole and the focused half is named unambiguously.
         The ring is the site's #1a3a2a at 3px, the same indicator every other control uses. */
      .pf-code:focus-visible,
      .pf-num:focus-visible{
        outline:3px solid #1a3a2a;outline-offset:-3px;
      }

      /* THE LIME ACCENT, AND WHY LIME IS NOT THE RING ITSELF.
         
         The owner asked for #d1f470 as the focus/selected/verified accent. It cannot be the focus
         INDICATOR: #d1f470 against this white field is 1.24:1, nowhere near the 3:1 WCAG 2.4.11
         requires of a focus indicator, so a lime ring would be a focus state a low-vision keyboard
         user cannot find. Measured, not assumed - #1a3a2a is 12.48:1 on white, which is why it
         stays the ring on both segments above.
         
         So the lime is layered AROUND the dark ring instead: the container takes a #1a3a2a border
         and a soft lime halo on focus-within. The accessible indicator and the brand accent are
         then two different things doing two different jobs, and neither is weakened. A box-shadow
         is used rather than a second outline because an element gets only one outline, and shadow
         does not affect layout so the 52px height is untouched. */
      .pf:focus-within{
        border-color:#1a3a2a;
        box-shadow:0 0 0 3px rgba(209,244,112,.38);
      }

      /* VERIFIED. The same lime accent, held permanently, plus the tick. The border goes dark green
         because "verified" is an important state and dark green is this site's weight for that;
         the lime says which KIND of important. */
      .pf-verified{
        border-color:#1a3a2a;
        box-shadow:0 0 0 3px rgba(209,244,112,.55);
      }
      .pf-tick{
        display:inline-flex;align-items:center;flex:0 0 auto;
        padding-inline-end:14px;
        color:#1a3a2a;font-size:17px;font-weight:700;line-height:1;
      }
      /* The announced half of the verified state. Positioned out of view rather than
         display:none - a display:none node is not announced at all, which would leave the tick as
         the only signal and make colour/glyph the whole message. */
      .pf-tick-sr{
        position:absolute;width:1px;height:1px;margin:-1px;padding:0;
        overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0;
      }

      /* Disabled is a tint on the whole field, not on one segment, because both go at once. */
      .pf-code:disabled,.pf-num:disabled{background:#f6f7f5;color:rgba(0,0,0,.54);cursor:default}

      /* NARROW VIEWPORTS. At 320px the field has roughly 288px to work with; the code segment is
         content-sized so a three-digit code like +971 does not get clipped, and the number segment
         absorbs the rest. The padding tightens rather than the segments shrinking, so the 52px
         target height is never traded away. */
      /* The header is 96px below 768px, so the clearance steps with it - the same
         128px/112px pair .lgd-section and .cl use. Declared in its own query because the
         header's breakpoint is 767px and the padding tightening below is at 360px. */
      @media(max-width:767px){
        .pf-num{scroll-margin-top:112px}
      }

      @media(max-width:360px){
        .pf-code{padding-inline:8px}
        .pf-num{padding-inline:12px}
      }
    `}</style>
  </div>
  );
};

export default PhoneField;
