/**
 * WsFooter — the /ws-scoped footer, mounted by WsShell at the foot of the scrollable content.
 *
 * This REPRODUCES the homepage footer idiom (src/components/Footer.tsx `.ft-footer`: a top
 * hairline over a white surface, a left-aligned compact brand lockup, a short muted line, and a
 * 56x3 lime dash motif) but is built fresh for the workspace. The public Footer carries marketing
 * copy ("Trusted everyday services for Bharat") and an IntersectionObserver scroll-animation that
 * are both wrong inside an app shell, so NONE of that JS is copied here — the dash is a static
 * CSS span and the workspace line is a neutral descriptor, not the marketing tagline.
 *
 * BrandLockup is imported compact (the footer's secondary scale) and wrapped in a Link to /ws.
 * All colours/spacing/radii come from src/styles/tokens.css via co-located styled-jsx.
 */
import React from 'react';
import Link from 'next/link';
import BrandLockup from '../BrandLockup';

const WsFooter: React.FC = () => (
  <footer className="ws-footer">
    <div className="ws-footer-in">
      <Link href="/ws" className="ws-footer-brand" aria-label="Workspace home">
        <BrandLockup compact className="public-footer" />
      </Link>
      <p className="ws-footer-line">WECARE workspace</p>
      {/* Static lime dash — the homepage footer's .ft-dash motif WITHOUT the scroll animation. */}
      <span className="ws-footer-dash" aria-hidden="true" />
    </div>

    <style jsx>{`
      /* A top hairline over the white surface — the homepage .ft-footer idiom. Honours the
         bottom safe-area inset so it clears the home bar on device shells. Visually subordinate
         to the header: left-aligned, compact lockup, muted line, small accent dash. */
      .ws-footer{
        background:var(--surface,#fff);
        border-top:1px solid var(--border,#e5e7eb);
        padding:28px 0 calc(16px + env(safe-area-inset-bottom,0px));
        box-sizing:border-box;
      }
      .ws-footer-in{
        display:flex;
        flex-direction:column;
        align-items:flex-start;
        gap:12px;
        min-width:0;
        padding:0 max(16px,env(safe-area-inset-right,0px)) 0 max(16px,env(safe-area-inset-left,0px));
        box-sizing:border-box;
      }

      /* inline-flex with a 44px tap floor — the lockup's logo is ~40px, so the anchor needs the
         floor to stay a valid touch target. Plain inline styles only; BrandLockup is scoped. */
      .ws-footer-brand{
        display:inline-flex;
        align-items:center;
        min-width:0;
        min-height:var(--tap-min,44px);
        text-decoration:none;
        border-radius:var(--radius-md,8px);
      }
      .ws-footer-brand:focus-visible{
        outline:2px solid var(--accent,#1a3a2a);
        outline-offset:2px;
      }

      /* A short, neutral workspace descriptor — NOT the public marketing tagline. */
      .ws-footer-line{
        margin:0;
        font-size:13px;
        line-height:1.5;
        color:var(--text-muted,#6b7280);
      }

      /* Static lime dash, 56x3, purely decorative (aria-hidden). No JS, no animation. */
      .ws-footer-dash{
        display:block;
        width:56px;
        height:3px;
        border-radius:var(--radius-full,9999px);
        background:var(--lime,#d1f470);
      }

      @media (forced-colors:active){
        .ws-footer{ border-color:CanvasText; }
      }
    `}</style>
  </footer>
);

export default WsFooter;
