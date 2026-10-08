/**
 * WhatsApp Business Profile Management
 * View and update business profile for each phone number
 */
import React, { useState, useEffect } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { WHATSAPP_PHONES } from '../../../../config/constants';
import { RawJsonDrawer } from '../../../../components/wa';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const PHONES = [
  { id: WHATSAPP_PHONES.primary.id, metaId: '1016149501586345', display: WHATSAPP_PHONES.primary.display, name: WHATSAPP_PHONES.primary.name },
  { id: WHATSAPP_PHONES.secondary.id, metaId: '1055232054343117', display: WHATSAPP_PHONES.secondary.display, name: WHATSAPP_PHONES.secondary.name },
];

const VERTICALS = [ 'UNDEFINED', 'OTHER', 'AUTO', 'BEAUTY', 'APPAREL', 'EDU', 'ENTERTAIN', 'EVENT_PLAN', 'FINANCE', 'GROCERY', 'GOVT', 'HOTEL', 'HEALTH', 'NONPROFIT', 'PROF_SERVICES', 'RETAIL', 'TRAVEL', 'RESTAURANT', 'NOT_A_BIZ' ];

/** The leading '' row is the placeholder ROW, selectable exactly as the old `<option value="">` was. */
const VERTICAL_OPTIONS: SelectOption[] = [
  { value: '', label: 'Select...' },
  ...VERTICALS.map( v => ( { value: v, label: v.replace( /_/g, ' ' ) } ) ),
];

const BusinessProfilePage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ selectedPhone, setSelectedPhone ] = useState( PHONES[ 0 ] );
  const [ profile, setProfile ] = useState<any>( null );
  const [ loading, setLoading ] = useState( false );
  const [ saving, setSaving ] = useState( false );
  const [ form, setForm ] = useState( { about: '', description: '', email: '', address: '', websites: '', vertical: '' } );
  const [ phoneSettings, setPhoneSettings ] = useState<any>( null );
  const [ loadError, setLoadError ] = useState<string | null>( null );

  const loadProfile = async ( phone: typeof PHONES[ 0 ] ) => {
    setLoading( true );
    setLoadError( null );
    try
    {
      const [ p, s ] = await Promise.all( [
        api.getBusinessProfile( phone.metaId ),
        api.getPhoneSettings( phone.metaId ),
      ] );
      setProfile( p );
      setPhoneSettings( s );
      if ( p )
      {
        setForm( {
          about: p.about || '',
          description: p.description || '',
          email: p.email || '',
          address: p.address || '',
          websites: ( p.websites || [] ).join( ', ' ),
          vertical: p.vertical || '',
        } );
      } else
      {
        setLoadError( `Could not load business profile for ${phone.name} (${phone.display}). The Meta API may be temporarily unavailable. Try refreshing.` );
      }
    } catch ( e )
    {
      setLoadError( `Failed to load profile for ${phone.name} — check your Meta API token and permissions.` );
      toast.error( `Failed to load profile for ${phone.name}` );
    }
    setLoading( false );
  };

  useEffect( () => { loadProfile( selectedPhone ); }, [ selectedPhone ] );

  const handleSave = async () => {
    setSaving( true );
    try
    {
      const updates: any = {};
      if ( form.about ) updates.about = form.about;
      if ( form.description ) updates.description = form.description;
      if ( form.email ) updates.email = form.email;
      if ( form.address ) updates.address = form.address;
      if ( form.vertical ) updates.vertical = form.vertical;
      if ( form.websites.trim() ) updates.websites = form.websites.split( ',' ).map( ( w: string ) => w.trim() ).filter( Boolean );
      if ( Object.keys( updates ).length === 0 ) { toast.warning( 'No changes to save' ); setSaving( false ); return; }
      const ok = await api.updateBusinessProfile( selectedPhone.metaId, updates );
      if ( ok ) { toast.success( 'Profile updated' ); loadProfile( selectedPhone ); }
      else toast.error( 'Update failed' );
    } catch ( e ) { toast.error( 'Update failed' ); }
    setSaving( false );
  };

  const content = (
    <>
      <SEO title="Business Profile" description="WhatsApp Business Profile" noindex />
      <div className="inner-page-container" style={ { background: '#fff' } }>
        <h2 style={ { margin: '0 0 16px', fontSize: 20 } }>WhatsApp Business Profile</h2>

        <div style={ { display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' } }>
          { PHONES.map( p => (
            <button key={ p.id } onClick={ () => setSelectedPhone( p ) }
              style={ { padding: '8px 16px', borderRadius: 6, border: selectedPhone.id === p.id ? '2px solid #1a3a2a' : '1px solid #ddd', background: selectedPhone.id === p.id ? '#f9fafb' : '#fff', cursor: 'pointer', fontSize: 13 } }>
              { p.name } ({ p.display })
            </button>
          ) ) }
        </div>

        { loading ? <p>Loading...</p> : loadError ? (
          <div style={ { textAlign: 'center', padding: 40, color: '#666' } }>
            <p style={ { fontSize: 16, color: '#1a3a2a' } }>Profile Unavailable</p>
            <p style={ { fontSize: 13, marginTop: 8 } }>{ loadError }</p>
            <button onClick={ () => loadProfile( selectedPhone ) } style={ { marginTop: 12, padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 } }>
              Retry
            </button>
          </div>
        ) : (
          <>
            {/* Phone Info */ }
            { phoneSettings && (
              <div style={ { background: '#f9fafb', padding: 16, borderRadius: 8, marginBottom: 20, fontSize: 13 } }>
                <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 } }>
                  <div><span style={ { color: '#666' } }>Phone:</span> { phoneSettings.display_phone_number }</div>
                  <div><span style={ { color: '#666' } }>Name:</span> { phoneSettings.verified_name }</div>
                  <div><span style={ { color: '#666' } }>Quality:</span> <span style={ { color: phoneSettings.quality_rating === 'GREEN' ? '#1a3a2a' : '#1a3a2a' } }>{ phoneSettings.quality_rating }</span></div>
                  <div><span style={ { color: '#666' } }>Tier:</span> { phoneSettings.messaging_limit_tier }</div>
                  <div><span style={ { color: '#666' } }>Official:</span> { phoneSettings.is_official_business_account ? 'Yes' : 'No' }</div>
                  <div><span style={ { color: '#666' } }>Name Status:</span> { phoneSettings.name_status }</div>
                </div>
              </div>
            ) }

            {/* Profile Picture */ }
            { profile?.profile_picture_url && (
              <div style={ { marginBottom: 16 } }>
                <img src={ profile.profile_picture_url } alt="Profile" style={ { width: 80, height: 80, borderRadius: '50%', objectFit: 'cover' } } />
              </div>
            ) }

            {/* Edit Form */ }
            <div style={ { display: 'grid', gap: 16 } }>
              <div>
                <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 } }>About (max 139 chars)</label>
                <input value={ form.about } onChange={ e => setForm( { ...form, about: e.target.value } ) } maxLength={ 139 }
                  style={ { width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 } } />
              </div>
              <div>
                <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 } }>Description (max 512 chars)</label>
                <textarea value={ form.description } onChange={ e => setForm( { ...form, description: e.target.value } ) } maxLength={ 512 } rows={ 3 }
                  style={ { width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14, resize: 'vertical' } } />
              </div>
              <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 16 } }>
                <div>
                  <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 } }>Email</label>
                  <input value={ form.email } onChange={ e => setForm( { ...form, email: e.target.value } ) }
                    style={ { width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 } } />
                </div>
                <div>
                  <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 } }>Vertical</label>
                  <Select ariaLabel="Vertical" value={ form.vertical }
                    onChange={ v => setForm( { ...form, vertical: v } ) }
                    options={ VERTICAL_OPTIONS } />
                </div>
              </div>
              <div>
                <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 } }>Address</label>
                <input value={ form.address } onChange={ e => setForm( { ...form, address: e.target.value } ) }
                  style={ { width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 } } />
              </div>
              <div>
                <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 } }>Websites (comma-separated)</label>
                <input value={ form.websites } onChange={ e => setForm( { ...form, websites: e.target.value } ) } placeholder="https://wecare.digital, https://www.wecare.digital"
                  style={ { width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 } } />
              </div>
              <button onClick={ handleSave } disabled={ saving }
                style={ { padding: '10px 24px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14, width: 'fit-content' } }>
                { saving ? 'Saving...' : 'Save Profile' }
              </button>
              <RawJsonDrawer data={ { profile, phoneSettings } } label="Raw profile + settings JSON" />
            </div>
          </>
        ) }
      </div>
    </>
  );

  if ( embedded ) return content;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      { content }
    </Layout>
  );
};

export default BusinessProfilePage;
