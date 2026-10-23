import React from 'react';

function joinClassNames( ...parts: Array<string | false | null | undefined> ) {
  return parts.filter( Boolean ).join( ' ' );
}

export const VayuLokCompactPill = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement>>(
  function VayuLokCompactPill( { className, type = 'button', ...props }, ref ) {
    return <button ref={ ref } type={ type } className={ joinClassNames( 'vl-ui-compact-pill', className ) } { ...props } />;
  }
);

export const VayuLokHorizontalRail = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function VayuLokHorizontalRail( { className, ...props }, ref ) {
    return <div ref={ ref } className={ joinClassNames( 'vl-ui-horizontal-rail', className ) } { ...props } />;
  }
);

export const VayuLokDataCard = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement>>(
  function VayuLokDataCard( { className, type = 'button', ...props }, ref ) {
    return <button ref={ ref } type={ type } className={ joinClassNames( 'vl-ui-data-card', className ) } { ...props } />;
  }
);

export const VayuLokIconAction = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement>>(
  function VayuLokIconAction( { className, type = 'button', ...props }, ref ) {
    return <button ref={ ref } type={ type } className={ joinClassNames( 'vl-ui-icon-action', className ) } { ...props } />;
  }
);

export function VayuLokSectionHeading( { className, ...props }: React.HTMLAttributes<HTMLHeadingElement> ) {
  return <h4 className={ joinClassNames( 'vl-ui-section-heading', className ) } { ...props } />;
}

interface FreshnessStampProps extends React.HTMLAttributes<HTMLSpanElement> {
  iconPath: string;
  iconClassName?: string;
  text: string;
}

export function VayuLokFreshnessStamp( { className, iconClassName, iconPath, text, ...props }: FreshnessStampProps ) {
  return (
    <span className={ joinClassNames( 'vl-ui-freshness-stamp', className ) } { ...props }>
      <svg className={ joinClassNames( 'vl-ui-freshness-icon', iconClassName ) } viewBox="0 -960 960 960" aria-hidden="true">
        <path d={ iconPath } />
      </svg>
      <span>{ text }</span>
    </span>
  );
}

export function VayuLokUiStyles() {
  return (
    <style jsx global>{`
      .vl-ui-compact-pill{
        min-height:32px;padding:0 10px;border:1px solid var(--hair,var(--public-hairline));
        border-radius:var(--pill-r,var(--radius-full));background:#fff;color:var(--green,var(--public-brand-green));
        font:inherit;font-size:var(--vl-meta-size,var(--public-meta-size));font-weight:700;line-height:1;white-space:nowrap;cursor:pointer
      }
      .vl-ui-compact-pill:hover{border-color:var(--lime,var(--public-brand-lime));background:var(--lime-tint,var(--public-lime-tint))}
      .vl-ui-compact-pill.is-active{border-color:var(--lime,var(--public-brand-lime));background:var(--lime,var(--public-brand-lime));color:var(--green,var(--public-brand-green))}
      .vl-ui-horizontal-rail{
        display:flex;gap:8px;overflow-x:auto;padding:0 0 8px;scroll-snap-type:x proximity;scrollbar-width:thin;
        overscroll-behavior-x:contain;touch-action:pan-x;-webkit-overflow-scrolling:touch;scroll-padding-inline:2px
      }
      .vl-ui-horizontal-rail::-webkit-scrollbar{height:6px}
      .vl-ui-data-card{
        display:flex;flex:0 0 clamp(142px,42vw,168px);width:clamp(142px,42vw,168px);min-width:142px;
        scroll-snap-align:start;flex-direction:column;align-items:flex-start;gap:4px;padding:10px 12px;
        border:1px solid var(--hair,var(--public-hairline));border-radius:var(--radius-lg,12px);background:#fff;
        color:var(--body,var(--public-body));text-align:start;touch-action:manipulation;cursor:pointer
      }
      .vl-ui-data-card:hover,.vl-ui-data-card.is-active{border-color:var(--lime,var(--public-brand-lime));background:var(--lime-tint,var(--public-lime-tint))}
      .vl-ui-data-card.is-active{background:var(--lime,var(--public-brand-lime));color:var(--green,var(--public-brand-green))}
      .vl-ui-data-card>span{color:var(--muted,var(--public-muted));font-size:var(--vl-meta-size,var(--public-meta-size));font-weight:600;line-height:1.4;white-space:normal}
      .vl-ui-data-card>strong{color:#000;font-size:var(--vl-data-size,var(--public-data-size));font-weight:700;line-height:1.35;letter-spacing:-.18px}
      .vl-ui-data-card>small{color:var(--muted,var(--public-muted));font-size:var(--vl-meta-size,var(--public-meta-size));font-weight:600;line-height:1.4}
      .vl-ui-icon-action{
        position:relative;display:inline-flex;flex:0 0 var(--tap-min,44px);width:var(--tap-min,44px);height:var(--tap-min,44px);
        min-height:var(--tap-min,44px);align-items:center;justify-content:center;padding:0;border:1px solid var(--hair,var(--public-hairline));
        border-radius:50%;background:#fff;color:var(--green,var(--public-brand-green));line-height:1;scroll-snap-align:start;cursor:pointer
      }
      .vl-ui-icon-action:hover{border-color:var(--lime,var(--public-brand-lime));background:var(--lime-tint,var(--public-lime-tint))}
      .vl-ui-icon-action.is-active{border-color:var(--lime,var(--public-brand-lime));background:var(--lime,var(--public-brand-lime))}
      .vl-ui-section-heading{
        display:block;margin:0;color:#000;font-size:var(--vl-panel-heading-size,var(--public-data-size));font-weight:var(--vl-panel-heading-weight,700);
        line-height:var(--vl-panel-heading-lh,1.35);letter-spacing:var(--vl-panel-heading-track,-.18px);
        padding-inline-start:10px;border-inline-start:3px solid var(--lime,var(--public-brand-lime))
      }
      .vl-ui-freshness-stamp{
        display:inline-flex;align-items:center;gap:5px;width:fit-content;color:var(--muted,var(--public-muted));
        font-size:var(--vl-meta-size,var(--public-meta-size));font-weight:600;line-height:1.35;white-space:nowrap
      }
      .vl-ui-freshness-icon{flex:0 0 15px;width:15px;height:15px;fill:currentColor}
    `}</style>
  );
}
