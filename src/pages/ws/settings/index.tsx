/**
 * /ws/settings — signed-in identity + a prominent Sign out, plus any lightweight, already-available
 * device control (FEAT-004). No backend settings are invented here.
 *
 * Auth is automatic via AuthShell (see src/pages/_app.tsx); this page receives { signOut, user }.
 * Sign out is wired to the `signOut` prop, which already calls Cognito signOut then
 * router.push('/'). The one extra surface is PushOptIn — a self-contained control that registers a
 * device push token through an existing authenticated endpoint and renders NOTHING on web /
 * unsupported platforms, so it never shows an empty or dead section in a browser.
 */
import React from 'react';
import SEO from '../../../components/SEO';
import WsShell from '../../../components/ws/WsShell';
import PushOptIn from '../../../components/PushOptIn';

interface PageProps { signOut?: () => void; user?: any; }

const WsSettings: React.FC<PageProps> = ( { signOut, user } ) => {
  const loginId = user?.signInDetails?.loginId || user?.email || '';

  return (
    <>
      <SEO title="Settings" description="WECARE workspace settings." noindex />
      <WsShell active="settings" user={ user } signOut={ signOut }>
        <section className="ws-page">
          <h1 className="ws-page-title">Settings</h1>

          <div className="ws-settings-card" data-wc-no-translate="true">
            <span className="ws-settings-label">Signed in as</span>
            <span className="ws-settings-id">{ loginId || 'Account' }</span>
          </div>

          {/* Self-contained: renders nothing on web/unsupported, so no empty section appears. */}
          <div className="ws-settings-push">
            <PushOptIn />
          </div>

          <button type="button" className="ws-settings-signout" onClick={ () => signOut?.() }>
            Sign out
          </button>
          <p className="ws-page-note">More account controls are coming soon.</p>
        </section>

        <style jsx>{`
          .ws-page{ width:100%; min-width:0; }
          .ws-page-title{
            margin:0 0 16px;
            font-size:26px;
            font-weight:700;
            letter-spacing:-0.5px;
            color:var(--text,#1a1a1a);
          }
          .ws-settings-card{
            display:flex;
            flex-direction:column;
            gap:4px;
            padding:16px;
            margin-bottom:16px;
            border:1px solid var(--border,#e5e7eb);
            border-radius:var(--radius-xl,14px);
            background:var(--surface,#fff);
          }
          .ws-settings-label{
            font-size:12px;
            font-weight:700;
            text-transform:uppercase;
            letter-spacing:0.4px;
            color:var(--text-muted,#6b7280);
          }
          .ws-settings-id{
            font-size:16px;
            color:var(--text,#1a1a1a);
            overflow-wrap:anywhere;
          }
          /* PushOptIn draws its own top border; give it the card frame so it reads as a setting. */
          .ws-settings-push{
            margin-bottom:16px;
            border:1px solid var(--border,#e5e7eb);
            border-radius:var(--radius-xl,14px);
            background:var(--surface,#fff);
            overflow:hidden;
          }
          .ws-settings-push :global(.push-optin){ border-top:0; }
          .ws-settings-signout{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:var(--tap-min,44px);
            padding:12px 20px;
            border:1px solid var(--border,#e5e7eb);
            border-radius:var(--radius-lg,12px);
            background:var(--surface,#fff);
            color:var(--text,#1a1a1a);
            font-size:15px;
            font-weight:700;
            cursor:pointer;
          }
          .ws-settings-signout:hover{
            border-color:var(--danger,#dc2626);
            color:var(--danger,#dc2626);
          }
          .ws-settings-signout:focus-visible{
            outline:2px solid var(--accent,#1a3a2a);
            outline-offset:2px;
          }
          .ws-page-note{
            margin:16px 0 0;
            font-size:15px;
            color:var(--text-muted,#6b7280);
          }
        `}</style>
      </WsShell>
    </>
  );
};

export default WsSettings;
