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
        display:inline-flex;align-items:center;gap:8px;
        box-sizing:border-box;min-width:0;max-width:100%;
        padding:7px 12px;border-radius:9999px;
        background:var(--public-brand-lime,#d1f470);color:var(--public-brand-green,#1a3a2a);
        font-size:14px;font-weight:600;letter-spacing:-.125px;line-height:1.35;
        white-space:normal;
      }
      .brand-badge-label{min-width:0;overflow-wrap:anywhere}
    ` }</style>
  </span>
);

export default BrandBadge;
