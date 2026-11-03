/**
 * WsHeader — the /ws-scoped top header, mounted by WsShell on every width.
 *
 * This REPRODUCES the homepage header idiom (src/components/Header.tsx `.hdr`: a white surface
 * with a 1px bottom hairline, the shared brand lockup on the left) but is built fresh for the
 * authenticated workspace rather than mounting the public Header. The public Header is
 * position:fixed and drags in the public search/nav/cart/SupportWidget wiring, all of which is
 * wrong inside the /ws fixed shell and would collide with WsShell's sticky topbar / sidebar /
 * bottom-nav. So this is a lightweight, sticky-within-the-shell bar that carries only:
 *   - the brand mark (shared BrandLockup) linking to /ws Home, and
 *   - the signed-in identity + a single quiet Sign out control (the identity/Sign out that
 *     previously lived only in the sidebar foot is consolidated here).
 *
 * BrandLockup is the shared brand mark; its docstring explicitly sanctions reuse OUTSIDE the
 * public shell (e.g. the workspace sidebar), so it is imported here. It is a self-contained
 * component with its own styled-jsx, so wrapping it in a Link is safe as long as the Link uses
 * plain inline styles that do not rely on styled-jsx scoping.
 *
 * All colours/spacing/radii come from src/styles/tokens.css via co-located styled-jsx (the repo
 * convention). Icons are inline SVG so the header does not depend on the Material Symbols subset.
 */
import React from 'react';
import Link from 'next/link';
import BrandLockup from '../BrandLockup';

interface WsHeaderProps {
  /** The signed-in identity to show on the right (login id / email). */
  loginId?: string;
  /** Called by the Sign out control. */
  signOut?: () => void;
}

const SignOutGlyph = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M15 4h4v16h-4" /><path d="M10 12H3" /><path d="m6 8-4 4 4 4" />
  </svg>
);

const WsHeader: React.FC<WsHeaderProps> = ( { loginId, signOut } ) => (
  <header className="ws-header">
    <div className="ws-header-in">
      <Link href="/ws" className="ws-header-brand" aria-label="Workspace home">
        <BrandLockup className="public-header" />
      </Link>

      <div className="ws-header-end" data-wc-no-translate="true">
        { loginId ? <span className="ws-header-id" title={ loginId }>{ loginId }</span> : null }
        <button type="button" className="ws-header-signout" onClick={ () => signOut?.() }>
          <SignOutGlyph />
          <span className="ws-header-signout-label">Sign out</span>
        </button>
      </div>
    </div>

    <style jsx>{`
      /* White surface with a 1px bottom hairline — the homepage .hdr idiom, adapted for an
         authenticated shell. NOT position:fixed (the public header is, which is wrong inside
         WsShell): sticky to the top of the content column is enough and does not fight the
         shell's own sticky/fixed chrome. Honours the top safe-area inset. */
      .ws-header{
        position:sticky;
        top:0;
        z-index:20;
        background:var(--surface,#fff);
        border-bottom:1px solid var(--border,#e5e7eb);
        padding-top:env(safe-area-inset-top,0px);
        box-sizing:border-box;
      }
      .ws-header-in{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        min-width:0;
        min-height:64px;
        padding:10px max(16px,env(safe-area-inset-right,0px)) 10px max(16px,env(safe-area-inset-left,0px));
        box-sizing:border-box;
        overflow-x:hidden;
        overflow-x:clip;
      }

      /* inline-flex, min-height:44px tap floor, min-width:0 so the lockup can compress rather
         than push the bar wide at 320px. Plain inline styles only — BrandLockup brings its own
         scoped styles. */
      .ws-header-brand{
        display:inline-flex;
        align-items:center;
        min-width:0;
        min-height:var(--tap-min,44px);
        text-decoration:none;
        border-radius:var(--radius-lg,12px);
      }
      .ws-header-brand:focus-visible{
        outline:2px solid var(--accent,#1a3a2a);
        outline-offset:2px;
      }

      .ws-header-end{
        display:inline-flex;
        align-items:center;
        gap:12px;
        min-width:0;
        flex:0 1 auto;
      }
      /* The signed-in identity: muted, truncates on narrow widths. Hidden entirely below 420px
         so Sign out stays reachable without overflow at 320px. */
      .ws-header-id{
        font-size:13px;
        color:var(--text-muted,#6b7280);
        max-width:220px;
        overflow:hidden;
        text-overflow:ellipsis;
        white-space:nowrap;
      }

      /* A quiet Notion button: hairline border, grey text, danger-on-hover. */
      .ws-header-signout{
        display:inline-flex;
        align-items:center;
        justify-content:center;
        gap:8px;
        flex:0 0 auto;
        min-height:var(--tap-min,44px);
        padding:8px 14px;
        border:1px solid var(--border,#e5e7eb);
        border-radius:var(--radius-md,8px);
        background:var(--surface,#fff);
        color:var(--text-muted,#6b7280);
        font-family:inherit;
        font-size:14px;
        font-weight:600;
        line-height:1;
        cursor:pointer;
        transition:border-color var(--transition-normal,0.15s ease),color var(--transition-normal,0.15s ease),background var(--transition-normal,0.15s ease);
      }
      .ws-header-signout:hover{
        border-color:var(--danger,#dc2626);
        color:var(--danger,#dc2626);
        background:var(--danger-light,#fef2f2);
      }
      .ws-header-signout:focus-visible{
        outline:2px solid var(--accent,#1a3a2a);
        outline-offset:2px;
      }

      @media (max-width:419px){
        .ws-header-id{ display:none; }
      }
      @media (max-width:359px){
        .ws-header-signout{ padding:8px 10px; }
      }
      @media (prefers-reduced-motion:reduce){
        .ws-header-signout{ transition:none; }
      }
      @media (forced-colors:active){
        .ws-header{ border-color:CanvasText; }
        .ws-header-signout{ border-color:CanvasText; }
      }
    `}</style>
  </header>
);

export default WsHeader;
