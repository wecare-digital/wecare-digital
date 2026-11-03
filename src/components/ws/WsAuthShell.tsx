/**
 * /ws sign-in: a full layout, not a second authentication implementation.
 *
 * The public homepage supplies the brand lime, typography and Material 3 icons.
 * All sign-in presentation is scoped to the /ws AuthGate in WsNotionTheme.
 * Cognito configuration, Authenticator state, MFA, and signOut are unchanged.
 * The old /workspace and public routes still use their existing shells.
 */
import type React from 'react';
import Link from 'next/link';
import '../../lib/amplifyConfig';
import { Authenticator, ThemeProvider, type Theme, useAuthenticator } from '@aws-amplify/ui-react';
import { symbol, type MaterialSymbol } from '../../config/materialSymbols';
import WsNotionTheme from './WsNotionTheme';

interface ModulePreview {
  title: string;
  sub: string;
  icon: MaterialSymbol;
}

/* Decorative product navigation preview: labels only, not mock account data. */
const WORKSPACE_MODULES: readonly ModulePreview[] = [
  { title: 'Inbox', sub: 'Conversations', icon: symbol('inbox') },
  { title: 'Collect', sub: 'Invoices & Vault', icon: symbol('receipt_long') },
  { title: 'Customers', sub: 'People & history', icon: symbol('group') },
  { title: 'Commerce', sub: 'Orders & prices', icon: symbol('shopping_bag') },
];

/* The verified SVG lives in S3's public media prefix. Keep the image URL exact:
   s3://wecare-digital-get/o/stream/media/m/wecare-digital.svg
   It is a square, white-backed icon with generous viewBox margins; its frame
   crops only the whitespace and never replaces or redraws the brand artwork. */
const WECARE_SVG_URL = 'https://wecare.digital/get/o/stream/media/m/wecare-digital.svg';

/* Authenticator's real header slot stays connected throughout sign-in and MFA. */
const WsBrandHeader = (): React.JSX.Element => (
  <div className="wsauth-auth-badge">
    <span className="wsauth-symbol" aria-hidden="true">{ symbol('lock') }</span>
    <span>SECURE SIGN IN</span>
  </div>
);

/* Amplify controls authentication; the /ws theme owns the button and field visuals. */
const wsAuthTheme: Theme = {
  name: 'ws-homepage-lime-auth',
  tokens: {
    colors: {
      brand: {
        primary: {
          10: { value: '#faffec' },
          20: { value: '#f0fad5' },
          40: { value: '#dff6a1' },
          60: { value: '#d1f470' },
          80: { value: '#1a3a2a' },
          90: { value: '#0f2a1d' },
          100: { value: '#0a1f15' },
        },
      },
      font: { interactive: { value: '#1a3a2a' } },
      background: {
        primary: { value: '#ffffff' },
        secondary: { value: '#f5f6f3' },
      },
    },
    components: {
      authenticator: {
        router: { borderWidth: { value: '0' }, boxShadow: { value: 'none' } },
      },
      fieldcontrol: {
        borderWidth: { value: '0px' },
        borderColor: { value: 'transparent' },
        borderRadius: { value: '12px' },
        fontSize: { value: '16px' },
      },
    },
    fonts: {
      default: {
        variable: { value: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
        static: { value: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
      },
    },
  },
};

const WsAuthGate: React.FC<{ children: React.ReactNode }> = ( { children } ) => {
  const { authStatus } = useAuthenticator( ( ctx ) => [ ctx.authStatus ] );
  if ( authStatus === 'authenticated' ) return <>{ children }</>;

  return (
    <div className="wsauth-shell ws-notion-auth">
      <WsNotionTheme />
      <div className="wsauth-layout">
        <aside className="wsauth-story" aria-label="Workspace introduction">
          <div className="wsauth-story-inner">
            <Link className="wsauth-public-home" href="/" aria-label="WECARE.DIGITAL homepage">
              <span className="wsauth-brandlockup" data-wc-no-translate="true">
                <span className="wsauth-svg-frame" aria-hidden="true">
                  <img src={ WECARE_SVG_URL } alt="" width={ 5000 } height={ 5000 } decoding="async" />
                </span>
                <span className="wsauth-wordmark">
                  <strong>WECARE<span className="wsauth-wordmark-dot">.</span></strong>
                  <strong>DIGITAL</strong>
                </span>
              </span>
            </Link>

            <div className="wsauth-story-main">
              <span className="wsauth-story-kicker">THE WECARE WORKSPACE</span>
              <h1>Less switching.<br />More <em>doing.</em></h1>
              <p>
                Conversations, invoices, customers and orders —
                brought together in one focused workspace.
              </p>

              <div className="wsauth-workbook" aria-hidden="true">
                <div className="wsauth-workbook-head">
                  <span className="wsauth-workbook-window">
                    <span /><span /><span />
                  </span>
                  <span>YOUR WORKSPACE</span>
                  <span className="wsauth-symbol">{ symbol('arrow_forward') }</span>
                </div>
                <div className="wsauth-workbook-grid">
                  { WORKSPACE_MODULES.map( item => (
                    <div className="wsauth-module" key={ item.title }>
                      <span className="wsauth-module-icon wsauth-symbol">{ item.icon }</span>
                      <span className="wsauth-module-copy">
                        <strong>{ item.title }</strong>
                        <small>{ item.sub }</small>
                      </span>
                      <span className="wsauth-module-chevron wsauth-symbol">{ symbol('chevron_right') }</span>
                    </div>
                  ) ) }
                </div>
              </div>
            </div>

            <div className="wsauth-story-foot">
              Built for the team behind WECARE.DIGITAL
            </div>
          </div>
        </aside>

        <main className="wsauth-signin-side">
          <div className="wsauth-form-frame">
            <div className="wsauth-form-header">
              <p className="wsauth-form-kicker">WECARE.DIGITAL</p>
              <h2>Welcome back.</h2>
              <p>Enter your team credentials to continue.</p>
            </div>

            <div className="wsauth-card">{ children }</div>

            <footer className="wsauth-form-footer">
              <p>Access is restricted to authorized staff.</p>
              <nav aria-label="Site policies">
                <Link href="/terms/">Terms of Service</Link>
                <span aria-hidden="true">·</span>
                <Link href="/privacy/">Privacy Policy</Link>
              </nav>
            </footer>
          </div>

          <Link className="wsauth-backsite" href="/">
            Back to wecare.digital
            <span className="wsauth-symbol" aria-hidden="true">{ symbol('arrow_forward') }</span>
          </Link>
        </main>
      </div>
    </div>
  );
};

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
