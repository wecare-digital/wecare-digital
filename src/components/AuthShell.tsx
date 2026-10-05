/**
 * The authenticated shell: Amplify UI's ThemeProvider, the Authenticator, and the public
 * chrome that wraps the sign-in card.
 *
 * WHY IT IS A SEPARATE MODULE, AND WHY `_app.tsx` LOADS IT WITH next/dynamic
 * -------------------------------------------------------------------------
 * `@aws-amplify/ui-react` builds to a 450 kB client chunk. While `_app.tsx` imported it at
 * module scope, that chunk was in the shared bundle, so it was downloaded and parsed by every
 * visitor to every PUBLIC page - 41% of the home page's 1,098 kB of JavaScript, for a sign-in
 * card a marketing page never renders. Measured in `out/index.html` before the split:
 * `2crp25xr6p9wh.js`, 450.7 kB, containing `amplify-authenticator`, `amplify-field`,
 * `amplify-radio` and the rest of the component library.
 *
 * `_app.tsx` has always had exactly two branches - a public one and this one - so the
 * dependency was never shared in any real sense; it was shared only because an import at the
 * top of a file is unconditional. Moving the branch into its own module makes the bundler's
 * split match the runtime's.
 *
 * SSR IS OFF, AND IT HAS TO BE. This said the opposite until 2026-10-05 - "SSR is left on,
 * the site is a static export so SSR means rendered to HTML at build time" - and the
 * consequence was that every /workspace/* page rendered BLANK in a browser. A Turbopack
 * pages-router build emits no react-loadable manifest, so `__NEXT_DATA__` carries no
 * `dynamicIds`; Next awaits those before hydrating, finds none, and hydrates while this
 * chunk is still loading. The client's first render is then null against a server tree full
 * of Amplify markup, hydration fails, and React leaves the build-time copy in the document
 * and appends a live one below it - two trees in `#__next`, the working one pushed past the
 * fold. `ssr: false` makes both first renders null, so they agree.
 * The full measurement, and why the HTML those pages lose is worth nothing, is recorded at
 * the `dynamic()` call in `src/pages/_app.tsx`. The chunk stays split either way.
 *
 * THE STYLESHEET TRAVELS SEPARATELY, and it has to. Next refuses a global CSS import from any
 * file but the custom App, so `@aws-amplify/ui-react/styles.css` cannot be imported here.
 * `scripts/generate-vendor-css.js` copies it to `public/vendor/amplify-ui.css` and `_app.tsx`
 * links it from the same branch that renders this component.
 *
 * WHAT MOVED HERE VERBATIM: `authTheme` and `AuthGate`, including AuthGate's styled-jsx. The
 * reasoning in those comments is unchanged and is not re-litigated by the move - read them
 * where they are. `src/test/PublicWidgets.test.tsx` sums the support-widget mounts across
 * this file AND `_app.tsx` for that reason: the invariant it protects is "three places a
 * visitor can land", not "three occurrences in one file", and AuthGate is one of the three.
 * That sentence deliberately does not write the JSX tag - the test counts the tag, so naming
 * it in prose here would inflate the count, which is exactly how it first failed.
 */

import type React from 'react';
import { Authenticator, ThemeProvider, type Theme, useAuthenticator } from '@aws-amplify/ui-react';
import AuthBrandHeader from './AuthBrand';
import Header from './Header';
import Footer from './Footer';
import SupportWidget from './SupportWidget';

// Custom Amplify UI Theme - Lime + Dark Green matching site design
const authTheme: Theme = {
  name: 'stack-crm-theme',
  tokens: {
    colors: {
      brand: {
        primary: {
          10: { value: '#f9fafb' },
          20: { value: '#f3f4f6' },
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
          boxShadow: { value: '0 4px 24px rgba(0, 0, 0, 0.08)' },
        },
      },
      button: {
        primary: {
          backgroundColor: { value: '#d1f470' },
          color: { value: '#1a3a2a' },
          _hover: {
            backgroundColor: { value: '#c5e866' },
          },
          _active: {
            backgroundColor: { value: '#b8dc5a' },
          },
        },
        link: {
          color: { value: '#1a3a2a' },
          _hover: {
            color: { value: '#0f2a1d' },
            backgroundColor: { value: 'transparent' },
          },
        },
      },
      fieldcontrol: {
        borderRadius: { value: '13px' },
        // #e5e7eb at rest, NOT lime. The design contract's hairline rule is that
        // the colour is always #e5e7eb and lime marks an interactive state; a lime
        // resting border made every idle input on the sign-in card read as focused,
        // and spent the page's one accent on three inert outlines. Lime returns
        // below, in the focus ring, which is where the contract puts it.
        borderColor: { value: '#e5e7eb' },
        _focus: {
          borderColor: { value: '#1a3a2a' },
          boxShadow: { value: '0 0 0 3px rgba(209, 244, 112, 0.3)' },
        },
      },
      // INERT while the Authenticator is mounted with hideSignUp - with sign-up
      // hidden, Amplify renders no tab list at all, so nothing below is visible on
      // [retired public path] today (measured in a browser: zero elements match [role="tab"]).
      // Kept and corrected rather than deleted so that flipping hideSignUp cannot
      // ship off-palette tabs: the idle colour was #6b7280, which is the legacy
      // --color-muted from Pages.css and not a palette value at all.
      //
      // The active state is the palette's own tab treatment - #d1f470 fill with
      // #1a3a2a type, the pair used by .pp-tab.active, .msg.sent and BrandBadge -
      // rather than the underline-only version this had before.
      tabs: {
        item: {
          color: { value: 'rgba(0, 0, 0, 0.54)' },
          _active: {
            color: { value: '#1a3a2a' },
            backgroundColor: { value: '#d1f470' },
            borderColor: { value: '#d1f470' },
          },
          _hover: {
            color: { value: '#1a3a2a' },
          },
        },
      },
    },
    radii: {
      small: { value: '10px' },
      medium: { value: '13px' },
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
    // Amplify ships its own stack - 'InterVariable','Inter var','Inter',… - which
    // resolves to the same face the rest of the site uses, so this was never a
    // visible bug. It is pinned to the site stack anyway so the sign-in card cannot
    // drift onto a different font than .page declares: InterVariable is a
    // *different file* from the Inter that _app loads from Google Fonts at
    // 400;500;600;700;800, and if a variable build ever resolves locally on a
    // visitor's machine the card would render in it while every other surface did
    // not. Same list, same order as grahak-os/index.tsx .page.
    fonts: {
      default: {
        variable: { value: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
        static: { value: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
      },
    },
  },
};

/**
 * AuthGate — the public chrome around the sign-in card.
 *
 * This is the THIRD place chrome is mounted, and it is easy to forget because it is not
 * a route: any visitor who opens a staff URL without a session lands here, including
 * every mistyped path that does not match the allowlist. So it is a page the public
 * genuinely sees, and it gets the same three pieces as a public page - Header, Footer and
 * SupportWidget.
 *
 * SupportWidget was missing here until now, and the gap mattered in exactly the situation
 * this screen exists for: someone who cannot get in had no way to reach us from the screen
 * telling them they cannot get in. It is mounted below, outside .ag-shell, because the
 * widget is position:fixed and does not belong in a flex column.
 *
 * Once authenticated this returns children directly. Header and Footer are deliberately
 * NOT carried into the dashboard: Layout.tsx has its own top bar and sidebar and no footer
 * at all, and adding a second fixed header would collide with both.
 */
const AuthGate: React.FC<{ children: React.ReactNode }> = ( { children } ) => {
  const { authStatus } = useAuthenticator( ( ctx ) => [ ctx.authStatus ] );
  const isAuthed = authStatus === 'authenticated';

  if ( isAuthed ) return <>{ children }</>;

  return (
    <>
      <Header />
      <div className="ag-shell">
        <div className="ag-centre">
          { children }
        </div>
        <Footer />
      </div>
      <SupportWidget />
      <style jsx>{`
        /* 108px, not the flat 96px this used to inline.
           The public header is position:fixed and 108px tall, dropping to 96px only
           below 768px - so a single 96px value pulled the whole centred block 12px
           up UNDER the header on every desktop, which is exactly where the new brand
           badge above the form sits. Matched to both of the header's heights rather
           than to one of them.
           Moved out of inline styles for that reason: a style attribute cannot carry
           a media query, so the two-height fix is not expressible inline. */
        .ag-shell{display:flex;flex-direction:column;min-height:100vh;padding-top:108px}
        .ag-centre{flex:1;display:flex;align-items:center;justify-content:center}
        @media(max-width:767px){.ag-shell{padding-top:96px}}
      `}</style>
      {/* GLOBAL, deliberately: this styles the Amplify Authenticator's own card,
          which is rendered inside a composite component that styled-jsx cannot
          scope into. Targeted via data-amplify-router, a documented Amplify data
          attribute, rather than the amplify-* class names, which are internal.
          Scoped under .ag-shell so it can only ever apply to the unauthenticated
          sign-in chrome and not to anything in the dashboard.

          A 4px lime TOP EDGE, not a lime outline on all four sides. The owner asked
          for a lime border, and a full lime outline is the one thing that should not
          go here: the contract reserves lime for interactive state and #e5e7eb for
          static edges, and a lime ring around a resting card is precisely what made
          the input fields read as permanently focused - the defect fixed one commit
          ago. A single heavy top edge reads as brand, cannot be mistaken for focus,
          and still uses full-strength #d1f470, which is correct here because this
          card IS one of our own surfaces. The other three sides take the static
          hairline. */}
      <style jsx global>{`
        /* AMPLIFY'S ThemeProvider HARDCODES dir="ltr" ON ITS WRAPPER, AND IT MADE THE
           DASHBOARD HALF-MIRROR.
           The rendered element is <div data-amplify-theme="stack-crm-theme" dir="ltr">, and
           everything on an authenticated route sits inside it. So when a visitor picked
           Arabic, <html dir="rtl"> set the document direction and this wrapper immediately
           overrode it for the entire subtree: text and flex axes stayed left-to-right, while
           the [dir='rtl'] rules in Header.tsx and SupportWidget.tsx still matched, because
           those select on the html attribute rather than on computed direction. The nav panel
           then anchored to its rtl edge inside an unmirrored header and landed at
           left:-504px - off screen on 105 of 125 routes, measured by rtlcheck.js. Public
           routes were unaffected: they render no Amplify wrapper at all.
           An author declaration beats the dir attribute's presentational hint, so one rule
           puts the subtree back in step with the document. Fixing it here rather than by
           passing a direction prop to ThemeProvider keeps it out of React state: direction
           changes at runtime when the language changes, and a prop would need the document
           attribute mirrored into state and kept in sync.
           unicode-bidi is set with it. The dir attribute implies unicode-bidi:isolate in the
           UA stylesheet, and overriding direction alone leaves the isolation behaving as
           though the wrapper were still a left-to-right island.
           NO BACKTICKS IN THIS COMMENT - it is inside a styled-jsx template literal and one
           closes it, failing the build far below with an unrelated-looking parse error. */
        [dir='rtl'] [data-amplify-theme]{
          direction:rtl;
          unicode-bidi:isolate;
        }

        .ag-shell [data-amplify-router]{
          border:1px solid #e5e7eb;
          border-top:4px solid #d1f470;
          border-radius:16px;
          overflow:hidden;
        }

        /* ===== The MFA chooser =====
           Appears because the user's preferred factor is unset, so Cognito
           returns a selection challenge. Amplify renders it as a radio group
           inside [data-amplify-authenticator-select-mfa-type] - a documented
           data attribute, unlike the amplify-* class names, which are internal
           and would be a private API to depend on.

           Unstyled, the options are bare radios with no hit area, which on a
           phone means three small circles and no obvious way to pick. Each one
           becomes a card the whole row of which is tappable.

           Values are the public contract's: 2px #e5e7eb because each row HAS a
           hover, swapping to lime; rgba(0,0,0,.898) label; #1a3a2a on the
           checked mark, which is the palette's active-state green. */
        .ag-shell [data-amplify-authenticator-select-mfa-type] fieldset{
          gap:10px;
        }
        .ag-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio{
          display:flex;
          align-items:center;
          gap:12px;
          padding:14px 18px;
          border:2px solid #e5e7eb;
          border-radius:13px;
          background:#fff;
          cursor:pointer;
          transition:all .25s;
        }
        .ag-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio:hover{
          border-color:#d1f470;
        }
        /* :focus-within, not :focus - the focus lands on the input inside the
           label, so a rule on the row itself would never match. */
        .ag-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio:focus-within{
          border-color:#d1f470;
          box-shadow:0 0 0 3px rgba(26,58,42,.3);
        }
        .ag-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio__label{
          font-size:17px;
          font-weight:500;
          line-height:1.4;
          letter-spacing:-.125px;
          color:rgba(0,0,0,.898);
          cursor:pointer;
        }
        .ag-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio__button{
          --amplify-components-radio-button-color:#1a3a2a;
          --amplify-components-radio-button-border-color:#e5e7eb;
        }
        @media(prefers-reduced-motion:reduce){
          .ag-shell [data-amplify-authenticator-select-mfa-type] .amplify-radio{
            transition:none;
          }
        }
      `}</style>
    </>
  );
};

/**
 * The shell itself. Takes a render function rather than plain children so that
 * `Component`/`pageProps` and the dashboard's own widget mounts stay in `_app.tsx`, where
 * every other route decision is made - this module owns the Amplify dependency, not the
 * routing.
 */
const AuthShell: React.FC<{
  children: ( props: { signOut?: () => void; user?: unknown } ) => React.ReactNode;
}> = ( { children } ) => (
  <ThemeProvider theme={ authTheme }>
    <Authenticator.Provider>
      <AuthGate>
        <Authenticator hideSignUp={ true } components={ { Header: AuthBrandHeader } }>
          { ( { signOut, user } ) => <>{ children( { signOut, user } ) }</> }
        </Authenticator>
      </AuthGate>
    </Authenticator.Provider>
  </ThemeProvider>
);

export default AuthShell;
