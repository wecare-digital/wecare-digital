/**
 * Homepage-aligned /ws sign-in.
 *
 * The user sees a WECARE.DIGITAL eyebrow and Cognito's real credential
 * form, within the same public header, share rail and footer as the homepage.
 * The official brand logo already appears in the shared header, never twice.
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

/* The homepage Header already contains the brand logo. Keep only the
   requested text eyebrow above the real Cognito form (including MFA/recovery). */
const WsBrandHeader = (): React.JSX.Element => (
  <div className="wsauth-eyebrow" data-wc-no-translate="true">WECARE.DIGITAL</div>
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
