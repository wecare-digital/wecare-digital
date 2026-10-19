import React, { useEffect, useRef } from 'react';

interface ClosingBandProps {
  id: string;
  eyebrow: string;
  title: string;
  lead: string;
  points: string[];
  href: string;
  action: string;
}

/** One reveal and one accessible panel. Copy and destination belong to each public page.
 * Content ships visible; animation is armed only when supported. Focus and reduced motion
 * always reveal the action, including when the preference changes after the observer starts.
 */
export default function ClosingBand( { id, eyebrow, title, lead, points, href, action }: ClosingBandProps ) {
  const ref = useRef<HTMLElement | null>( null );
  useEffect( () => {
    const el = ref.current;
    if ( !el || typeof IntersectionObserver === 'undefined' ) return;
    if ( typeof window.matchMedia === 'function' && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return;
    el.classList.add( 'is-armed' );
    const observer = new IntersectionObserver( entries => {
      if ( entries.some( entry => entry.isIntersecting ) ) {
        el.classList.add( 'is-in' );
        observer.disconnect();
      }
    }, { threshold: 0.18 } );
    observer.observe( el );
    return () => { observer.disconnect(); el.classList.remove( 'is-armed', 'is-in' ); };
  }, [] );
  return <section className={ `cb ${id}` } aria-labelledby={ `${id}-title` } ref={ ref }>
    <div className={ `cb-panel ${id}-panel` }>
      <p className={ `cb-eyebrow ${id}-eyebrow` }>{ eyebrow }</p>
      <h2 className={ `cb-title ${id}-title` } id={ `${id}-title` }>{ title }</h2>
      <p className={ `cb-lead ${id}-lead` }>{ lead }</p>
      <span className={ `cb-rule ${id}-rule` } aria-hidden="true" />
      <ul className={ `cb-points ${id}-points` }>{ points.map( point => <li key={ point }>{ point }</li> ) }</ul>
      {/* Plain anchor retains styled-jsx's class on the focusable control. */}
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a className={ `cb-cta ${id}-cta` } href={ href }>{ action }</a>
    </div>
    <style jsx>{`        .cb-panel{
          padding:clamp(28px,4vw,56px);
          border:2px solid var(--public-brand-lime);border-radius:14px;
          background:var(--public-lime-tint);
        }
        .cb-eyebrow{
          margin:0 0 14px;font-size:14px;font-weight:700;
          letter-spacing:.08em;text-transform:uppercase;color:var(--public-brand-green);
        }
        .cb-title{
          margin:0 0 16px;max-width:19ch;
          font-size:var(--public-section-size);font-weight:var(--public-section-weight);line-height:var(--public-section-leading);
          letter-spacing:var(--public-section-tracking);color:var(--public-heading);
        }
        .cb-lead{
          margin:0;max-width:62ch;
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
          color:var(--public-body);
        }
        .cb-rule{
          display:block;height:3px;margin:30px 0;background:var(--public-brand-lime);
          transform-origin:left center;
          transition:transform .62s cubic-bezier(.22,.61,.36,1);
        }
        .cb.is-armed .cb-rule{transform:scaleX(0)}
        .cb.is-armed.is-in .cb-rule{transform:scaleX(1)}
        .cb-points{margin:0;padding:0;max-width:62ch;list-style:none;display:flex;flex-direction:column;gap:12px}
        .cb-points li{
          position:relative;padding-inline-start:26px;
          font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-body);
          transition:opacity .5s ease,transform .5s ease;
        }
        .cb-points li:nth-child(2)::before{border-left-color:#2563eb;border-bottom-color:#2563eb}
        .cb-points li:nth-child(3)::before{border-left-color:#9849e8;border-bottom-color:#9849e8}
        .cb-points li::before{
          content:'';position:absolute;inset-inline-start:2px;top:7px;
          width:11px;height:6px;
          border-left:2.5px solid #3da35a;border-bottom:2.5px solid #3da35a;
          transform:rotate(-45deg);
        }
        .cb.is-armed .cb-points li{opacity:0;transform:translateY(8px)}
        .cb.is-armed.is-in .cb-points li{opacity:1;transform:none}
        .cb.is-armed.is-in .cb-points li:nth-child(1){transition-delay:.34s}
        .cb.is-armed.is-in .cb-points li:nth-child(2){transition-delay:.43s}
        .cb.is-armed.is-in .cb-points li:nth-child(3){transition-delay:.52s}
        .cb-cta{
          display:inline-flex;align-items:center;min-height:var(--public-cta-height);margin-top:32px;
          padding:0 28px;border:var(--public-cta-border) solid var(--public-brand-green);border-radius:var(--public-cta-radius);
          background:var(--public-brand-lime);color:var(--public-brand-green);font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);text-decoration:none;
          transition:opacity .5s ease,transform .5s ease,background-color .2s,box-shadow .2s;
        }
        .cb.is-armed .cb-cta{opacity:0;transform:translateY(8px);pointer-events:none}
        .cb.is-armed.is-in .cb-cta{opacity:1;transform:none;pointer-events:auto;transition-delay:.62s}
        .cb.is-armed .cb-cta:focus{opacity:1;transform:none;pointer-events:auto;transition:none}
        .cb-cta:hover{background:#fff;transform:translateY(-2px);box-shadow:var(--public-lift-shadow)}
        .cb-cta:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
        @media(prefers-reduced-motion:reduce){
          .cb-rule,.cb-points li,.cb-cta{transition:none}
          .cb.is-armed .cb-rule{transform:scaleX(1)}
          .cb.is-armed .cb-points li,
          .cb.is-armed .cb-cta{opacity:1;transform:none}
          .cb.is-armed .cb-cta{pointer-events:auto}
          .cb-cta:hover{transform:none}
        }
        @media(max-width:767px){
          .cb-title{max-width:none}
        }`}</style>
  </section>;
}
