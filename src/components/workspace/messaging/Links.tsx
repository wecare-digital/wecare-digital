/**
 * Link Page - URL Shortener & Deep Links
 *
 * New links are minted under the canonical apex path wecare.digital/r.
 *
 * General-purpose short links, click tracking, deep links for iOS/Android
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../Layout';
import SEO from '../../SEO';
import Button from '../../ui/Button';
import DateField from '../../ui/DateField';
import { useToastContext } from '../../../contexts/ToastContext';
import { useActionCopy } from '../../../hooks/useActionCopy';
import { useConfirm } from '../../../contexts/ConfirmContext';

// The link CRUD API. wecare.digital/api is now the ONLY way to reach HTTP API
// zllr9lrg7j through the canonical apex rewrite; the API is reached through the
// Amplify /api/<*> rewrite. This constant was already pointed at the apex before the
// retirement, which is why the dashboard was unaffected by it.
const API_BASE = process.env.NEXT_PUBLIC_LINK_API_BASE || 'https://wecare.digital/api';

// The base shown to an operator and used to build a copyable link. Display only —
// what actually gets stored comes back from the Lambda's SHORT_LINK_BASE.
const SHORT_LINK_BASE = 'wecare.digital/r';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

// The lifecycle a short link moves through. ACTIVE <-> INACTIVE is reversible; RETIRED is
// terminal (the code is spent for good, but the row and its click history survive as audit).
// The backend is the authority on legal transitions — this list exists so the UI can label and
// gate the controls without re-deriving the rule.
type LinkLifecycle = 'ACTIVE' | 'INACTIVE' | 'RETIRED';

// The record a link may optionally be attached to. 'general' is the unattached default.
type RelatedType = 'general' | 'customer' | 'campaign' | 'order' | 'invoice' | 'service';

const RELATED_OPTIONS: Array<{ value: RelatedType; label: string }> = [
  { value: 'general', label: 'General (no record)' },
  { value: 'customer', label: 'Customer' },
  { value: 'campaign', label: 'Campaign' },
  { value: 'order', label: 'Order' },
  { value: 'invoice', label: 'Invoice / payment' },
  { value: 'service', label: 'Service request' },
];

const RELATED_LABEL: Record<RelatedType, string> = {
  general: 'General', customer: 'Customer', campaign: 'Campaign',
  order: 'Order', invoice: 'Invoice', service: 'Service',
};

const LIFECYCLE_PAINT: Record<LinkLifecycle, { label: string; color: string }> = {
  ACTIVE: { label: 'Active', color: '#1a7a4a' },
  INACTIVE: { label: 'Inactive', color: '#b45309' },
  RETIRED: { label: 'Retired', color: '#9ca3af' },
};

// Resolve a link's lifecycle from the record. New rows carry lifecycleState; legacy rows carry
// only `active`, and a missing/true `active` reads as ACTIVE while an explicit false reads as
// INACTIVE (never RETIRED — that is a deliberate terminal decision nothing legacy recorded).
function resolveLifecycle ( l: ShortLink ): LinkLifecycle {
  if ( l.lifecycleState === 'ACTIVE' || l.lifecycleState === 'INACTIVE' || l.lifecycleState === 'RETIRED' ) {
    return l.lifecycleState;
  }
  return l.active === false ? 'INACTIVE' : 'ACTIVE';
}

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
  lifecycleState?: LinkLifecycle;
  purpose?: string;
  relatedType?: RelatedType;
  relatedId?: string;
}

/* ── Icons ── */
const LinkIcon = ( { size = 18 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
  </svg>
);
const CopyIcon = ( { size = 14 }: { size?: number } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
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

const LinksPanel: React.FC<PageProps> = ( { signOut, user, embedded } ) => {
  const [ links, setLinks ] = useState<ShortLink[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ loadError, setLoadError ] = useState( false );
  const [ creating, setCreating ] = useState( false );
  const [ showForm, setShowForm ] = useState( false );
  const [ formUrl, setFormUrl ] = useState( '' );
  const [ formTitle, setFormTitle ] = useState( '' );
  const [ formCode, setFormCode ] = useState( '' );
  const [ formDeepLink, setFormDeepLink ] = useState( false );
  const [ formIosUrl, setFormIosUrl ] = useState( '' );
  const [ formAndroidUrl, setFormAndroidUrl ] = useState( '' );
  const [ formExpiry, setFormExpiry ] = useState( '' );
  const [ formActive, setFormActive ] = useState( true );
  const [ formPurpose, setFormPurpose ] = useState( '' );
  const [ formRelatedType, setFormRelatedType ] = useState<RelatedType>( 'general' );
  const [ formRelatedId, setFormRelatedId ] = useState( '' );
  const [ editingCode, setEditingCode ] = useState<string | null>( null );
  const [ editingRetired, setEditingRetired ] = useState( false );
  const [ analyticsCode, setAnalyticsCode ] = useState<string | null>( null );
  const [ analyticsData, setAnalyticsData ] = useState<any>( null );

  const toast = useToastContext();
  const copyAction = useActionCopy();
  const confirm = useConfirm();

  const totalClicks = links.reduce( ( s, l ) => s + ( Number( l.clicks ) || 0 ), 0 );
  const deepLinkCount = links.filter( l => l.deepLink ).length;

  const loadLinks = useCallback( async () => {
    setLoading( true );
    setLoadError( false );
    try
    {
      const resp = await fetch( `${API_BASE}/links` );
      if ( !resp.ok ) throw new Error( 'Links unavailable' );
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
  }, [ toast ] );

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
    setFormActive( true ); setFormPurpose( '' ); setFormRelatedType( 'general' );
    setFormRelatedId( '' ); setEditingCode( null ); setEditingRetired( false );
  };

  const openCreate = () => {
    resetForm();
    generateCode();
    setShowForm( true );
  };

  const openEdit = ( l: ShortLink ) => {
    const lifecycle = resolveLifecycle( l );
    setEditingCode( l.shortCode );
    setEditingRetired( lifecycle === 'RETIRED' );
    setFormUrl( l.originalUrl || '' );
    setFormTitle( l.title || '' );
    setFormCode( l.shortCode );
    setFormDeepLink( !!l.deepLink );
    setFormIosUrl( l.iosUrl || '' );
    setFormAndroidUrl( l.androidUrl || '' );
    setFormExpiry( l.expiresAt || '' );
    setFormActive( lifecycle === 'ACTIVE' );
    setFormPurpose( l.purpose || '' );
    setFormRelatedType( ( l.relatedType as RelatedType ) || 'general' );
    setFormRelatedId( l.relatedId || '' );
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
          purpose: formPurpose.trim(),
          relatedType: formRelatedType,
          relatedId: formRelatedId.trim(),
          deepLink: formDeepLink,
          iosUrl: formIosUrl || '',
          androidUrl: formAndroidUrl || '',
          expiresAt: formExpiry || '',
          // active maps server-side to the reversible ACTIVE <-> INACTIVE move. Retirement is a
          // separate, deliberate action (handleRetire), never a side effect of an edit.
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
          purpose: formPurpose.trim() || undefined,
          relatedType: formRelatedType,
          relatedId: formRelatedId.trim() || undefined,
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

  const handleDeactivate = async ( code: string ) => {
    const ok = await confirm( 'Deactivate this short link? Existing copies will stop redirecting, but the record and click history are preserved.' );
    if ( !ok ) return;
    try
    {
      const resp = await fetch( `${API_BASE}/links/${code}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { active: false } ),
      } );
      const data = await resp.json();
      if ( !resp.ok || !data.success )
      {
        toast.error( data.error || 'Failed to deactivate link' );
        return;
      }
      toast.success( 'Link deactivated' );
      loadLinks();
    } catch
    {
      toast.error( 'Failed to deactivate link' );
    }
  };

  const handleReactivate = async ( code: string ) => {
    try
    {
      const resp = await fetch( `${API_BASE}/links/${code}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { active: true } ),
      } );
      const data = await resp.json();
      if ( !resp.ok || !data.success )
      {
        toast.error( data.error || 'Failed to reactivate link' );
        return;
      }
      toast.success( 'Link reactivated' );
      loadLinks();
    } catch
    {
      toast.error( 'Failed to reactivate link' );
    }
  };

  // Retire is the one irreversible action, and it is deliberately NOT a delete: the row and its
  // click history are kept as audit, the code simply never resolves again. A retired link lives
  // on cards/QRs/sent messages, so destroying it would strand every copy and discard the audit.
  const handleRetire = async ( code: string ) => {
    const ok = await confirm( 'Retire this short link permanently? It will stop redirecting for good and cannot be reactivated. The record and click history are kept for audit. Prefer Deactivate if you may need it again.' );
    if ( !ok ) return;
    try
    {
      const resp = await fetch( `${API_BASE}/links/${code}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { lifecycleState: 'RETIRED' } ),
      } );
      const data = await resp.json();
      if ( !resp.ok || !data.success )
      {
        toast.error( data.error || 'Failed to retire link' );
        return;
      }
      toast.success( 'Link retired' );
      loadLinks();
    } catch
    {
      toast.error( 'Failed to retire link' );
    }
  };

  const handleAnalytics = async ( code: string ) => {
    if ( analyticsCode === code ) { setAnalyticsCode( null ); return; }
    try
    {
      const resp = await fetch( `${API_BASE}/links/${code}` );
      if ( !resp.ok ) throw new Error( 'Link analytics unavailable' );
      const data = await resp.json();
      if ( data?.success === false ) throw new Error( 'Link analytics unavailable' );
      setAnalyticsData( data );
      setAnalyticsCode( code );
    } catch
    {
      toast.error( 'Failed to load analytics' );
    }
  };

  const content = (
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
            <div style={ { padding: 40, textAlign: 'center', color: 'var(--text-muted)' } }>Loading links...</div>
          ) : loadError ? (
            <div style={ { padding: 40, textAlign: 'center' } }><p style={ { color: '#991b1b', fontSize: 'var(--text-sm)', marginBottom: 8 } }>Failed to load links</p><button onClick={ () => loadLinks() } style={ { padding: '6px 14px', background: 'var(--lime)', color: 'var(--accent)', border: 'none', borderRadius: 13, fontSize: 'var(--text-xs)', fontWeight: 600, cursor: 'pointer' } }>Retry</button></div>
          ) : links.length === 0 ? (
            <div style={ { padding: 40, textAlign: 'center', color: 'var(--text-muted)' } }>No links yet. Create your first short link.</div>
          ) : (
            <table className="link-table" role="table" aria-label="Short links">
              <thead>
                <tr><th>Short URL</th><th>Destination</th><th>Title</th><th>Related</th><th>Status</th><th>Clicks</th><th>Deep Link</th><th>Created</th><th>Actions</th></tr>
              </thead>
              <tbody>
                { links.map( l => {
                  const lifecycle = resolveLifecycle( l );
                  const paint = LIFECYCLE_PAINT[ lifecycle ];
                  const related = ( l.relatedType as RelatedType ) || 'general';
                  return (
                  <React.Fragment key={ l.shortCode }>
                    <tr>
                      <td><a href={ l.shortUrl } target="_blank" rel="noopener noreferrer" className="link-short-a">{ l.shortUrl.replace( 'https://', '' ) }</a></td>
                      <td style={ { maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ l.originalUrl }</td>
                      <td style={ { fontWeight: 500, fontSize: 'var(--text-sm)' } }>{ l.title }</td>
                      <td style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>
                        { related === 'general'
                          ? <span style={ { color: '#9ca3af' } }>General</span>
                          : <span>{ RELATED_LABEL[ related ] }{ l.relatedId ? <span style={ { color: '#9ca3af' } }> · { l.relatedId }</span> : null }</span> }
                      </td>
                      <td><span style={ { fontSize: 'var(--text-xs)', fontWeight: 600, color: paint.color } }>{ paint.label }</span></td>
                      <td style={ { fontWeight: 600, color: 'var(--accent)' } }>{ l.clicks }</td>
                      <td>{ l.deepLink ? <span className="link-deep-badge">iOS + Android</span> : <span style={ { color: '#9ca3af', fontSize: 'var(--text-xs)' } }>No</span> }</td>
                      <td style={ { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>{ l.createdAt ? new Date( l.createdAt ).toLocaleDateString() : '-' }</td>
                      <td>
                        <div className="link-actions">
                          <button className="link-act-btn" onClick={ () => { void copyAction( l.shortUrl ); } } title="Copy" aria-label="Copy link">
                            <CopyIcon />
                          </button>
                          <button className="link-act-btn" onClick={ () => openEdit( l ) } title="Edit" aria-label="Edit link" disabled={ lifecycle === 'RETIRED' }><EditIcon /></button>
                          <button className="link-act-btn" onClick={ () => handleAnalytics( l.shortCode ) } title="Analytics" aria-label="View analytics"><BarChartIcon /></button>
                          { lifecycle === 'ACTIVE' && (
                            <button className="link-act-btn" onClick={ () => handleDeactivate( l.shortCode ) } title="Deactivate" aria-label="Deactivate link">Off</button>
                          ) }
                          { lifecycle === 'INACTIVE' && (
                            <button className="link-act-btn" onClick={ () => handleReactivate( l.shortCode ) } title="Reactivate" aria-label="Reactivate link">On</button>
                          ) }
                          { lifecycle !== 'RETIRED' && (
                            <button className="link-act-btn danger" onClick={ () => handleRetire( l.shortCode ) } title="Retire permanently" aria-label="Retire link">Retire</button>
                          ) }
                        </div>
                      </td>
                    </tr>
                    { analyticsCode === l.shortCode && analyticsData && (
                      <tr><td colSpan={ 9 } style={ { background: 'var(--bg-secondary)', padding: 12 } }>
                        <div style={ { fontSize: 'var(--text-xs)', color: '#374151' } }>
                          <strong>Recent Clicks ({ ( analyticsData.recentClicks || [] ).length })</strong>
                          { ( analyticsData.recentClicks || [] ).length === 0 ? <p style={ { color: '#9ca3af' } }>No clicks yet</p> : (
                            <div style={ { display: 'grid', gap: 4, marginTop: 6 } }>
                              { ( analyticsData.recentClicks || [] ).slice( 0, 10 ).map( ( c: any, i: number ) => (
                                <div key={ i } style={ { display: 'flex', gap: 12, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }>
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
                  );
                } ) }
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
                  Purpose
                  <input className="link-input" type="text" placeholder="Why this link exists (e.g. Diwali campaign CTA)" value={ formPurpose } onChange={ e => setFormPurpose( e.target.value ) } />
                </label>
                <div className="link-deep-fields">
                  <label className="link-label">
                    Attach to record
                    <select className="link-input" value={ formRelatedType } onChange={ e => setFormRelatedType( e.target.value as RelatedType ) }>
                      { RELATED_OPTIONS.map( o => <option key={ o.value } value={ o.value }>{ o.label }</option> ) }
                    </select>
                  </label>
                  { formRelatedType !== 'general' && (
                    <label className="link-label">
                      { RELATED_LABEL[ formRelatedType ] } ID
                      <input className="link-input" type="text" placeholder="Record identifier" value={ formRelatedId } onChange={ e => setFormRelatedId( e.target.value ) } />
                    </label>
                  ) }
                </div>
                <label className="link-label">
                  { editingCode ? 'Short Code' : 'Custom Code (optional)' }
                  <div style={ { display: 'flex', gap: 8, alignItems: 'center' } }>
                    <span style={ { fontSize: 'var(--text-sm)', color: 'var(--text-muted)', whiteSpace: 'nowrap' } }>{ SHORT_LINK_BASE }/</span>
                    <input className="link-input" type="text" placeholder={ formCode } value={ formCode } onChange={ e => setFormCode( e.target.value ) } style={ { flex: 1 } } disabled={ !!editingCode } />
                    { !editingCode && <button className="link-gen-btn" onClick={ generateCode } type="button">Random</button> }
                  </div>
                  { editingCode && <span style={ { fontSize: 'var(--text-xs)', color: '#9ca3af', marginTop: 4 } }>Short code can&apos;t be changed. Create a new link to use a different code.</span> }
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
                     out, so `formExpiry` reaches handleSave unchanged.

                     layer="overlay" IS REQUIRED, not a precaution. This field is only ever
                     rendered inside `.link-modal-overlay`, which is position:fixed inset:0 at
                     `z-index: 9999` (flex-layout.css:329-337), and the Popover portals to
                     document.body - so at its default 1500 the calendar paints BEHIND both the
                     veil and the opaque `.link-modal`, hidden rather than merely dimmed, in the
                     one place this control exists. 10001 clears the overlay and still loses to
                     the 10002 toast band, which is the ordering design 5.1 picked. */ }
                <DateField className="link-label" label="Expiry Date (optional)" value={ formExpiry } onChange={ setFormExpiry } layer="overlay" />
              </div>
              <div className="link-modal-footer">
                <button className="link-cancel-btn" onClick={ () => { setShowForm( false ); resetForm(); } }>Cancel</button>
                <Button variant="primary" onClick={ handleSave } disabled={ creating || editingRetired || !formUrl.trim() }>
                  { creating ? ( editingCode ? 'Saving...' : 'Creating...' ) : ( editingCode ? 'Save Changes' : 'Create Link' ) }
                </Button>
              </div>
            </div>
          </div>
        ) }

      </div>

  );

  if ( embedded ) return content;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Links" description="URL shortener and deep links — wecare.digital/r" />
      { content }
    </Layout>
  );
};

export default LinksPanel;