/**
 * WhatsApp Unified Inbox
 * Single inbox showing messages from all WABAs
 * Select WABA when sending messages
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import Layout from '../../../../components/Layout';
import RichTextEditor from '../../../../components/RichTextEditor';
import InteractiveMessageComposer from '../../../../components/InteractiveMessageComposer';
import TemplateSender from '../../../../components/TemplateSender';
import Button from '../../../../components/ui/Button';
import { SkeletonContact } from '../../../../components/Skeleton';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import SEO, { PAGE_SEO } from '../../../../components/SEO';
import * as api from '../../../../api/client';
import type { WaContactCard } from '../../../../api/client';
import ContactCardBubble from '../../../../components/ContactCardBubble';
import { WHATSAPP_PHONES } from '../../../../config/constants';
import { inferMimeFromName, validateWaMediaSize, formatBytes } from '../../../../lib/wa-media';
import { describeWaError } from '../../../../lib/wa-errors';
import InfoTooltip from '../../../../components/ui/InfoTooltip';
import { scrollToEnd } from '../../../../lib/scroll-to-end';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

interface Message {
  id: string;
  direction: 'inbound' | 'outbound';
  content: string;
  timestamp: string;
  status: string;
  contactId: string;
  whatsappMessageId?: string | null;
  mediaUrl?: string | null;
  messageType?: string | null;  // image, video, audio, document, sticker, text
  receivingPhone?: string | null;
  awsPhoneNumberId?: string | null;
  senderName?: string | null;
  senderPhone?: string | null;
  s3Key?: string | null;
  errorDetails?: string | null;
  errorCode?: number | null;
  transcription?: string | null;       // English transcription of voice notes
  detectedLanguage?: string | null;    // Detected language of voice note
  contactsPayload?: WaContactCard[] | null;  // shared contact card(s), messageType=contacts
}

interface Contact {
  id: string;
  name: string;
  phone: string;
  bsuid?: string;
  username?: string;
  contactBookName?: string;
  lastMessage?: string;
  lastMessageTime?: string;
  lastWabaId?: string;
  unread: number;
}

const WABA_CONFIG = {
  [ WHATSAPP_PHONES.primary.id ]: {
    name: WHATSAPP_PHONES.primary.name,
    phone: WHATSAPP_PHONES.primary.display,
    color: '#000',
    shortName: 'WC'
  },
  [ WHATSAPP_PHONES.secondary.id ]: {
    name: WHATSAPP_PHONES.secondary.name,
    phone: WHATSAPP_PHONES.secondary.display,
    color: '#4a4a4a',
    shortName: 'MA'
  },
};

const WABA_SEND_OPTIONS: SelectOption[] = Object.entries( WABA_CONFIG ).map( ( [ id, config ] ) => ( {
  value: id,
  label: `${ config.name } (${ config.phone })`,
} ) );
/* The native control sized itself to its widest option; `flex: 0 1` lets the trigger shrink
   inside the chat header instead, and .ui-select-value already truncates. */
const WABA_SEND_STYLE: React.CSSProperties = { flex: '0 1 170px', minWidth: 0 };

// Infer a WhatsApp-supported MIME type from a filename extension.
// (shared helper lives in src/lib/wa-media.ts — imported above)

// Avatar color palette - consistent per contact
const AVATAR_COLORS = [
  '#1a3a2a', '#0f2a1d', '#0f2a1d', '#1a3a2a', '#34d399',
  '#1a3a2a', '#0f2a1d', '#0f2a1d', '#1a3a2a', '#34d399',
];

// Delete/clear icon — trash can (lime + dark green themed)
const DeleteIcon: React.FC<{ size?: number; className?: string }> = ( { size = 14, className } ) => (
  <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className={ className } style={ { display: 'block' } }>
    <path fill="none" stroke="#1a3a2a" strokeMiterlimit="10" strokeWidth="1.5" d="M16.88 22.5H7.12a1.9 1.9 0 0 1-1.9-1.8L4.36 5.32h15.28l-.86 15.38a1.9 1.9 0 0 1-1.9 1.8ZM2.45 5.32h19.1M10.09 1.5h3.82a1.91 1.91 0 0 1 1.91 1.91v1.91H8.18V3.41a1.91 1.91 0 0 1 1.91-1.91ZM12 8.18v11.46m3.82-11.46v11.46M8.18 8.18v11.46" />
  </svg>
);

const getAvatarColor = ( name: string ): string => {
  let hash = 0;
  for ( let i = 0; i < name.length; i++ )
  {
    hash = name.charCodeAt( i ) + ( ( hash << 5 ) - hash );
  }
  return AVATAR_COLORS[ Math.abs( hash ) % AVATAR_COLORS.length ];
};

// ── Language code to human-readable label ──
const LANG_LABELS: Record<string, string> = {
  'en-US': 'English', 'en-GB': 'English', 'en-IN': 'English',
  'en-AU': 'English', 'en-NZ': 'English', 'en-ZA': 'English',
  'hi-IN': 'Hindi', 'ar-SA': 'Arabic', 'es-US': 'Spanish',
  'es-ES': 'Spanish', 'es-MX': 'Spanish', 'fr-FR': 'French',
  'fr-CA': 'French', 'de-DE': 'German', 'ja-JP': 'Japanese',
  'ko-KR': 'Korean', 'pt-BR': 'Portuguese', 'pt-PT': 'Portuguese',
  'zh-CN': 'Chinese', 'it-IT': 'Italian', 'tr-TR': 'Turkish',
  'ru-RU': 'Russian', 'nl-NL': 'Dutch', 'pl-PL': 'Polish',
  'sv-SE': 'Swedish', 'da-DK': 'Danish', 'nb-NO': 'Norwegian',
  'fi-FI': 'Finnish', 'ca-ES': 'Catalan', 'ro-RO': 'Romanian',
  'id-ID': 'Indonesian', 'ms-MY': 'Malay', 'th-TH': 'Thai',
  'vi-VN': 'Vietnamese', 'ta-IN': 'Tamil', 'te-IN': 'Telugu',
  'bn-IN': 'Bengali', 'mr-IN': 'Marathi', 'gu-IN': 'Gujarati',
  'kn-IN': 'Kannada', 'ml-IN': 'Malayalam', 'ur-IN': 'Urdu',
  'pa-IN': 'Punjabi', 'arb': 'Arabic', 'cy-GB': 'Welsh',
};

// ── Voice Note Transcription sub-component ──
const VoiceNoteTranscription: React.FC<{ msg: Message }> = ( { msg } ) => {
  const [ expanded, setExpanded ] = useState( false );
  const [ transcription, setTranscription ] = useState( msg.transcription || '' );
  const [ detectedLang, setDetectedLang ] = useState( msg.detectedLanguage || '' );
  const [ loading, setLoading ] = useState( false );

  const handleTranscribe = async () => {
    if ( loading ) return;
    setLoading( true );
    try
    {
      const result = await api.transcribeVoiceNote( {
        messageId: msg.id,
        s3Key: msg.s3Key || undefined,
        direction: msg.direction === 'inbound' ? 'INBOUND' : 'OUTBOUND',
      } );
      if ( result?.transcription )
      {
        setTranscription( result.transcription );
        setDetectedLang( result.detectedLanguage || '' );
      }
    } catch
    {
      // silent
    } finally
    {
      setLoading( false );
    }
  };

  if ( transcription )
  {
    const langLabel = LANG_LABELS[ detectedLang ] || detectedLang || '';
    return (
      <div className="voice-transcription" style={ { marginTop: 4 } }>
        <button
          className="transcription-toggle"
          onClick={ () => setExpanded( !expanded ) }
          style={ {
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: '0.75rem', color: '#6b7280', display: 'flex',
            alignItems: 'center', gap: 4, padding: '2px 0',
          } }
        >
          <span style={ { fontSize: '0.7rem' } }>📝</span>
          { expanded ? 'Hide transcript' : 'Show transcript' }
          { langLabel && <span style={ {
            fontSize: '0.65rem', background: '#e5e7eb', borderRadius: 4,
            padding: '1px 4px', marginLeft: 4,
          } }>{ langLabel }</span> }
        </button>
        { expanded && (
          <p style={ {
            margin: '4px 0 0', fontSize: '0.8rem', color: '#374151',
            lineHeight: 1.4, fontStyle: 'italic', padding: '4px 8px',
            background: 'rgba(0,0,0,0.03)', borderRadius: 6,
            borderLeft: '2px solid #9ca3af',
          } }>
            { transcription }
          </p>
        ) }
      </div>
    );
  }

  // No transcription yet — show "Transcribe" button
  return (
    <div className="voice-transcription" style={ { marginTop: 4 } }>
      <button
        onClick={ handleTranscribe }
        disabled={ loading }
        style={ {
          background: 'none', border: '1px solid #d1d5db', borderRadius: 4,
          cursor: loading ? 'wait' : 'pointer', fontSize: '0.72rem',
          color: '#6b7280', padding: '2px 8px', display: 'flex',
          alignItems: 'center', gap: 4,
        } }
      >
        <span style={ { fontSize: '0.7rem' } }>{ loading ? '⏳' : '📝' }</span>
        { loading ? 'Transcribing...' : 'Transcribe' }
      </button>
    </div>
  );
};

const WhatsAppUnifiedInbox: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const [ selectedContact, setSelectedContact ] = useState<Contact | null>( null );
  const [ contacts, setContacts ] = useState<Contact[]>( [] );
  const [ messages, setMessages ] = useState<Message[]>( [] );
  const [ messageText, setMessageText ] = useState( '' );
  const [ loading, setLoading ] = useState( true );
  const [ loadError, setLoadError ] = useState( false );
  const [ sending, setSending ] = useState( false );
  const [ selectedWaba, setSelectedWaba ] = useState<string>( WHATSAPP_PHONES.primary.id );
  const [ searchQuery, setSearchQuery ] = useState( '' );
  const [ deleting, setDeleting ] = useState<string | null>( null );
  const [ mediaFiles, setMediaFiles ] = useState<File[]>( [] );
  const [ mediaPreview, setMediaPreview ] = useState<string | null>( null );
  const [ uploadingMedia, setUploadingMedia ] = useState( false );
  const [ contactsPage, setContactsPage ] = useState( 1 );
  const [ clearing, setClearing ] = useState( false );
  // Modal states
  const [ showInteractiveComposer, setShowInteractiveComposer ] = useState( false );
  const [ showTemplateSender, setShowTemplateSender ] = useState( false );
  const [ showNewTemplate, setShowNewTemplate ] = useState( false );  // template → new/unsaved number
  const [ showEmojiPicker, setShowEmojiPicker ] = useState( false );
  const [ emojiSearch, setEmojiSearch ] = useState( '' );
  const [ mobileShowChat, setMobileShowChat ] = useState( false );
  const CONTACTS_PER_PAGE = 100;
  const MESSAGES_PER_PAGE = 50;
  const [ visibleMessageCount, setVisibleMessageCount ] = useState( MESSAGES_PER_PAGE );
  const [ loadingOlder, setLoadingOlder ] = useState( false );
  const messagesEndRef = useRef<HTMLDivElement>( null );
  const messagesAreaRef = useRef<HTMLDivElement>( null );
  const pendingScrollRestore = useRef( false );
  const fileInputRef = useRef<HTMLInputElement>( null );
  const toast = useToastContext();
  const confirm = useConfirm();

  // Clear all inbox data handler
  const handleClearAllInbox = async () => {
    const ok = await confirm( {
      title: 'Clear All Inbox Data',
      message: (
        <div>
          <p style={ { color: '#0f2a1d', fontWeight: 500, marginBottom: 12 } }>WARNING: This will permanently delete:</p>
          <ul style={ { margin: '0 0 12px 20px', lineHeight: 1.6 } }>
            <li>All WhatsApp messages (inbound &amp; outbound)</li>
            <li>All SMS messages (inbound &amp; outbound)</li>
            <li>All SMS IN messages</li>
            <li>All Voice call records (inbound &amp; outbound)</li>
            <li>All Voice IN call records</li>
            <li>All contacts</li>
            <li>All media files from S3</li>
          </ul>
          <p style={ { color: '#0f2a1d', fontWeight: 500 } }>This action cannot be undone!</p>
        </div>
      ),
      confirmInput: 'DELETE ALL',
      confirmText: 'Delete Everything',
      danger: true,
    } );
    if ( !ok ) return;
    setClearing( true );
    try
    {
      const result = await api.clearAllInboxData();
      toast.success( `Cleared: ${result.messagesDeleted} messages, ${result.contactsDeleted} contacts` );
      setSelectedContact( null );
      await loadData();
    } catch ( err: any )
    {
      toast.error( 'Failed to clear inbox: ' + ( err.message || 'Unknown error' ) );
    } finally
    {
      setClearing( false );
    }
  };

  const scrollToBottom = ( force = false ) => {
    const area = messagesAreaRef.current;
    if ( !area )
    {
      scrollToEnd( messagesEndRef.current );
      return;
    }
    // Only auto-scroll if user is near the bottom (within 150px) or forced
    const isNearBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 150;
    if ( force || isNearBottom )
    {
      scrollToEnd( messagesEndRef.current );
    }
  };

  // Auto-scroll on new messages (not on initial load — that's handled by contact selection)
  const prevMessageCount = useRef( 0 );
  useEffect( () => {
    if ( pendingScrollRestore.current ) return; // Don't auto-scroll during load-older
    if ( messages.length > prevMessageCount.current && prevMessageCount.current > 0 )
    {
      scrollToBottom();
    }
    prevMessageCount.current = messages.length;
  }, [ messages ] );

  // Scroll to bottom when selecting a new contact
  useEffect( () => {
    if ( selectedContact )
    {
      setTimeout( () => scrollToBottom( true ), 50 );
    }
  }, [ selectedContact ] );

  const isFirstLoad = useRef( true );

  const loadData = useCallback( async () => {
    if ( isFirstLoad.current )
    {
      setLoading( true );
      setLoadError( false );
    }
    try
    {
      const [ contactsData, messagesData ] = await Promise.all( [
        api.listContacts(),
        api.listMessages( undefined, 'WHATSAPP', 2000 ),
      ] );

      // If contacts empty but messages exist, build contacts from messages
      let effectiveContacts = contactsData;
      if ( contactsData.length === 0 && messagesData.length > 0 )
      {
        const phoneMap = new Map<string, { phone: string; name: string; contactId: string }>();
        messagesData.forEach( m => {
          const phone = m.senderPhone || m.receivingPhone || '';
          if ( phone && !phoneMap.has( m.contactId ) )
          {
            phoneMap.set( m.contactId, {
              phone,
              name: m.senderName || phone,
              contactId: m.contactId,
            } );
          }
        } );
        effectiveContacts = Array.from( phoneMap.values() ).map( p => ( {
          contactId: p.contactId,
          name: p.name,
          phone: p.phone,
          email: '',
          optInWhatsApp: true, optInSms: false, optInEmail: false,
          allowlistWhatsApp: true, allowlistSms: false, allowlistEmail: false,
          createdAt: '', updatedAt: '',
        } as api.Contact ) );
      }

      // Process messages to get last message info per contact
      // Also track sender names from inbound messages
      const contactMsgMap = new Map<string, { lastMsg: any; lastWabaId: string; unread: number; senderName: string }>();

      messagesData.forEach( m => {
        const existing = contactMsgMap.get( m.contactId );
        const msgTime = new Date( m.timestamp ).getTime();

        // Track sender name from inbound messages
        const senderName = m.direction === 'INBOUND' && m.senderName ? m.senderName : ( existing?.senderName || '' );

        if ( !existing || msgTime > new Date( existing.lastMsg.timestamp ).getTime() )
        {
          contactMsgMap.set( m.contactId, {
            lastMsg: m,
            lastWabaId: m.awsPhoneNumberId || '',
            unread: ( existing?.unread || 0 ) + ( m.direction === 'INBOUND' && m.status === 'received' ? 1 : 0 ),
            senderName: senderName || existing?.senderName || ''
          } );
        } else if ( senderName && !existing.senderName )
        {
          // Update sender name if we found one
          existing.senderName = senderName;
        }
      } );

      const displayContacts: Contact[] = effectiveContacts
        .filter( c => c.phone || c.bsuid )
        .map( c => {
          const msgInfo = contactMsgMap.get( c.contactId );
          // Use contact name, or sender name from messages, or phone as fallback
          const displayName = c.name || msgInfo?.senderName || c.phone;

          // Format last message with media type indicator
          let lastMsgPreview = '';
          if ( msgInfo?.lastMsg )
          {
            const msg = msgInfo.lastMsg;
            const msgType = msg.messageType?.toLowerCase();

            // Add media type icon prefix
            if ( msgType === 'image' ) lastMsgPreview = '[Image] ';
            else if ( msgType === 'video' ) lastMsgPreview = '[Video] ';
            else if ( msgType === 'audio' || msgType === 'voice' ) lastMsgPreview = '[Audio] ';
            else if ( msgType === 'document' ) lastMsgPreview = '[Doc] ';
            else if ( msgType === 'sticker' ) lastMsgPreview = '[Sticker] ';
            else if ( msgType === 'location' ) lastMsgPreview = '[Location] ';
            else if ( msgType === 'contacts' ) lastMsgPreview = '[Contact] ';

            // Add content preview. A contacts row already carries a `[Contact] `
            // prefix above, so strip the stored `[Contact Card]` label or the
            // preview reads "[Contact] Contact Card Punit Kumar · +91…".
            let content = msg.content || '';
            if ( msgType === 'contacts' && content.startsWith( '[Contact Card]' ) )
            {
              // Keep the bare label when nothing follows it — that is the one
              // pre-change row, and an empty preview says less than the label.
              const stripped = content.slice( '[Contact Card]'.length ).trim();
              if ( stripped ) content = stripped;
            }
            if ( content.startsWith( '[' ) && content.endsWith( ']' ) )
            {
              // Special message type - show type name
              lastMsgPreview += content.replace( /[\[\]]/g, '' );
            } else
            {
              lastMsgPreview += content.substring( 0, 40 );
              if ( content.length > 40 ) lastMsgPreview += '...';
            }
          }

          return {
            id: c.contactId,
            name: displayName,
            phone: c.phone,
            bsuid: c.bsuid || '',
            username: c.username || '',
            contactBookName: c.contactBookName || '',
            lastMessage: lastMsgPreview,
            lastMessageTime: msgInfo?.lastMsg?.timestamp,
            lastWabaId: msgInfo?.lastWabaId || '',
            unread: msgInfo?.unread || 0,
          };
        } )
        .sort( ( a, b ) => {
          if ( !a.lastMessageTime ) return 1;
          if ( !b.lastMessageTime ) return -1;
          return new Date( b.lastMessageTime ).getTime() - new Date( a.lastMessageTime ).getTime();
        } );

      setContacts( displayContacts );
      setMessages( messagesData.map( m => ( {
        id: m.messageId,
        direction: m.direction.toLowerCase() as 'inbound' | 'outbound',
        content: m.content || '',
        timestamp: m.timestamp,
        status: m.status?.toLowerCase() || 'sent',
        contactId: m.contactId,
        whatsappMessageId: m.whatsappMessageId,
        mediaUrl: m.mediaUrl,  // Use pre-signed URL from API
        messageType: m.messageType,  // image, video, audio, document, sticker, text
        receivingPhone: m.receivingPhone,
        awsPhoneNumberId: m.awsPhoneNumberId,
        senderName: m.senderName,  // Sender's WhatsApp profile name
        senderPhone: m.senderPhone,  // Sender's phone number
        s3Key: m.s3Key,
        errorDetails: m.errorDetails,
        errorCode: m.errorCode,
        transcription: m.transcription,
        detectedLanguage: m.detectedLanguage,
        // Enumerated mapping — an omitted field is silently dropped, so the
        // contact card needs this line as much as it needs the one in client.ts.
        contactsPayload: m.contactsPayload,
      } ) ) );
    } catch ( err )
    {
      if ( isFirstLoad.current )
      {
        setLoadError( true );
        toast.error( 'Failed to load data' );
      }
    } finally
    {
      setLoading( false );
      isFirstLoad.current = false;
    }
  }, [] );

  useEffect( () => {
    loadData();
    const interval = setInterval( loadData, 10000 );
    return () => clearInterval( interval );
  }, [ loadData ] );

  // When selecting a contact, auto-select the WABA they last messaged from
  useEffect( () => {
    if ( selectedContact?.lastWabaId && WABA_CONFIG[ selectedContact.lastWabaId as keyof typeof WABA_CONFIG ] )
    {
      setSelectedWaba( selectedContact.lastWabaId );
    }
    setVisibleMessageCount( MESSAGES_PER_PAGE );
  }, [ selectedContact ] );

  const filteredMessages = messages
    .filter( m => {
      if ( !selectedContact ) return false;
      // Match by contactId - handle both inbound and outbound
      const contactMatch = m.contactId === selectedContact.id;
      if ( !contactMatch )
      {
        console.debug( 'Message contactId mismatch:', {
          messageContactId: m.contactId,
          selectedContactId: selectedContact.id,
          messageId: m.id,
          direction: m.direction
        } );
      }
      return contactMatch;
    } )
    .sort( ( a, b ) => new Date( a.timestamp ).getTime() - new Date( b.timestamp ).getTime() );

  // Show only the most recent N messages, with option to load more
  const totalFilteredCount = filteredMessages.length;
  const hasOlderMessages = totalFilteredCount > visibleMessageCount;
  const visibleMessages = hasOlderMessages
    ? filteredMessages.slice( totalFilteredCount - visibleMessageCount )
    : filteredMessages;

  // Native WhatsApp typing indicator: when the agent is composing, mark the
  // customer's last inbound message as read + show a typing bubble (max 25s).
  // Throttled to once per ~20s per conversation (Meta only needs a fresh ping).
  const lastTypingRef = useRef<{ id: string; at: number }>( { id: '', at: 0 } );
  useEffect( () => {
    if ( !messageText.trim() || !selectedContact ) return;
    const lastInbound = [ ...filteredMessages ].reverse().find(
      m => m.direction === 'inbound' && m.whatsappMessageId
    );
    const wamid = lastInbound?.whatsappMessageId;
    if ( !wamid ) return;
    const now = Date.now();
    if ( lastTypingRef.current.id === selectedContact.id && now - lastTypingRef.current.at < 20000 ) return;
    lastTypingRef.current = { id: selectedContact.id, at: now };
    api.sendTypingIndicator( selectedWaba, wamid ).catch( () => { } );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ messageText, selectedContact?.id ] );

  // Infinite scroll: load older messages when scrolled near top
  useEffect( () => {
    const area = messagesAreaRef.current;
    if ( !area ) return;
    const handleScroll = () => {
      if ( area.scrollTop < 80 && hasOlderMessages && !loadingOlder && !pendingScrollRestore.current )
      {
        const prevScrollHeight = area.scrollHeight;
        const prevScrollTop = area.scrollTop;
        setLoadingOlder( true );
        pendingScrollRestore.current = true;
        setVisibleMessageCount( c => c + MESSAGES_PER_PAGE );
        setTimeout( () => {
          const newScrollHeight = area.scrollHeight;
          area.scrollTop = prevScrollTop + ( newScrollHeight - prevScrollHeight );
          setLoadingOlder( false );
          pendingScrollRestore.current = false;
        }, 50 );
      }
    };
    area.addEventListener( 'scroll', handleScroll, { passive: true } );
    return () => area.removeEventListener( 'scroll', handleScroll );
  }, [ hasOlderMessages, loadingOlder ] );

  const filteredContacts = contacts.filter( c => {
    const q = searchQuery.toLowerCase();
    return c.name.toLowerCase().includes( q ) ||
      c.phone.includes( searchQuery ) ||
      ( c.bsuid && c.bsuid.toLowerCase().includes( q ) ) ||
      ( c.username && c.username.toLowerCase().includes( q ) ) ||
      ( c.contactBookName && c.contactBookName.toLowerCase().includes( q ) );
  } );

  // Pagination for contacts
  const totalContactPages = Math.ceil( filteredContacts.length / CONTACTS_PER_PAGE );
  const paginatedContacts = filteredContacts.slice(
    ( contactsPage - 1 ) * CONTACTS_PER_PAGE,
    contactsPage * CONTACTS_PER_PAGE
  );

  // Reset page when search changes
  useEffect( () => {
    setContactsPage( 1 );
  }, [ searchQuery ] );

  const handleSend = async () => {
    if ( !selectedContact || ( !messageText.trim() && mediaFiles.length === 0 ) || sending ) return;
    setSending( true );

    try
    {
      const wabaName = WABA_CONFIG[ selectedWaba as keyof typeof WABA_CONFIG ]?.name || 'WhatsApp';

      // ── Media messages: upload each file directly to S3 (presigned) then send. ──
      // Direct browser→S3 upload bypasses the API Gateway (10MB) / Lambda (6MB)
      // base64 ceiling so large video/audio/documents send. Multiple files are sent
      // sequentially; the typed text is attached as a caption to the FIRST item only.
      if ( mediaFiles.length > 0 )
      {
        let sentCount = 0;
        let failCount = 0;
        for ( let i = 0; i < mediaFiles.length; i++ )
        {
          const file = mediaFiles[ i ];
          // Browser File.type can be empty for some types (.amr, sometimes .webp) — infer from extension.
          const sendType = file.type || inferMimeFromName( file.name );
          const s3Key = await api.uploadMediaForSend( file, sendType, file.name );
          if ( !s3Key )
          {
            failCount++;
            toast.error( `Upload failed: ${file.name}` );
            continue;
          }
          const res = await api.sendWhatsAppMessage( {
            contactId: selectedContact.id,
            content: i === 0 ? messageText : '', // caption on first item only
            phoneNumberId: selectedWaba,
            recipientBsuid: selectedContact.bsuid || undefined,
            mediaFile: s3Key,
            mediaType: sendType,
            mediaFileName: file.name,
          } );
          if ( res ) sentCount++; else failCount++;
        }

        if ( sentCount > 0 )
        {
          toast.success( `Sent ${sentCount} item${sentCount > 1 ? 's' : ''} via ${wabaName}` );
          setMessageText( '' );
          setMediaFiles( [] );
          setMediaPreview( null );
          if ( fileInputRef.current ) fileInputRef.current.value = '';
          await loadData();
        }
        if ( failCount > 0 && sentCount === 0 )
        {
          toast.error( 'Failed to send. Check if the 24h window is open or use a template.' );
        }
        return;
      }

      // ── Text-only message ──
      const result = await api.sendWhatsAppMessage( {
        contactId: selectedContact.id,
        content: messageText,
        phoneNumberId: selectedWaba,
        recipientBsuid: selectedContact.bsuid || undefined,
      } );

      if ( result )
      {
        toast.success( `Sent via ${wabaName}` );
        setMessageText( '' );
        await loadData();
      } else
      {
        toast.error( 'Failed to send. Check if 24h window is open or use a template.' );
      }
    } catch ( err: any )
    {
      toast.error( err.message || 'Failed to send message' );
    } finally
    {
      setSending( false );
    }
  };

  const handleMediaSelect = ( e: React.ChangeEvent<HTMLInputElement> ) => {
    const files = Array.from( e.target.files || [] );
    if ( files.length === 0 ) return;

    const accepted: File[] = [];
    for ( const file of files )
    {
      // Warn (non-blocking) if filename has special characters
      const validFilenameChars = /^[a-zA-Z0-9\s._\-()]+$/;
      if ( !validFilenameChars.test( file.name ) )
      {
        const invalidChars = file.name.replace( /[a-zA-Z0-9\s._\-()]/g, '' ).split( '' ).filter( ( v, i, a ) => a.indexOf( v ) === i );
        console.warn( 'Filename contains special characters that may be removed:', invalidChars );
      }

      // Validate file size based on type per WhatsApp API docs
      const ftype = file.type || inferMimeFromName( file.name );
      const sizeCheck = validateWaMediaSize( { size: file.size, name: file.name, type: ftype }, ftype );
      if ( !sizeCheck.ok )
      {
        toast.error( `${file.name} too large. Max: ${formatBytes( sizeCheck.limit )}` );
        continue;
      }
      accepted.push( file );
    }

    if ( accepted.length === 0 ) return;

    setMediaFiles( prev => [ ...prev, ...accepted ] );

    // Preview the first image if present
    const firstImage = accepted.find( f => ( f.type || inferMimeFromName( f.name ) ).startsWith( 'image/' ) );
    if ( firstImage && !mediaPreview )
    {
      const reader = new FileReader();
      reader.onload = ( ev ) => setMediaPreview( ev.target?.result as string );
      reader.readAsDataURL( firstImage );
    }
  };

  const clearMedia = () => {
    setMediaFiles( [] );
    setMediaPreview( null );
    if ( fileInputRef.current ) fileInputRef.current.value = '';
  };

  const removeMediaAt = ( index: number ) => {
    setMediaFiles( prev => prev.filter( ( _, i ) => i !== index ) );
  };

  // TTS callback for RichTextEditor panel
  const handleSendTTS = async ( data: { text: string; voiceId: string; languageCode: string; engine: string } ): Promise<boolean> => {
    if ( !selectedContact ) return false;
    try
    {
      const result = await api.sendWhatsAppTTS( {
        contactId: selectedContact.id,
        messageText: data.text,
        voiceId: data.voiceId,
        languageCode: data.languageCode,
        engine: data.engine,
        phoneNumberId: selectedWaba,
        recipientBsuid: selectedContact.bsuid || undefined,
      } );
      if ( result?.messageId )
      {
        toast.success( 'Voice note sent via Polly TTS' );
        await loadData();
        return true;
      } else
      {
        toast.error( 'Failed to send voice note' );
        return false;
      }
    } catch ( err: any )
    {
      toast.error( err.message || 'TTS failed' );
      return false;
    }
  };

  const handleReaction = async ( whatsappMessageId: string, wabaId?: string | null ) => {
    if ( !selectedContact || !whatsappMessageId ) return;
    try
    {
      await api.sendWhatsAppReaction( {
        contactId: selectedContact.id,
        reactionMessageId: whatsappMessageId,
        reactionEmoji: '👍',
        phoneNumberId: wabaId || selectedWaba,
        recipientBsuid: selectedContact.bsuid || undefined,
      } );
    } catch ( err )
    {
      console.error( 'Reaction failed:', err );
    }
  };

  // Send location request via WhatsApp interactive location_request_message
  // Uses native WhatsApp location picker — no Google Maps needed
  // User taps "Send location" → WhatsApp opens device GPS picker → sends lat/lng back
  const handleSendLocationRequest = async () => {
    if ( !selectedContact || sending ) return;
    setSending( true );
    try
    {
      const result = await api.sendWhatsAppInteractive( {
        contactId: selectedContact.id,
        phoneNumberId: selectedWaba,
        recipientBsuid: selectedContact.bsuid || undefined,
        interactiveType: 'location_request',
        interactiveData: {
          body: 'Please share your location so we can assist you better.',
        },
      } );
      if ( result )
      {
        toast.success( 'Location request sent' );
        await loadData();
      } else
      {
        toast.error( 'Failed to send location request' );
      }
    } catch ( err: any )
    {
      toast.error( err.message || 'Location request failed' );
    } finally
    {
      setSending( false );
    }
  };

  const handleDeleteMessage = async ( msg: Message ) => {
    const ok = await confirm( { title: 'Delete Message', message: 'Delete this message?', confirmText: 'Delete', danger: true } );
    if ( !ok ) return;
    setDeleting( msg.id );
    try
    {
      const direction = msg.direction === 'inbound' ? 'INBOUND' : 'OUTBOUND';
      const success = await api.deleteMessage( msg.id, direction );
      if ( success )
      {
        toast.success( 'Message deleted' );
        await loadData();
      } else
      {
        toast.error( 'Failed to delete message' );
      }
    } catch ( err )
    {
      toast.error( 'Delete error occurred' );
    } finally
    {
      setDeleting( null );
    }
  };

  const handleDeleteContact = async ( contact: Contact ) => {
    const ok = await confirm( {
      title: 'Delete Contact',
      message: ( <p>Delete contact &quot;{ contact.name }&quot;?<br /><br /><span style={ { color: '#666', fontSize: 13 } }>Note: Messages will remain in the database.</span></p> ),
      confirmText: 'Delete Contact',
      danger: true,
    } );
    if ( !ok ) return;
    setDeleting( contact.id );
    try
    {
      const success = await api.deleteContact( contact.id );
      if ( success )
      {
        toast.success( 'Contact deleted (messages preserved)' );
        setSelectedContact( null );
        await loadData();
      } else
      {
        toast.error( 'Failed to delete contact' );
      }
    } catch ( err )
    {
      toast.error( 'Delete error occurred' );
    } finally
    {
      setDeleting( null );
    }
  };

  const handleClearAllMessages = async () => {
    if ( !selectedContact ) return;
    const ok = await confirm( {
      title: 'Clear All Messages',
      message: ( <p>Clear all { filteredMessages.length } messages for &quot;{ selectedContact.name }&quot;?<br /><br />This will delete all messages but keep the contact.</p> ),
      confirmText: 'Clear Messages',
      danger: true,
    } );
    if ( !ok ) return;
    const contactMessages = filteredMessages;
    if ( contactMessages.length === 0 )
    {
      toast.error( 'No messages to clear' );
      return;
    }

    setDeleting( 'clearing' );
    try
    {
      let deleted = 0;
      let failed = 0;

      // Delete messages in batches to avoid overwhelming the API
      for ( const msg of contactMessages )
      {
        try
        {
          const direction = msg.direction === 'inbound' ? 'INBOUND' : 'OUTBOUND';
          const success = await api.deleteMessage( msg.id, direction );
          if ( success )
          {
            deleted++;
          } else
          {
            failed++;
          }
        } catch ( e )
        {
          failed++;
          console.error( 'Failed to delete message:', msg.id, e );
        }
      }

      if ( deleted > 0 )
      {
        toast.success( `Cleared ${deleted} messages${failed > 0 ? ` (${failed} failed)` : ''}` );
      } else
      {
        toast.error( 'Failed to clear messages' );
      }
      await loadData();
    } catch ( err )
    {
      toast.error( 'Failed to clear messages' );
    } finally
    {
      setDeleting( null );
    }
  };

  const getWabaInfo = ( wabaId?: string | null ) => {
    if ( !wabaId ) return null;
    return WABA_CONFIG[ wabaId as keyof typeof WABA_CONFIG ];
  };

  const formatTime = ( timestamp: string ) => {
    const date = new Date( timestamp );
    const now = new Date();
    const diff = now.getTime() - date.getTime();

    if ( diff < 86400000 )
    {
      return date.toLocaleTimeString( [], { hour: '2-digit', minute: '2-digit' } );
    } else if ( diff < 604800000 )
    {
      return date.toLocaleDateString( [], { weekday: 'short' } );
    }
    return date.toLocaleDateString( [], { month: 'short', day: 'numeric' } );
  };

  // Helper to detect media type from messageType, content, or URL
  const getMediaType = ( msg: Message ): 'image' | 'video' | 'audio' | 'document' | 'sticker' | null => {
    if ( !msg.mediaUrl ) return null;

    // First check messageType field from API
    const msgType = msg.messageType?.toLowerCase();
    if ( msgType === 'image' ) return 'image';
    if ( msgType === 'video' ) return 'video';
    if ( msgType === 'audio' || msgType === 'voice' ) return 'audio';
    if ( msgType === 'document' ) return 'document';
    if ( msgType === 'sticker' ) return 'sticker';

    // Fallback: check content text
    const content = ( msg.content || '' ).toLowerCase();
    if ( content.includes( 'image' ) || content.includes( 'photo' ) ) return 'image';
    if ( content.includes( 'video' ) ) return 'video';
    if ( content.includes( 'audio' ) || content.includes( 'voice' ) || content.includes( 'ptt' ) ) return 'audio';
    if ( content.includes( 'document' ) || content.includes( 'file' ) ) return 'document';
    if ( content.includes( 'sticker' ) ) return 'sticker';

    // Fallback: check URL extension
    const url = msg.mediaUrl.toLowerCase();
    if ( url.includes( '.jpg' ) || url.includes( '.jpeg' ) || url.includes( '.png' ) || url.includes( '.gif' ) ) return 'image';
    if ( url.includes( '.webp' ) ) return 'sticker';
    if ( url.includes( '.mp4' ) || url.includes( '.3gp' ) || url.includes( '.mov' ) ) return 'video';
    if ( url.includes( '.mp3' ) || url.includes( '.ogg' ) || url.includes( '.aac' ) || url.includes( '.amr' ) || url.includes( '.m4a' ) || url.includes( '.opus' ) ) return 'audio';
    if ( url.includes( '.pdf' ) || url.includes( '.doc' ) || url.includes( '.xls' ) || url.includes( '.ppt' ) || url.includes( '.txt' ) ) return 'document';

    // Default to document for unknown types
    return 'document';
  };

  // Get label for media type - text only, no emojis
  const getMediaLabel = ( type: string | null ): string => {
    switch ( type )
    {
      case 'image': return 'Image';
      case 'video': return 'Video';
      case 'audio': return 'Audio';
      case 'sticker': return 'Sticker';
      case 'document': return 'File';
      default: return 'File';
    }
  };

  // Render message content with special handling for unsupported types
  const renderMessageContent = ( msg: Message ) => {
    const content = msg.content || '';
    const msgType = msg.messageType?.toLowerCase() || '';

    // Check if this is an unsupported message type
    const isUnsupported = msgType === 'unsupported' ||
      content.includes( '[Unsupported' ) ||
      content.includes( '[Message type not supported' );

    // Check if this is a disappearing/ephemeral message
    const isEphemeral = msgType === 'ephemeral' ||
      content.includes( '[Disappearing Message' ) ||
      content.includes( 'disappearing' );

    // For ephemeral/disappearing messages
    if ( isEphemeral && !msg.mediaUrl )
    {
      return (
        <span className="unsupported-msg ephemeral-notice">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={ { display: 'inline', verticalAlign: 'middle', marginRight: 4 } }><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
          Disappearing message — ask sender to disable disappearing messages for this chat
        </span>
      );
    }

    // For unsupported messages with media, show download link
    if ( isUnsupported && msg.mediaUrl )
    {
      return (
        <span className="unsupported-with-media">
          <span className="unsupported-label">Media attachment</span>
          <a
            href={ msg.mediaUrl }
            target="_blank"
            rel="noopener noreferrer"
            className="media-download-link"
          >
            Download
          </a>
        </span>
      );
    }

    // For unsupported messages without media
    if ( isUnsupported )
    {
      // Detect OTP / authentication messages (hidden by WhatsApp for security)
      const isOtp = content.includes( 'OTP' ) || content.includes( 'authentication' ) || content.includes( 'security' );
      if ( isOtp )
      {
        return (
          <span className="unsupported-msg otp-notice">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={ { display: 'inline', verticalAlign: 'middle', marginRight: 4 } }><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg> OTP / verification message — content hidden by WhatsApp
          </span>
        );
      }
      // Detect disappearing message errors in unsupported type
      const isDisappearing = content.toLowerCase().includes( 'disappearing' ) || content.toLowerCase().includes( 'ephemeral' );
      if ( isDisappearing )
      {
        return (
          <span className="unsupported-msg ephemeral-notice">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={ { display: 'inline', verticalAlign: 'middle', marginRight: 4 } }><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
            Disappearing message — disable disappearing messages in this chat to fix
          </span>
        );
      }
      // Detect view-once messages
      const isViewOnce = content.toLowerCase().includes( 'view-once' ) || content.toLowerCase().includes( 'view once' );
      if ( isViewOnce )
      {
        return (
          <span className="unsupported-msg">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={ { display: 'inline', verticalAlign: 'middle', marginRight: 4 } }><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
            View-once message — content hidden by WhatsApp
          </span>
        );
      }
      // Detect poll messages
      if ( content.includes( '[Poll' ) )
      {
        const pollMatch = content.match( /\[Poll: (.+?)\]/ );
        return <span className="special-msg">📊 Poll: { pollMatch ? pollMatch[ 1 ] : 'Poll' }</span>;
      }
      // Detect forwarded messages
      if ( content.includes( 'Forwarded message' ) )
      {
        return <span className="unsupported-msg">↪ Forwarded message — content not available</span>;
      }
      // Try to extract useful info from the content
      const match = content.match( /\[Unsupported: (.+?)\]/ );
      let detail: string;
      if ( match )
      {
        detail = match[ 1 ];
      } else if ( content.trim() && !content.startsWith( '[' ) )
      {
        // Real readable text was delivered even though Meta flagged the type — show it.
        detail = content;
      } else if ( content.startsWith( '[' ) )
      {
        detail = content.replace( /[\[\]]/g, '' );
      } else
      {
        detail = 'Message type not viewable';
      }
      return (
        <span className="unsupported-msg">
          { detail }
        </span>
      );
    }

    // Handle special message types with better display
    if ( content === '[Sticker]' && msg.mediaUrl )
    {
      return null; // Sticker image is shown in media container
    }

    if ( content === '[Audio]' && msg.mediaUrl )
    {
      return null; // Audio player is shown in media container
    }

    if ( content.startsWith( '[Image]' ) || content.startsWith( '[Video]' ) )
    {
      // Show caption if present, otherwise hide (media shown above)
      const caption = content.replace( /^\[(Image|Video)\]\s*/, '' ).trim();
      return caption || null;
    }

    // Location messages
    if ( content.startsWith( '[Location:' ) )
    {
      const match = content.match( /\[Location: ([\d.-]+), ([\d.-]+)\]/ );
      if ( match )
      {
        const [ , lat, lng ] = match;
        return (
          <a
            href={ `https://maps.google.com/?q=${lat},${lng}` }
            target="_blank"
            rel="noopener noreferrer"
            className="location-link"
          >
            View Location
          </a>
        );
      }
    }

    // Contact card. Prefix match, not equality: the stored content now carries the
    // shared name and number after the label. The component returns null when no
    // payload was stored, which is the path the one pre-change row keeps using.
    if ( content.startsWith( '[Contact Card]' ) )
    {
      // The emptiness test lives here rather than relying on the component
      // returning null — a JSX element is an object and so always truthy, which
      // makes `<Component/> || fallback` a fallback that can never fire.
      const cards = msg.contactsPayload;
      if ( Array.isArray( cards ) && cards.length > 0 )
      {
        return <ContactCardBubble contacts={ cards } fallbackLabel="Contact Card" />;
      }
      return <span className="special-msg">Contact Card</span>;
    }

    // Interactive messages
    if ( content.startsWith( '[Interactive:' ) || content.startsWith( '[Button' ) || content.startsWith( '[List' ) )
    {
      return <span className="special-msg">{ content.replace( /[\[\]]/g, '' ) }</span>;
    }

    // Flow responses
    if ( content.startsWith( '[Flow Response:' ) )
    {
      return <span className="special-msg">Flow Response</span>;
    }

    // Order messages
    if ( content === '[Order]' )
    {
      return <span className="special-msg">Order</span>;
    }

    // Payment messages (from Pay page / RichTextEditor)
    if ( content.startsWith( '[Payment:' ) )
    {
      const match = content.match( /\[Payment: (.+?)\]/ );
      if ( match )
      {
        return <span className="special-msg">{ match[ 1 ] }</span>;
      }
      return <span className="special-msg">Payment Request</span>;
    }

    // Order Status messages (payment confirmation/failure)
    if ( content.startsWith( 'Order Status:' ) )
    {
      const isSuccess = content.includes( 'completed' ) || content.includes( 'captured' );
      return <span className="special-msg">{ isSuccess ? 'Paid' : 'Failed' } — { content.replace( 'Order Status: ', '' ) }</span>;
    }

    // Referral messages (click-to-WhatsApp ads)
    if ( content.startsWith( '[Referral:' ) )
    {
      const detail = content.replace( /^\[Referral: ?\w*\]\s*/, '' ).trim();
      return <span className="special-msg">{ detail || 'Ad Referral' }</span>;
    }

    // Ad click messages
    if ( content.startsWith( '[Ad Click' ) )
    {
      return <span className="special-msg">Ad Click</span>;
    }

    // Product / catalog messages
    if ( content.startsWith( '[Product' ) )
    {
      const detail = content.replace( /[\[\]]/g, '' );
      return <span className="special-msg">{ detail }</span>;
    }

    // Poll messages
    if ( content.startsWith( '[Poll' ) )
    {
      const question = content.match( /\[Poll: (.+?)\]/ )?.[ 1 ] || 'Poll';
      return <span className="special-msg">{ question }</span>;
    }

    // System messages
    if ( content === '[System Message]' )
    {
      return <span className="system-msg">System Message</span>;
    }

    // Default: show content as-is (hide blank messages)
    if ( !content.trim() )
    {
      return <span className="special-msg" style={ { opacity: 0.5, fontStyle: 'italic' } }>Menu / Interactive message</span>;
    }
    return content;
  };

  const inboxContent = (
    <>
      { !embedded && (
        <SEO
          title={ PAGE_SEO.whatsapp.title }
          description={ PAGE_SEO.whatsapp.description }
          keywords={ PAGE_SEO.whatsapp.keywords }
          canonical="/workspace/engage/whatsapp"
          noindex={ true }
        />
      ) }


      <div className={ `whatsapp-inbox ${mobileShowChat ? 'mobile-chat-active' : ''}` } style={ embedded ? { height: '100%', maxHeight: '100%' } : undefined }>
        {/* Contacts Sidebar */ }
        <div className="contacts-sidebar">
          <div className="sidebar-header">
            <div className="sidebar-controls">
              <button
                onClick={ handleClearAllInbox }
                disabled={ clearing || loading }
                title="Delete all messages and contacts"
                className="delete-all-btn"
              >
                { clearing ? '...' : <DeleteIcon size={ 20 } /> }
              </button>
              <input
                type="text"
                placeholder="Search contacts..."
                value={ searchQuery }
                onChange={ ( e ) => setSearchQuery( e.target.value ) }
                className="contacts-search"
              />
            </div>

            {/* Send a template to a brand-new / unsaved number or in bulk via CSV */ }
            <Button
              variant="primary"
              size="sm"
              onClick={ () => setShowNewTemplate( true ) }
              ariaLabel="Send an approved template to new numbers or in bulk via CSV"
              style={ { width: '100%', marginTop: 8 } }
            >
              New template message
            </Button>

            {/* Pagination Controls - Below Search - Show when multiple pages */ }
            { totalContactPages > 1 && (
              <div className="contacts-pagination top">
                <button
                  onClick={ () => setContactsPage( 1 ) }
                  disabled={ contactsPage === 1 }
                  title="First page"
                >
                  ««
                </button>
                <button
                  onClick={ () => setContactsPage( p => Math.max( 1, p - 1 ) ) }
                  disabled={ contactsPage === 1 }
                  title="Previous page"
                >
                  ‹
                </button>
                <span className="page-info">{ contactsPage } / { totalContactPages }</span>
                <button
                  onClick={ () => setContactsPage( p => Math.min( totalContactPages || 1, p + 1 ) ) }
                  disabled={ contactsPage >= ( totalContactPages || 1 ) }
                  title="Next page"
                >
                  ›
                </button>
                <button
                  onClick={ () => setContactsPage( totalContactPages || 1 ) }
                  disabled={ contactsPage >= ( totalContactPages || 1 ) }
                  title="Last page"
                >
                  »»
                </button>
              </div>
            ) }
            {/* Contact count */ }
            <div style={ { textAlign: 'center', fontSize: 11, color: '#9ca3af', padding: '4px 0 0' } }>
              { filteredContacts.length } contact{ filteredContacts.length !== 1 ? 's' : '' }{ searchQuery ? ' found' : '' }
            </div>
          </div>

          <div className="contacts-list">
            { loading ? (
              Array.from( { length: 8 } ).map( ( _, i ) => (
                <div key={ i } style={ { padding: '12px 16px' } }>
                  <SkeletonContact />
                </div>
              ) )
            ) : paginatedContacts.map( contact => {
              const wabaInfo = getWabaInfo( contact.lastWabaId );
              return (
                <div
                  key={ contact.id }
                  className={ `contact-item ${selectedContact?.id === contact.id ? 'selected' : ''}` }
                  onClick={ () => { setSelectedContact( contact ); setMobileShowChat( true ); } }
                >
                  <div className="contact-avatar" style={ { background: getAvatarColor( contact.name ), color: '#fff' } }>
                    { contact.name.charAt( 0 ).toUpperCase() }
                  </div>
                  <div className="contact-info">
                    <div className="contact-name">{ contact.name }{ contact.username ? <span style={ { color: '#9ca3af', fontWeight: 400, fontSize: 12, marginLeft: 4 } }>{ contact.username }</span> : null }</div>
                    <div className="contact-last-msg">
                      { wabaInfo && (
                        <span
                          className="waba-indicator"
                          style={ { background: wabaInfo.color } }
                        >
                          { wabaInfo.shortName }
                        </span>
                      ) }
                      { contact.lastMessage || 'No messages' }
                    </div>
                  </div>
                  <div className="contact-meta">
                    { contact.lastMessageTime && (
                      <span className="contact-time">{ formatTime( contact.lastMessageTime ) }</span>
                    ) }
                    { contact.unread > 0 && (
                      <span className="unread-badge">{ contact.unread }</span>
                    ) }
                    <button
                      className="contact-delete-btn"
                      onClick={ ( e ) => { e.stopPropagation(); handleDeleteContact( contact ); } }
                      disabled={ deleting === contact.id }
                      title="Delete contact"
                    >
                      { deleting === contact.id ? '...' : <DeleteIcon size={ 14 } /> }
                    </button>
                  </div>
                </div>
              );
            } ) }

            { !loading && loadError && filteredContacts.length === 0 && (
              <div style={ { padding: '20px', textAlign: 'center' } }>
                <p style={ { color: '#991b1b', fontSize: 13, marginBottom: 8 } }>Failed to connect to API</p>
                <button onClick={ () => loadData() } style={ { padding: '6px 14px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 12, fontWeight: 600, cursor: 'pointer' } }>Retry</button>
              </div>
            ) }
            { !loading && !loadError && filteredContacts.length === 0 && (
              <div style={ { padding: '20px', textAlign: 'center', color: '#6b7280' } }>
                { searchQuery ? 'No contacts found' : 'No WhatsApp conversations yet' }
              </div>
            ) }
          </div>
        </div>

        {/* Chat Area */ }
        <div className="chat-area">
          { selectedContact ? (
            <>
              {/* Chat Header */ }
              <div className="chat-header">
                <div className="chat-contact-info">
                  <button
                    className="mobile-back-btn"
                    onClick={ () => setMobileShowChat( false ) }
                    aria-label="Back to contacts"
                  >
                    ‹
                  </button>
                  <div className="contact-avatar" style={ { width: 40, height: 40, fontSize: 16, background: getAvatarColor( selectedContact.name ), color: '#fff' } }>
                    { selectedContact.name.charAt( 0 ).toUpperCase() }
                  </div>
                  <div>
                    <div className="chat-contact-name">{ selectedContact.name }</div>
                    <div className="chat-contact-phone">
                      { selectedContact.phone || selectedContact.bsuid || 'No identifier' }
                      { selectedContact.username ? ` · ${selectedContact.username}` : '' }
                      { !selectedContact.phone && selectedContact.bsuid ? ' (BSUID)' : '' }
                      { totalFilteredCount > 0 && (
                        <span style={ { marginLeft: 8, color: '#9ca3af', fontSize: 11 } }>
                          { totalFilteredCount } message{ totalFilteredCount !== 1 ? 's' : '' }
                        </span>
                      ) }
                    </div>
                  </div>
                </div>

                <div className="waba-selector">
                  <label>Send from:</label>
                  <Select
                    ariaLabel="Send from"
                    value={ selectedWaba }
                    onChange={ ( v ) => setSelectedWaba( v ) }
                    options={ WABA_SEND_OPTIONS }
                    style={ WABA_SEND_STYLE }
                  />
                  <button
                    className="clear-chat-btn"
                    onClick={ () => loadData() }
                    title="Refresh messages & delivery status"
                    aria-label="Refresh messages and delivery status"
                    style={ { marginRight: 4 } }
                  >
                    ↻
                  </button>
                  <button
                    className="clear-chat-btn"
                    onClick={ handleClearAllMessages }
                    disabled={ deleting === 'clearing' || filteredMessages.length === 0 }
                    title="Clear all messages for this contact"
                  >
                    { deleting === 'clearing' ? '...' : <DeleteIcon size={ 14 } /> }
                  </button>
                </div>
              </div>

              {/* Messages */ }
              <div className="messages-area" ref={ messagesAreaRef }>
                { loading && filteredMessages.length === 0 && (
                  <div className="messages-loading-state">
                    Loading messages...
                  </div>
                ) }

                { hasOlderMessages && (
                  <div className="load-older-container">
                    <button
                      className="load-older-btn"
                      onClick={ () => {
                        const area = messagesAreaRef.current;
                        const prevScrollHeight = area?.scrollHeight || 0;
                        const prevScrollTop = area?.scrollTop || 0;
                        setLoadingOlder( true );
                        pendingScrollRestore.current = true;
                        setVisibleMessageCount( c => c + MESSAGES_PER_PAGE );
                        setTimeout( () => {
                          if ( area )
                          {
                            const newScrollHeight = area.scrollHeight;
                            area.scrollTop = prevScrollTop + ( newScrollHeight - prevScrollHeight );
                          }
                          setLoadingOlder( false );
                          pendingScrollRestore.current = false;
                        }, 50 );
                      } }
                      disabled={ loadingOlder }
                    >
                      { loadingOlder ? 'Loading...' : `↑ Load ${Math.min( MESSAGES_PER_PAGE, totalFilteredCount - visibleMessageCount )} older messages (${totalFilteredCount - visibleMessageCount} remaining)` }
                    </button>
                  </div>
                ) }

                { visibleMessages.map( ( msg, idx ) => {
                  const wabaInfo = getWabaInfo( msg.awsPhoneNumberId );
                  const showDate = idx === 0 ||
                    new Date( msg.timestamp ).toDateString() !==
                    new Date( visibleMessages[ idx - 1 ].timestamp ).toDateString();

                  return (
                    <React.Fragment key={ msg.id }>
                      { showDate && (
                        <div className="date-divider">
                          <span>{ new Date( msg.timestamp ).toLocaleDateString( [], {
                            weekday: 'long',
                            month: 'short',
                            day: 'numeric'
                          } ) }</span>
                        </div>
                      ) }
                      <div className={ `message-bubble ${msg.direction}` }>
                        { msg.direction === 'inbound' && msg.senderName && (
                          <div className="message-sender-name">
                            { msg.senderName }
                          </div>
                        ) }
                        { msg.mediaUrl && (
                          <div className="message-media-container">
                            { ( () => {
                              const mediaType = getMediaType( msg );

                              if ( mediaType === 'image' || mediaType === 'sticker' )
                              {
                                return (
                                  <a href={ msg.mediaUrl } target="_blank" rel="noopener noreferrer">
                                    <img
                                      src={ msg.mediaUrl }
                                      alt={ mediaType === 'sticker' ? 'Sticker' : 'Image' }
                                      className={ `message-media ${mediaType === 'sticker' ? 'message-sticker' : 'message-image'}` }
                                      onError={ ( e ) => {
                                        console.error( 'Image load error:', msg.mediaUrl );
                                        ( e.target as HTMLImageElement ).style.display = 'none';
                                      } }
                                    />
                                  </a>
                                );
                              }

                              if ( mediaType === 'video' )
                              {
                                return (
                                  <video
                                    src={ msg.mediaUrl }
                                    controls
                                    className="message-media message-video"
                                    onError={ ( e ) => {
                                      console.error( 'Video load error:', msg.mediaUrl );
                                      ( e.target as HTMLVideoElement ).style.display = 'none';
                                    } }
                                  />
                                );
                              }

                              if ( mediaType === 'audio' )
                              {
                                return (
                                  <div className="voice-note-container">
                                    <audio
                                      src={ msg.mediaUrl }
                                      controls
                                      className="message-media message-audio"
                                      onError={ ( e ) => {
                                        console.error( 'Audio load error:', msg.mediaUrl );
                                        ( e.target as HTMLAudioElement ).style.display = 'none';
                                      } }
                                    />
                                    <VoiceNoteTranscription msg={ msg } />
                                  </div>
                                );
                              }

                              // Document or unknown type
                              return (
                                <div className="message-media message-document">
                                  <a
                                    href={ msg.mediaUrl }
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="document-link"
                                  >
                                    { getMediaLabel( mediaType ) } — View/Download
                                  </a>
                                </div>
                              );
                            } )() }
                          </div>
                        ) }
                        <div className="message-content">
                          { renderMessageContent( msg ) }
                        </div>
                        <div className="message-footer">
                          { wabaInfo && (
                            <span
                              className="message-waba-tag"
                              style={ { background: wabaInfo.color } }
                            >
                              { wabaInfo.shortName }
                            </span>
                          ) }
                          <span className="message-time">
                            { new Date( msg.timestamp ).toLocaleTimeString( [], {
                              hour: '2-digit',
                              minute: '2-digit'
                            } ) }
                          </span>
                          { msg.direction === 'outbound' && (
                            ( () => {
                              if ( msg.status === 'failed' )
                              {
                                let raw = '';
                                try { raw = msg.errorDetails ? ( JSON.parse( msg.errorDetails )?.message || '' ) : ''; } catch { raw = msg.errorDetails || ''; }
                                const info = describeWaError( msg.errorCode, raw );
                                const tipContent = info ? (
                                  <>
                                    <div style={ { fontWeight: 700, marginBottom: 4 } }>{ msg.errorCode ? `${msg.errorCode} · ` : '' }{ info.title }</div>
                                    <div style={ { marginBottom: 6 } }>{ info.reason }</div>
                                    <div style={ { color: 'rgba(0, 0, 0, 0.54)' } }><strong>Fix:</strong> { info.action }</div>
                                  </>
                                ) : 'Message failed to send.';
                                return (
                                  <span className="message-status failed">
                                    Failed{ info ? ` · ${info.title}` : '' }{ ' ' }
                                    <InfoTooltip content={ tipContent } label="Why this message failed" />
                                  </span>
                                );
                              }
                              return (
                                <span className={ `message-status ${msg.status}` }>
                                  { msg.status === 'read' ? 'Read' : msg.status === 'delivered' ? 'Delivered' : 'Sent' }
                                </span>
                              );
                            } )()
                          ) }
                          { msg.mediaUrl && (
                            <a
                              href={ msg.mediaUrl }
                              target="_blank"
                              rel="noopener noreferrer"
                              className="media-download-btn"
                              title="Open media in new tab"
                              download
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                            </a>
                          ) }
                        </div>
                        { msg.direction === 'inbound' && msg.whatsappMessageId && (
                          <div className="message-actions">
                            <button
                              className="reaction-btn"
                              onClick={ () => handleReaction( msg.whatsappMessageId!, msg.awsPhoneNumberId ) }
                              title="React"
                            >
                              +
                            </button>
                            <button
                              className="delete-msg-btn"
                              onClick={ () => handleDeleteMessage( msg ) }
                              disabled={ deleting === msg.id }
                              title="Delete message"
                            >
                              { deleting === msg.id ? '...' : <DeleteIcon size={ 12 } /> }
                            </button>
                          </div>
                        ) }
                        { msg.direction === 'outbound' && (
                          <div className="message-actions">
                            <button
                              className="delete-msg-btn"
                              onClick={ () => handleDeleteMessage( msg ) }
                              disabled={ deleting === msg.id }
                              title="Delete message"
                            >
                              { deleting === msg.id ? '...' : <DeleteIcon size={ 12 } /> }
                            </button>
                          </div>
                        ) }
                      </div>
                    </React.Fragment>
                  );
                } ) }
                <div ref={ messagesEndRef } />
              </div>

              {/* Input Area */ }
              <div className="input-area">
                {/* Media Preview (supports multiple files) */ }
                { mediaFiles.length > 0 && (
                  <div className="media-preview" style={ { display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' } }>
                    { mediaPreview && ( mediaFiles[ 0 ]?.type || '' ).startsWith( 'image/' ) && (
                      <img src={ mediaPreview } alt="Preview" style={ { maxHeight: 60, borderRadius: 6 } } />
                    ) }
                    { mediaFiles.map( ( f, i ) => (
                      <div key={ `${f.name}-${i}` } className="file-preview" style={ { display: 'flex', alignItems: 'center', gap: 6, background: 'var(--bg-secondary,#f3f4f6)', padding: '4px 8px', borderRadius: 6, fontSize: 12 } }>
                        <span style={ { maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }>{ f.name }</span>
                        <button className="clear-media-btn" onClick={ () => removeMediaAt( i ) } title="Remove"><DeleteIcon size={ 11 } /></button>
                      </div>
                    ) ) }
                    <button className="clear-media-btn" onClick={ clearMedia } title="Clear all" style={ { marginLeft: 4 } }><DeleteIcon size={ 12 } /></button>
                  </div>
                ) }

                {/* Quick actions row */ }
                <div style={ { display: 'flex', gap: 8, marginBottom: 6 } }>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={ () => setShowTemplateSender( true ) }
                    ariaLabel="Send an approved template message (works outside the 24h window)"
                  >
                    Send template
                  </Button>
                </div>

                <div className="input-wrapper">
                  {/* Hidden file input for RichTextEditor attachment button (multiple media supported) */ }
                  <input
                    type="file"
                    ref={ fileInputRef }
                    onChange={ handleMediaSelect }
                    multiple
                    accept="image/jpeg,image/png,image/webp,video/mp4,video/3gpp,audio/aac,audio/amr,audio/mpeg,audio/mp3,audio/mp4,audio/x-m4a,audio/ogg,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,text/plain"
                    style={ { display: 'none' } }
                  />

                  <div className="input-box">
                    <RichTextEditor
                      value={ messageText }
                      onChange={ setMessageText }
                      placeholder="Type a message..."
                      channel="whatsapp"
                      onSend={ handleSend }
                      showAISuggestions={ true }
                      selectedContactId={ selectedContact?.id }
                      phoneNumberId={ selectedWaba }
                      contactContext={ selectedContact?.name }
                      onAttachClick={ () => fileInputRef.current?.click() }
                      onSendTTS={ handleSendTTS }
                      onEmojiClick={ () => setShowEmojiPicker( !showEmojiPicker ) }
                      emojiActive={ showEmojiPicker }
                      onInteractiveClick={ () => setShowInteractiveComposer( !showInteractiveComposer ) }
                      interactiveActive={ showInteractiveComposer }
                      onLocationClick={ handleSendLocationRequest }
                    />
                  </div>
                </div>

                {/* Emoji picker panel */ }
                { showEmojiPicker && (
                  <div className="emoji-picker-panel">
                    <div className="emoji-search-row">
                      <input
                        type="text"
                        className="emoji-search-input"
                        placeholder="Search emoji..."
                        value={ emojiSearch }
                        onChange={ ( e ) => setEmojiSearch( e.target.value ) }
                        autoFocus
                      />
                    </div>
                    <div className="emoji-grid-scroll">
                      { ( () => {
                        const emojiData: Record<string, string[]> = {
                          'Smileys': [ '😀', '😃', '😄', '😁', '😆', '😅', '🤣', '😂', '🙂', '😊', '😇', '🥰', '😍', '🤩', '😘', '😗', '😚', '😙', '🥲', '😋', '😛', '😜', '🤪', '😝', '🤑', '🤗', '🤭', '🤫', '🤔', '🫡', '🤐', '🤨', '😐', '😑', '😶', '🫥', '😏', '😒', '🙄', '😬', '🤥', '😌', '😔', '😪', '🤤', '😴', '😷', '🤒', '🤕', '🤢', '🤮', '🥵', '🥶', '🥴', '😵', '🤯', '🤠', '🥳', '🥸', '😎', '🤓', '🧐', '😕', '🫤', '😟', '🙁', '😮', '😯', '😲', '😳', '🥺', '🥹', '😦', '😧', '😨', '😰', '😥', '😢', '😭', '😱', '😖', '😣', '😞', '😓', '😩', '😫', '🥱', '😤', '😡', '😠', '🤬', '😈', '👿', '💀', '☠️', '💩', '🤡', '👹', '👺', '👻', '👽', '👾', '🤖' ],
                          'Gestures': [ '👋', '🤚', '🖐️', '✋', '🖖', '🫱', '🫲', '🫳', '🫴', '👌', '🤌', '🤏', '✌️', '🤞', '🫰', '🤟', '🤘', '🤙', '👈', '👉', '👆', '🖕', '👇', '☝️', '🫵', '👍', '👎', '✊', '👊', '🤛', '🤜', '👏', '🙌', '🫶', '👐', '🤲', '🤝', '🙏', '✍️', '💅', '🤳', '💪', '🦾', '🦿', '🦵', '🦶', '👂', '🦻', '👃', '🧠', '🫀', '🫁', '🦷', '🦴', '👀', '👁️', '👅', '👄' ],
                          'Hearts': [ '❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍', '🤎', '💔', '❤️‍🔥', '❤️‍🩹', '❣️', '💕', '💞', '💓', '💗', '💖', '💘', '💝', '💟', '♥️', '🫶', '😍', '🥰', '😘', '💋', '💏', '💑' ],
                          'Objects': [ '📱', '💻', '⌨️', '🖥️', '🖨️', '🖱️', '💾', '💿', '📀', '📷', '📸', '📹', '🎥', '📽️', '🎞️', '📞', '☎️', '📟', '📠', '📺', '📻', '🎙️', '🎚️', '🎛️', '⏱️', '⏲️', '⏰', '🕰️', '⌛', '⏳', '📡', '🔋', '🔌', '💡', '🔦', '🕯️', '🧯', '🛢️', '💸', '💵', '💴', '💶', '💷', '🪙', '💰', '💳', '💎', '⚖️', '🪜', '🧰', '🪛', '🔧', '🔨', '⚒️', '🛠️', '⛏️', '🪚', '🔩', '⚙️', '🪤', '🧲', '🔫', '💣', '🧨', '🪓', '🔪', '🗡️', '⚔️', '🛡️', '🚬', '⚰️', '🪦', '⚱️', '🏺', '🔮', '📿', '🧿', '🪬', '💈', '⚗️', '🔭', '🔬', '🕳️', '🩹', '🩺', '🩻', '🩼', '💊', '💉', '🩸', '🧬', '🦠', '🧫', '🧪', '🌡️', '🧹', '🪠', '🧺', '🧻', '🚰', '🚿', '🛁', '🛀', '🧼', '🪥', '🪒', '🧽', '🪣', '🧴', '🛎️', '🔑', '🗝️', '🚪', '🪑', '🛋️', '🛏️', '🛌', '🧸', '🪆', '🖼️', '🪞', '🪟', '🛍️', '🛒', '🎁', '🎈', '🎏', '🎀', '🪄', '🪅', '🎊', '🎉', '🎎', '🏮', '🎐', '🧧', '✉️', '📩', '📨', '📧', '💌', '📥', '📤', '📦', '🏷️', '🪧', '📪', '📫', '📬', '📭', '📮', '📯', '📜', '📃', '📄', '📑', '🧾', '📊', '📈', '📉', '🗒️', '🗓️', '📆', '📅', '🗑️', '📇', '🗃️', '🗳️', '🗄️', '📋', '📁', '📂', '🗂️', '🗞️', '📰', '📓', '📔', '📒', '📕', '📗', '📘', '📙', '📚', '📖', '🔖', '🧷', '🔗', '📎', '🖇️', '📐', '📏', '🧮', '📌', '📍', '✂️', '🖊️', '🖋️', '✒️', '🖌️', '🖍️', '📝', '✏️', '🔍', '🔎', '🔏', '🔐', '🔒', '🔓' ],
                          'Travel': [ '🚗', '🚕', '🚙', '🚌', '🚎', '🏎️', '🚓', '🚑', '🚒', '🚐', '🛻', '🚚', '🚛', '🚜', '🏍️', '🛵', '🚲', '🛴', '🛹', '🛼', '🚏', '🛣️', '🛤️', '🛞', '⛽', '🛞', '🚨', '🚥', '🚦', '🛑', '🚧', '⚓', '🛟', '⛵', '🛶', '🚤', '🛳️', '⛴️', '🛥️', '🚢', '✈️', '🛩️', '🛫', '🛬', '🪂', '💺', '🚁', '🚟', '🚠', '🚡', '🛰️', '🚀', '🛸', '🌍', '🌎', '🌏', '🗺️', '🧭', '🏔️', '⛰️', '🌋', '🗻', '🏕️', '🏖️', '🏜️', '🏝️', '🏞️', '🏟️', '🏛️', '🏗️', '🧱', '🪨', '🪵', '🛖', '🏘️', '🏚️', '🏠', '🏡', '🏢', '🏣', '🏤', '🏥', '🏦', '🏨', '🏩', '🏪', '🏫', '🏬', '🏭', '🏯', '🏰', '💒', '🗼', '🗽', '⛪', '🕌', '🛕', '🕍', '⛩️', '🕋', '⛲', '⛺', '🌁', '🌃', '🏙️', '🌄', '🌅', '🌆', '🌇', '🌉', '♨️', '🎠', '🛝', '🎡', '🎢', '💈', '🎪', '🚂', '🚃', '🚄', '🚅', '🚆', '🚇', '🚈', '🚉', '🚊', '🚝', '🚞', '🚋', '🚌' ],
                          'Food': [ '🍏', '🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🫐', '🍈', '🍒', '🍑', '🥭', '🍍', '🥥', '🥝', '🍅', '🍆', '🥑', '🥦', '🥬', '🥒', '🌶️', '🫑', '🌽', '🥕', '🫒', '🧄', '🧅', '🥔', '🍠', '🫘', '🥐', '🥯', '🍞', '🥖', '🥨', '🧀', '🥚', '🍳', '🧈', '🥞', '🧇', '🥓', '🥩', '🍗', '🍖', '🦴', '🌭', '🍔', '🍟', '🍕', '🫓', '🥪', '🥙', '🧆', '🌮', '🌯', '🫔', '🥗', '🥘', '🫕', '🥫', '🍝', '🍜', '🍲', '🍛', '🍣', '🍱', '🥟', '🦪', '🍤', '🍙', '🍚', '🍘', '🍥', '🥠', '🥮', '🍢', '🍡', '🍧', '🍨', '🍦', '🥧', '🧁', '🍰', '🎂', '🍮', '🍭', '🍬', '🍫', '🍿', '🍩', '🍪', '🌰', '🥜', '🍯', '🥛', '🍼', '🫖', '☕', '🍵', '🧃', '🥤', '🧋', '🍶', '🍺', '🍻', '🥂', '🍷', '🥃', '🍸', '🍹', '🧉', '🍾', '🧊', '🥄', '🍴', '🍽️', '🥣', '🥡', '🥢', '🧂' ],
                          'Nature': [ '🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐻‍❄️', '🐨', '🐯', '🦁', '🐮', '🐷', '🐽', '🐸', '🐵', '🙈', '🙉', '🙊', '🐒', '🐔', '🐧', '🐦', '🐤', '🐣', '🐥', '🦆', '🦅', '🦉', '🦇', '🐺', '🐗', '🐴', '🦄', '🐝', '🪱', '🐛', '🦋', '🐌', '🐞', '🐜', '🪰', '🪲', '🪳', '🦟', '🦗', '🕷️', '🕸️', '🦂', '🐢', '🐍', '🦎', '🦖', '🦕', '🐙', '🦑', '🦐', '🦞', '🦀', '🪸', '🐡', '🐠', '🐟', '🐬', '🐳', '🐋', '🦈', '🐊', '🐅', '🐆', '🦓', '🦍', '🦧', '🐘', '🦛', '🦏', '🐪', '🐫', '🦒', '🦘', '🦬', '🐃', '🐂', '🐄', '🐎', '🐖', '🐏', '🐑', '🦙', '🐐', '🦌', '🐕', '🐩', '🦮', '🐕‍🦺', '🐈', '🐈‍⬛', '🪶', '🐓', '🦃', '🦤', '🦚', '🦜', '🦢', '🦩', '🕊️', '🐇', '🦝', '🦨', '🦡', '🦫', '🦦', '🦥', '🐁', '🐀', '🐿️', '🦔', '🌵', '🎄', '🌲', '🌳', '🌴', '🪵', '🌱', '🌿', '☘️', '🍀', '🎍', '🪴', '🎋', '🍃', '🍂', '🍁', '🪺', '🪹', '🍄', '🐚', '🪨', '🌾', '💐', '🌷', '🌹', '🥀', '🌺', '🌸', '🌼', '🌻', '🌞', '🌝', '🌛', '🌜', '🌚', '🌕', '🌖', '🌗', '🌘', '🌑', '🌒', '🌓', '🌔', '🌙', '🌎', '🌍', '🌏', '🪐', '💫', '⭐', '🌟', '✨', '⚡', '☄️', '💥', '🔥', '🌪️', '🌈', '☀️', '🌤️', '⛅', '🌥️', '☁️', '🌦️', '🌧️', '⛈️', '🌩️', '🌨️', '❄️', '☃️', '⛄', '🌬️', '💨', '💧', '💦', '🫧', '☔', '☂️', '🌊', '🌫️' ],
                          'Symbols': [ '✅', '❌', '⭕', '🔴', '🟠', '🟡', '🟢', '🔵', '🟣', '⚫', '⚪', '🟤', '🔺', '🔻', '🔸', '🔹', '🔶', '🔷', '💠', '🔘', '🔳', '🔲', '🏁', '🚩', '🎌', '🏴', '🏳️', '🏳️‍🌈', '🏳️‍⚧️', '🏴‍☠️', '🇮🇳', '❗', '❓', '❕', '❔', '‼️', '⁉️', '💯', '🔅', '🔆', '🔱', '⚜️', '〽️', '⚠️', '🚸', '🔰', '♻️', '✳️', '❇️', '🌐', '💹', '💲', '💱', '©️', '®️', '™️', '#️⃣', '*️⃣', '0️⃣', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟', '🔠', '🔡', '🔢', '🔣', '🔤', '🅰️', '🆎', '🅱️', '🆑', '🆒', '🆓', 'ℹ️', '🆔', 'Ⓜ️', '🆕', '🆖', '🅾️', '🆗', '🅿️', '🆘', '🆙', '🆚', '🈁', '🈂️', '🈷️', '🈶', '🈯', '🉐', '🈹', '🈚', '🈲', '🉑', '🈸', '🈴', '🈳', '㊗️', '㊙️', '🈺', '🈵', '🔴', '🟠', '🟡', '🟢', '🔵', '🟣', '🟤', '⚫', '⚪', '🔘' ],
                        };
                        const search = emojiSearch.toLowerCase();
                        const categoryNames = Object.keys( emojiData );
                        return categoryNames.map( cat => {
                          const emojis = emojiData[ cat ];
                          if ( search )
                          {
                            // Simple search: filter by category name match
                            if ( !cat.toLowerCase().includes( search ) ) return null;
                          }
                          return (
                            <div key={ cat } className="emoji-category">
                              <div className="emoji-category-label">{ cat }</div>
                              <div className="emoji-category-grid">
                                { emojis.map( ( emoji, i ) => (
                                  <button
                                    key={ `${cat}-${i}` }
                                    className="emoji-btn"
                                    onClick={ () => { setMessageText( prev => prev + emoji ); setShowEmojiPicker( false ); setEmojiSearch( '' ); } }
                                  >
                                    { emoji }
                                  </button>
                                ) ) }
                              </div>
                            </div>
                          );
                        } ).filter( Boolean );
                      } )() }
                    </div>
                  </div>
                ) }

                {/* Interactive Message Composer */ }
                { showInteractiveComposer && selectedContact && (
                  <InteractiveMessageComposer
                    contactId={ selectedContact.id }
                    phoneNumberId={ selectedWaba }
                    recipientBsuid={ selectedContact.bsuid || undefined }
                    onClose={ () => setShowInteractiveComposer( false ) }
                    onSent={ () => loadData() }
                    onError={ ( msg ) => toast.error( msg ) }
                  />
                ) }

                {/* Template Sender — fetches the selected WABA's approved templates */ }
                { showTemplateSender && selectedContact && (
                  <TemplateSender
                    contactId={ selectedContact.id }
                    contactName={ selectedContact.name }
                    phoneNumberId={ selectedWaba }
                    recipientBsuid={ selectedContact.bsuid || undefined }
                    onClose={ () => setShowTemplateSender( false ) }
                    onSent={ () => { setShowTemplateSender( false ); loadData(); } }
                    onError={ ( msg ) => toast.error( msg ) }
                  />
                ) }
              </div>
            </>
          ) : (
            <div className="empty-chat">
              <div className="empty-chat-icon">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                </svg>
              </div>
              <h3>WhatsApp Unified Inbox</h3>
              <p>Select a contact to start messaging</p>
              <p style={ { fontSize: '12px', marginTop: '12px', color: '#6b7280' } }>
                Messages from all WABAs appear here · Auto-refreshes every 10s
              </p>
            </div>
          ) }
        </div>

        {/* New Template Message → send to a brand-new / unsaved number */ }
        { showNewTemplate && (
          <TemplateSender
            contactName=""
            phoneNumberId={ selectedWaba }
            enableManualRecipient
            onClose={ () => setShowNewTemplate( false ) }
            onSent={ () => { setShowNewTemplate( false ); loadData(); } }
            onError={ ( msg ) => toast.error( msg ) }
          />
        ) }
      </div>
    </>
  );

  if ( embedded )
  {
    return inboxContent;
  }

  return (
    <Layout user={ user } onSignOut={ signOut }>
      { inboxContent }
    </Layout>
  );
};

export default WhatsAppUnifiedInbox;
