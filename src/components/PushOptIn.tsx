/**
 * PushOptIn - "Notifications on this device", inside the Workspace profile menu.
 *
 * WHY IT EXISTS. Launch no longer shows the OS notification prompt (src/lib/capacitor.ts), because
 * .kiro/steering/00-common.md requires a permission prompt to follow a clear user action that has
 * explained why first, and never to appear on load. This control is that action. It lives in the
 * Profile menu because Layout.tsx reserves that menu for personal and session controls, and
 * notifications on one handset are exactly that.
 *
 * EVERY STATE IS HANDLED, and none of them is a dead end:
 *   web / unsupported  renders nothing - there is no web push here, so offering it would lead
 *                      nowhere;
 *   prompt             one sentence on what arrives, then one button that asks the device;
 *   granted            says so;
 *   denied             says how to change it in device settings, and never asks again (iOS will
 *                      not show the prompt a second time, and re-prompting is forbidden anyway).
 *
 * Registration needs a Workspace session - POST /push/register runs through authFetch - which is
 * why this is mounted only inside the authenticated shell, never on the public site.
 */
import React, { useEffect, useState } from 'react';
import { pushPermissionState, requestPushPermission, type PushPermission } from '../lib/capacitor';
import { registerPushToken } from '../lib/pushRegistration';

type ViewState = PushPermission | 'checking' | 'asking';

const PushOptIn: React.FC = () => {
  const [ state, setState ] = useState<ViewState>( 'checking' );

  // Read-only: checkPermissions() never shows a prompt.
  useEffect( () => {
    let live = true;
    const read = async () => {
      const next = await pushPermissionState();
      if ( live ) setState( next );
    };
    void read();
    return () => { live = false; };
  }, [] );

  if ( state === 'checking' || state === 'unsupported' ) return null;

  const turnOn = async () => {
    setState( 'asking' );
    const next = await requestPushPermission( ( token, platform ) => {
      void registerPushToken( token, platform );
    } );
    setState( next );
  };

  return (
    <div className="push-optin" role="group" aria-labelledby="push-optin-title">
      <strong id="push-optin-title">Notifications on this device</strong>
      { state === 'granted' && (
        <p role="status">On. Notifications your team sends from Workspace arrive on this device.</p>
      ) }
      { ( state === 'prompt' || state === 'asking' ) && (
        <>
          <p>
            Get the notifications your team sends from Workspace on this device. Your device asks
            you to confirm, and you can turn them off in its settings at any time.
          </p>
          <button type="button" onClick={ () => void turnOn() } disabled={ state === 'asking' }>
            { state === 'asking' ? 'Waiting for your device…' : 'Turn on notifications' }
          </button>
        </>
      ) }
      { state === 'denied' && (
        <p role="status">
          Off for this app. To turn them on, open your device Settings, choose this app and allow
          notifications.
        </p>
      ) }
      <style jsx>{`
        .push-optin{display:flex;flex-direction:column;gap:8px;padding:12px 16px;border-top:1px solid var(--border)}
        .push-optin strong{font-size:var(--text-sm);color:var(--text)}
        .push-optin p{margin:0;font-size:var(--text-xs);line-height:1.45;color:var(--text-muted)}
        /* The shared 44px tap floor; the menu's own Sign out row is 48px. */
        .push-optin button{
          min-height:var(--tap-min);border:1px solid var(--border);border-radius:10px;
          background:var(--bg-secondary);color:var(--text);font:inherit;font-weight:650;
          padding:10px 14px;cursor:pointer;
        }
        .push-optin button:hover{border-color:var(--lime)}
        .push-optin button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
        .push-optin button:disabled{cursor:progress;opacity:.7}
      `}</style>
    </div>
  );
};

export default PushOptIn;
