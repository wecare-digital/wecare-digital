/**
 * App Builder Tab - WECARE.DIGITAL Dashboard
 * Provision to create iOS + Android app builds,
 * connect App Store & Google Play Store,
 * manage app configuration and deployment.
 */
import React, { useState } from 'react';
import { DashboardData } from '../../../types/dashboard';
import Select, { type SelectOption } from '../../ui/Select';

interface Props { data: DashboardData; }

/*
 * The three option lists, hoisted. Same order, same values, same visible text, and every
 * cast preserved verbatim at the call sites.
 *
 * THIS FILE'S FOUR input[type="color"] CONTROLS ARE DELIBERATELY NOT TOUCHED HERE. They
 * belong to the picker batch, and the split is recorded because an earlier revision had this
 * file in that batch for its colour inputs ONLY and lost these three selects entirely - they
 * appeared in no batch at all, which is the failure the per-file reconciliation exists to
 * catch.
 */
const PLAY_TRACK_OPTIONS: SelectOption[] = [
  { value: 'internal', label: 'Internal Testing' },
  { value: 'alpha', label: 'Closed Testing (Alpha)' },
  { value: 'beta', label: 'Open Testing (Beta)' },
  { value: 'production', label: 'Production' },
];
const STATUS_BAR_STYLE_OPTIONS: SelectOption[] = [
  { value: 'dark-content', label: 'Dark Content' },
  { value: 'light-content', label: 'Light Content' },
];
const ORIENTATION_OPTIONS: SelectOption[] = [
  { value: 'portrait', label: 'Portrait' },
  { value: 'landscape', label: 'Landscape' },
  { value: 'both', label: 'Both' },
];

/* ── SVG Icons (inline, no emoji) ── */
const AppleIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2C9.5 2 8 3.5 8 3.5S6.5 2 4 4c-2 2-1 5.5 1 8s4 5 5 6c.5.5 1.5 1 2 1s1.5-.5 2-1c1-1 3-3.5 5-6s3-6 1-8c-2.5-2-4-.5-4-.5S14.5 2 12 2z" />
  </svg>
);
const PlayStoreIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="5 3 19 12 5 21 5 3" />
  </svg>
);
const BuildIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
  </svg>
);
const ShieldIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);
const UploadIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
  </svg>
);
const CheckCircleIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
  </svg>
);
const AlertIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
  </svg>
);
const GlobeIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
);

type SubTab = 'overview' | 'ios' | 'android' | 'pwa' | 'config' | 'deploy';

const AppBuilderTab: React.FC<Props> = ( { data } ) => {
  const [ subTab, setSubTab ] = useState<SubTab>( 'overview' );

  /* ── App Config State ── */
  const [ appConfig, setAppConfig ] = useState( {
    appName: 'WECARE.DIGITAL',
    bundleId: 'digital.wecare.app',
    packageName: 'digital.wecare.app',
    version: '1.0.0',
    buildNumber: '1',
    primaryColor: '#1a3a2a',
    accentColor: '#d1f470',
    splashBg: '#ffffff',
    statusBarStyle: 'dark-content' as 'dark-content' | 'light-content',
    orientation: 'portrait' as 'portrait' | 'landscape' | 'both',
    deepLinkScheme: 'wecare',
    universalLinkDomain: 'wecare.digital',
  } );

  /* ── Store Connection State ── */
  const [ storeConfig, setStoreConfig ] = useState( {
    // Apple
    appleTeamId: '',
    appleBundleId: 'digital.wecare.app',
    appleAppId: '',
    appleConnected: false,
    // Google
    googlePackageName: 'digital.wecare.app',
    googlePlayTrack: 'internal' as 'internal' | 'alpha' | 'beta' | 'production',
    googleConnected: false,
  } );

  /* ── Build State ── */
  const [ builds, setBuilds ] = useState<Array<{
    id: string; platform: 'ios' | 'android'; status: 'queued' | 'building' | 'success' | 'failed';
    version: string; createdAt: string; downloadUrl?: string; size?: string;
  }>>( [
    { id: 'b1', platform: 'ios', status: 'success', version: '1.0.0 (1)', createdAt: '2026-03-08T10:30:00Z', downloadUrl: '#', size: '24.3 MB' },
    { id: 'b2', platform: 'android', status: 'success', version: '1.0.0 (1)', createdAt: '2026-03-08T10:28:00Z', downloadUrl: '#', size: '18.7 MB' },
  ] );

  const [ building, setBuilding ] = useState( false );

  const triggerBuild = ( platform: 'ios' | 'android' | 'both' ) => {
    setBuilding( true );
    const newBuilds: typeof builds = [];
    if ( platform === 'ios' || platform === 'both' )
    {
      newBuilds.push( { id: `b${Date.now()}`, platform: 'ios' as const, status: 'building' as const, version: `${appConfig.version} (${appConfig.buildNumber})`, createdAt: new Date().toISOString() } );
    }
    if ( platform === 'android' || platform === 'both' )
    {
      newBuilds.push( { id: `b${Date.now() + 1}`, platform: 'android' as const, status: 'building' as const, version: `${appConfig.version} (${appConfig.buildNumber})`, createdAt: new Date().toISOString() } );
    }
    setBuilds( prev => [ ...newBuilds, ...prev ] );
    setTimeout( () => {
      setBuilds( prev => prev.map( b => b.status === 'building' ? { ...b, status: 'success' as const, downloadUrl: '#', size: b.platform === 'ios' ? '24.3 MB' : '18.7 MB' } : b ) );
      setBuilding( false );
    }, 3000 );
  };

  const statusBadge = ( status: string ) => {
    const colors: Record<string, { bg: string; color: string; border: string }> = {
      queued: { bg: '#f9fafb', color: '#6b7280', border: '#e5e7eb' },
      building: { bg: '#f9fafb', color: '#1a3a2a', border: '#d1f470' },
      success: { bg: '#f0fdf4', color: '#1a3a2a', border: '#d1f470' },
      failed: { bg: '#fef2f2', color: '#dc2626', border: '#fecaca' },
    };
    const c = colors[ status ] || colors.queued;
    return <span style={ { padding: '3px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: c.bg, color: c.color, border: `1px solid ${c.border}` } }>{ status }</span>;
  };

  return (
    <div className="app-builder-tab">
      {/* Sub-tabs */ }
      <div className="ab-subtabs">
        { ( [
          { id: 'overview', label: 'Overview' },
          { id: 'ios', label: 'iOS' },
          { id: 'android', label: 'Android' },
          { id: 'pwa', label: 'PWA' },
          { id: 'config', label: 'App Config' },
          { id: 'deploy', label: 'Deploy' },
        ] as { id: SubTab; label: string }[] ).map( t => (
          <button key={ t.id } className={ `ab-subtab ${subTab === t.id ? 'active' : ''}` } onClick={ () => setSubTab( t.id ) }>{ t.label }</button>
        ) ) }
      </div>

      {/* ═══ OVERVIEW ═══ */ }
      { subTab === 'overview' && (
        <div className="ab-section">
          {/* Status Cards */ }
          <div className="ab-status-grid">
            <div className="ab-status-card">
              <div className="ab-status-icon"><AppleIcon /></div>
              <div className="ab-status-info">
                <div className="ab-status-label">iOS App Store</div>
                <div className="ab-status-value">{ storeConfig.appleConnected ? 'Connected' : 'Not Connected' }</div>
              </div>
              { storeConfig.appleConnected ? <CheckCircleIcon /> : <AlertIcon /> }
            </div>
            <div className="ab-status-card">
              <div className="ab-status-icon"><PlayStoreIcon /></div>
              <div className="ab-status-info">
                <div className="ab-status-label">Google Play Store</div>
                <div className="ab-status-value">{ storeConfig.googleConnected ? 'Connected' : 'Not Connected' }</div>
              </div>
              { storeConfig.googleConnected ? <CheckCircleIcon /> : <AlertIcon /> }
            </div>
            <div className="ab-status-card">
              <div className="ab-status-icon"><GlobeIcon /></div>
              <div className="ab-status-info">
                <div className="ab-status-label">PWA</div>
                <div className="ab-status-value">Ready</div>
              </div>
              <CheckCircleIcon />
            </div>
            <div className="ab-status-card">
              <div className="ab-status-icon"><BuildIcon /></div>
              <div className="ab-status-info">
                <div className="ab-status-label">Latest Build</div>
                <div className="ab-status-value">v{ appConfig.version }</div>
              </div>
              <CheckCircleIcon />
            </div>
          </div>

          {/* Quick Actions */ }
          <h3 className="ab-heading">Quick Actions</h3>
          <div className="ab-actions-grid">
            <button className="ab-action-btn" onClick={ () => triggerBuild( 'both' ) } disabled={ building }>
              <BuildIcon />
              <span>{ building ? 'Building...' : 'Build iOS + Android' }</span>
            </button>
            <button className="ab-action-btn" onClick={ () => setSubTab( 'ios' ) }>
              <AppleIcon />
              <span>Connect App Store</span>
            </button>
            <button className="ab-action-btn" onClick={ () => setSubTab( 'android' ) }>
              <PlayStoreIcon />
              <span>Connect Play Store</span>
            </button>
            <button className="ab-action-btn" onClick={ () => setSubTab( 'config' ) }>
              <ShieldIcon />
              <span>App Configuration</span>
            </button>
          </div>

          {/* Recent Builds */ }
          <h3 className="ab-heading">Recent Builds</h3>
          <div className="ab-table-wrap">
            <table className="ab-table">
              <thead>
                <tr>
                  <th>Platform</th><th>Version</th><th>Status</th><th>Date</th><th>Size</th><th>Action</th>
                </tr>
              </thead>
              <tbody>
                { builds.slice( 0, 5 ).map( b => (
                  <tr key={ b.id }>
                    <td>{ b.platform === 'ios' ? 'iOS' : 'Android' }</td>
                    <td style={ { fontFamily: 'monospace', fontSize: 12 } }>{ b.version }</td>
                    <td>{ statusBadge( b.status ) }</td>
                    <td style={ { fontSize: 12, color: '#6b7280' } }>{ new Date( b.createdAt ).toLocaleString() }</td>
                    <td style={ { fontSize: 12 } }>{ b.size || '—' }</td>
                    <td>
                      { b.downloadUrl && b.status === 'success' && (
                        <button className="ab-sm-btn" onClick={ () => { } }>Download</button>
                      ) }
                    </td>
                  </tr>
                ) ) }
              </tbody>
            </table>
          </div>

          {/* Mobile Readiness Checklist */ }
          <h3 className="ab-heading">Mobile App Readiness Checklist</h3>
          <div className="ab-checklist">
            { [
              { done: true, label: 'Safe area insets (notch/dynamic island)' },
              { done: true, label: '44px minimum touch targets' },
              { done: true, label: '16px input font (iOS zoom prevention)' },
              { done: true, label: 'Overscroll behavior (native feel)' },
              { done: true, label: 'Pull-to-refresh prevention' },
              { done: true, label: 'Momentum scrolling (-webkit-overflow-scrolling)' },
              { done: true, label: 'Bottom sheet modals on mobile' },
              { done: true, label: 'Responsive grids (1-col on mobile)' },
              { done: true, label: 'Horizontal scroll tabs (WhatsApp 14 tabs)' },
              { done: true, label: 'Mobile sidebar slide-out with overlay' },
              { done: true, label: 'Touch-action: manipulation (no double-tap zoom)' },
              { done: true, label: 'User-select: none on UI elements' },
              { done: false, label: 'Push notifications (FCM + APNs)' },
              { done: false, label: 'Biometric authentication (Face ID / Fingerprint)' },
              { done: false, label: 'Offline mode with local cache' },
              { done: false, label: 'App icon + splash screen assets' },
              { done: false, label: 'Deep linking (wecare://)' },
              { done: false, label: 'App Store screenshots + metadata' },
            ].map( ( item, i ) => (
              <div key={ i } className={ `ab-check-item ${item.done ? 'done' : 'pending'}` }>
                { item.done ? <CheckCircleIcon /> : <span className="ab-check-empty" /> }
                <span>{ item.label }</span>
              </div>
            ) ) }
          </div>
        </div>
      ) }

      {/* ═══ iOS SUB-TAB ═══ */ }
      { subTab === 'ios' && (
        <div className="ab-section">
          <h3 className="ab-heading">Apple App Store Connect</h3>
          <div className={ `ab-conn-badge ${storeConfig.appleConnected ? 'connected' : 'disconnected'}` }>
            { storeConfig.appleConnected ? 'Connected' : 'Not Connected' }
          </div>
          <div className="ab-form-section">
            <div className="ab-form-grid">
              <div className="ab-form-field">
                <label>Apple Team ID</label>
                <input type="text" value={ storeConfig.appleTeamId } onChange={ e => setStoreConfig( { ...storeConfig, appleTeamId: e.target.value } ) } placeholder="e.g. A1B2C3D4E5" />
              </div>
              <div className="ab-form-field">
                <label>Bundle ID</label>
                <input type="text" value={ storeConfig.appleBundleId } onChange={ e => setStoreConfig( { ...storeConfig, appleBundleId: e.target.value } ) } placeholder="digital.wecare.app" />
              </div>
              <div className="ab-form-field">
                <label>App Store App ID</label>
                <input type="text" value={ storeConfig.appleAppId } onChange={ e => setStoreConfig( { ...storeConfig, appleAppId: e.target.value } ) } placeholder="e.g. 1234567890" />
              </div>
              <div className="ab-form-field full">
                <label>App Store Connect Credentials</label>
                <p>Signing credentials are managed server-side and are never entered or displayed in the browser. Current status: not configured.</p>
              </div>
            </div>
          </div>
          <div className="ab-info-box">
            <ShieldIcon />
            <div>
              <strong>Server-side credentials required</strong>
              <p>Provision the App Store Connect key through the approved server-side secret workflow before enabling iOS builds.</p>
            </div>
          </div>
        </div>
      ) }

      {/* ═══ ANDROID SUB-TAB ═══ */ }
      { subTab === 'android' && (
        <div className="ab-section">
          <h3 className="ab-heading">Google Play Console</h3>
          <div className={ `ab-conn-badge ${storeConfig.googleConnected ? 'connected' : 'disconnected'}` }>
            { storeConfig.googleConnected ? 'Connected' : 'Not Connected' }
          </div>
          <div className="ab-form-section">
            <div className="ab-form-grid">
              <div className="ab-form-field">
                <label>Package Name</label>
                <input type="text" value={ storeConfig.googlePackageName } onChange={ e => setStoreConfig( { ...storeConfig, googlePackageName: e.target.value } ) } placeholder="digital.wecare.app" />
              </div>
              <div className="ab-form-field">
                <label>Release Track</label>
                <Select ariaLabel="Release track" value={ storeConfig.googlePlayTrack }
                  onChange={ v => setStoreConfig( { ...storeConfig, googlePlayTrack: v as any } ) }
                  options={ PLAY_TRACK_OPTIONS } />
              </div>
              <div className="ab-form-field full">
                <label>Google Play Credentials</label>
                <p>Service-account credentials are managed server-side and are never entered or displayed in the browser. Current status: not configured.</p>
              </div>
            </div>
          </div>
          <div className="ab-info-box">
            <ShieldIcon />
            <div>
              <strong>Server-side credentials required</strong>
              <p>Provision the Google Play service account through the approved server-side secret workflow before enabling Android builds.</p>
            </div>
          </div>
        </div>
      ) }

      {/* ═══ PWA SUB-TAB ═══ */ }
      { subTab === 'pwa' && (
        <div className="ab-section">
          <h3 className="ab-heading">Progressive Web App (PWA)</h3>
          <div className="ab-conn-badge connected">PWA Ready</div>
          <div className="ab-pwa-grid">
            <div className="ab-pwa-card">
              <GlobeIcon />
              <div>
                <strong>manifest.json</strong>
                <p>Configured at /manifest.json with app name, icons, theme color, and display mode.</p>
              </div>
              <CheckCircleIcon />
            </div>
            <div className="ab-pwa-card">
              <ShieldIcon />
              <div>
                <strong>HTTPS</strong>
                <p>Site served over HTTPS via wecare.digital — required for PWA.</p>
              </div>
              <CheckCircleIcon />
            </div>
            <div className="ab-pwa-card">
              <BuildIcon />
              <div>
                <strong>Meta Tags</strong>
                <p>apple-mobile-web-app-capable, mobile-web-app-capable, theme-color configured.</p>
              </div>
              <CheckCircleIcon />
            </div>
            <div className="ab-pwa-card">
              <AppleIcon />
              <div>
                <strong>Apple Touch Icon</strong>
                <p>apple-touch-icon configured for iOS home screen.</p>
              </div>
              <CheckCircleIcon />
            </div>
          </div>
          <h3 className="ab-heading" style={ { marginTop: 24 } }>Manifest Preview</h3>
          <div className="ab-code-block">
            <pre>{ JSON.stringify( {
              name: 'WECARE.DIGITAL',
              short_name: 'WECARE.DIGITAL',
              description: 'Enterprise WhatsApp Business API Platform',
              start_url: '/',
              display: 'standalone',
              background_color: '#ffffff',
              theme_color: '#1a3a2a',
              orientation: 'any',
              icons: [
                { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
                { src: '/icon-512.png', sizes: '512x512', type: 'image/png' }
              ]
            }, null, 2 ) }</pre>
          </div>
          <div className="ab-info-box">
            <GlobeIcon />
            <div>
              <strong>Install as App</strong>
              <p>Users can install this PWA from Chrome (desktop/mobile) or Safari (iOS). On iOS, tap Share &gt; Add to Home Screen. On Android Chrome, tap the install banner or menu &gt; Install app.</p>
            </div>
          </div>
        </div>
      ) }

      {/* ═══ CONFIG SUB-TAB ═══ */ }
      { subTab === 'config' && (
        <div className="ab-section">
          <h3 className="ab-heading">App Configuration</h3>
          <div className="ab-form-section">
            <div className="ab-form-grid">
              <div className="ab-form-field">
                <label>App Name</label>
                <input type="text" value={ appConfig.appName } onChange={ e => setAppConfig( { ...appConfig, appName: e.target.value } ) } />
              </div>
              <div className="ab-form-field">
                <label>Bundle ID (iOS)</label>
                <input type="text" value={ appConfig.bundleId } onChange={ e => setAppConfig( { ...appConfig, bundleId: e.target.value } ) } />
              </div>
              <div className="ab-form-field">
                <label>Package Name (Android)</label>
                <input type="text" value={ appConfig.packageName } onChange={ e => setAppConfig( { ...appConfig, packageName: e.target.value } ) } />
              </div>
              <div className="ab-form-field">
                <label>Version</label>
                <input type="text" value={ appConfig.version } onChange={ e => setAppConfig( { ...appConfig, version: e.target.value } ) } />
              </div>
              <div className="ab-form-field">
                <label>Build Number</label>
                <input type="text" value={ appConfig.buildNumber } onChange={ e => setAppConfig( { ...appConfig, buildNumber: e.target.value } ) } />
              </div>
              <div className="ab-form-field">
                <label>Primary Color</label>
                <div className="ab-color-row">
                  <input type="color" value={ appConfig.primaryColor } onChange={ e => setAppConfig( { ...appConfig, primaryColor: e.target.value } ) } />
                  <input type="text" value={ appConfig.primaryColor } onChange={ e => setAppConfig( { ...appConfig, primaryColor: e.target.value } ) } />
                </div>
              </div>
              <div className="ab-form-field">
                <label>Accent Color</label>
                <div className="ab-color-row">
                  <input type="color" value={ appConfig.accentColor } onChange={ e => setAppConfig( { ...appConfig, accentColor: e.target.value } ) } />
                  <input type="text" value={ appConfig.accentColor } onChange={ e => setAppConfig( { ...appConfig, accentColor: e.target.value } ) } />
                </div>
              </div>
              <div className="ab-form-field">
                <label>Splash Background</label>
                <div className="ab-color-row">
                  <input type="color" value={ appConfig.splashBg } onChange={ e => setAppConfig( { ...appConfig, splashBg: e.target.value } ) } />
                  <input type="text" value={ appConfig.splashBg } onChange={ e => setAppConfig( { ...appConfig, splashBg: e.target.value } ) } />
                </div>
              </div>
              <div className="ab-form-field">
                <label>Status Bar Style</label>
                <Select ariaLabel="Status bar style" value={ appConfig.statusBarStyle }
                  onChange={ v => setAppConfig( { ...appConfig, statusBarStyle: v as any } ) }
                  options={ STATUS_BAR_STYLE_OPTIONS } />
              </div>
              <div className="ab-form-field">
                <label>Orientation</label>
                <Select ariaLabel="Orientation" value={ appConfig.orientation }
                  onChange={ v => setAppConfig( { ...appConfig, orientation: v as any } ) }
                  options={ ORIENTATION_OPTIONS } />
              </div>
              <div className="ab-form-field">
                <label>Deep Link Scheme</label>
                <input type="text" value={ appConfig.deepLinkScheme } onChange={ e => setAppConfig( { ...appConfig, deepLinkScheme: e.target.value } ) } placeholder="wecare" />
              </div>
              <div className="ab-form-field">
                <label>Universal Link Domain</label>
                <input type="text" value={ appConfig.universalLinkDomain } onChange={ e => setAppConfig( { ...appConfig, universalLinkDomain: e.target.value } ) } placeholder="wecare.digital" />
              </div>
            </div>
            <div className="ab-form-actions">
              <button className="ab-btn primary" onClick={ () => { } }>Save Configuration</button>
            </div>
          </div>
        </div>
      ) }

      {/* ═══ DEPLOY SUB-TAB ═══ */ }
      { subTab === 'deploy' && (
        <div className="ab-section">
          <h3 className="ab-heading">Deploy to Stores</h3>
          <div className="ab-deploy-grid">
            <div className="ab-deploy-card">
              <div className="ab-deploy-header">
                <AppleIcon />
                <div>
                  <strong>Apple App Store</strong>
                  <span className={ storeConfig.appleConnected ? 'connected' : 'disconnected' }>{ storeConfig.appleConnected ? 'Connected' : 'Not Connected' }</span>
                </div>
              </div>
              <p>Submit your iOS build to App Store Connect for TestFlight or production release.</p>
              <button className="ab-btn primary" disabled={ !storeConfig.appleConnected || building } onClick={ () => triggerBuild( 'ios' ) }>
                <UploadIcon /> { building ? 'Building...' : 'Build + Deploy iOS' }
              </button>
            </div>
            <div className="ab-deploy-card">
              <div className="ab-deploy-header">
                <PlayStoreIcon />
                <div>
                  <strong>Google Play Store</strong>
                  <span className={ storeConfig.googleConnected ? 'connected' : 'disconnected' }>{ storeConfig.googleConnected ? 'Connected' : 'Not Connected' }</span>
                </div>
              </div>
              <p>Upload your Android build to Google Play Console on the { storeConfig.googlePlayTrack } track.</p>
              <button className="ab-btn primary" disabled={ !storeConfig.googleConnected || building } onClick={ () => triggerBuild( 'android' ) }>
                <UploadIcon /> { building ? 'Building...' : 'Build + Deploy Android' }
              </button>
            </div>
          </div>

          <h3 className="ab-heading" style={ { marginTop: 24 } }>Build History</h3>
          <div className="ab-table-wrap">
            <table className="ab-table">
              <thead>
                <tr>
                  <th>Platform</th><th>Version</th><th>Status</th><th>Date</th><th>Size</th><th>Actions</th>
                </tr>
              </thead>
              <tbody>
                { builds.map( b => (
                  <tr key={ b.id }>
                    <td>{ b.platform === 'ios' ? 'iOS' : 'Android' }</td>
                    <td style={ { fontFamily: 'monospace', fontSize: 12 } }>{ b.version }</td>
                    <td>{ statusBadge( b.status ) }</td>
                    <td style={ { fontSize: 12, color: '#6b7280' } }>{ new Date( b.createdAt ).toLocaleString() }</td>
                    <td style={ { fontSize: 12 } }>{ b.size || '—' }</td>
                    <td className="ab-action-cell">
                      { b.downloadUrl && b.status === 'success' && (
                        <>
                          <button className="ab-sm-btn" onClick={ () => { } }>Download</button>
                          <button className="ab-sm-btn deploy" onClick={ () => { } }>Deploy</button>
                        </>
                      ) }
                    </td>
                  </tr>
                ) ) }
              </tbody>
            </table>
          </div>
        </div>
      ) }

    </div>
  );
};

/* ── Styles ── */
const styles = `
.app-builder-tab { padding: 0; }
.ab-subtabs { display: flex; gap: 4px; padding: 0 0 16px; border-bottom: 1px solid #e5e7eb; margin-bottom: 20px; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.ab-subtab { padding: 8px 16px; border: none; background: none; border-radius: 8px; font-size: 13px; font-weight: 500; color: #6b7280; cursor: pointer; white-space: nowrap; min-height: 44px; transition: all .15s; }
.ab-subtab:hover { background: #f3f4f6; color: #1a3a2a; }
.ab-subtab.active { background: #1a3a2a; color: #fff; }
.ab-section { animation: abFadeIn .2s ease; }
@keyframes abFadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
.ab-heading { font-size: 14px; font-weight: 600; color: #1a3a2a; margin: 20px 0 12px; }
.ab-status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.ab-status-card { display: flex; align-items: center; gap: 12px; padding: 16px; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; }
.ab-status-icon { width: 40px; height: 40px; border-radius: 10px; background: #f3f4f6; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.ab-status-info { flex: 1; min-width: 0; }
.ab-status-label { font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: .5px; }
.ab-status-value { font-size: 14px; font-weight: 600; color: #1a3a2a; }
.ab-actions-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.ab-action-btn { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; cursor: pointer; font-size: 13px; font-weight: 500; color: #1a3a2a; transition: all .15s; min-height: 44px; }
.ab-action-btn:hover { border-color: #d1f470; background: #f9fdf0; }
.ab-action-btn:disabled { opacity: .5; cursor: not-allowed; }
.ab-table-wrap { overflow-x: auto; border: 1px solid #e5e7eb; border-radius: 10px; }
.ab-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.ab-table th { padding: 10px 14px; text-align: left; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: #6b7280; background: #f9fafb; border-bottom: 1px solid #e5e7eb; }
.ab-table td { padding: 10px 14px; border-bottom: 1px solid #f3f4f6; }
.ab-table tr:last-child td { border-bottom: none; }
.ab-sm-btn { padding: 4px 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #fff; font-size: 12px; cursor: pointer; color: #1a3a2a; min-height: 32px; }
.ab-sm-btn:hover { border-color: #d1f470; background: #f9fdf0; }
.ab-sm-btn.deploy { background: #1a3a2a; color: #fff; border-color: #1a3a2a; }
.ab-sm-btn.deploy:hover { background: #0f2a1d; }
.ab-checklist { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.ab-check-item { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 8px; font-size: 13px; }
.ab-check-item.done { background: #f0fdf4; color: #1a3a2a; }
.ab-check-item.pending { background: #f9fafb; color: #6b7280; }
.ab-check-empty { width: 16px; height: 16px; border: 2px solid #d1d5db; border-radius: 50%; flex-shrink: 0; }
.ab-conn-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; margin-bottom: 16px; }
.ab-conn-badge.connected { background: #f0fdf4; color: #1a3a2a; border: 1px solid #d1f470; }
.ab-conn-badge.disconnected { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }
.ab-form-section { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 20px; }
.ab-form-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-bottom: 16px; }
.ab-form-field { display: flex; flex-direction: column; gap: 4px; }
.ab-form-field.full { grid-column: 1 / -1; }
.ab-form-field label { font-size: 12px; font-weight: 600; color: #374151; text-transform: uppercase; letter-spacing: .3px; }
.ab-form-field input, .ab-form-field select, .ab-form-field textarea { padding: 10px 12px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; color: #1a1a1a; background: #fff; min-height: 44px; font-family: inherit; }
.ab-form-field input:focus, .ab-form-field select:focus, .ab-form-field textarea:focus { outline: none; border-color: #1a3a2a; box-shadow: 0 0 0 3px rgba(209,244,112,.3); }
.ab-form-field textarea { resize: vertical; font-family: monospace; font-size: 13px; }
.ab-form-actions { display: flex; gap: 10px; padding-top: 8px; }
.ab-btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; min-height: 44px; transition: all .15s; }
.ab-btn.primary { background: #1a3a2a; color: #fff; }
.ab-btn.primary:hover { background: #0f2a1d; }
.ab-btn.primary:disabled { opacity: .5; cursor: not-allowed; }
.ab-btn.secondary { background: #f3f4f6; color: #1a3a2a; border: 1px solid #e5e7eb; }
.ab-btn.secondary:hover { background: #e5e7eb; }
.ab-info-box { display: flex; gap: 12px; padding: 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; margin-top: 16px; font-size: 13px; color: #475569; }
.ab-info-box strong { display: block; color: #1a3a2a; margin-bottom: 4px; }
.ab-info-box p { margin: 0; line-height: 1.5; }
.ab-color-row { display: flex; gap: 8px; align-items: center; }
.ab-color-row input[type="color"] { width: 44px; height: 44px; border: 1px solid #d1d5db; border-radius: 8px; padding: 2px; cursor: pointer; }
.ab-color-row input[type="text"] { flex: 1; }
.ab-pwa-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.ab-pwa-card { display: flex; align-items: flex-start; gap: 12px; padding: 16px; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; }
.ab-pwa-card strong { display: block; color: #1a3a2a; margin-bottom: 2px; font-size: 13px; }
.ab-pwa-card p { margin: 0; font-size: 12px; color: #6b7280; line-height: 1.4; }
.ab-pwa-card > div { flex: 1; }
.ab-code-block { background: #1a1a1a; color: #d1f470; padding: 16px; border-radius: 10px; overflow-x: auto; }
.ab-code-block pre { margin: 0; font-size: 12px; font-family: monospace; line-height: 1.5; white-space: pre; }
.ab-deploy-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.ab-deploy-card { padding: 20px; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; }
.ab-deploy-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.ab-deploy-header strong { display: block; font-size: 14px; color: #1a3a2a; }
.ab-deploy-header span { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.ab-deploy-header span.connected { background: #f0fdf4; color: #1a3a2a; }
.ab-deploy-header span.disconnected { background: #fef2f2; color: #dc2626; }
.ab-deploy-card p { font-size: 13px; color: #6b7280; margin: 0 0 16px; line-height: 1.5; }
.ab-action-cell { display: flex; gap: 6px; }

/* ── Mobile ── */
@media (max-width: 768px) {
  .ab-status-grid { grid-template-columns: repeat(2, 1fr); }
  .ab-actions-grid { grid-template-columns: repeat(2, 1fr); }
  .ab-checklist { grid-template-columns: 1fr; }
  .ab-form-grid { grid-template-columns: 1fr; }
  .ab-pwa-grid { grid-template-columns: 1fr; }
  .ab-deploy-grid { grid-template-columns: 1fr; }
  .ab-subtabs { gap: 2px; }
  .ab-subtab { padding: 8px 12px; font-size: 12px; }
}
@media (max-width: 480px) {
  .ab-status-grid { grid-template-columns: 1fr; }
  .ab-actions-grid { grid-template-columns: 1fr; }
  .ab-status-card { padding: 12px; }
  .ab-form-section { padding: 14px; }
  .ab-deploy-card { padding: 14px; }
}
`;

// Inject styles
if ( typeof document !== 'undefined' )
{
  const id = 'ab-tab-styles';
  if ( !document.getElementById( id ) )
  {
    const el = document.createElement( 'style' );
    el.id = id;
    el.textContent = styles;
    document.head.appendChild( el );
  }
}

export default AppBuilderTab;