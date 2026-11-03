/**
 * Homepage-aligned /ws sign-in.
 *
 * The user sees the original WECARE SVG icon to the left of WECARE.DIGITAL
 * in a single eyebrow pill above Cognito's real credential form, while the
 * homepage Header, share rail and Footer retain their existing implementation.
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

/* Original WECARE SVG from the verified S3 media prefix. This small icon
   belongs inside the eyebrow, LEFT of the one-line WECARE.DIGITAL label.
   The homepage header retains its existing independent site brand lockup. */
const WECARE_SVG_URL = 'https://wecare.digital/get/o/stream/media/m/wecare-digital.svg';

/* Amplify keeps this header above the actual sign-in, recovery and MFA form. */
const WsBrandHeader = (): React.JSX.Element => (
  <div className="wsauth-eyebrow" data-wc-no-translate="true">
    <span className="wsauth-eyebrow-icon" aria-hidden="true">
      <img src={ WECARE_SVG_URL } alt="" width={ 96 } height={ 96 } decoding="async" />
    </span>
    <span className="wsauth-eyebrow-text">WECARE.DIGITAL</span>
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
