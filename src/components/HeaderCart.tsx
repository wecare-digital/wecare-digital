import React, { useEffect, useState } from 'react';
import { cartCount, CART_CHANGED_EVENT } from '../lib/cart';

/**
 * The Shopping Bag control on the right of the public header.
 *
 * SELF-STYLING, like BrandLockup and RotatingHero. styled-jsx only attaches its scoping class to
 * lowercase DOM tags it can see in the file it compiles, never to a capitalised component, so a
 * `<style jsx>` block in Header.tsx cannot reach in here. The component owns its CSS and Header
 * owns nothing but the placement of the element - which is why `margin-inline-start:auto` is
 * declared below rather than in the parent.
 *
 * A PLAIN <a>, NOT next/link, for the same reason the logo above it is one: styled-jsx cannot
 * scope `<Link className="...">`, and every other row in this header is a plain anchor too. The
 * trailing slash is load-bearing - next.config.js sets trailingSlash, so /cart would 308 before
 * resolving.
 *
 * THE GLYPH IS INLINE SVG, which is a new pattern in this header (the menu chevron is drawn from
 * two borders). It is the right one here: the bag carries a live numeric badge inside it, so it
 * must inherit `currentColor` and re-paint with the control's state, and an <img> from the media
 * CDN would add a request and a layout shift to the first paint of every public page. A standalone
 * copy of the same artwork is committed at public/icons/shopping-bag.svg for upload to the media
 * prefix; nothing in the code points at a hosted URL, because a URL that 404s is worse than no URL.
 *
 * Artwork: Material Symbols Outlined "shopping_bag", 48px, FILL 0 / wght 400 / GRAD 0 / opsz 48,
 * Apache-2.0, recoloured from the stock #1f1f1f to this site's #1a3a2a.
 *
 * THE COUNT IS READ AFTER MOUNT, AND THAT IS NOT LAZINESS. The cart lives in localStorage
 * (src/lib/cart.ts) and these pages are statically exported, so the server render has no cart to
 * read. Rendering a server-side 0 and then swapping it for 3 is a hydration mismatch; rendering
 * nothing until the effect runs is not. `null` therefore means "not read yet" and is distinct from
 * 0, and the badge is absent in both cases - so there is no flash of a wrong number, only a badge
 * that appears.
 *
 * THE NUMBER IS A TEXT NODE, NOT AN ATTRIBUTE. SupportWidget's translation walker rewrites text
 * nodes and never attribute text, so an aria-label carrying the count would stay English in every
 * language (skill §5: 1329 such strings sitewide). The accessible name is therefore built from
 * real text: a visible "Shopping Bag" label and a visually-hidden count phrase. The digits drawn
 * inside the bag are decorative - the glyph is aria-hidden - and carry data-wc-no-translate for
 * the same reason prices do: a regrouped numeral is a different number.
 */

/** Above this, the badge reads as a smudge rather than a number. */
const BADGE_CEILING = 99;

const HeaderCart: React.FC = () => {
  const [ count, setCount ] = useState<number | null>( null );

  useEffect( () => {
    const sync = (): void => setCount( cartCount() );
    sync();
    // `storage` covers another tab; the custom event covers this one, where a write made by
    // /shop/<slug>/'s add-to-cart button does not fire `storage` on its own window.
    window.addEventListener( 'storage', sync );
    window.addEventListener( CART_CHANGED_EVENT, sync );
    return () => {
      window.removeEventListener( 'storage', sync );
      window.removeEventListener( CART_CHANGED_EVENT, sync );
    };
  }, [] );

  const badge = count !== null && count > 0
    ? ( count > BADGE_CEILING ? `${BADGE_CEILING}+` : String( count ) )
    : '';

  /**
   * The whole accessible name, as an attribute — there is NO text in the markup at all.
   *
   * The owner asked for the label deleted, not clipped, so the visually-hidden span and the clipped
   * count phrase are both gone. The name has to live somewhere: a link whose only content is an
   * aria-hidden glyph has no accessible name, which a screen reader announces as a bare "link" and
   * Lighthouse fails as a discernible-name violation (it is one of the audits that keeps this site
   * at 100).
   *
   * THE COST, STATED PLAINLY: attribute text is never translated. SupportWidget's walker rewrites
   * text nodes only, so this string stays English in languages where a text node would have been
   * translated. That is the trade "delete it" buys, and it was the only reason the clipped node
   * existed.
   *
   * The count is folded in because the digits drawn inside the glyph are aria-hidden, so without it
   * the number would be invisible to a screen reader. Absent before the cart has been read, rather
   * than guessed at zero.
   */
  const accessibleName = count === null
    ? 'Shopping Bag'
    : count === 0
      ? 'Shopping Bag, empty'
      : `Shopping Bag, ${count} ${count === 1 ? 'item' : 'items'}`;

  return (
    // A plain anchor rather than next/link: styled-jsx does not scope a capitalised component, so
    // `<Link className="hdr-cart">` would render with none of the CSS below. The logo in Header.tsx
    // and every row of the nav menu carry the same exemption for the same reason.
    // eslint-disable-next-line @next/next/no-html-link-for-pages
    <a className="hdr-cart" href="/checkout/" aria-label={ accessibleName }>
      <span className="hdr-cart-glyph" aria-hidden="true">
        <svg viewBox="0 -960 960 960" focusable="false">
          <path d="M220-80q-24 0-42-18t-18-42v-520q0-24 18-42t42-18h110v-10q0-63 43.5-106.5T480-880q63 0 106.5 43.5T630-730v10h110q24 0 42 18t18 42v520q0 24-18 42t-42 18H220Zm0-60h520v-520H630v90q0 12.75-8.68 21.37-8.67 8.63-21.5 8.63-12.82 0-21.32-8.63-8.5-8.62-8.5-21.37v-90H390v90q0 12.75-8.68 21.37-8.67 8.63-21.5 8.63-12.82 0-21.32-8.63-8.5-8.62-8.5-21.37v-90H220v520Zm170-580h180v-10q0-38-26-64t-64-26q-38 0-64 26t-26 64v10ZM220-140v-520 520Z" />
        </svg>
        { badge && (
          // data-wide, not a second class name: styled-jsx scopes a STATIC className string, and a
          // ternary there is a scoping risk for no gain. The attribute is only ever set for the
          // three-character "99+" case - measured at 22.56px against a 19.5px hollow bag body, so
          // it needs the tighter rung or it crosses the outline.
          <span
            className="hdr-cart-n"
            data-wide={ badge.length > 2 ? 'true' : undefined }
            data-wc-no-translate="true"
          >{ badge }</span>
        ) }
      </span>

      <style jsx>{`
        /* THE BAG ONLY - NO LABEL, NO BORDER, NO FILL AT REST, on owner instruction. "Shopping
           Bag" was how the icon was identified, not copy to render. The chip treatment that
           matched .nav-trigger is gone with it.
           44px square is kept: it is the WCAG 2.5.8 target floor, and it is now pure hit area
           rather than a visible box. margin-inline-start:auto puts it on the right of .hdr-in's
           flex row and mirrors on its own in an RTL document. flex-shrink:0 because the brand
           lockup beside it is nowrap, so without it a narrow viewport squeezes the bag. */
        .hdr-cart{
          margin-inline-start:auto;flex-shrink:0;
          display:inline-flex;align-items:center;justify-content:center;
          inline-size:44px;min-height:44px;padding:0;box-sizing:border-box;
          background:none;border:0;border-radius:10px;
          color:var(--public-brand-green);text-decoration:none;
          transition:background-color .18s ease;
        }
        /* HOVER IS THE MENU ICON'S HOVER, EXACTLY, on owner instruction: "cart hover color should
           match menu hover color".
           .nav-trigger's hover (Header.tsx) sets background:#d1f470 with the chevron staying
           #1a3a2a - a LIME SURFACE, not a glyph recolour. So matching it means painting the surface
           lime and leaving the bag dark, which is the reverse of what this rule did a moment ago.
           THE EARLIER "NO BACKGROUND" INSTRUCTION IS NOT CONTRADICTED, and the distinction is the
           word that was used: "dont show back grund rounc cicilr" - a round CIRCLE. The menu chip is
           a 10px ROUNDED SQUARE, so the radius above moved 50% -> 10px to match it. What was
           rejected was a circular disc in a header whose only other control is a rounded-square
           chip; what is drawn now is the same shape and the same colour as that chip.
           A previous pass here used #3da35a because it measured 3.19:1 on white as a glyph colour.
           That was the right answer to the wrong question - it is not a colour the menu icon uses,
           and the instruction is about matching the menu, not about finding a third green.
           CONTRAST, measured: #1a3a2a on #d1f470 is 10.03:1, so the bag and its badge digits are far
           clearer on hover than at rest. The lime surface itself is 1.24:1 against the white header,
           which is why lime is never used for a glyph here - but as a transient hover SURFACE it is
           the established pattern, shipped on .nav-trigger already.
           ONE LIME SURFACE PER PAGE still holds: that rule governs the resting actionable surface
           (the page's primary CTA). Both header chips spend lime only while the pointer is on them,
           and never at the same time as each other.
           No border is added. The owner removed this control's border outright ("only cart icon no
           text or boder"); the instruction here names the colour, so the 2px dark edge .nav-trigger
           grows on hover is deliberately NOT copied. */
        .hdr-cart:hover{background:var(--public-brand-lime)}
        /* The focus ring STAYS. It is not decoration - removing the border is a visual request,
           and a keyboard user still has to see where they are (WCAG 2.4.7, and 1.4.11 for the
           indicator's own contrast). */
        /* The two-tone ring .nav-trigger uses: a 2px white spacer so the ring is not drawn flush
           against the chip it surrounds, then 3px of opaque #1a3a2a, which measures 12.48:1
           against the white header. A single translucent stop was measured at 1.44:1 and failed
           WCAG 1.4.11 on the sibling control. */
        .hdr-cart:focus-visible{box-shadow:0 0 0 2px #fff,0 0 0 5px var(--public-brand-green)}

        /* 36px of glyph inside the 44px target, up from 30px on owner instruction. 36 is the
           largest even step that keeps a 4px inset on each side, so the bag still has air inside
           the hit area and the focus ring is not drawn through the artwork. The 44px target itself
           does NOT grow: it is the WCAG 2.5.8 floor and it is also what holds .hdr-in's row at the
           pinned 108px / 96px header height, which Header.test.tsx asserts.
           The bag is drawn FILL@0, so its body is hollow - which is the whole reason the number can
           sit inside it rather than on a separate dot pinned to a corner. */
        .hdr-cart-glyph{position:relative;display:inline-flex;flex-shrink:0;inline-size:36px;block-size:36px}
        .hdr-cart-glyph svg{inline-size:36px;block-size:36px;display:block;fill:currentColor}

        /* CENTRED IN THE BAG'S BODY, NOT IN THE ICON BOX. The glyph's viewBox is 0 -960 960 960
           and the body runs from y=-660 to y=-140, so its centre is at y=-400 - which is 58.3%
           of the way down the box, not 50%. 60% is that, rounded to the nearest percent the
           36px box can actually resolve (0.36px steps).
           Dark green digits on the hollow white interior, never lime: lime means actionable on
           this site and a page is allowed one lime surface, which /cart/ spends on its
           Proceed-to-checkout button. tabular-nums so 1 and 11 sit on the same centre. */
        .hdr-cart-n{
          position:absolute;inset-inline-start:50%;inset-block-start:60%;
          transform:translate(-50%,-50%);
          /* 12px, not the 13.2px a straight 30->36 scale would give: the hollow body is only
             520/960 of the box wide, which is 19.5px at a 36px glyph, so the box grew by 20% but
             the room for digits did not grow with the font. Measured at 12px: one digit 7.53px,
             two 15.05px - both comfortably inside. Three characters do NOT fit at this size; they
             get the narrower rung below rather than dragging every badge down with them. */
          font-size:12px;font-weight:700;line-height:1;letter-spacing:-.02em;
          font-variant-numeric:tabular-nums;color:currentColor;pointer-events:none;
        }
        /* THE "99+" CASE ONLY, and the numbers are measured on the built page: at 12px the three
           characters render 22.56px wide against a hollow body 19.5px across, so they cross the
           bag's outline by 1.53px on each side. 10px with tighter tracking brings them back inside.
           One and two digits keep the full 12px - shrinking every badge to fit the rarest one would
           undo the size increase that was asked for. */
        .hdr-cart-n[data-wide]{font-size:10px;letter-spacing:-.04em}

        /* NO LABEL RULES AT ALL ANY MORE. The two clipped text nodes this component used to render
           are deleted, so their rules went with them. The name is an aria-label on the anchor - see
           the note beside accessibleName for what that costs. No width breakpoint either: the
           control is a constant 44px square, so the old 767px label-clipping query had nothing
           left to clip. */
        @media(prefers-reduced-motion:reduce){
          .hdr-cart{transition:none}
        }
      `}</style>
    </a>
  );
};

export default HeaderCart;
