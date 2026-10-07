/**
 * Link Page - URL Shortener & Deep Links
 *
 * New links are minted under wecare.digital/r (canonical since 2026-09-26).
 * r.wecare.digital is RETIRED: its Route 53 record went on 2026-09-28 under confirmation
 * YES R53-DELETE-001 and its API Gateway custom domain was deleted in 396b87ad, so the
 * host is NXDOMAIN and a link on it fails to RESOLVE rather than 404ing. Every code ever
 * issued is still honoured, but only on the apex form wecare.digital/r/<code>.
 *
 * General-purpose short links, click tracking, deep links for iOS/Android
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import DateField from '../../../components/ui/DateField';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';

// The link CRUD API. wecare.digital/api is now the ONLY way to reach HTTP API
// zllr9lrg7j: r.wecare.digital used to be mapped to the same API and return identical
// results, but that custom domain and its prod mapping were deleted in 396b87ad, so the
// account has zero API Gateway custom domains and the API is reached solely through the
// Amplify /api/<*> rewrite. This constant was already pointed at the apex before the
// retirement, which is why the dashboard was unaffected by it.
const API_BASE = process.env.NEXT_PUBLIC_LINK_API_BASE || 'https://wecare.digital/api';

// The base shown to an operator and used to build a copyable link. Display only —
// what actually gets stored comes back from the Lambda's SHORT_LINK_BASE.
const SHORT_LINK_BASE = 'wecare.digital/r';

interface PageProps { signOut?: () => void; user?: any; }

interface ShortLink {
  shortCode: string;
  shortUrl: string;
  originalUrl: string;
  title: string;
  clicks: number;
  createdAt: string;
  expiresAt?: string;
  deepLink?: boolean;
  iosUrl?: string;
  androidUrl?: string;
  active?: boolean;
}

/* ── Icons ── */
const LinkIcon = ( { size = 18 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
  </svg>
);
const CopyIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);
const TrashIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
);
const BarChartIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" />
  </svg>
);
const PlusIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);
const EditIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);

const LinkPage: React.FC<PageProps> = ( { signOut, user } ) => {
  const [ links, setLinks ] = useState<ShortLink[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ loadError, setLoadError ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ copied, setCopied ] = useState<string | null>( null );
  const [ showForm, setShowForm ] = useState( false );
  const [ formUrl, setFormUrl ] = useState( '' );
  const [ formTitle, setFormTitle ] = useState( '' );
  const [ formCode, setFormCode ] = useState( '' );
  const [ formDeepLink, setFormDeepLink ] = useState( false );
  const [ formIosUrl, setFormIosUrl ] = useState( '' );
  const [ formAndroidUrl, setFormAndroidUrl ] = useState( '' );
  const [ formExpiry, setFormExpiry ] = useState( '' );
  const [ formActive, setFormActive ] = useState( true );
  const [ editingCode, setEditingCode ] = useState<string | null>( null );
  const [ analyticsCode, setAnalyticsCode ] = useState<string | null>( null );
  const [ analyticsData, setAnalyticsData ] = useState<any>( null );

  const toast = useToastContext();
  const confirm = useConfirm();

  const totalClicks = links.reduce( ( s, l ) => s + ( Number( l.clicks ) || 0 ), 0 );
  const deepLinkCount = links.filter( l => l.deepLink ).length;

  const loadLinks = useCallback( async () => {
    setLoading( true );
    setLoadError( false );
    try
    {
      const resp = await fetch( `${API_BASE}/links` );
      const data = await resp.json();
      setLinks( ( data.links || [] ).map( ( l: any ) => ( {
        ...l,
        clicks: Number( l.clicks ) || 0,
        shortUrl: `https://${SHORT_LINK_BASE}/${l.shortCode}`,
      } ) ) );
    } catch ( err )
    {
      console.error( 'Load links error:', err );
      setLoadError( true );
      toast.error( 'Failed to load links' );
    } finally
    {
      setLoading( false );
    }
  }, [] );

  useEffect( () => { loadLinks(); }, [ loadLinks ] );

  const generateCode = () => {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let code = '';
    for ( let i = 0; i < 6; i++ ) code += chars[ Math.floor( Math.random() * chars.length ) ];
    setFormCode( code );
  };

  const resetForm = () => {
    setFormUrl( '' ); setFormTitle( '' ); setFormCode( '' ); setFormDeepLink( false );
    setFormIosUrl( '' ); setFormAndroidUrl( '' ); setFormExpiry( '' );
    setFormActive( true ); setEditingCode( null );
  };

  const openCreate = () => {
    resetForm();
    generateCode();
    setShowForm( true );
  };

  const openEdit = ( l: ShortLink ) => {
    setEditingCode( l.shortCode );
    setFormUrl( l.originalUrl || '' );
    setFormTitle( l.title || '' );
    setFormCode( l.shortCode );
    setFormDeepLink( !!l.deepLink );
    setFormIosUrl( l.iosUrl || '' );
    setFormAndroidUrl( l.androidUrl || '' );
    setFormExpiry( l.expiresAt || '' );
    setFormActive( l.active !== false );
    setShowForm( true );
  };

  const handleSave = async () => {
    if ( editingCode ) return handleUpdate();
    return handleCreate();
  };

  const handleUpdate = async () => {
    if ( !editingCode || !formUrl.trim() ) return;
    setCreating( true );
    try
    {
      const resp = await fetch( `${API_BASE}/links/${editingCode}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( {
          originalUrl: formUrl.trim(),
          title: formTitle.trim() || formUrl.trim(),
          deepLink: formDeepLink,
          iosUrl: formIosUrl || '',
          androidUrl: formAndroidUrl || '',
          expiresAt: formExpiry || '',
          active: formActive,
        } ),
      } );
      const data = await resp.json();
      if ( data.success )
      {
        toast.success( 'Link updated' );
        resetForm();
        setShowForm( false );
        loadLinks();
      } else
      {
        toast.error( data.error || 'Failed to update link' );
      }
    } catch
    {
      toast.error( 'Failed to update link' );
    } finally
    {
      setCreating( false );
    }
  };

  const handleCreate = async () => {
    if ( !formUrl.trim() ) return;
    setCreating( true );
    try
    {
      const resp = await fetch( `${API_BASE}/links`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( {
          shortCode: formCode.trim() || undefined,
          originalUrl: formUrl.trim(),
          title: formTitle.trim() || formUrl.trim(),
          deepLink: formDeepLink,
          iosUrl: formIosUrl || undefined,
          androidUrl: formAndroidUrl || undefined,
          expiresAt: formExpiry || undefined,
        } ),
      } );
      const data = await resp.json();
      if ( data.success )
      {
        toast.success( 'Link created' );
        resetForm();
        setShowForm( false );
        loadLinks();
      } else
      {
        toast.error( data.error || 'Failed to create link' );
      }
    } catch
    {
      toast.error( 'Failed to create link' );
    } finally
    {
      setCreating( false );
    }
  };

  const handleDelete = async ( code: string ) => {
    const ok = await confirm( 'Delete this short link? This cannot be undone.' );
    if ( !ok ) return;
    try
    {
      await fetch( `${API_BASE}/links/${code}`, { method: 'DELETE' } );
      toast.success( 'Link deleted' );
      loadLinks();
    } catch
    {
      toast.error( 'Failed to delete' );
    }
  };

  const handleAnalytics = async ( code: string ) => {
    if ( analyticsCode === code ) { setAnalyticsCode( null ); return; }
    try
    {
      const resp = await fetch( `${API_BASE}/links/${code}` );
      const data = await resp.json();
      setAnalyticsData( data );
      setAnalyticsCode( code );
    } catch
    {
      toast.error( 'Failed to load analytics' );
    }
  };

  const copyLink = ( url: string, code: string ) => {
    navigator.clipboard.writeText( url );
    setCopied( code );
    setTimeout( () => setCopied( null ), 2000 );
  };

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Link" description="URL shortener and deep links — wecare.digital/r" />
      <div className="link-page">
        <div className="link-page-header">
          <div>
            <h1>Link</h1>
            <p>URL shortener &amp; deep links via <strong>{ SHORT_LINK_BASE }</strong></p>
          </div>
          <Button variant="primary" onClick={ openCreate }>
            <PlusIcon size={ 14 } /> Create Short Link
          </Button>
        </div>

        <div className="link-stats">
          <div className="link-stat"><div className="link-stat-val">{ links.length }</div><div className="link-stat-lbl">Total Links</div></div>
          <div className="link-stat"><div className="link-stat-val">{ totalClicks }</div><div className="link-stat-lbl">Total Clicks</div></div>
          <div className="link-stat"><div className="link-stat-val">{ deepLinkCount }</div><div className="link-stat-lbl">Deep Links</div></div>
          <div className="link-stat"><div className="link-stat-val">{ SHORT_LINK_BASE }</div><div className="link-stat-lbl">Domain</div></div>
        </div>

        <div className="link-table-wrap">
          { loading ? (
            <div style={ { padding: 40, textAlign: 'center', color: '#6b7280' } }>Loading links...</div>
          ) : loadError ? (
            <div style={ { padding: 40, textAlign: 'center' } }><p style={ { color: '#991b1b', fontSize: 13, marginBottom: 8 } }>Failed to load links</p><button onClick={ () => loadLinks() } style={ { padding: '6px 14px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>Retry</button></div>
          ) : links.length === 0 ? (
            <div style={ { padding: 40, textAlign: 'center', color: '#6b7280' } }>No links yet. Create your first short link.</div>
          ) : (
            <table className="link-table" role="table" aria-label="Short links">
              <thead>
                <tr><th>Short URL</th><th>Destination</th><th>Title</th><th>Status</th><th>Clicks</th><th>Deep Link</th><th>Created</th><th>Actions</th></tr>
              </thead>
              <tbody>
                { links.map( l => (
                  <React.Fragment key={ l.shortCode }>
                    <tr>
                      <td><a href={ l.shortUrl } target="_blank" rel="noopener noreferrer" className="link-short-a">{ l.shortUrl.replace( 'https://', '' ) }</a></td>
                      <td style={ { maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, color: '#6b7280' } }>{ l.originalUrl }</td>
                      <td style={ { fontWeight: 500, fontSize: 13 } }>{ l.title }</td>
                      <td>{ l.active === false ? <span style={ { fontSize: 11, fontWeight: 600, color: '#9ca3af' } }>Disabled</span> : <span style={ { fontSize: 11, fontWeight: 600, color: '#1a7a4a' } }>Active</span> }</td>
                      <td style={ { fontWeight: 600, color: '#1a3a2a' } }>{ l.clicks }</td>
                      <td>{ l.deepLink ? <span className="link-deep-badge">iOS + Android</span> : <span style={ { color: '#9ca3af', fontSize: 12 } }>No</span> }</td>
                      <td style={ { fontSize: 12, color: '#6b7280' } }>{ l.createdAt ? new Date( l.createdAt ).toLocaleDateString() : '-' }</td>
                      <td>
                        <div className="link-actions">
                          <button className="link-act-btn" onClick={ () => copyLink( l.shortUrl, l.shortCode ) } title="Copy" aria-label="Copy link">
                            { copied === l.shortCode ? <span style={ { fontSize: 11, color: '#1a3a2a' } }>Copied</span> : <CopyIcon /> }
                          </button>
                          <button className="link-act-btn" onClick={ () => openEdit( l ) } title="Edit" aria-label="Edit link"><EditIcon /></button>
                          <button className="link-act-btn" onClick={ () => handleAnalytics( l.shortCode ) } title="Analytics" aria-label="View analytics"><BarChartIcon /></button>
                          <button className="link-act-btn danger" onClick={ () => handleDelete( l.shortCode ) } title="Delete" aria-label="Delete link"><TrashIcon /></button>
                        </div>
                      </td>
                    </tr>
                    { analyticsCode === l.shortCode && analyticsData && (
                      <tr><td colSpan={ 8 } style={ { background: '#f9fafb', padding: 12 } }>
                        <div style={ { fontSize: 12, color: '#374151' } }>
                          <strong>Recent Clicks ({ ( analyticsData.recentClicks || [] ).length })</strong>
                          { ( analyticsData.recentClicks || [] ).length === 0 ? <p style={ { color: '#9ca3af' } }>No clicks yet</p> : (
                            <div style={ { display: 'grid', gap: 4, marginTop: 6 } }>
                              { ( analyticsData.recentClicks || [] ).slice( 0, 10 ).map( ( c: any, i: number ) => (
                                <div key={ i } style={ { display: 'flex', gap: 12, fontSize: 11, color: '#6b7280' } }>
                                  <span>{ new Date( c.clickedAt ).toLocaleString() }</span>
                                  <span>{ c.platform }</span>
                                  <span>{ c.sourceIp }</span>
                                </div>
                              ) ) }
                            </div>
                          ) }
                        </div>
                      </td></tr>
                    ) }
                  </React.Fragment>
                ) ) }
              </tbody>
            </table>
          ) }
        </div>

        {/* Create / Edit Modal */ }
        { showForm && (
          <div className="link-modal-overlay" onClick={ () => { setShowForm( false ); resetForm(); } } role="dialog" aria-modal="true" aria-label={ editingCode ? 'Edit short link' : 'Create short link' }>
            <div className="link-modal" onClick={ e => e.stopPropagation() }>
              <div className="link-modal-bar" />
              <div className="link-modal-header">
                <h2>{ editingCode ? 'Edit Short Link' : 'Create Short Link' }</h2>
                <button className="link-modal-close" onClick={ () => { setShowForm( false ); resetForm(); } } aria-label="Close">&times;</button>
              </div>
              <div className="link-modal-body">
                <label className="link-label">
                  Destination URL <span style={ { color: '#dc2626' } }>*</span>
                  <input className="link-input" type="url" placeholder="https://example.com/page" value={ formUrl } onChange={ e => setFormUrl( e.target.value ) } autoFocus />
                </label>
                <label className="link-label">
                  Title
                  <input className="link-input" type="text" placeholder="My Link" value={ formTitle } onChange={ e => setFormTitle( e.target.value ) } />
                </label>
                <label className="link-label">
                  { editingCode ? 'Short Code' : 'Custom Code (optional)' }
                  <div style={ { display: 'flex', gap: 8, alignItems: 'center' } }>
                    <span style={ { fontSize: 13, color: '#6b7280', whiteSpace: 'nowrap' } }>{ SHORT_LINK_BASE }/</span>
                    <input className="link-input" type="text" placeholder={ formCode } value={ formCode } onChange={ e => setFormCode( e.target.value ) } style={ { flex: 1 } } disabled={ !!editingCode } />
                    { !editingCode && <button className="link-gen-btn" onClick={ generateCode } type="button">Random</button> }
                  </div>
                  { editingCode && <span style={ { fontSize: 11, color: '#9ca3af', marginTop: 4 } }>Short code can&apos;t be changed. Delete and recreate to use a different code.</span> }
                </label>

                <label className="link-label" style={ { flexDirection: 'row', alignItems: 'center', gap: 8 } }>
                  <input type="checkbox" checked={ formActive } onChange={ e => setFormActive( e.target.checked ) } />
                  <span>Active (link redirects when enabled)</span>
                </label>

                <label className="link-label" style={ { flexDirection: 'row', alignItems: 'center', gap: 8 } }>
                  <input type="checkbox" checked={ formDeepLink } onChange={ e => setFormDeepLink( e.target.checked ) } />
                  <span>Enable Deep Link (iOS / Android)</span>
                </label>

                { formDeepLink && (
                  <div className="link-deep-fields">
                    <label className="link-label">
                      iOS App URL
                      <input className="link-input" type="url" placeholder="myapp://path" value={ formIosUrl } onChange={ e => setFormIosUrl( e.target.value ) } />
                    </label>
                    <label className="link-label">
                      Android App URL
                      <input className="link-input" type="url" placeholder="myapp://path" value={ formAndroidUrl } onChange={ e => setFormAndroidUrl( e.target.value ) } />
                    </label>
                  </div>
                ) }

                { /* THE URL SHORTENER's expiry date, and the one date input an earlier revision
                     of the plan attributed to `pay/link`. There is no date input anywhere under
                     src/pages/workspace/pay/, and nothing in that directory is edited by this
                     batch. SHAPE (a): the wrapping <label className="link-label"> is gone, for
                     the reason DateField's header gives - a <label> around a text box plus a
                     trigger button names itself by walking both and double-activates the button
                     on a click. `.link-label` moves to the field wrapper - it is a global class
                     in flex-layout.css rather than styled-jsx, so it still applies - which keeps
                     the 13px type and the column layout the other seven fields have. ISO in, ISO
                     out, so `formExpiry` reaches handleSave unchanged. */ }
                <DateField className="link-label" label="Expiry Date (optional)" value={ formExpiry } onChange={ setFormExpiry } />
              </div>
              <div className="link-modal-footer">
                <button className="link-cancel-btn" onClick={ () => { setShowForm( false ); resetForm(); } }>Cancel</button>
                <Button variant="primary" onClick={ handleSave } disabled={ creating || !formUrl.trim() }>
                  { creating ? ( editingCode ? 'Saving...' : 'Creating...' ) : ( editingCode ? 'Save Changes' : 'Create Link' ) }
                </Button>
              </div>
            </div>
          </div>
        ) }

      </div>

      {/* Styles now in flex-layout.css — no inline styles needed */ }
    </Layout>
  );
};

export default LinkPage;