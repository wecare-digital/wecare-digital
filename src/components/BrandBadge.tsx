import React from 'react';
import BrandMark from './BrandMark';

interface BrandBadgeProps {
  /** Page/product identity; not an action or a status. */
  label: string;
}

/**
 * The canonical public hero eyebrow. Keep the established first-party lime/forest
 * pair; neither a new product hue nor the rotating headline's current colour is
 * needed here. The mark and type share the same ink.
 *
 * This component owns its paint (styled-jsx cannot reach a composite child).
 * A dedicated shrinkable label lets long names reflow at narrow widths and zoom
 * without shrinking the mark or clipping the text. The consumer owns spacing
 * outside the badge. Brand labels remain intact through LanguageBar translation.
 */
const BrandBadge: React.FC<BrandBadgeProps> = ( { label } ) => (
  <span className="brand-badge" data-wc-no-translate="true">
    <BrandMark />
    <span className="brand-badge-label">{ label }</span>
    <style jsx>{ `
      .brand-badge{
        --brand-mark-height:1.2em;
        display:inline-flex;align-items:center;justify-content:center;gap:6px;
        vertical-align:middle;box-sizing:border-box;width:fit-content;min-width:0;max-width:100%;
        padding:5px 10px;border-radius:9999px;
        background:var(--public-brand-lime,#d1f470);color:var(--public-brand-green,#1a3a2a);
        font-size:17px;font-weight:650;letter-spacing:-.125px;line-height:1.2;
        text-align:center;white-space:normal;
      }
      .brand-badge-label{
        display:block;min-width:0;margin:0;padding:0;font:inherit;
        letter-spacing:inherit;text-align:center;overflow-wrap:anywhere;
      }
      @media(min-width:768px){.brand-badge{font-size:18px}}
    ` }</style>
  </span>
);

export default BrandBadge;
