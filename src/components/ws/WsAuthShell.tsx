/**
 * WsAuthShell — the /ws-scoped sign-in skin.
 *
 * SCOPE, STATED FIRST: this component is used by src/pages/_app.tsx ONLY when the active
 * route is under /ws (router.pathname.startsWith('/ws')). Every other authenticated route —
 * /workspace and anything else that is not public — keeps using src/components/AuthShell.tsx
 * and its AuthGate chrome, byte-unchanged. So this file changes the login for the new /ws
 * workspace and nothing else.
 *
 * WHAT IT IS, AND WHAT IT IS NOT. It is a FRESH visual skin authored from scratch in the /ws
 * design language (forest green --accent #1a3a2a, lime --lime #d1f470, --lime-tint, Inter,
 * --tap-min 44px, safe-area insets, the --radius-* scale from src/styles/tokens.css, matched
 * to src/components/ws/WsShell.tsx). It deliberately does NOT import or reuse AuthShell's
 * authTheme, AuthGate chrome, AuthBrand or its styled-jsx. The visuals here are new.
 *
 * It is NOT a second auth system. There is one Cognito user pool for the whole site; this skin
 * authenticates against the SAME pool with the SAME credentials as /workspace. It wraps the
 * SAME Amplify <Authenticator> state machine (hideSignUp, the MFA selection challenge, the
 * signOut/user render props) — only the surrounding layout, the Amplify Theme object and the
 * brand header are new. lib/amplifyConfig is imported for its side effect first, exactly as
 * AuthShell does, so Cognito is configured before the Authenticator renders. If the
 * NEXT_PUBLIC_COGNITO_* env is absent (as locally), Amplify shows "Auth UserPool not
 * configured" inside the card — that is an environment-config gap, not a defect in this skin.
 *
 * Auth plumbing beyond the sign-in UI is unchanged: once authenticated this returns children
 * directly, and _app.tsx renders the /ws page (which mounts its own WsShell).
 */

import type React from 'react';
// Configure Amplify before this module's first Auth call — same side-effect import AuthShell
// uses. Do NOT remove: without it the Authenticator has no pool to talk to.
import '../../lib/amplifyConfig';
import { Authenticator, ThemeProvider, type Theme, useAuthenticator } from '@aws-amplify/ui-react';

/**
 * WsBrandHeader — a fresh brand line above the /ws sign-in form, handed to Amplify's
 * Authenticator through its `components.Header` slot.
 *
 * Authored new for /ws: the brand mark here is the same lime-tile wordmark idiom WsShell uses
 * for its own sidebar/topbar brand (a lime rounded tile carrying the peak glyph, the WECARE
 * wordmark beside it), so the sign-in screen feels like the destination it opens into. It is
 * NOT AuthBrand/BrandBadge — those belong to the old login.
 *
 * Typed as a zero-argument function, not React.FC: Amplify's slot is declared
 * `Header?: () => React.JSX.Element | null`, and React.FC's `(props, context?)` signature is
 * not assignable to it (tsc: "Target signature provides too few arguments").
 */
const WsBrandHeader = (): React.JSX.Element => (
  <div className="wsauth-brand">
    <span className="wsauth-brand-tile" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 13.5 5.5 7l3 8L12 5l3.5 10 3-8L21 13.5" />
      </svg>
    </span>
    <span className="wsauth-brand-text">
      <span className="wsauth-brand-name">WECARE</span>
      <span className="wsauth-brand-sub">Workspace sign in</span>
    </span>
    <style jsx>{`
      .wsauth-brand{
        display:flex;
        align-items:center;
        gap:12px;
        padding:4px 4px 20px;
      }
      .wsauth-brand-tile{
        display:inline-flex;
        align-items:center;
        justify-content:center;
        width:40px;
        height:40px;
        flex:0 0 auto;
        border-radius:var(--radius-lg,12px);
        background:var(--lime,#d1f470);
        color:var(--accent,#1a3a2a);
      }
      .wsauth-brand-text{
        display:flex;
        flex-direction:column;
        gap:2px;
        min-width:0;
      }
      .wsauth-brand-name{
        font-weight:700;
        font-size:18px;
        letter-spacing:-0.3px;
        line-height:1.1;
        color:var(--accent,#1a3a2a);
      }
      .wsauth-brand-sub{
        font-size:13px;
        font-weight:500;
        line-height:1.2;
        color:var(--text-muted,#6b7280);
      }
    `}</style>
  </div>
);

/**
 * wsAuthTheme — a FRESH Amplify UI Theme authored for /ws. Not copied from AuthShell's
 * authTheme; the values are re-derived straight from the /ws tokens so the card reads as part
 * of the new workspace.
 *
 *   - primary button: lime fill (--lime), forest-green type (--accent) — the /ws action idiom.
 *   - fields: 1px hairline (--border #e5e7eb) at rest; lime-tinted ring + green border on focus,
 *     matching tokens.css --focus-ring / --control-border-focus. Radius 12px (--radius-lg).
 *   - radii/space/font tuned to the /ws scale (Inter, 16px base to avoid iOS input zoom).
 *
 * The router (the card itself) is deliberately left plain here and skinned by the global
 * styled-jsx below, which is scoped under .wsauth-shell so it can never leak onto /workspace.
 */
const wsAuthTheme: Theme = {
  name: 'ws-auth-theme',
  tokens: {
    colors: {
      brand: {
        primary: {
          10: { value: '#f3f7ec' },
          20: { value: '#e7f3c4' },
          40: { value: '#d1f470' },
          60: { value: '#d1f470' },
          80: { value: '#1a3a2a' },
          90: { value: '#0f2a1d' },
          100: { value: '#0a1f15' },
        },
      },
      font: {
        interactive: { value: '#1a3a2a' },
      },
      background: {
        primary: { value: '#ffffff' },
        secondary: { value: '#f9fafb' },
      },
    },
    components: {
      authenticator: {
        router: {
          borderWidth: { value: '0' },
          boxShadow: { value: 'none' },
        },
      },
      button: {
        primary: {
          backgroundColor: { value: '#d1f470' },
          color: { value: '#1a3a2a' },
          _hover: { backgroundColor: { value: '#c5e866' } },
          _focus: { backgroundColor: { value: '#c5e866' } },
          _active: { backgroundColor: { value: '#b7dd4a' } },
        },
        link: {
          color: { value: '#1a3a2a' },
          _hover: { color: { value: '#0f2a1d' }, backgroundColor: { value: 'transparent' } },
        },
      },
      fieldcontrol: {
        borderRadius: { value: '12px' },
        borderColor: { value: '#e5e7eb' },
        fontSize: { value: '16px' },
        _focus: {
          borderColor: { value: '#1a3a2a' },
          boxShadow: { value: '0 0 0 3px rgba(209, 244, 112, 0.35)' },
        },
      },
    },
    radii: {
      small: { value: '8px' },
      medium: { value: '12px' },
      large: { value: '16px' },
    },
    space: {
      small: { value: '0.75rem' },
      medium: { value: '1rem' },
      large: { value: '1.5rem' },
    },
    fontSizes: {
      small: { value: '0.875rem' },
      medium: { value: '1rem' },
      large: { value: '1.125rem' },
    },
    fonts: {
      default: {
        variable: { value: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
        static: { value: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
      },
    },
  },
};

/**
 * WsAuthGate — the fresh /ws chrome around the sign-in card.
 *
 * Mobile-first, authored new. A single centred column on a tinted surface: a lime hairline
 * banner at the top of the card, the brand header, then the Amplify form. No public Header /
 * Footer / PublicShare / SupportWidget — this is the workspace's own door, not a marketing
 * page, which also keeps it visually distinct from the old AuthGate on purpose.
 *
 * Once authenticated it returns children directly; the /ws page mounts its own WsShell.
 */
const WsAuthGate: React.FC<{ children: React.ReactNode }> = ( { children } ) => {
  const { authStatus } = useAuthenticator( ( ctx ) => [ ctx.authStatus ] );
  if ( authStatus === 'authenticated' ) return <>{ children }</>;

  return (
    <div className="wsauth-shell">
      <div className="wsauth-centre">
        <div className="wsauth-card">
          { children }
        </div>
        <p className="wsauth-note">Staff access only. Use your WECARE workspace credentials.</p>
      </div>

      <style jsx>{`
        .wsauth-shell{
          min-height:100vh;
          min-height:100dvh;
          display:flex;
          align-items:center;
          justify-content:center;
          box-sizing:border-box;
          /* phone-first gutters + safe-area insets; floors to 16px on a non-notch device */
          padding:
            max(24px,env(safe-area-inset-top,0px))
            max(16px,env(safe-area-inset-right,0px))
            max(24px,env(safe-area-inset-bottom,0px))
            max(16px,env(safe-area-inset-left,0px));
          background:
            radial-gradient(130% 90% at 50% 0%, var(--lime-tint,rgba(209,244,112,0.22)) 0%, transparent 60%),
            var(--bg-secondary,#f9fafb);
          font-family:var(--font-sans,'Inter',system-ui,sans-serif);
          color:var(--text,#1a1a1a);
        }
        .wsauth-centre{
          width:100%;
          max-width:420px;
          display:flex;
          flex-direction:column;
          align-items:stretch;
          gap:16px;
        }
        .wsauth-card{
          position:relative;
          background:var(--surface,#fff);
          border:1px solid var(--border,#e5e7eb);
          /* 4px lime TOP edge reads as brand without implying the fields are focused */
          border-top:4px solid var(--lime,#d1f470);
          border-radius:var(--radius-2xl,16px);
          box-shadow:var(--shadow-xl,0 8px 24px rgba(0,0,0,0.12));
          padding:24px 20px 28px;
          box-sizing:border-box;
          overflow:hidden;
        }
        .wsauth-note{
          margin:0;
          text-align:center;
          font-size:13px;
          line-height:1.4;
          color:var(--text-muted,#6b7280);
          padding:0 8px;
        }
        @media (min-width:480px){
          .wsauth-card{ padding:28px 28px 32px; }
        }
      `}</style>

      {/* GLOBAL, and deliberately: this reskins Amplify's own card internals, which live inside
          a composite component styled-jsx cannot scope into. Targeted via documented
          data-amplify-* attributes, not internal amplify-* class names, and scoped under
          .wsauth-shell so it can NEVER touch the old /workspace AuthGate. All values are the
          /ws tokens, authored fresh. */}
      <style jsx global>{`
        /* Keep the Amplify wrapper in step with document direction when RTL — same reasoning
           as AuthShell, re-stated locally so this skin is self-contained and does not depend
           on the old file's global rule being present.
           NO BACKTICKS in this comment: it is inside a styled-jsx template literal. */
        [dir='rtl'] .wsauth-shell [data-amplify-theme]{
          direction:rtl;
          unicode-bidi:isolate;
        }

        .wsauth-shell [data-amplify-router]{
          border:0;
          box-shadow:none;
          background:transparent;
        }
        .wsauth-shell [data-amplify-authenticator] [data-amplify-container]{
          width:100%;
        }
        .wsauth-shell [data-amplify-form]{
          padding:0;
        }
        /* The Authenticator's own "Sign in" heading, tuned to the /ws type scale. */
        .wsauth-shell .amplify-heading{
          font-size:20px;
          font-weight:700;
          letter-spacing:-0.3px;
          color:var(--accent,#1a3a2a);
        }
        /* Field labels + inputs. 16px input text avoids the iOS focus-zoom; 44px min height
           is the device-compat tap target. */
        .wsauth-shell .amplify-label{
          font-size:13px;
          font-weight:600;
          color:var(--text,#1a1a1a);
        }
        .wsauth-shell .amplify-input,
        .wsauth-shell .amplify-select,
        .wsauth-shell .amplify-passwordfield .amplify-input{
          font-size:16px;
          min-height:var(--tap-min,44px);
          border-radius:var(--radius-lg,12px);
          border-color:var(--border,#e5e7eb);
        }
        .wsauth-shell .amplify-input:focus,
        .wsauth-shell .amplify-select:focus{
          border-color:var(--accent,#1a3a2a);
          box-shadow:0 0 0 3px rgba(209,244,112,0.35);
        }
        /* Primary submit: lime fill, forest-green type, full-width, 44px+ tap target. */
        .wsauth-shell .amplify-button[data-variation='primary']{
          min-height:var(--tap-min,44px);
          border-radius:var(--radius-lg,12px);
          font-weight:700;
          background-color:var(--lime,#d1f470);
          color:var(--accent,#1a3a2a);
          border:0;
        }
        .wsauth-shell .amplify-button[data-variation='primary']:hover{
          background-color:var(--lime-hover,#c5e866);
        }
        /* Link/ghost buttons (Forgot password, Back to sign in). */
        .wsauth-shell .amplify-button[data-variation='link']{
          color:var(--accent,#1a3a2a);
          min-height:var(--tap-min,44px);
          font-weight:600;
        }
        .wsauth-shell .amplify-button[data-variation='link']:hover{
          color:var(--accent-hover,#0f2a1d);
          background-color:var(--lime-tint,rgba(209,244,112,0.22));
        }
        /* Visible keyboard focus on every interactive element in the card. */
        .wsauth-shell [data-amplify-router] :focus-visible{
          outline:2px solid var(--accent,#1a3a2a);
          outline-offset:2px;
        }

        /* ===== MFA chooser (the SelectMfaType challenge) =====
           Appears when the user's preferred factor is unset and Cognito returns a selection
           challenge. Each option becomes a full-row tappable card so it works on a phone.
           Fresh /ws values; scoped so it cannot touch /workspace. */
        .wsauth-shell [data-amplify-authenticator-select-mfa-type] fieldset{
          gap:10px;
        }
        .wsauth-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio{
          display:flex;
          align-items:center;
          gap:12px;
          min-height:var(--tap-min,44px);
          padding:12px 16px;
          border:1px solid var(--border,#e5e7eb);
          border-radius:var(--radius-lg,12px);
          background:var(--surface,#fff);
          cursor:pointer;
          transition:border-color .2s ease, box-shadow .2s ease;
        }
        .wsauth-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio:hover{
          border-color:var(--lime,#d1f470);
        }
        .wsauth-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio:focus-within{
          border-color:var(--accent,#1a3a2a);
          box-shadow:0 0 0 3px rgba(209,244,112,0.35);
        }
        .wsauth-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio__label{
          font-size:15px;
          font-weight:500;
          line-height:1.4;
          color:var(--text,#1a1a1a);
          cursor:pointer;
        }
        .wsauth-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio__button{
          --amplify-components-radio-button-color:#1a3a2a;
          --amplify-components-radio-button-border-color:#e5e7eb;
        }
        @media (prefers-reduced-motion:reduce){
          .wsauth-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio{
            transition:none;
          }
        }
      `}</style>
    </div>
  );
};

/**
 * The shell. Mirrors AuthShell's render-function contract exactly — it takes
 * `children: ({ signOut, user }) => ReactNode` — so src/pages/_app.tsx can swap between the
 * two by route with zero change to the inner render logic.
 */
const WsAuthShell: React.FC<{
  children: ( props: { signOut?: () => void; user?: unknown } ) => React.ReactNode;
}> = ( { children } ) => (
  <ThemeProvider theme={ wsAuthTheme }>
    <Authenticator.Provider>
      <WsAuthGate>
        <Authenticator hideSignUp={ true } components={ { Header: WsBrandHeader } }>
          { ( { signOut, user } ) => <>{ children( { signOut, user } ) }</> }
        </Authenticator>
      </WsAuthGate>
    </Authenticator.Provider>
  </ThemeProvider>
);

export default WsAuthShell;
