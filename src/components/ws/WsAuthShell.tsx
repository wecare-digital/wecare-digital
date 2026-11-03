/**
 * Homepage-aligned /ws sign-in.
 *
 * The user sees only the S3 WECARE.DIGITAL logo, Cognito's real credential
 * form, and the same public header, share rail and footer as the homepage.
 * No simulated workspace, marketing panel or second auth implementation.
 * When Cognito authenticates, the public chrome unmounts and the /ws page
 * continues rendering through its existing WsShell.
 */
import type React from 'react';
import '../../lib/amplifyConfig';
import { Authenticator, ThemeProvider, type Theme, useAuthenticator } from '@aws-amplify/ui-react';
import Header from '../Header';
import Footer from '../Footer';
import PublicShare from '../PublicShare';
import PublicToastProvider from '../public/PublicToastProvider';
import WsNotionTheme from './WsNotionTheme';

/* Original, verified S3 SVG. Use its public asset URL, not a re-created glyph.
   Its artwork occupies the centre of a 5000x5000 SVG viewBox. The image is
   displayed at 166px and clipped by the small logo frame around the artwork. */
const WECARE_SVG_URL = 'https://wecare.digital/get/o/stream/media/m/wecare-digital.svg';

/* The Amplify header slot is directly ABOVE the login form, and remains
   present for genuine Cognito password recovery and MFA challenges. */
const WsBrandHeader = (): React.JSX.Element => (
  <div className="wsauth-brand" data-wc-no-translate="true">
    <span className="wsauth-svg-frame" aria-hidden="true">
      <img src={ WECARE_SVG_URL } alt="" width={ 166 } height={ 166 } decoding="async" />
    </span>
    <span className="wsauth-wordmark">
      <strong>WECARE<span className="wsauth-wordmark-dot">.</span></strong>
      <strong>DIGITAL</strong>
    </span>
  </div>
);

/* Visual-only Amplify tokens; the shared /ws theme owns fields and buttons. */
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
        borderRadius: { value: '14px' },
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
      <PublicToastProvider>
        <Header />
        <div className="wsauth-site">
          <main className="wsauth-login-main" aria-label="WECARE.DIGITAL workspace sign in">
            <div className="wsauth-form">
              { children }
            </div>
          </main>
          {/* Share the public homepage, never a protected workspace URL. */}
          <div className="wsauth-public-share">
            <PublicShare url="https://wecare.digital/" title="WECARE.DIGITAL" />
          </div>
          <Footer />
        </div>
      </PublicToastProvider>
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
