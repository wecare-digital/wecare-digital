/**
 * Push Notifications Page - WECARE.DIGITAL
 * Send push notifications to iOS (APNs) and Android (FCM) devices.
 * Manage device tokens, send targeted/broadcast pushes, view delivery logs.
 */
import React, { useState, useEffect } from 'react';
import Layout from '../../../components/Layout';
import PageShell, { ShellTab } from '../../../components/PageShell';
import Button from '../../../components/ui/Button';
import { API_BASE } from '../../../config/constants';
import { authFetch } from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

/* ── Icons ── */
const BellIcon = ( { size = 18 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
);
const AppleIcon = ( { size = 16 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2C9.5 2 8 3.5 8 3.5S6.5 2 4 4c-2 2-1 5.5 1 8s4 5 5 6c.5.5 1.5 1 2 1s1.5-.5 2-1c1-1 3-3.5 5-6s3-6 1-8c-2.5-2-4-.5-4-.5S14.5 2 12 2z" />
  </svg>
);
const AndroidIcon = ( { size = 16 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="5 3 19 12 5 21 5 3" />
  </svg>
);
const SendIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);
const RefreshIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
  </svg>
);
const TrashIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
);

interface DeviceToken {
  deviceId: string;
  userId: string;
  platform: 'ios' | 'android';
  registeredAt: string;
}

interface PushConfiguration {
  android: boolean;
  ios: boolean;
}

interface PushLog {
  id: string;
  title: string;
  body: string;
  platform: 'ios' | 'android' | 'all';
  sentAt: string;
  sent: number;
  failed: number;
  targetType: 'broadcast' | 'user' | 'device';
}

const TABS: ShellTab[] = [
  { id: 'send', label: 'Send Push' },
  { id: 'devices', label: 'Devices' },
  { id: 'logs', label: 'Delivery Logs' },
  { id: 'config', label: 'Configuration' },
];

const PushPage: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  /* ── State ── */
  const [ devices, setDevices ] = useState<DeviceToken[]>( [] );
  const [ logs, setLogs ] = useState<PushLog[]>( [
    { id: 'p1', title: 'New message received', body: 'You have a new WhatsApp message from +91 98xxx', platform: 'all', sentAt: '2026-03-09T08:30:00Z', sent: 142, failed: 3, targetType: 'broadcast' },
    { id: 'p2', title: 'Payment received', body: 'Payment of Rs 2,500 received from Rahul S.', platform: 'ios', sentAt: '2026-03-09T07:15:00Z', sent: 1, failed: 0, targetType: 'user' },
    { id: 'p3', title: 'Campaign complete', body: 'Your bulk WhatsApp campaign has been delivered', platform: 'android', sentAt: '2026-03-08T22:00:00Z', sent: 89, failed: 5, targetType: 'broadcast' },
  ] );
  const [ loading, setLoading ] = useState( false );
  const [ sending, setSending ] = useState( false );

  // Send form
  const [ pushTitle, setPushTitle ] = useState( '' );
  const [ pushBody, setPushBody ] = useState( '' );
  const [ pushPlatform, setPushPlatform ] = useState<'all' | 'ios' | 'android'>( 'all' );
  const [ pushTarget, setPushTarget ] = useState<'broadcast' | 'user'>( 'broadcast' );
  const [ pushUserId, setPushUserId ] = useState( '' );
  const [ pushData, setPushData ] = useState( '' );

  // Server-side delivery configuration status (credentials never enter browser state)
  const [ pushConfiguration, setPushConfiguration ] = useState<PushConfiguration>( { android: false, ios: false } );

  const loadDevices = async () => {
    setLoading( true );
    try
    {
      const res = await authFetch( `${API_BASE}/push/devices` );
      if ( res.ok )
      {
        const data = await res.json();
        setDevices( data.devices || [] );
        setPushConfiguration( data.configured || { android: false, ios: false } );
      }
    } catch { /* API not deployed yet */ }
    setLoading( false );
  };

  useEffect( () => { loadDevices(); }, [] );

  const handleSendPush = async () => {
    if ( !pushTitle.trim() || !pushBody.trim() ) return;
    setSending( true );
    try
    {
      const payload: any = { title: pushTitle, body: pushBody };
      if ( pushTarget === 'user' && pushUserId ) payload.userId = pushUserId;
      if ( pushData.trim() )
      {
        try { payload.data = JSON.parse( pushData ); } catch { payload.data = { raw: pushData }; }
      }

      const endpoints = pushPlatform === 'all'
        ? devices
        : devices.filter( d => d.platform === pushPlatform );

      const response = await authFetch( `${API_BASE}/push/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( pushTarget === 'user' && pushUserId
          ? payload
          : { ...payload, broadcast: true, platform: pushPlatform } ),
      } );
      if ( !response.ok )
      {
        const error = await response.json().catch( () => ( {} ) );
        throw new Error( error.error || `Push send failed (${response.status})` );
      }
      const result = await response.json();

      // Add to local logs
      setLogs( prev => [ {
        id: `p${Date.now()}`,
        title: pushTitle,
        body: pushBody,
        platform: pushPlatform,
        sentAt: new Date().toISOString(),
        sent: result.sent ?? endpoints.length,
        failed: result.failed ?? 0,
        targetType: pushTarget === 'user' ? 'user' : 'broadcast',
      }, ...prev ] );

      setPushTitle( '' );
      setPushBody( '' );
      setPushData( '' );
      setPushUserId( '' );
    } catch ( err )
    {
      console.error( 'Push send error:', err );
    }
    setSending( false );
  };

  const iosCount = devices.filter( d => d.platform === 'ios' ).length;
  const androidCount = devices.filter( d => d.platform === 'android' ).length;

  const shellContent = (
    <PageShell title="Push Notifications" subtitle="Apple APNs + Android FCM — Send to iOS and Android devices" tabs={ TABS } defaultTab="send">
      { ( activeTab ) => (
        <>
          {/* ═══ SEND TAB ═══ */ }
          { activeTab === 'send' && (
            <div className="push-send">
              {/* Stats row */ }
              <div className="push-stats">
                <div className="push-stat-card">
                  <AppleIcon size={ 20 } />
                  <div><div className="push-stat-val">{ iosCount }</div><div className="push-stat-lbl">iOS Devices</div></div>
                </div>
                <div className="push-stat-card">
                  <AndroidIcon size={ 20 } />
                  <div><div className="push-stat-val">{ androidCount }</div><div className="push-stat-lbl">Android Devices</div></div>
                </div>
                <div className="push-stat-card">
                  <BellIcon size={ 20 } />
                  <div><div className="push-stat-val">{ logs.length }</div><div className="push-stat-lbl">Sent Today</div></div>
                </div>
              </div>

              <div className="push-form-card">
                <h3 className="push-form-heading">Compose Push Notification</h3>

                {/* Platform selector */ }
                <div className="push-field">
                  <label>Platform</label>
                  <div className="push-platform-btns">
                    { ( [ 'all', 'ios', 'android' ] as const ).map( p => (
                      <button key={ p } className={ `push-plat-btn ${pushPlatform === p ? 'active' : ''}` } onClick={ () => setPushPlatform( p ) }>
                        { p === 'ios' && <AppleIcon size={ 14 } /> }
                        { p === 'android' && <AndroidIcon size={ 14 } /> }
                        { p === 'all' && <BellIcon size={ 14 } /> }
                        <span>{ p === 'all' ? 'All' : p === 'ios' ? 'iOS' : 'Android' }</span>
                      </button>
                    ) ) }
                  </div>
                </div>

                {/* Target */ }
                <div className="push-field">
                  <label>Target</label>
                  <div className="push-platform-btns">
                    <button className={ `push-plat-btn ${pushTarget === 'broadcast' ? 'active' : ''}` } onClick={ () => setPushTarget( 'broadcast' ) }>Broadcast (All)</button>
                    <button className={ `push-plat-btn ${pushTarget === 'user' ? 'active' : ''}` } onClick={ () => setPushTarget( 'user' ) }>Specific User</button>
                  </div>
                </div>

                { pushTarget === 'user' && (
                  <div className="push-field">
                    <label>User ID / Phone</label>
                    <input type="text" value={ pushUserId } onChange={ e => setPushUserId( e.target.value ) } placeholder="+91 98xxx xxxxx or user ID" />
                  </div>
                ) }

                <div className="push-field">
                  <label>Title *</label>
                  <input type="text" value={ pushTitle } onChange={ e => setPushTitle( e.target.value ) } placeholder="Notification title" />
                </div>

                <div className="push-field">
                  <label>Body *</label>
                  <textarea rows={ 3 } value={ pushBody } onChange={ e => setPushBody( e.target.value ) } placeholder="Notification message body..." />
                </div>

                <div className="push-field">
                  <label>Custom Data (JSON, optional)</label>
                  <textarea rows={ 2 } value={ pushData } onChange={ e => setPushData( e.target.value ) } placeholder='{"url": "/workspace/engage/inbox", "type": "alert"}' style={ { fontFamily: 'monospace', fontSize: 'var(--text-sm)' } } />
                </div>

                {/* Preview */ }
                <div className="push-preview">
                  <div className="push-preview-label">Preview</div>
                  <div className="push-preview-card">
                    <div className="push-preview-app">
                      <img src="https://wecare.digital/get/o/stream/media/m/wecaredigital.png" alt="" width={ 20 } height={ 20 } style={ { borderRadius: 4 } } />
                      <span>Stack CRM</span>
                      <span className="push-preview-time">now</span>
                    </div>
                    <div className="push-preview-title">{ pushTitle || 'Notification Title' }</div>
                    <div className="push-preview-body">{ pushBody || 'Notification body text will appear here...' }</div>
                  </div>
                </div>

                <Button variant="primary" onClick={ handleSendPush } disabled={ sending || !pushTitle.trim() || !pushBody.trim() } loading={ sending } style={ { width: '100%', marginTop: 8 } }>
                  <SendIcon /> { sending ? 'Sending...' : `Send to ${pushPlatform === 'all' ? 'All Devices' : pushPlatform === 'ios' ? 'iOS' : 'Android'}` }
                </Button>
              </div>
            </div>
          ) }

          {/* ═══ DEVICES TAB ═══ */ }
          { activeTab === 'devices' && (
            <div className="push-devices">
              <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } }>
                <h3 className="push-form-heading">Registered Devices ({ devices.length })</h3>
                <Button variant="secondary" size="sm" onClick={ loadDevices } loading={ loading }><RefreshIcon /> Refresh</Button>
              </div>

              { devices.length === 0 ? (
                <div className="push-empty">
                  <BellIcon size={ 32 } />
                  <h4>No Devices Registered</h4>
                  <p>Devices will appear here once users install the mobile app and grant push notification permissions.</p>
                </div>
              ) : (
                <div className="push-table-wrap">
                  <table className="push-table">
                    <thead>
                      <tr><th>Platform</th><th>User</th><th>Token</th><th>Registered</th><th>Action</th></tr>
                    </thead>
                    <tbody>
                      { devices.map( ( d, i ) => (
                        <tr key={ i }>
                          <td><span className={ `push-badge ${d.platform}` }>{ d.platform === 'ios' ? 'iOS' : 'Android' }</span></td>
                          <td style={ { fontSize: 'var(--text-sm)' } }>{ d.userId }</td>
                          <td style={ { fontFamily: 'monospace', fontSize: 'var(--text-xs)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }>{ d.deviceId }</td>
                          <td style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ new Date( d.registeredAt ).toLocaleString() }</td>
                          <td><button className="push-icon-btn" title="Remove"><TrashIcon /></button></td>
                        </tr>
                      ) ) }
                    </tbody>
                  </table>
                </div>
              ) }
            </div>
          ) }

          {/* ═══ LOGS TAB ═══ */ }
          { activeTab === 'logs' && (
            <div className="push-logs">
              <h3 className="push-form-heading">Delivery Logs</h3>
              <div className="push-table-wrap">
                <table className="push-table">
                  <thead>
                    <tr><th>Title</th><th>Platform</th><th>Target</th><th>Sent</th><th>Failed</th><th>Date</th></tr>
                  </thead>
                  <tbody>
                    { logs.map( l => (
                      <tr key={ l.id }>
                        <td>
                          <div style={ { fontWeight: 500, fontSize: 'var(--text-sm)' } }>{ l.title }</div>
                          <div style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 } }>{ l.body.length > 60 ? l.body.slice( 0, 60 ) + '...' : l.body }</div>
                        </td>
                        <td><span className={ `push-badge ${l.platform}` }>{ l.platform === 'all' ? 'All' : l.platform === 'ios' ? 'iOS' : 'Android' }</span></td>
                        <td style={ { fontSize: 'var(--text-xs)' } }>{ l.targetType }</td>
                        <td style={ { fontWeight: 600, color: 'var(--accent)' } }>{ l.sent }</td>
                        <td style={ { fontWeight: 600, color: l.failed > 0 ? '#dc2626' : 'var(--text-muted)' } }>{ l.failed }</td>
                        <td style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ new Date( l.sentAt ).toLocaleString() }</td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            </div>
          ) }

          {/* ═══ CONFIG TAB ═══ */ }
          { activeTab === 'config' && (
            <div className="push-config">
              <h3 className="push-form-heading">Push Notification Configuration</h3>

              <div className="push-config-section">
                <div className="push-config-header">
                  <AndroidIcon size={ 18 } />
                  <div>
                    <strong>Firebase Cloud Messaging (Android)</strong>
                    <p>{ pushConfiguration.android ? 'Configured server-side' : 'Not configured server-side' }</p>
                  </div>
                </div>
              </div>

              <div className="push-config-section">
                <div className="push-config-header">
                  <AppleIcon size={ 18 } />
                  <div>
                    <strong>Apple Push Notification service (iOS)</strong>
                    <p>{ pushConfiguration.ios ? 'Configured server-side' : 'Not configured server-side' }</p>
                  </div>
                </div>
              </div>

              <div className="push-info-box">
                <BellIcon size={ 18 } />
                <div>
                  {/*
                    The reassurance is "your keys never touch this browser". Naming the
                    services that hold them adds nothing to that promise and is not
                    something the reader configures from here.
                  */}
                  <strong>Credentials are managed server-side</strong>
                  <p>Platform credentials and private keys are never entered into, or returned to, the browser. Push credentials are configured during deployment, not from this screen.</p>
                  <p>Device registrations are stored on the server and matched to their push destination there.</p>
                </div>
              </div>
            </div>
          ) }
        </>
      ) }
    </PageShell>
  );

  if ( embedded ) return shellContent;
  return <Layout user={ user } onSignOut={ signOut }>{ shellContent }</Layout>;
};

/* ── Styles ── */
const pushStyles = `
.push-send,.push-devices,.push-logs,.push-config{padding:0;animation:pushFadeIn .2s ease}
@keyframes pushFadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.push-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}
.push-stat-card{display:flex;align-items:center;gap:12px;padding:16px;background:#fff;border:1px solid var(--border);border-radius:10px}
.push-stat-val{font-size:20px;font-weight:700;color:var(--accent)}
.push-stat-lbl{font-size:var(--text-xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px}
.push-form-card{background:#fff;border:1px solid var(--border);border-radius:10px;padding:20px}
.push-form-heading{font-size:var(--text-md);font-weight:600;color:var(--accent);margin:0 0 16px}
.push-field{margin-bottom:14px}
.push-field label{display:block;font-size:var(--text-xs);font-weight:600;color:#374151;text-transform:uppercase;letter-spacing:.3px;margin-bottom:4px}
.push-field input,.push-field textarea,.push-field select{width:100%;padding:10px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:var(--text-md);color:var(--text);background:#fff;min-height:44px;font-family:inherit;box-sizing:border-box}
.push-field input:focus,.push-field textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(209,244,112,.3)}
.push-field textarea{resize:vertical}
.push-platform-btns{display:flex;gap:6px;flex-wrap:wrap}
.push-plat-btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border:1.5px solid var(--border);border-radius:10px;background:#fff;font-size:var(--text-sm);font-weight:500;color:var(--text-muted);cursor:pointer;min-height:44px;font-family:inherit;transition:all .15s}
.push-plat-btn:hover{border-color:var(--lime);color:var(--accent)}
.push-plat-btn.active{background:var(--lime);border-color:var(--accent);color:var(--accent);font-weight:600}
.push-preview{margin:16px 0 8px;padding:16px;background:#f3f4f6;border-radius:10px}
.push-preview-label{font-size:var(--text-xs);font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
.push-preview-card{background:#fff;border-radius:12px;padding:12px 14px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.push-preview-app{display:flex;align-items:center;gap:6px;font-size:var(--text-xs);color:var(--text-muted);margin-bottom:6px}
.push-preview-time{margin-left:auto;font-size:var(--text-xs)}
.push-preview-title{font-size:var(--text-md);font-weight:600;color:var(--text);margin-bottom:2px}
.push-preview-body{font-size:var(--text-sm);color:rgba(0, 0, 0, 0.54);line-height:1.4}
.push-table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:10px}
.push-table{width:100%;border-collapse:collapse;font-size:var(--text-sm)}
.push-table th{padding:10px 14px;text-align:left;font-weight:600;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)}
.push-table td{padding:10px 14px;border-bottom:1px solid #f3f4f6}
.push-table tr:last-child td{border-bottom:none}
.push-badge{padding:3px 10px;border-radius:6px;font-size:var(--text-xs);font-weight:600}
.push-badge.ios{background:#f0f0ff;color:#6366f1;border:1px solid #c7d2fe}
.push-badge.android{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0}
.push-badge.all{background:var(--bg-secondary);color:var(--accent);border:1px solid var(--border)}
.push-icon-btn{width:32px;height:32px;border:1px solid var(--border);border-radius:6px;background:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text-muted)}
.push-icon-btn:hover{border-color:#dc2626;color:#dc2626;background:#fef2f2}
.push-empty{text-align:center;padding:48px 20px;color:var(--text-muted)}
.push-empty h4{margin:12px 0 4px;color:var(--accent);font-size:var(--text-base)}
.push-empty p{margin:0;font-size:var(--text-sm);max-width:360px;margin:0 auto;line-height:1.5}
.push-config-section{background:#fff;border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:16px}
.push-config-header{display:flex;align-items:flex-start;gap:12px;margin-bottom:16px}
.push-config-header strong{display:block;color:var(--accent);font-size:var(--text-md)}
.push-config-header p{margin:2px 0 0;font-size:var(--text-xs);color:var(--text-muted)}
.push-config-fields{display:flex;flex-direction:column;gap:12px}
.push-config-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.push-info-box{display:flex;gap:12px;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;font-size:var(--text-sm);color:#475569}
.push-info-box strong{display:block;color:var(--accent);margin-bottom:4px}
.push-info-box p{margin:0 0 6px;line-height:1.5}
.push-info-box ul{margin:4px 0 0 16px;padding:0;line-height:1.6}
@media(max-width:768px){.push-stats{grid-template-columns:1fr}.push-config-grid{grid-template-columns:1fr}.push-platform-btns{flex-wrap:wrap}}
`;
if ( typeof document !== 'undefined' ) { const id = 'push-page-styles'; if ( !document.getElementById( id ) ) { const el = document.createElement( 'style' ); el.id = id; el.textContent = pushStyles; document.head.appendChild( el ) } }

export default PushPage;