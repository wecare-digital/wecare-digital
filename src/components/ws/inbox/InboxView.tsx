/**
 * InboxView — the fresh, mobile-first conversation inbox for /ws/inbox (FEAT-004).
 *
 * Built ground-up for /ws; it does NOT copy the 138KB legacy inbox
 * (src/pages/workspace/engage/inbox/index.tsx). From that file it borrows only the DATA MODEL,
 * not the layout:
 *   - read every channel's messages once with api.listMessages(undefined, 'ALL', limit),
 *   - group them into conversations by contactId (falling back to senderPhone / receivingPhone),
 *   - resolve participant names with api.listContacts,
 *   - tell an empty table apart from a failed read with api.collectApiFailures (listMessages /
 *     listContacts both return [] on failure, so a bare catch would render "No conversations"
 *     over an outage).
 *
 * LAYOUT is phone-first and a clean rebuild:
 *   - Mobile (<768px): master/detail that swaps full-screen — the conversation LIST, or an opened
 *     THREAD with a back button. Only one is on screen at a time.
 *   - Desktop (>=768px): list and thread side by side.
 *
 * Message bubbles read the normalized Message fields (direction, content, timestamp, channel,
 * isRevoked). Selecting a thread loads its team-inbox meta via api.getConversationMeta (read-only
 * here; status is shown as a small badge).
 *
 * SEND is included only for WhatsApp threads that have a saved contactId, and it uses the existing
 * api.sendWhatsAppMessage export — never a new endpoint and never a bare fetch. Any other channel,
 * or a phone-only thread with no saved contact, shows a clear read-only notice instead of a broken
 * composer. React 19: icon helpers typed React.JSX.Element.
 */
import React from 'react';
import type { Message, Contact, ConversationMeta, ApiFailure } from '../../../api/client';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';

interface Conversation {
  key: string;
  contactId: string;     // '' when the thread is phone-only (no saved contact)
  title: string;
  subtitle: string;
  channel: Message['channel'];
  last: Message;
  count: number;
}

const CHANNEL_LABEL: Record<Message['channel'], string> = {
  WHATSAPP: 'WhatsApp',
  SMS: 'SMS',
  EMAIL: 'Email',
  RCS: 'RCS',
  VOICE: 'Voice',
};

const BackGlyph = (): React.JSX.Element => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m15 6-6 6 6 6" />
  </svg>
);

const SendGlyph = (): React.JSX.Element => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 12 20 4l-6 16-3-7-7-1Z" />
  </svg>
);

function convKeyOf ( m: Message ): string {
  return m.contactId || m.senderPhone || m.receivingPhone || 'unknown';
}

function initialsOf ( label: string ): string {
  const source = ( label || '?' ).trim();
  const parts = source.split( /\s+/ ).filter( Boolean );
  if ( parts.length >= 2 ) return ( parts[ 0 ][ 0 ] + parts[ 1 ][ 0 ] ).toUpperCase();
  return source.slice( 0, 2 ).toUpperCase();
}

function timeShort ( iso: string ): string {
  const d = new Date( iso );
  if ( Number.isNaN( d.getTime() ) ) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if ( sameDay ) return d.toLocaleTimeString( [], { hour: 'numeric', minute: '2-digit' } );
  const year = d.getFullYear() === now.getFullYear();
  return d.toLocaleDateString( [], year ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' } );
}

function timeFull ( iso: string ): string {
  const d = new Date( iso );
  if ( Number.isNaN( d.getTime() ) ) return '';
  return d.toLocaleString( [], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' } );
}

function previewText ( m: Message ): string {
  if ( m.isRevoked ) return 'Message deleted';
  const body = ( m.content || '' ).trim();
  if ( body ) return body;
  if ( m.messageType && m.messageType !== 'text' ) return `[${ m.messageType }]`;
  return '…';
}

const InboxView: React.FC = () => {
  const toast = useToastContext();

  const [ messages, setMessages ] = React.useState<Message[]>( [] );
  const [ names, setNames ] = React.useState<Record<string, string>>( {} );
  const [ loading, setLoading ] = React.useState( true );
  const [ failure, setFailure ] = React.useState<ApiFailure | null>( null );
  const [ query, setQuery ] = React.useState( '' );

  const [ selected, setSelected ] = React.useState<string | null>( null );
  const [ meta, setMeta ] = React.useState<ConversationMeta | null>( null );

  const [ draft, setDraft ] = React.useState( '' );
  const [ sending, setSending ] = React.useState( false );

  const load = React.useCallback( async () => {
    setFailure( null );
    try {
      // Both calls return [] on failure as well as on an empty table, so a bare catch would
      // render "No conversations" over an outage. collectApiFailures recovers the reason.
      const { data: [ msgs, contacts ], failures } = await api.collectApiFailures( () => Promise.all( [
        api.listMessages( undefined, 'ALL', 2000 ),
        api.listContacts(),
      ] ) );
      setFailure( failures[ 0 ] ?? null );
      const dir: Record<string, string> = {};
      ( contacts as Contact[] ).forEach( c => { dir[ c.contactId ] = c.name || c.email || c.phone || ''; } );
      setNames( dir );
      setMessages( msgs as Message[] );
    } catch {
      setFailure( {
        kind: 'network',
        status: null,
        message: 'The inbox could not be loaded.',
        url: '',
        retryable: true,
        at: Date.now(),
      } );
    } finally {
      setLoading( false );
    }
  }, [] );

  React.useEffect( () => { void load(); }, [ load ] );

  // Read-only team-inbox meta for the selected thread (status badge only here).
  React.useEffect( () => {
    setMeta( null );
    if ( selected ) api.getConversationMeta( selected ).then( setMeta ).catch( () => {} );
  }, [ selected ] );

  // Reset the composer when switching threads.
  React.useEffect( () => { setDraft( '' ); }, [ selected ] );

  const conversations = React.useMemo<Conversation[]>( () => {
    const map = new Map<string, Conversation>();
    for ( const m of messages ) {
      const key = convKeyOf( m );
      const title = names[ m.contactId ] || m.senderName || m.senderPhone || m.receivingPhone || m.contactId || 'Unknown';
      const existing = map.get( key );
      if ( !existing ) {
        map.set( key, {
          key,
          contactId: m.contactId || '',
          title,
          subtitle: previewText( m ),
          channel: m.channel,
          last: m,
          count: 1,
        } );
      } else {
        existing.count += 1;
        if ( new Date( m.timestamp ).getTime() >= new Date( existing.last.timestamp ).getTime() ) {
          existing.last = m;
          existing.subtitle = previewText( m );
          existing.channel = m.channel;
        }
        if ( !existing.contactId && m.contactId ) existing.contactId = m.contactId;
        if ( ( !existing.title || existing.title === 'Unknown' ) && title ) existing.title = title;
      }
    }
    return Array.from( map.values() ).sort(
      ( a, b ) => new Date( b.last.timestamp ).getTime() - new Date( a.last.timestamp ).getTime()
    );
  }, [ messages, names ] );

  const filtered = React.useMemo( () => {
    const q = query.trim().toLowerCase();
    if ( !q ) return conversations;
    return conversations.filter( c =>
      c.title.toLowerCase().includes( q ) || c.subtitle.toLowerCase().includes( q ) );
  }, [ conversations, query ] );

  const selectedConv = React.useMemo(
    () => conversations.find( c => c.key === selected ) || null,
    [ conversations, selected ]
  );

  const thread = React.useMemo<Message[]>( () => {
    if ( !selected ) return [];
    return messages
      .filter( m => convKeyOf( m ) === selected )
      .slice()
      .sort( ( a, b ) => new Date( a.timestamp ).getTime() - new Date( b.timestamp ).getTime() );
  }, [ messages, selected ] );

  // Send is only wired for a WhatsApp thread with a saved contactId (the one clean existing
  // export, api.sendWhatsAppMessage). Everything else stays read-only.
  const canSend = !!selectedConv && selectedConv.channel === 'WHATSAPP' && !!selectedConv.contactId;

  const send = async () => {
    const text = draft.trim();
    if ( !canSend || !selectedConv || !text || sending ) return;
    setSending( true );
    try {
      const res = await api.sendWhatsAppMessage( { contactId: selectedConv.contactId, content: text } );
      if ( res && res.messageId ) {
        setDraft( '' );
        toast.success( 'Message sent.' );
        await load();
      } else {
        toast.error( 'Message could not be sent.' );
      }
    } catch {
      toast.error( 'Message could not be sent.' );
    } finally {
      setSending( false );
    }
  };

  const showThreadPane = selected !== null;

  return (
    <section className={ `ib ${ showThreadPane ? 'ib-thread-open' : '' }` }>
      {/* ---- LIST PANE ---- */}
      <div className="ib-list-pane">
        <header className="ib-head">
          <div className="ib-titleblock">
            <p className="ib-eyebrow">Workspace / Inbox</p>
            <h1 className="ib-title">Inbox</h1>
          </div>
          <label className="ib-search">
            <span className="ib-search-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
              </svg>
            </span>
            <input
              type="search"
              className="ib-search-input"
              placeholder="Search conversations"
              value={ query }
              onChange={ e => setQuery( e.target.value ) }
              aria-label="Search conversations"
            />
          </label>
        </header>

        { loading ? (
          <p className="ib-note">Loading conversations…</p>
        ) : failure ? (
          <div className="ib-error" role="alert">
            <p>{ failure.message || 'The inbox could not be loaded.' }</p>
            <button type="button" className="ib-ghost" onClick={ () => void load() }>Retry</button>
          </div>
        ) : filtered.length === 0 ? (
          <p className="ib-note">{ query ? 'No conversations match your search.' : 'No conversations yet.' }</p>
        ) : (
          <ul className="ib-list" data-wc-no-translate="true">
            { filtered.map( c => (
              <li key={ c.key }>
                <button
                  type="button"
                  className={ `ib-row ${ c.key === selected ? 'active' : '' }` }
                  onClick={ () => setSelected( c.key ) }
                  aria-current={ c.key === selected ? 'true' : undefined }
                >
                  <span className="ib-avatar" aria-hidden="true">{ initialsOf( c.title ) }</span>
                  <span className="ib-rowmeta">
                    <span className="ib-rowtop">
                      <span className="ib-rowname">{ c.title }</span>
                      <span className="ib-rowtime">{ timeShort( c.last.timestamp ) }</span>
                    </span>
                    <span className="ib-rowbottom">
                      <span className="ib-rowpreview">{ c.subtitle }</span>
                      <span className="ib-rowchannel">{ CHANNEL_LABEL[ c.channel ] }</span>
                    </span>
                  </span>
                </button>
              </li>
            ) ) }
          </ul>
        ) }
      </div>

      {/* ---- THREAD PANE ---- */}
      <div className="ib-thread-pane">
        { !selectedConv ? (
          <div className="ib-empty">
            <p>Select a conversation to read it.</p>
          </div>
        ) : (
          <>
            <header className="ib-thead">
              <button type="button" className="ib-back" onClick={ () => setSelected( null ) } aria-label="Back to conversations">
                <BackGlyph />
              </button>
              <span className="ib-thead-avatar" aria-hidden="true">{ initialsOf( selectedConv.title ) }</span>
              <span className="ib-thead-meta">
                <span className="ib-thead-name">{ selectedConv.title }</span>
                <span className="ib-thead-sub">
                  { CHANNEL_LABEL[ selectedConv.channel ] }
                  { meta?.status ? ` · ${ meta.status }` : '' }
                </span>
              </span>
            </header>

            <div className="ib-bubbles" data-wc-no-translate="true">
              { thread.map( m => {
                const outbound = m.direction === 'OUTBOUND';
                return (
                  <div key={ m.id || m.messageId } className={ `ib-bubblerow ${ outbound ? 'out' : 'in' }` }>
                    <div className={ `ib-bubble ${ outbound ? 'out' : 'in' } ${ m.isRevoked ? 'revoked' : '' }` }>
                      { m.isRevoked ? (
                        <span className="ib-revoked">Message deleted</span>
                      ) : m.content ? (
                        <span className="ib-body">{ m.content }</span>
                      ) : (
                        <span className="ib-body ib-body-muted">
                          { m.messageType && m.messageType !== 'text' ? `[${ m.messageType }]` : '…' }
                        </span>
                      ) }
                      <span className="ib-time">
                        { timeFull( m.timestamp ) }
                        { m.channel !== selectedConv.channel ? ` · ${ CHANNEL_LABEL[ m.channel ] }` : '' }
                      </span>
                    </div>
                  </div>
                );
              } ) }
            </div>

            { canSend ? (
              <form
                className="ib-composer"
                onSubmit={ e => { e.preventDefault(); void send(); } }
              >
                <input
                  type="text"
                  className="ib-composer-input"
                  placeholder="Type a message"
                  value={ draft }
                  onChange={ e => setDraft( e.target.value ) }
                  disabled={ sending }
                  aria-label="Message"
                />
                <button type="submit" className="ib-composer-send" disabled={ sending || !draft.trim() } aria-label="Send">
                  <SendGlyph />
                </button>
              </form>
            ) : (
              <p className="ib-readonly">
                { selectedConv.channel === 'WHATSAPP'
                  ? 'Replies need a saved customer. Open this person in Customers to reply.'
                  : `Replies for ${ CHANNEL_LABEL[ selectedConv.channel ] } are read-only here.` }
              </p>
            ) }
          </>
        ) }
      </div>

      <style jsx>{`
        .ib{
          width:100%;
          min-width:0;
          display:grid;
          grid-template-columns:1fr;
          gap:0;
        }

        /* ---- shared small controls ---- */
        .ib-ghost{
          min-height:var(--tap-min,44px); padding:8px 14px; box-sizing:border-box;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-lg,12px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a);
          font:inherit; font-weight:600; font-size:14px; cursor:pointer;
        }
        .ib-ghost:hover{ background:var(--bg-hover,#f5f5f5); }
        .ib-ghost:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }

        .ib-note{ margin:0; font-size:14px; color:var(--text-muted,#6b7280); }
        .ib-error{
          display:grid; gap:10px; justify-items:start; padding:12px;
          border:1px solid var(--danger,#dc2626); border-radius:var(--radius-lg,12px);
          background:var(--danger-bg,#fef2f2);
        }
        .ib-error p{ margin:0; font-size:14px; color:var(--danger,#dc2626); }

        /* ---- LIST pane ---- */
        .ib-list-pane{ min-width:0; display:grid; gap:14px; align-content:start; }
        .ib-head{ display:grid; gap:12px; }
        .ib-titleblock{ display:grid; gap:4px; }
        .ib-eyebrow{ margin:0; font-size:11px; color:var(--text-muted,#6b7280); }
        .ib-title{ margin:0; font-size:24px; font-weight:700; letter-spacing:-0.5px; color:var(--text,#1a1a1a); }
        .ib-search{
          display:flex; align-items:center; gap:8px;
          min-height:var(--tap-min,44px); padding:0 14px; box-sizing:border-box;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-full,9999px);
          background:var(--surface,#fff);
        }
        .ib-search-icon{ display:inline-flex; color:var(--text-muted,#6b7280); flex:0 0 auto; }
        .ib-search-input{
          flex:1 1 auto; min-width:0; border:0; outline:none; background:transparent;
          font:inherit; font-size:16px; color:var(--text,#1a1a1a);
        }

        .ib-list{ list-style:none; margin:0; padding:0; display:grid; gap:8px; }
        .ib-row{
          width:100%; min-width:0; display:flex; align-items:center; gap:12px;
          padding:10px 12px; min-height:var(--tap-min,44px); box-sizing:border-box;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-xl,14px);
          background:var(--surface,#fff); text-align:left; cursor:pointer; font:inherit;
        }
        .ib-row:hover{ background:var(--bg-hover,#f5f5f5); }
        .ib-row.active{ border-color:var(--accent,#1a3a2a); background:var(--lime-tint,rgba(209,244,112,0.22)); }
        .ib-row:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:-2px; }
        .ib-avatar{
          flex:0 0 auto; width:40px; height:40px; border-radius:var(--radius-full,9999px);
          display:inline-flex; align-items:center; justify-content:center;
          background:var(--lime,#d1f470); color:var(--accent,#1a3a2a);
          font-weight:700; font-size:13px;
        }
        .ib-rowmeta{ min-width:0; flex:1 1 auto; display:grid; gap:3px; }
        .ib-rowtop{ display:flex; align-items:baseline; gap:8px; min-width:0; }
        .ib-rowname{
          flex:1 1 auto; min-width:0; font-weight:700; font-size:15px; color:var(--text,#1a1a1a);
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }
        .ib-rowtime{ flex:0 0 auto; font-size:12px; color:var(--text-muted,#6b7280); }
        .ib-rowbottom{ display:flex; align-items:center; gap:8px; min-width:0; }
        .ib-rowpreview{
          flex:1 1 auto; min-width:0; font-size:13px; color:var(--text-muted,#6b7280);
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }
        .ib-rowchannel{
          flex:0 0 auto; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.4px;
          padding:2px 7px; border-radius:var(--radius-full,9999px);
          background:var(--bg-hover,#f5f5f5); color:var(--text-muted,#6b7280);
        }

        /* ---- THREAD pane ---- */
        .ib-thread-pane{ min-width:0; display:none; }
        .ib-empty{
          min-height:220px; display:flex; align-items:center; justify-content:center;
          color:var(--text-muted,#6b7280); font-size:14px; text-align:center;
        }
        .ib-thead{
          display:flex; align-items:center; gap:10px; min-width:0;
          padding:10px 0; margin-bottom:10px;
          border-bottom:1px solid var(--border,#e5e7eb);
        }
        .ib-back{
          flex:0 0 auto; width:var(--tap-min,44px); height:var(--tap-min,44px);
          display:inline-flex; align-items:center; justify-content:center;
          border:0; background:transparent; color:var(--text,#1a1a1a); cursor:pointer;
          border-radius:var(--radius-lg,12px);
        }
        .ib-back:hover{ background:var(--bg-hover,#f5f5f5); }
        .ib-back:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:-2px; }
        .ib-thead-avatar{
          flex:0 0 auto; width:38px; height:38px; border-radius:var(--radius-full,9999px);
          display:inline-flex; align-items:center; justify-content:center;
          background:var(--lime,#d1f470); color:var(--accent,#1a3a2a);
          font-weight:700; font-size:13px;
        }
        .ib-thead-meta{ min-width:0; display:grid; gap:1px; }
        .ib-thead-name{
          font-weight:700; font-size:16px; color:var(--text,#1a1a1a);
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }
        .ib-thead-sub{ font-size:12px; color:var(--text-muted,#6b7280); text-transform:capitalize; }

        .ib-bubbles{ display:grid; gap:8px; padding:4px 0 12px; min-width:0; }
        .ib-bubblerow{ display:flex; min-width:0; }
        .ib-bubblerow.in{ justify-content:flex-start; }
        .ib-bubblerow.out{ justify-content:flex-end; }
        .ib-bubble{
          max-width:min(80%,520px); min-width:0;
          display:grid; gap:4px;
          padding:9px 12px; border-radius:var(--radius-xl,14px);
          font-size:15px; line-height:1.4;
        }
        .ib-bubble.in{
          background:var(--surface,#fff); color:var(--text,#1a1a1a);
          border:1px solid var(--border,#e5e7eb);
          border-bottom-left-radius:var(--radius-sm,6px);
        }
        .ib-bubble.out{
          background:var(--accent,#1a3a2a); color:#fff;
          border-bottom-right-radius:var(--radius-sm,6px);
        }
        .ib-bubble.revoked{ opacity:0.85; }
        .ib-body{ overflow-wrap:anywhere; white-space:pre-wrap; }
        .ib-body-muted{ color:var(--text-muted,#6b7280); font-style:italic; }
        .ib-bubble.out .ib-body-muted{ color:rgba(255,255,255,0.75); }
        .ib-revoked{ font-style:italic; opacity:0.8; }
        .ib-time{ font-size:11px; opacity:0.7; }

        .ib-readonly{
          margin:0; padding:12px; font-size:13px; color:var(--text-muted,#6b7280);
          border:1px dashed var(--border,#e5e7eb); border-radius:var(--radius-lg,12px);
          background:var(--bg-secondary,#f9fafb);
        }

        .ib-composer{
          display:flex; align-items:center; gap:8px; min-width:0;
          padding-top:4px;
        }
        .ib-composer-input{
          flex:1 1 auto; min-width:0;
          min-height:var(--tap-min,44px); padding:10px 14px; box-sizing:border-box;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-full,9999px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a);
          font:inherit; font-size:16px;
        }
        .ib-composer-input:focus-visible{ outline:none; border-color:var(--lime,#d1f470); box-shadow:var(--focus-ring,0 0 0 2px rgba(209,244,112,0.35)); }
        .ib-composer-send{
          flex:0 0 auto; width:var(--tap-min,44px); height:var(--tap-min,44px);
          display:inline-flex; align-items:center; justify-content:center;
          border:0; border-radius:var(--radius-full,9999px);
          background:var(--accent,#1a3a2a); color:#fff; cursor:pointer;
        }
        .ib-composer-send:disabled{ opacity:0.5; cursor:not-allowed; }
        .ib-composer-send:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }

        /* ======================================================================
         * MOBILE master/detail swap: show the list OR the thread, full-screen.
         * ====================================================================== */
        @media (max-width:767.98px){
          .ib.ib-thread-open .ib-list-pane{ display:none; }
          .ib.ib-thread-open .ib-thread-pane{ display:block; }
        }

        /* ======================================================================
         * DESKTOP (>=768px): list + thread side by side.
         * ====================================================================== */
        @media (min-width:768px){
          .ib{
            grid-template-columns:minmax(260px,340px) minmax(0,1fr);
            gap:20px;
            align-items:start;
          }
          .ib-title{ font-size:26px; }
          .ib-thread-pane{ display:block; }
          .ib-back{ display:none; }
          .ib-thead{ padding-top:0; }
        }

        @media (prefers-reduced-motion:reduce){
          .ib-row,.ib-back,.ib-composer-send{ transition:none; }
        }
      `}</style>
    </section>
  );
};

export default InboxView;
