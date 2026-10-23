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
