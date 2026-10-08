/**
 * WhatsApp Groups Management — Full Feature
 * Cloud API Groups: create, manage, message, settings, privacy, image
 *
 * Limits: 512 participants/group, 10K groups/phone, invite-only
 * Messages: text, image, video, document, audio, templates (recipient_type=group)
 * Privacy: messaging_permission (all|admins), member_visibility (all|admins)
 * Ref: https://developers.facebook.com/docs/whatsapp/cloud-api
 */
import React, { useState, useEffect } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import * as api from '../../../../api/client';
import { MaskedWaId, useConfirmDanger } from '../../../../components/wa';
import { WHATSAPP_PHONES } from '../../../../config/constants';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
const MAX_P = 512;

const WABAS = [
  { id: WHATSAPP_PHONES.primary.wabaId, phoneId: WHATSAPP_PHONES.primary.id, metaId: WHATSAPP_PHONES.primary.metaPhoneId, name: WHATSAPP_PHONES.primary.name, display: WHATSAPP_PHONES.primary.display },
  { id: WHATSAPP_PHONES.secondary.wabaId, phoneId: WHATSAPP_PHONES.secondary.id, metaId: WHATSAPP_PHONES.secondary.metaPhoneId, name: WHATSAPP_PHONES.secondary.name, display: WHATSAPP_PHONES.secondary.display },
];

const pill = ( active: boolean ) => ( { padding: '4px 10px', fontSize: 12, border: active ? '2px solid #1a3a2a' : '1px solid #ddd', borderRadius: 4, background: active ? '#f0fdf4' : '#fff', cursor: 'pointer' } );
const btn = ( bg = '#d1f470', color = '#1a3a2a' ) => ( { padding: '6px 14px', fontSize: 12, background: bg, color, border: 'none', borderRadius: 6, cursor: 'pointer' } );
const card = { padding: 12, background: '#fff', borderRadius: 6, border: '1px solid #e5e7eb', marginBottom: 16 };

const NEW_APPROVAL_OPTIONS: SelectOption[] = [
  { value: 'auto_approve', label: 'Auto-approve joins' },
  { value: 'approval_required', label: 'Require approval' },
];
const MESSAGING_PERMISSION_OPTIONS: SelectOption[] = [
  { value: 'all', label: 'Everyone' },
  { value: 'admins', label: 'Admins only' },
];
const MEMBER_VISIBILITY_OPTIONS: SelectOption[] = [
  { value: 'all', label: 'All members visible' },
  { value: 'admins', label: 'Hidden (admins only)' },
];
const JOIN_APPROVAL_OPTIONS: SelectOption[] = [
  { value: 'auto_approve', label: 'Auto-approve' },
  { value: 'approval_required', label: 'Require approval' },
];
/** Layout only: the three settings rows are flex children beside a 140px caption. */
const SETTING_SELECT_STYLE: React.CSSProperties = { flex: '0 0 200px' };

const GroupsPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const confirm = useConfirm();
  const confirmDanger = useConfirmDanger();
  const [ waba, setWaba ] = useState( WABAS[ 0 ] );
  const [ groups, setGroups ] = useState<any[]>( [] );
  const [ loading, setLoading ] = useState( false );
  const [ showCreate, setShowCreate ] = useState( false );
  const [ newSubject, setNewSubject ] = useState( '' );
  const [ newDesc, setNewDesc ] = useState( '' );
  const [ newApproval, setNewApproval ] = useState( 'auto_approve' );
  const [ creating, setCreating ] = useState( false );
  const [ sel, setSel ] = useState<any>( null );
  const [ detail, setDetail ] = useState<any>( null );
  const [ msgText, setMsgText ] = useState( '' );
  const [ msgType, setMsgType ] = useState<'text' | 'image' | 'document'>( 'text' );
  const [ mediaUrl, setMediaUrl ] = useState( '' );
  const [ caption, setCaption ] = useState( '' );
  const [ sending, setSending ] = useState( false );
  const [ inviteLink, setInviteLink ] = useState( '' );
  const [ joinReqs, setJoinReqs ] = useState<any[]>( [] );
  const [ showSettings, setShowSettings ] = useState( false );
  const [ imageUrl, setImageUrl ] = useState( '' );

  const load = async ( w: typeof WABAS[ 0 ] ) => { setLoading( true ); try { setGroups( await api.listGroups( w.id, w.metaId ) ); } catch { toast.error( 'Failed to load groups' ); } setLoading( false ); };
  useEffect( () => { load( waba ); }, [ waba ] );

  const handleCreate = async () => {
    if ( !newSubject.trim() ) return;
    setCreating( true );
    try
    {
      const r = await api.createGroup( waba.metaId, newSubject.trim(), newDesc.trim() || undefined, undefined, newApproval );
      if ( r ) { toast.success( 'Group created — share invite link to add members' ); setShowCreate( false ); setNewSubject( '' ); setNewDesc( '' ); load( waba ); }
      else toast.error( 'Create failed' );
    } catch { toast.error( 'Create failed' ); }
    setCreating( false );
  };

  const viewDetail = async ( g: any ) => {
    setSel( g ); setInviteLink( '' ); setJoinReqs( [] ); setShowSettings( false );
    const d = await api.getGroup( g.id );
    setDetail( d );
  };

  const handleSend = async () => {
    if ( !sel ) return;
    setSending( true );
    try
    {
      if ( msgType === 'text' )
      {
        if ( !msgText.trim() ) { setSending( false ); return; }
        const r = await api.sendGroupMessage( waba.metaId, sel.id, msgText.trim() );
        if ( r?.success ) { toast.success( 'Sent' ); setMsgText( '' ); } else toast.error( 'Send failed' );
      } else
      {
        if ( !mediaUrl.trim() ) { toast.error( 'Media URL required' ); setSending( false ); return; }
        const r = await api.sendGroupMessage( waba.metaId, sel.id, '', { type: msgType, mediaUrl: mediaUrl.trim(), caption: caption.trim() || undefined } );
        if ( r?.success ) { toast.success( `${msgType} sent` ); setMediaUrl( '' ); setCaption( '' ); } else toast.error( 'Send failed' );
      }
    } catch { toast.error( 'Send failed' ); }
    setSending( false );
  };

  const handleUpdateSettings = async ( key: string, value: string ) => {
    if ( !sel ) return;
    const ok = await api.updateGroupSettings( sel.id, { [ key ]: value } as any );
    if ( ok ) { toast.success( `${key} updated` ); viewDetail( sel ); } else toast.error( 'Update failed' );
  };

  const handleSetImage = async () => {
    if ( !sel || !imageUrl.trim() ) return;
    const ok = await api.setGroupImage( sel.id, imageUrl.trim() );
    if ( ok ) { toast.success( 'Group image updated' ); setImageUrl( '' ); } else toast.error( 'Image upload failed' );
  };

  const pCount = detail?.total_participant_count || 0;
  const remaining = MAX_P - pCount;

  const content = (
    <>
      <SEO title="WhatsApp Groups" description="Manage WhatsApp Groups" noindex />
      <div className="inner-page-container" style={ { background: '#fff' } }>
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } }>
          <h2 style={ { margin: 0, fontSize: 20 } }>WhatsApp Groups</h2>
          <button onClick={ () => setShowCreate( true ) } style={ { ...btn(), padding: '8px 16px', border: '1.5px solid #1a3a2a', borderRadius: 13, fontSize: 13 } }>+ Create Group</button>
        </div>

        <div style={ { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: 14, marginBottom: 20, fontSize: 13 } }>
          <strong>Groups API</strong> — Up to { MAX_P } members/group (invite-only). Supports text, image, video, document, audio, and template messages.
          Privacy: admin-only posting, hidden member list. <a href="https://developers.facebook.com/docs/whatsapp/cloud-api" target="_blank" rel="noopener noreferrer" style={ { color: '#1a3a2a' } }>Docs ↗</a>
        </div>

        <div style={ { display: 'flex', gap: 8, marginBottom: 20 } }>
          { WABAS.map( w => (
            <button key={ w.id } onClick={ () => { setWaba( w ); setSel( null ); setDetail( null ); } }
              style={ { padding: '8px 16px', borderRadius: 6, border: waba.id === w.id ? '2px solid #1a3a2a' : '1px solid #ddd', background: waba.id === w.id ? '#f9fafb' : '#fff', cursor: 'pointer', fontSize: 13 } }>
              { w.name } ({ w.display })
            </button>
          ) ) }
        </div>

        { showCreate && (
          <div style={ { ...card, background: '#f9fafb', padding: 20, marginBottom: 20 } }>
            <h3 style={ { margin: '0 0 12px', fontSize: 16 } }>Create New Group</h3>
            <p style={ { fontSize: 12, color: '#666', margin: '0 0 12px' } }>Invite-only. Share the invite link after creation.</p>
            <div style={ { display: 'grid', gap: 10, marginBottom: 12 } }>
              <input value={ newSubject } onChange={ e => setNewSubject( e.target.value ) } placeholder="Group name" style={ { padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 } } />
              <input value={ newDesc } onChange={ e => setNewDesc( e.target.value ) } placeholder="Description (optional)" style={ { padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 } } />
              <Select ariaLabel="Join approval" value={ newApproval } onChange={ v => setNewApproval( v ) }
                options={ NEW_APPROVAL_OPTIONS } />
            </div>
            <div style={ { display: 'flex', gap: 8 } }>
              <button onClick={ handleCreate } disabled={ creating } style={ btn() }>{ creating ? 'Creating...' : 'Create' }</button>
              <button onClick={ () => setShowCreate( false ) } style={ { ...btn( '#fff', '#333' ), border: '1px solid #ddd' } }>Cancel</button>
            </div>
          </div>
        ) }

        { loading ? <p>Loading...</p> : groups.length === 0 ? (
          <div style={ { textAlign: 'center', padding: 40, color: '#666' } }><p>No groups found</p></div>
        ) : (
          <div style={ { display: 'grid', gap: 12 } }>
            { groups.map( g => (
              <div key={ g.id } style={ { ...card, marginBottom: 0 } }>
                <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                  <div>
                    <span style={ { fontWeight: 600, fontSize: 15 } }>{ g.subject || 'Unnamed' }</span>
                    { g.total_participant_count != null && <span style={ { marginLeft: 8, fontSize: 12, color: '#666' } }>{ g.total_participant_count }/{ MAX_P }</span> }
                  </div>
                  <div style={ { display: 'flex', gap: 6 } }>
                    <button onClick={ () => viewDetail( g ) } style={ pill( sel?.id === g.id ) }>Details</button>
                    <button onClick={ async () => { if ( await confirmDanger( 'delete', `Delete group "${g.subject || g.id}"? This cannot be undone.` ) ) { const ok = await api.deleteGroup( g.id ); if ( ok ) { toast.success( 'Deleted' ); setSel( null ); load( waba ); } } } }
                      style={ { ...pill( false ), background: '#fee2e2', color: '#991b1b', border: 'none' } }>Delete</button>
                  </div>
                </div>
                <div style={ { fontSize: 11, color: '#999', marginTop: 4 } }>{ g.id }</div>
              </div>
            ) ) }
          </div>
        ) }

        {/* Detail Panel */ }
        { sel && (
          <div style={ { marginTop: 20, background: '#f9fafb', padding: 20, borderRadius: 8, border: '1px solid #e5e7eb' } }>
            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } }>
              <h3 style={ { margin: 0, fontSize: 16 } }>{ detail?.subject || sel.subject || 'Group' }</h3>
              <div style={ { display: 'flex', gap: 6 } }>
                <button onClick={ () => setShowSettings( !showSettings ) } style={ pill( showSettings ) }>⚙ Settings</button>
                <button onClick={ () => { setSel( null ); setDetail( null ); setInviteLink( '' ); } } style={ pill( false ) }>Close</button>
              </div>
            </div>

            { detail && (
              <div style={ { fontSize: 13, marginBottom: 16, display: 'grid', gap: 4 } }>
                <div><span style={ { color: '#666' } }>Description:</span> { detail.description || 'None' }</div>
                <div><span style={ { color: '#666' } }>Join mode:</span> { detail.join_approval_mode || 'auto_approve' }</div>
                <div><span style={ { color: '#666' } }>Messaging:</span> { detail.messaging_permission === 'admins' ? '🔒 Admin-only' : '💬 Everyone can post' }</div>
                <div><span style={ { color: '#666' } }>Member visibility:</span> { detail.member_visibility === 'admins' ? '🔒 Hidden (admins only)' : '👥 Visible to all' }</div>
                <div><span style={ { color: '#666' } }>Participants:</span> <strong>{ pCount }/{ MAX_P }</strong> <span style={ { color: '#16a34a' } }>({ remaining } slots)</span></div>
                { detail.suspended && <div style={ { color: '#dc2626' } }>⚠ Suspended</div> }
              </div>
            ) }

            {/* Settings Panel */ }
            { showSettings && (
              <div style={ card }>
                <h4 style={ { fontSize: 14, margin: '0 0 12px' } }>Group Settings & Privacy</h4>
                <div style={ { display: 'grid', gap: 10 } }>
                  <div style={ { display: 'flex', alignItems: 'center', gap: 8 } }>
                    <span style={ { fontSize: 13, minWidth: 140 } }>Who can post:</span>
                    <Select ariaLabel="Who can post" value={ detail?.messaging_permission || 'all' }
                      onChange={ v => handleUpdateSettings( 'messaging_permission', v ) }
                      options={ MESSAGING_PERMISSION_OPTIONS } style={ SETTING_SELECT_STYLE } />
                  </div>
                  <div style={ { display: 'flex', alignItems: 'center', gap: 8 } }>
                    <span style={ { fontSize: 13, minWidth: 140 } }>Member visibility:</span>
                    <Select ariaLabel="Member visibility" value={ detail?.member_visibility || 'all' }
                      onChange={ v => handleUpdateSettings( 'member_visibility', v ) }
                      options={ MEMBER_VISIBILITY_OPTIONS } style={ SETTING_SELECT_STYLE } />
                  </div>
                  <div style={ { display: 'flex', alignItems: 'center', gap: 8 } }>
                    <span style={ { fontSize: 13, minWidth: 140 } }>Join approval:</span>
                    <Select ariaLabel="Join approval" value={ detail?.join_approval_mode || 'auto_approve' }
                      onChange={ v => handleUpdateSettings( 'join_approval_mode', v ) }
                      options={ JOIN_APPROVAL_OPTIONS } style={ SETTING_SELECT_STYLE } />
                  </div>
                  <div style={ { borderTop: '1px solid #e5e7eb', paddingTop: 10 } }>
                    <span style={ { fontSize: 13, color: '#666' } }>Group Image (URL to square PNG/JPG):</span>
                    <div style={ { display: 'flex', gap: 8, marginTop: 4 } }>
                      <input value={ imageUrl } onChange={ e => setImageUrl( e.target.value ) } placeholder="https://example.com/image.png"
                        style={ { flex: 1, padding: '6px 10px', border: '1px solid #ddd', borderRadius: 4, fontSize: 13 } } />
                      <button onClick={ handleSetImage } style={ btn() }>Set Image</button>
                    </div>
                  </div>
                </div>
              </div>
            ) }

            {/* Invite Link */ }
            <div style={ card }>
              <h4 style={ { fontSize: 14, margin: '0 0 8px' } }>Invite Link</h4>
              { inviteLink ? (
                <div style={ { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }>
                  <code style={ { fontSize: 12, background: '#f3f4f6', padding: '4px 8px', borderRadius: 4, wordBreak: 'break-all' } }>{ inviteLink }</code>
                  <button onClick={ () => { navigator.clipboard.writeText( inviteLink ); toast.success( 'Copied' ); } } style={ pill( false ) }>Copy</button>
                  <button onClick={ async () => { if ( await confirm( 'Reset link?' ) ) { const l = await api.resetGroupInviteLink( sel.id ); if ( l ) { setInviteLink( l ); toast.success( 'Reset' ); } } } }
                    style={ { ...pill( false ), color: '#991b1b', borderColor: '#fca5a5' } }>Reset</button>
                </div>
              ) : (
                <button onClick={ async () => { const l = await api.getGroupInviteLink( sel.id ); if ( l ) { setInviteLink( l ); toast.success( 'Fetched' ); } } } style={ btn() }>Get Invite Link</button>
              ) }
            </div>

            {/* Join Requests — shown for approval_required groups, also always show with a load button */ }
            <div style={ card }>
              <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } }>
                <h4 style={ { fontSize: 14, margin: 0 } }>Join Requests</h4>
                <div style={ { display: 'flex', gap: 6 } }>
                  { joinReqs.length > 0 && (
                    <button onClick={ async () => {
                      const ids = joinReqs.map( ( r: any ) => r.join_request_id );
                      await api.approveGroupJoinRequests( sel.id, ids );
                      toast.success( `Approved ${ids.length} request(s)` );
                      setJoinReqs( await api.getGroupJoinRequests( sel.id ) );
                      viewDetail( sel );
                    } } style={ btn() }>Approve All ({ joinReqs.length })</button>
                  ) }
                  <button onClick={ async () => { setJoinReqs( await api.getGroupJoinRequests( sel.id ) ); } } style={ pill( false ) }>Refresh</button>
                </div>
              </div>
              { joinReqs.length === 0 ? <p style={ { fontSize: 12, color: '#666', margin: 0 } }>No pending requests</p> : (
                <div style={ { display: 'grid', gap: 6 } }>
                  { joinReqs.map( ( r: any ) => (
                    <div key={ r.join_request_id } style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', background: '#f9fafb', borderRadius: 4 } }>
                      <span style={ { fontSize: 13 } }><MaskedWaId value={ r.wa_id } allowReveal /></span>
                      <div style={ { display: 'flex', gap: 4 } }>
                        <button onClick={ async () => { await api.approveGroupJoinRequests( sel.id, [ r.join_request_id ] ); toast.success( 'Approved' ); setJoinReqs( await api.getGroupJoinRequests( sel.id ) ); viewDetail( sel ); } } style={ btn() }>Approve</button>
                        <button onClick={ async () => { await api.rejectGroupJoinRequests( sel.id, [ r.join_request_id ] ); toast.success( 'Rejected' ); setJoinReqs( await api.getGroupJoinRequests( sel.id ) ); } } style={ { ...btn( '#fee2e2', '#991b1b' ) } }>Reject</button>
                      </div>
                    </div>
                  ) ) }
                </div>
              ) }
            </div>

            {/* Participants */ }
            { detail?.participants && (
              <div style={ { marginBottom: 16 } }>
                <h4 style={ { fontSize: 14, marginBottom: 8 } }>Participants ({ pCount })</h4>
                <div style={ { display: 'flex', flexWrap: 'wrap', gap: 6 } }>
                  { ( detail.participants.data || detail.participants || [] ).map( ( p: any, i: number ) => (
                    <span key={ i } style={ { padding: '4px 10px', background: '#e5e7eb', borderRadius: 16, fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 } }>
                      <MaskedWaId value={ p.wa_id || p } allowReveal />
                      <button onClick={ async () => { if ( await confirm( `Remove ${p.wa_id || p}?` ) ) { await api.manageGroupParticipants( sel.id, [ p.wa_id || p ], 'remove' ); toast.success( 'Removed' ); viewDetail( sel ); } } }
                        style={ { background: 'none', border: 'none', cursor: 'pointer', color: '#1a3a2a', fontSize: 14, padding: 0 } }>×</button>
                    </span>
                  ) ) }
                </div>
              </div>
            ) }

            {/* Send Message — supports text, image, document */ }
            <div style={ card }>
              <h4 style={ { fontSize: 14, margin: '0 0 8px' } }>Send Group Message</h4>
              <div style={ { display: 'flex', gap: 6, marginBottom: 8 } }>
                { ( [ 'text', 'image', 'document' ] as const ).map( t => (
                  <button key={ t } onClick={ () => setMsgType( t ) } style={ pill( msgType === t ) }>{ t === 'text' ? '💬 Text' : t === 'image' ? '🖼 Image' : '📄 Document' }</button>
                ) ) }
              </div>
              { msgType === 'text' ? (
                <div style={ { display: 'flex', gap: 8 } }>
                  <input value={ msgText } onChange={ e => setMsgText( e.target.value ) } placeholder="Type a message..."
                    style={ { flex: 1, padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 } }
                    onKeyDown={ e => e.key === 'Enter' && handleSend() } />
                  <button onClick={ handleSend } disabled={ sending } style={ btn() }>{ sending ? '...' : 'Send' }</button>
                </div>
              ) : (
                <div style={ { display: 'grid', gap: 8 } }>
                  <input value={ mediaUrl } onChange={ e => setMediaUrl( e.target.value ) } placeholder={ `${msgType === 'image' ? 'Image' : 'Document'} URL (https://...)` }
                    style={ { padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 13 } } />
                  <input value={ caption } onChange={ e => setCaption( e.target.value ) } placeholder="Caption (optional)"
                    style={ { padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 13 } } />
                  <button onClick={ handleSend } disabled={ sending } style={ { ...btn(), width: 'fit-content' } }>{ sending ? 'Sending...' : `Send ${msgType}` }</button>
                </div>
              ) }
            </div>
          </div>
        ) }
      </div>
    </>
  );

  if ( embedded ) return content;
  return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default GroupsPage;
