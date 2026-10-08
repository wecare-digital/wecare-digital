/**
 * Unified Inbox — conversation-grouped view across ALL channels.
 *
 * Reads the single canonical MessagesTable (via api.listMessages channel=ALL), groups
 * by contact, and shows a threaded conversation with per-message channel badges.
 * Sending is channel-specific, so replies deep-link to the channel's own tool.
 *
 * WhatsApp's dedicated inbox ([retired public path]/whatsapp) stays as-is for full WhatsApp send features.
 */

import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import InteractiveMessageComposer from '../../../../components/InteractiveMessageComposer';
import ContactMessageComposer from '../../../../components/ContactMessageComposer';
import ContactCardBubble from '../../../../components/ContactCardBubble';
import LocationSendComposer from '../../../../components/LocationSendComposer';
import TemplateSender from '../../../../components/TemplateSender';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { colors, shadow } from '../../../../lib/design-tokens';
import { WHATSAPP_PHONES, PAYMENT_PHONES, DEFAULT_GSTIN, PAYMENT_CONFIG, GST_RATES } from '../../../../config/constants';
import { searchEmojiCategories } from '../../../../lib/emoji-data';
import { inferMimeFromName, validateWaMediaSize, formatBytes } from '../../../../lib/wa-media';
import { waErrorTooltip } from '../../../../lib/wa-errors';
import { scrollToEnd } from '../../../../lib/scroll-to-end';

const WABAS = [
    { id: WHATSAPP_PHONES.primary.id, name: WHATSAPP_PHONES.primary.name, display: WHATSAPP_PHONES.primary.display },
    { id: WHATSAPP_PHONES.secondary.id, name: WHATSAPP_PHONES.secondary.name, display: WHATSAPP_PHONES.secondary.display },
];

interface PageProps {
    signOut?: () => void;
    user?: any;
    embedded?: boolean;
    /**
     * Preset the channel filter. This is what lets one inbox replace the
     * per-channel ones: the RCS and Email hubs embed this with their own channel
     * rather than shipping their own 273- and 263-line copies, of which 196 lines
     * were byte-identical to each other.
     *
     * A preset, not a lock — unlike the logs view, the selector stays visible.
     * A conversation legitimately spans channels (a thread can open on RCS and
     * continue over SMS when RCS is not deliverable), so widening back to ALL is
     * the point rather than a mistake.
     *
     * `?channel=` is honoured too, so `/workspace/engage/inbox?channel=voice` is a real
     * destination. That is how Calls stopped needing a page of its own.
     */
    channel?: string;
}

// Channel identity (distinct, on-brand) + reply deep-link target.
const CHANNEL: Record<string, { label: string; fg: string; bg: string; reply: string }> = {
    whatsapp: { label: 'WhatsApp', fg: '#15803d', bg: '#f0fdf4', reply: '/workspace/engage/whatsapp' },
    sms: { label: 'SMS', fg: '#1d4ed8', bg: '#eff6ff', reply: '/workspace/engage/sms' },
    email: { label: 'Email', fg: '#b45309', bg: '#fffbeb', reply: '/workspace/engage/ses' },
    rcs: { label: 'RCS', fg: '#0f766e', bg: '#f0fdfa', reply: '/workspace/engage/rcs' },
    voice: { label: 'Voice', fg: '#6d28d9', bg: '#f5f3ff', reply: '/workspace/engage/voice' },
};

const chMeta = ( c?: string ) => CHANNEL[ ( c || 'whatsapp' ).toLowerCase() ] || { label: c || '?', fg: colors.textMuted, bg: colors.bgSecondary, reply: '/workspace/engage' };

/*
 * The toolbar channel filter's rows. 'ALL' is uppercase here and nowhere else in this file,
 * which is deliberate - `channelFilter` is compared against the API's uppercase `channel`
 * after lowercasing, and `?channel=` resolves to 'ALL' when it names nothing known.
 */
const CHANNEL_FILTER_OPTIONS: SelectOption[] = [
    { value: 'ALL', label: 'All channels' },
    { value: 'whatsapp', label: 'WhatsApp' },
    { value: 'sms', label: 'SMS' },
    { value: 'email', label: 'Email' },
    { value: 'rcs', label: 'RCS' },
    { value: 'voice', label: 'Voice' },
];

/*
 * The reply bar's two choosers: which WABA sends an outbound WhatsApp message, and the India
 * TRANSACTIONAL/PROMOTIONAL DLT classification on an outbound SMS. Same order, same values
 * and the same visible text as the <option> rows they replaced.
 */
const WABA_OPTIONS: SelectOption[] = WABAS.map(
    w => ( { value: w.id, label: `${ w.name } (${ w.display })` } )
);
const SMS_TYPE_OPTIONS: SelectOption[] = [
    { value: 'TRANSACTIONAL', label: 'Transactional' },
    { value: 'PROMOTIONAL', label: 'Promotional' },
];

/* LAYOUT ONLY - both sit in `.ui-wa-bar`, a flex row, and the box is the trigger's. */
const WABA_SELECT_STYLE: React.CSSProperties = { flex: '0 1 240px' };
const SMS_TYPE_SELECT_STYLE: React.CSSProperties = { flex: '0 0 160px' };
/*
 * BATCH 2f - THE TWO MONEY CONTROLS IN THE `ui-pay` REQUEST-PAYMENT PANEL, and the last two
 * selects in this file. They were held back from 2c deliberately: the sender chooser decides
 * which number a payment request is sent FROM, and the GST chooser sets the rate applied to an
 * amount, so both are on an India payment path and `whatsapp-payments-india-reference.md`
 * applies to them. Same values, same order, same visible text as the <option> rows they
 * replaced - the GST values stay STRINGS because `payItems[].gstRate` is a string and the
 * panel's own `parseInt` does the only conversion there is. No arithmetic is introduced here.
 */
const PAY_PHONE_OPTIONS: SelectOption[] = PAYMENT_PHONES.map( p => ( {
    value: p.id,
    label: `${ p.display } (${ p.name })${ p.paymentProtected ? ' [Protected]' : '' }`,
} ) );
const PAY_GST_OPTIONS: SelectOption[] = GST_RATES.map(
    g => ( { value: String( g.value ), label: `GST ${ g.label }` } )
);
/* LAYOUT ONLY - `.ui-pay-gst` capped the native control at 110px inside `.ui-pay-row`. */
const PAY_GST_SELECT_STYLE: React.CSSProperties = { flex: '0 0 110px' };

// Reaction quick-set for the per-message react popover.
const REACT_EMOJIS = [ '👍', '❤️', '😂', '😮', '😢', '🙏', '🔥', '✅' ];

// Friendly label for a message — avoids showing bare "[unknown]" / "[whatsapp]".
const TYPE_LABELS: Record<string, string> = {
    // `text`, `call`, `template` and `interactive_list` are here so an empty-content
    // row stops falling through to a bare "Message" — 234 outbound rows did.
    text: 'Message', call: 'Call', template: 'Template message', interactive_list: 'List reply',
    image: 'Photo', video: 'Video', audio: 'Voice message', voice: 'Voice message',
    document: 'Document', sticker: 'Sticker', location: 'Location', contacts: 'Contact card',
    order: 'Order', poll: 'Poll', reaction: 'Reaction', button: 'Button reply',
    interactive: 'Interactive reply', request_welcome: 'Started conversation', system: 'System update',
    referral: 'Ad referral', ad_click: 'Ad click', unsupported: 'Unsupported message', unknown: 'Message',
};
const prettyMsg = ( content?: string, messageType?: string ): string => {
    const raw = ( content || '' ).trim();
    const mt = ( messageType || '' ).toLowerCase();
    // Never show Meta's own error text to an agent. The two full-string checks below
    // covered one string the extractor never produced while missing the one it always
    // did, so match the `[Unsupported: ` PREFIX as well. This also catches rows stored
    // before the extractor started emitting a stable sentinel.
    if ( raw.toLowerCase().startsWith( '[unsupported: ' ) )
        return TYPE_LABELS[ 'unsupported' ];
    // A shared contact card stores `[Contact Card] <name> · <phone>`. Drop the
    // bracket label and show who was shared; show the label when that is all there is.
    if ( raw.startsWith( '[Contact Card]' ) )
        return raw.slice( '[Contact Card]'.length ).trim() || TYPE_LABELS[ 'contacts' ];
    // Real text/caption → show as-is (unless it's just the auto bracket placeholder).
    if ( raw && raw.toLowerCase() !== '[unknown]' && raw.toLowerCase() !== `[${mt}]` && raw.toLowerCase() !== '[message type not supported by whatsapp business api]' )
        return raw;
    return TYPE_LABELS[ mt ] || 'Message';
};
const isSysLabel = ( content?: string ) => /^\[.*\]$/.test( ( content || '' ).trim() );

// Themed line icons for the composer toolbar (outlined, currentColor — matches theme).
const ICON_PATHS: Record<string, string> = {
    emoji: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM9 10h.01M15 10h.01M8.5 14a4 4 0 0 0 7 0',
    chat: 'M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.5A8 8 0 1 1 21 12Z',
    attach: 'M21 11.5 12.6 19.9a5 5 0 0 1-7.1-7.1l8-8a3.3 3.3 0 0 1 4.7 4.7l-8 8a1.6 1.6 0 1 1-2.3-2.3l7-7',
    list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
    pin: 'M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11ZM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z',
    user: 'M20 21a8 8 0 1 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z',
    mic: 'M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3ZM5 11a7 7 0 0 0 14 0M12 18v3',
    sparkle: 'M12 3l1.8 4.9L18.7 10l-4.9 1.8L12 17l-1.8-5.2L5.3 10l4.9-1.1L12 3Z',
    pay: 'M3 7h18v10H3zM3 11h18M7 15h3',
    cart: 'M3 4h2l2.4 12.5a2 2 0 0 0 2 1.5h7.7a2 2 0 0 0 2-1.6L22 8H6M9 21a1 1 0 1 0 0-2 1 1 0 0 0 0 2Zm9 0a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z',
    refresh: 'M21 12a9 9 0 1 1-2.64-6.36M21 4v5h-5',
    phone: 'M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2Z',
    block: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM5.6 5.6l12.8 12.8',
    mail: 'M4 6h16v12H4zM4 7l8 6 8-6',
};
const Icon: React.FC<{ name: string; size?: number }> = ( { name, size = 18 } ) => (
    <svg width={ size } height={ size } viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" style={ { display: 'block' } }>
        <path d={ ICON_PATHS[ name ] } />
    </svg>
);

interface Conversation {
    contactId: string;
    name: string;
    channels: Set<string>;
    lastContent: string;
    // Carried so the preview can call prettyMsg instead of keeping a second copy of
    // its logic — a duplicate is how the unsupported label stayed wrong in one place.
    lastType: string;
    lastTs: number;
    lastChannel: string;
}

const fmtTime = ( ts: string | number ) => {
    const d = new Date( typeof ts === 'number' ? ts : ts );
    if ( isNaN( d.getTime() ) ) return '';
    const now = Date.now();
    const diff = now - d.getTime();
    if ( diff < 86400000 ) return d.toLocaleTimeString( 'en-IN', { hour: '2-digit', minute: '2-digit' } );
    return d.toLocaleDateString( 'en-IN', { day: '2-digit', month: 'short' } );
};

const UnifiedInbox: React.FC<PageProps> = ( { signOut, user, embedded, channel } ) => {
    const toast = useToastContext();
    const [ messages, setMessages ] = useState<api.Message[]>( [] );
    const [ contactNames, setContactNames ] = useState<Record<string, string>>( {} );
    const [ contactDir, setContactDir ] = useState<Record<string, { username?: string; bsuid?: string; book?: string }>>( {} );
    const [ selected, setSelected ] = useState<string | null>( null );
    // Seeded from the `channel` prop, else `?channel=`. Lowercased because the
    // comparisons below lowercase each message's own channel, and 'ALL' is the
    // only value that is not a channel name.
    const router = useRouter();
    const presetChannel = ( channel || '' ).toLowerCase();
    const [ channelFilter, setChannelFilter ] = useState<string>(
        presetChannel && presetChannel in CHANNEL ? presetChannel : 'ALL' );
    const [ search, setSearch ] = useState( '' );
    const [ loading, setLoading ] = useState( true );
    const [ replyText, setReplyText ] = useState( '' );
    const [ sending, setSending ] = useState( false );
    const [ replyingTo, setReplyingTo ] = useState<api.Message | null>( null );
    const [ deletingId, setDeletingId ] = useState<string | null>( null );
    const [ visibleCount, setVisibleCount ] = useState( 50 );
    const [ selectedWaba, setSelectedWaba ] = useState( WABAS[ 0 ].id );
    // True once the agent has changed "Send from" for the conversation that is
    // currently open. Reset on every thread change, so the default is always the
    // thread's own WABA and a deliberate override is per-conversation rather than
    // sticky across threads. State rather than a ref: it is read during render.
    const [ wabaOverridden, setWabaOverridden ] = useState( false );
    const [ showTemplateSender, setShowTemplateSender ] = useState( false );
    const [ aiSuggesting, setAiSuggesting ] = useState( false );
    const [ summary, setSummary ] = useState( '' );
    const [ summarizing, setSummarizing ] = useState( false );
    const [ quickReplies, setQuickReplies ] = useState<string[]>( [] );
    const [ showQuick, setShowQuick ] = useState( false );
    const [ meta, setMeta ] = useState<api.ConversationMeta | null>( null );
    const [ noteText, setNoteText ] = useState( '' );
    const [ showNotes, setShowNotes ] = useState( false );
    const [ showEmoji, setShowEmoji ] = useState( false );
    const [ composer, setComposer ] = useState<null | 'interactive' | 'contact' | 'location' | 'pay' | 'tts' | 'catalog'>( null );
    // Per-channel editor state
    const [ smsType, setSmsType ] = useState<'TRANSACTIONAL' | 'PROMOTIONAL'>( 'TRANSACTIONAL' );
    const [ emailSubject, setEmailSubject ] = useState( '' );
    const [ rcsTemplates, setRcsTemplates ] = useState<any[]>( [] );
    const [ showRcsTemplates, setShowRcsTemplates ] = useState( false );
    // Searchable emoji picker
    const [ emojiSearch, setEmojiSearch ] = useState( '' );
    // Multi-file media staging
    const [ mediaFiles, setMediaFiles ] = useState<File[]>( [] );
    const [ mediaPreview, setMediaPreview ] = useState<string | null>( null );
    // Per-message reaction
    const [ reactFor, setReactFor ] = useState<string | null>( null );
    // Full TTS picker
    const [ ttsText, setTtsText ] = useState( '' );
    const [ ttsLang, setTtsLang ] = useState( 'en-IN' );
    const [ ttsVoice, setTtsVoice ] = useState( 'Kajal' );
    const [ ttsEngine, setTtsEngine ] = useState( 'neural' );
    const [ pollyVoices, setPollyVoices ] = useState<Record<string, { id: string; gender: string; engine: string }[]>>( {} );
    // Full payment form
    const [ payPhone, setPayPhone ] = useState( PAYMENT_CONFIG.phoneNumberId );
    const [ payItems, setPayItems ] = useState<{ name: string; amount: string; quantity: string; gstRate: string }[]>( [ { name: '', amount: '', quantity: '1', gstRate: '0' } ] );
    const [ payPromo, setPayPromo ] = useState( '0' );
    const [ payDelivery, setPayDelivery ] = useState( '0' );
    const [ payGstin, setPayGstin ] = useState( DEFAULT_GSTIN );
    const [ payOrderId, setPayOrderId ] = useState( '' );
    const [ payUnlocked, setPayUnlocked ] = useState( false );
    // Catalog / product message
    const [ catalogId, setCatalogId ] = useState( '' );
    const [ catalogProducts, setCatalogProducts ] = useState( '' );
    const [ catalogBody, setCatalogBody ] = useState( '' );
    // No catalogList/catalogLoading: they existed only for the removed product picker.
    // Block + mark-unread + click-to-call
    const [ blocking, setBlocking ] = useState( false );
    const [ unreadIds, setUnreadIds ] = useState<Set<string>>( new Set() );
    const fileRef = useRef<HTMLInputElement | null>( null );
    const threadBodyRef = useRef<HTMLDivElement | null>( null );
    const threadEndRef = useRef<HTMLDivElement | null>( null );
    const pendingScrollRestore = useRef( false );
    const prevThreadLen = useRef( 0 );
    const lastTypingRef = useRef<{ id: string; at: number }>( { id: '', at: 0 } );
    const [ loadingOlder, setLoadingOlder ] = useState( false );
    // Why the last load returned nothing, when it returned nothing for a reason.
    const [ loadFailure, setLoadFailure ] = useState<api.ApiFailure | null>( null );

    const loadData = useCallback( async () => {
        try
        {
            // `listMessages`/`listContacts` return [] for BOTH "table is empty" and
            // "the request failed", so the catch below never fires on an API error
            // and the page would render "No conversations" over an outage.
            // collectApiFailures recovers the reason without changing 300 wrappers.
            const { data: [ msgs, contacts ], failures } = await api.collectApiFailures( () => Promise.all( [
                api.listMessages( undefined, 'ALL', 2000 ),
                api.listContacts(),
            ] ) );
            setLoadFailure( failures[ 0 ] ?? null );
            const names: Record<string, string> = {};
            const dir: Record<string, { username?: string; bsuid?: string; book?: string }> = {};
            contacts.forEach( c => {
                names[ c.contactId ] = c.name || c.phone || c.email || c.contactId;
                if ( c.username || c.bsuid || c.contactBookName )
                    dir[ c.contactId ] = { username: c.username || undefined, bsuid: c.bsuid || undefined, book: c.contactBookName || undefined };
            } );
            setContactNames( names );
            setContactDir( dir );
            setMessages( msgs );
        } catch
        {
            toast.error( 'Failed to load inbox' );
        } finally
        {
            setLoading( false );
        }
    }, [ toast ] );

    // `?channel=` applied after hydration. On a statically exported page
    // router.query is EMPTY on first render, so the state initializer above cannot
    // see it - this is not a duplicate of that. The prop wins, because a hub
    // presetting its own channel must not be overridden by a stale URL.
    //
    // It MUST reset to 'ALL' when the URL carries no channel. All six sidebar Inbox
    // entries are the same route `/workspace/engage/inbox` differing only by query string, so Next
    // keeps this component mounted across them and React state survives the
    // navigation. The first version of this effect only ever *set* the filter, so
    // going `?channel=email` -> "All channels" left it stuck on `email` - and email
    // has no rows, so the page that promises everything rendered "No conversations".
    // `dm/logs` avoided this by deriving its channel with useMemo; the inbox cannot,
    // because its selector has to stay user-changeable.
    //
    // Guarded on `router.isReady` so a deep link to `?channel=rcs` is not reset to
    // ALL during the pre-hydration pass when `router.query` is still empty.
    useEffect( () => {
        if ( presetChannel || !router.isReady ) return;
        const q = String( router.query.channel || '' ).toLowerCase();
        setChannelFilter( q && q in CHANNEL ? q : 'ALL' );
    }, [ router.isReady, router.query.channel, presetChannel ] );

    useEffect( () => {
        loadData();
        const t = setInterval( loadData, 15000 );
        return () => clearInterval( t );
    }, [ loadData ] );

    // Load approved WhatsApp templates once (for the template send button).
    useEffect( () => {
        api.listRcsTemplates().then( t => setRcsTemplates( t || [] ) ).catch( () => { } );
        api.getPollyVoices().then( r => { if ( r?.voices && Object.keys( r.voices ).length ) setPollyVoices( r.voices ); } ).catch( () => { } );
        try { const raw = window.localStorage.getItem( 'wd_unread' ); if ( raw ) setUnreadIds( new Set( JSON.parse( raw ) ) ); } catch { }
        api.listAutomationRules().then( rs => setQuickReplies(
            ( rs || [] ).filter( r => r.enabled && r.actionType === 'reply' && r.actionValue ).map( r => r.actionValue )
        ) ).catch( () => { } );
    }, [] );

    // Reset composer context when switching conversations.
    useEffect( () => {
        setReplyingTo( null ); setReplyText( '' ); setVisibleCount( 50 ); setShowTemplateSender( false ); setShowRcsTemplates( false ); setEmailSubject( '' ); setSummary( '' ); setMediaFiles( [] ); setMediaPreview( null ); setEmojiSearch( '' ); setShowEmoji( false ); setReactFor( null );
        if ( selected ) setUnreadIds( prev => { if ( !prev.has( selected ) ) return prev; const next = new Set( prev ); next.delete( selected ); try { window.localStorage.setItem( 'wd_unread', JSON.stringify( Array.from( next ) ) ); } catch { } return next; } );
    }, [ selected ] );

    // Load team-inbox meta for the selected conversation.
    useEffect( () => {
        setMeta( null ); setShowNotes( false ); setNoteText( '' );
        if ( selected ) api.getConversationMeta( selected ).then( setMeta ).catch( () => { } );
    }, [ selected ] );

    const saveMeta = useCallback( async ( updates: { status?: string; assignee?: string; tags?: string[] } ) => {
        if ( !selected ) return;
        const m = await api.updateConversationMeta( selected, updates );
        if ( m ) setMeta( m );
    }, [ selected ] );

    const addNote = useCallback( async () => {
        const t = noteText.trim();
        if ( !t || !selected ) return;
        const m = await api.addConversationNote( selected, t, user?.username || user?.signInDetails?.loginId || 'agent' );
        if ( m ) { setMeta( m ); setNoteText( '' ); }
    }, [ noteText, selected, user ] );

    const handleDelete = useCallback( async ( m: api.Message ) => {
        if ( deletingId ) return;
        setDeletingId( m.messageId );
        try
        {
            const ok = await api.deleteMessage( m.messageId, ( ( m.direction || '' ).toUpperCase() === 'OUTBOUND' ? 'OUTBOUND' : 'INBOUND' ) );
            if ( ok )
            {
                setMessages( prev => prev.filter( x => x.messageId !== m.messageId ) );
                toast.success( 'Message deleted' );
            } else toast.error( 'Delete failed' );
        } catch { toast.error( 'Delete failed' ); }
        finally { setDeletingId( null ); }
    }, [ deletingId, toast ] );

    // Multi-file media staging: validate per-type size, then queue for send.
    const handleMediaSelect = useCallback( ( e: React.ChangeEvent<HTMLInputElement> ) => {
        const files = Array.from( e.target.files || [] );
        if ( e.target ) e.target.value = '';
        if ( !files.length ) return;
        const accepted: File[] = [];
        for ( const file of files )
        {
            const ftype = file.type || inferMimeFromName( file.name );
            const check = validateWaMediaSize( { size: file.size, name: file.name, type: ftype }, ftype );
            if ( !check.ok ) { toast.error( `${file.name} too large. Max: ${formatBytes( check.limit )}` ); continue; }
            accepted.push( file );
        }
        if ( !accepted.length ) return;
        setMediaFiles( prev => [ ...prev, ...accepted ] );
        const firstImage = accepted.find( f => ( f.type || inferMimeFromName( f.name ) ).startsWith( 'image/' ) );
        if ( firstImage && !mediaPreview )
        {
            const reader = new FileReader();
            reader.onload = ev => setMediaPreview( ev.target?.result as string );
            reader.readAsDataURL( firstImage );
        }
    }, [ mediaPreview, toast ] );

    const removeMediaAt = useCallback( ( i: number ) => {
        setMediaFiles( prev => prev.filter( ( _, idx ) => idx !== i ) );
        if ( i === 0 ) setMediaPreview( null );
    }, [] );

    // The on-demand voice-note transcription handler was removed: its API route does not
    // exist in the live account, so the control it backed always failed. A transcription
    // already stored on a message is still rendered below.

    // Group messages into conversations by contact.
    const conversations = useMemo<Conversation[]>( () => {
        const map = new Map<string, Conversation>();
        for ( const m of messages )
        {
            const ch = ( m.channel || 'whatsapp' ).toLowerCase();
            if ( channelFilter !== 'ALL' && ch !== channelFilter ) continue;
            const cid = m.contactId || m.senderPhone || m.receivingPhone || 'unknown';
            const ts = new Date( m.timestamp ).getTime() || 0;
            const existing = map.get( cid );
            if ( !existing )
            {
                map.set( cid, {
                    contactId: cid,
                    name: contactNames[ cid ] || m.senderName || m.senderPhone || m.receivingPhone || cid,
                    channels: new Set( [ ch ] ),
                    lastContent: m.content || `[${m.messageType || ch}]`,
                    lastType: m.messageType || '',
                    lastTs: ts,
                    lastChannel: ch,
                } );
            } else
            {
                existing.channels.add( ch );
                if ( ts > existing.lastTs )
                {
                    existing.lastTs = ts;
                    existing.lastContent = m.content || `[${m.messageType || ch}]`;
                    existing.lastType = m.messageType || '';
                    existing.lastChannel = ch;
                }
            }
        }
        let list = Array.from( map.values() );
        if ( search.trim() )
        {
            const q = search.toLowerCase();
            list = list.filter( c => c.name.toLowerCase().includes( q ) || c.lastContent.toLowerCase().includes( q ) );
        }
        return list.sort( ( a, b ) => b.lastTs - a.lastTs );
    }, [ messages, contactNames, channelFilter, search ] );

    // Thread for the selected conversation (chronological).
    const thread = useMemo( () => {
        if ( !selected ) return [];
        return messages
            .filter( m => ( m.contactId || m.senderPhone || m.receivingPhone || 'unknown' ) === selected )
            .filter( m => channelFilter === 'ALL' || ( m.channel || 'whatsapp' ).toLowerCase() === channelFilter )
            .sort( ( a, b ) => ( new Date( a.timestamp ).getTime() || 0 ) - ( new Date( b.timestamp ).getTime() || 0 ) );
    }, [ messages, selected, channelFilter ] );

    const selectedConv = conversations.find( c => c.contactId === selected );
    const replyChannel = thread.length ? ( thread[ thread.length - 1 ].channel || 'whatsapp' ).toLowerCase() : 'whatsapp';

    // Derive the reply target (recipient phone, WABA, contactId) from the thread.
    const replyTarget = useMemo( () => {
        let phone = '';
        let waba = '';
        for ( let i = thread.length - 1; i >= 0; i-- )
        {
            const m = thread[ i ];
            if ( !phone )
            {
                phone = ( ( m.direction || '' ).toUpperCase() === 'INBOUND' ? m.senderPhone : m.receivingPhone )
                    || m.senderPhone || m.receivingPhone || '';
            }
            if ( !waba && m.awsPhoneNumberId ) waba = m.awsPhoneNumberId;
            if ( phone && waba ) break;
        }
        const isPhone = /^\+?\d{6,}$/.test( selected || '' );
        const contactId = isPhone ? '' : ( selected || '' );
        if ( isPhone && !phone ) phone = selected || '';
        return { phone, waba, contactId };
    }, [ thread, selected ] );

    // Reply on the conversation's own WABA. `selectedWaba` was seeded to WABAS[0]
    // and never synced, which is why an agent answering a WABA2 thread sent from
    // WABA1 — 17 `typing_indicator_error` and 12 code-100 "Message ID … does not
    // exist" in 30 days.
    // Keyed on `selected` ONLY: `messages` repolls every 15s, so keying on the
    // derived waba would stamp on an agent's manual "Send from" choice on every
    // poll. Guarded on membership — a partner WABA id would put the <select> on a
    // value with no matching <option>. This used to read "like whatsapp/inbox.tsx";
    // that file is now a wrapper that renders THIS component with channel="whatsapp",
    // so the comparison pointed at itself and the guard stands on its own.
    useEffect( () => {
        setWabaOverridden( false );
        const w = replyTarget.waba;
        if ( w && WABAS.some( x => x.id === w ) ) setSelectedWaba( w );
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ selected ] );

    // The WABA a reply actually goes out on. The thread's own WABA wins, because a
    // reply on the wrong one opens a conversation the customer never started; the
    // dropdown is honoured only once the agent has deliberately changed it for this
    // conversation. `selectedWaba` is the fallback, not the default.
    const sendWaba = wabaOverridden
        ? ( selectedWaba || replyTarget.waba )
        : ( replyTarget.waba || selectedWaba );

    const handleSendRcsTemplate = useCallback( async ( templateId: string ) => {
        const { phone } = replyTarget;
        if ( !phone ) { toast.error( 'No phone number for this conversation' ); return; }
        setSending( true );
        try
        {
            const r = await api.sendRcs( { phoneNumber: phone, templateId } );
            if ( r && ( r.success || r.messageId ) ) { toast.success( 'RCS template sent' ); setShowRcsTemplates( false ); setTimeout( loadData, 800 ); }
            else toast.error( 'RCS template send failed' );
        } catch { toast.error( 'RCS template send failed' ); }
        finally { setSending( false ); }
    }, [ replyTarget, toast, loadData ] );

    const handleReply = useCallback( async () => {
        if ( sending ) return;
        const base = replyText.trim();
        const hasMedia = replyChannel === 'whatsapp' && mediaFiles.length > 0;
        if ( !base && !hasMedia ) return;
        const text = replyingTo && base ? `> ${( replyingTo.content || '' ).slice( 0, 120 )}\n\n${base}` : base;
        const { phone, contactId } = replyTarget;
        // WhatsApp supports a native quoted reply (context). When available, use it
        // and skip the text-prefix quote.
        const waContext = ( replyChannel === 'whatsapp' && replyingTo && ( replyingTo as any ).whatsappMessageId ) ? ( replyingTo as any ).whatsappMessageId as string : undefined;
        const waText = waContext ? base : text;
        setSending( true );
        try
        {
            let ok = false;
            if ( replyChannel === 'whatsapp' )
            {
                if ( !contactId ) { toast.error( 'WhatsApp reply needs a saved contact — open the WhatsApp inbox' ); setSending( false ); return; }
                // Username-adopters may have their phone hidden, so fall back to the BSUID recipient when one is known.
                const bsuid = selected ? contactDir[ selected ]?.bsuid : undefined;
                if ( hasMedia )
                {
                    let sent = 0;
                    for ( let i = 0; i < mediaFiles.length; i++ )
                    {
                        const file = mediaFiles[ i ];
                        const type = file.type || inferMimeFromName( file.name );
                        const s3Key = await api.uploadMediaForSend( file, type, file.name );
                        if ( !s3Key ) { toast.error( `Upload failed: ${file.name}` ); continue; }
                        const r = await api.sendWhatsAppMessage( { contactId, content: i === 0 ? waText : '', phoneNumberId: sendWaba || undefined, recipientBsuid: bsuid, mediaFile: s3Key, mediaType: type, mediaFileName: file.name, contextMessageId: i === 0 ? waContext : undefined } );
                        if ( r ) sent++;
                    }
                    ok = sent > 0;
                    if ( ok ) { setMediaFiles( [] ); setMediaPreview( null ); }
                } else
                {
                    const r = await api.sendWhatsAppMessage( { contactId, content: waText, phoneNumberId: sendWaba || undefined, recipientBsuid: bsuid, contextMessageId: waContext } );
                    ok = !!r;
                }
            } else if ( replyChannel === 'sms' )
            {
                if ( !phone ) { toast.error( 'No phone number for this conversation' ); setSending( false ); return; }
                const r = await api.sendSmsAws( { contactId: contactId || undefined, phoneNumber: phone, content: text, messageType: smsType } );
                ok = !!( r && ( r.messageId || r.status === 'sent' ) );
            } else if ( replyChannel === 'rcs' )
            {
                if ( !phone ) { toast.error( 'No phone number for this conversation' ); setSending( false ); return; }
                const r = await api.sendRcs( { phoneNumber: phone, text } );
                ok = !!( r && ( r.success || r.messageId ) );
            } else if ( replyChannel === 'email' )
            {
                if ( !contactId ) { toast.error( 'Email reply needs a saved contact' ); setSending( false ); return; }
                const r = await api.sendEmailMessage( contactId, emailSubject.trim() || 'Re: your conversation', text );
                ok = !!r;
            }
            if ( ok )
            {
                setReplyText( '' );
                setReplyingTo( null );
                toast.success( `Sent via ${chMeta( replyChannel ).label}` );
                setTimeout( loadData, 800 );
            } else
            {
                toast.error( 'Failed to send' );
            }
        } catch
        {
            toast.error( 'Failed to send' );
        } finally
        {
            setSending( false );
        }
    }, [ replyText, sending, replyingTo, replyTarget, replyChannel, sendWaba, smsType, emailSubject, mediaFiles, selected, contactDir, toast, loadData ] );

    const handleSuggest = useCallback( async () => {
        if ( aiSuggesting || !thread.length ) return;
        const lastInbound = [ ...thread ].reverse().find( m => ( m.direction || '' ).toUpperCase() === 'INBOUND' );
        const seed = lastInbound?.content || thread[ thread.length - 1 ]?.content || '';
        if ( !seed ) { toast.error( 'Nothing to reply to yet' ); return; }
        setAiSuggesting( true );
        try
        {
            const history = thread.slice( -8 ).map( m => `${( m.direction || '' ).toUpperCase() === 'INBOUND' ? 'Customer' : 'Us'}: ${m.content || ''}` );
            const r = await api.generateAIResponse( seed, { channel: replyChannel, conversationHistory: history, contactName: selectedConv?.name } );
            if ( r?.response ) { setReplyText( r.response ); toast.success( 'AI suggestion ready' ); }
            else toast.error( 'No suggestion' );
        } catch { toast.error( 'AI suggest failed' ); }
        finally { setAiSuggesting( false ); }
    }, [ aiSuggesting, thread, replyChannel, selectedConv, toast ] );

    const handleSummarize = useCallback( async () => {
        if ( summarizing || !thread.length ) return;
        setSummarizing( true );
        try
        {
            const convo = thread.slice( -30 ).map( m => `${( m.direction || '' ).toUpperCase() === 'INBOUND' ? 'Customer' : 'Us'}: ${m.content || '[' + ( m.messageType || 'media' ) + ']'}` ).join( '\n' );
            const r = await api.generateAIResponse( `Summarize this customer conversation in 2-3 short bullet points (key intent, status, next action):\n\n${convo}`, { channel: replyChannel } );
            if ( r?.response ) setSummary( r.response ); else toast.error( 'No summary' );
        } catch { toast.error( 'Summarize failed' ); }
        finally { setSummarizing( false ); }
    }, [ summarizing, thread, replyChannel, toast ] );

    const openTts = useCallback( () => {
        if ( !replyTarget.contactId ) { toast.error( 'Voice note needs a saved contact' ); return; }
        setTtsText( replyText.trim() );
        setComposer( 'tts' );
    }, [ replyTarget, replyText, toast ] );

    const handleSendTTS = useCallback( async () => {
        const text = ttsText.trim();
        if ( !text ) { toast.error( 'Enter text for the voice note' ); return; }
        const { contactId } = replyTarget;
        if ( !contactId ) { toast.error( 'Voice note needs a saved contact' ); return; }
        setSending( true );
        try
        {
            const r = await api.sendWhatsAppTTS( { contactId, messageText: text, voiceId: ttsVoice, languageCode: ttsLang, engine: ttsEngine, phoneNumberId: selectedWaba } );
            if ( r ) { setComposer( null ); setTtsText( '' ); setReplyText( '' ); toast.success( 'Voice note sent' ); setTimeout( loadData, 800 ); }
            else toast.error( 'Voice note failed' );
        } catch { toast.error( 'Voice note failed' ); }
        finally { setSending( false ); }
    }, [ ttsText, ttsVoice, ttsLang, ttsEngine, replyTarget, selectedWaba, toast, loadData ] );

    const handleReact = useCallback( async ( m: api.Message, emoji: string ) => {
        const wamid = ( m as any ).whatsappMessageId;
        const { contactId } = replyTarget;
        setReactFor( null );
        if ( !wamid || !contactId ) { toast.error( 'Cannot react to this message' ); return; }
        try
        {
            const bsuid = selected ? contactDir[ selected ]?.bsuid : undefined;
            await api.sendWhatsAppReaction( { contactId, reactionMessageId: wamid, reactionEmoji: emoji, phoneNumberId: ( m as any ).awsPhoneNumberId || selectedWaba, recipientBsuid: bsuid } );
            toast.success( `Reacted ${emoji}` );
            setTimeout( loadData, 800 );
        } catch { toast.error( 'Reaction failed' ); }
    }, [ replyTarget, selectedWaba, selected, contactDir, toast, loadData ] );

    const updatePayItem = ( i: number, field: 'name' | 'amount' | 'quantity' | 'gstRate', val: string ) =>
        setPayItems( p => p.map( ( it, idx ) => idx === i ? { ...it, [ field ]: val } : it ) );
    const addPayItem = () => setPayItems( p => [ ...p, { name: '', amount: '', quantity: '1', gstRate: '0' } ] );
    const removePayItem = ( i: number ) => setPayItems( p => p.length > 1 ? p.filter( ( _, idx ) => idx !== i ) : p );
    const unlockPayPhone = async () => {
        try
        {
            setPayUnlocked( await api.verifyAdminAccess() );
        } catch
        {
            setPayUnlocked( false );
            toast.error( 'Unable to verify Admin access' );
        }
    };

    const handleSendPayment = useCallback( async () => {
        const { contactId } = replyTarget;
        if ( !contactId ) { toast.error( 'Payment needs a saved contact' ); return; }
        const phoneObj = PAYMENT_PHONES.find( p => p.id === payPhone );
        if ( phoneObj?.paymentProtected && !payUnlocked ) { toast.error( 'Unlock this number first' ); return; }
        const valid = payItems.filter( i => i.name.trim() && parseFloat( i.amount ) > 0 );
        if ( !valid.length ) { toast.error( 'Add at least one item with an amount' ); return; }
        setSending( true );
        try
        {
            const items = valid.map( it => ( { name: it.name.trim(), amount: Math.round( parseFloat( it.amount ) * 100 ), quantity: parseInt( it.quantity ) || 1, gstRate: parseInt( it.gstRate ) || 0 } ) );
            const tax = items.reduce( ( s, i ) => s + Math.round( i.amount * i.quantity * ( i.gstRate || 0 ) / 100 ), 0 );
            const r = await api.sendWhatsAppPaymentMessage( {
                contactId, phoneNumberId: payPhone,
                referenceId: `WD-PAY-${Date.now()}`,
                items,
                discount: Math.round( parseFloat( payPromo || '0' ) * 100 ),
                delivery: Math.round( parseFloat( payDelivery || '0' ) * 100 ),
                tax, gstin: payGstin || DEFAULT_GSTIN, orderId: payOrderId || 'Offline',
                useInteractive: true,
                paymentConfiguration: phoneObj?.paymentConfigName || 'WECAREDIGITAL',
            } );
            if ( r )
            {
                toast.success( 'Payment request sent' );
                setComposer( null );
                setPayItems( [ { name: '', amount: '', quantity: '1', gstRate: '0' } ] );
                setPayPromo( '0' ); setPayDelivery( '0' ); setPayOrderId( '' );
                setTimeout( loadData, 800 );
            } else toast.error( 'Payment send failed' );
        } catch { toast.error( 'Payment send failed' ); }
        finally { setSending( false ); }
    }, [ replyTarget, payPhone, payUnlocked, payItems, payPromo, payDelivery, payGstin, payOrderId, toast, loadData ] );

    const handleSendCatalog = useCallback( async () => {
        const { contactId } = replyTarget;
        if ( !contactId ) { toast.error( 'Catalog message needs a saved contact' ); return; }
        if ( !catalogId.trim() ) { toast.error( 'Enter the catalog ID' ); return; }
        const ids = catalogProducts.split( ',' ).map( s => s.trim() ).filter( Boolean );
        if ( !ids.length ) { toast.error( 'Enter at least one product retailer ID' ); return; }
        setSending( true );
        try
        {
            const r = await api.sendWhatsAppCatalogProduct( {
                contactId, phoneNumberId: selectedWaba, catalogId: catalogId.trim(),
                body: catalogBody.trim() || undefined,
                ...( ids.length === 1
                    ? { productRetailerId: ids[ 0 ] }
                    : { sections: [ { title: 'Products', productItems: ids.map( id => ( { productRetailerId: id } ) ) } ] } ),
            } );
            if ( r ) { toast.success( 'Catalog message sent' ); setComposer( null ); setCatalogProducts( '' ); setCatalogBody( '' ); setTimeout( loadData, 800 ); }
            else toast.error( 'Catalog send failed' );
        } catch { toast.error( 'Catalog send failed' ); }
        finally { setSending( false ); }
    }, [ replyTarget, selectedWaba, catalogId, catalogProducts, catalogBody, toast, loadData ] );

    // `loadCatalog` and `toggleCatalogProduct` were here, along with the product picker
    // they fed. Removed 2026-10-07: loadCatalog called api.getCatalogProducts, i.e.
    // /catalog/products, which has no live route. The 404 body came back parsed rather
    // than thrown, so the picker stayed empty and the operator was told "No products
    // found for this catalog" — a sentence that blames the catalog for a missing
    // endpoint. handleSendCatalog above is untouched: it posts over WA_BIZ_BASE, that
    // route IS live, and an operator can still send by typing retailer ids.

    const handleBlockToggle = useCallback( async ( block: boolean ) => {
        const { contactId, phone } = replyTarget;
        if ( !contactId && !phone ) { toast.error( 'No contact to block' ); return; }
        setBlocking( true );
        try
        {
            const fn = block ? api.blockWhatsAppUser : api.unblockWhatsAppUser;
            const r = await fn( { contactId: contactId || undefined, phoneNumber: phone || undefined, phoneNumberId: selectedWaba } );
            if ( r?.success ) toast.success( block ? 'Contact blocked' : 'Contact unblocked' );
            else toast.error( block ? 'Block failed — only contacts who messaged in the last 24h can be blocked' : 'Unblock failed' );
        } catch { toast.error( 'Block action failed' ); }
        finally { setBlocking( false ); }
    }, [ replyTarget, selectedWaba, toast ] );

    // Click-to-call from the inbox is retired. It rang the agent through a retired
    // India voice provider's bridge, and that endpoint now answers 410.
    //
    // This reports the change instead of prompting for a number and then failing:
    // asking the operator to type their phone number before telling them the
    // feature is gone is worse than telling them up front. The control that
    // invokes this is disabled too; this is the backstop.
    const handleCall = useCallback( async () => {
        toast.error(
            'Click-to-call is retired. PSTN voice is now Plivo, and outbound calling '
            + 'arrives with the Plivo browser softphone.'
        );
    }, [ toast ] );

    const markUnread = useCallback( () => {
        if ( !selected ) return;
        setUnreadIds( prev => {
            const next = new Set( prev ); next.add( selected );
            try { window.localStorage.setItem( 'wd_unread', JSON.stringify( Array.from( next ) ) ); } catch { }
            return next;
        } );
        setSelected( null );
    }, [ selected ] );

    // Auto-scroll to the latest message when a conversation is opened.
    useEffect( () => {
        if ( !selected ) return;
        prevThreadLen.current = 0;
        const t = setTimeout( () => threadEndRef.current?.scrollIntoView( { behavior: 'auto' } ), 60 );
        return () => clearTimeout( t );
    }, [ selected ] );

    // Auto-scroll on new messages — only if the user is already near the bottom
    // (so reading older history isn't interrupted). WhatsApp-style.
    useEffect( () => {
        if ( pendingScrollRestore.current ) { prevThreadLen.current = thread.length; return; }
        const area = threadBodyRef.current;
        if ( area && thread.length > prevThreadLen.current && prevThreadLen.current > 0 )
        {
            const nearBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 220;
            if ( nearBottom ) scrollToEnd( threadEndRef.current );
        }
        prevThreadLen.current = thread.length;
    }, [ thread ] );

    // Infinite scroll up: reveal older messages when scrolled near the top,
    // restoring scroll position so the view doesn't jump.
    useEffect( () => {
        const area = threadBodyRef.current;
        if ( !area ) return;
        const onScroll = () => {
            if ( area.scrollTop < 80 && thread.length > visibleCount && !pendingScrollRestore.current )
            {
                const prevH = area.scrollHeight;
                const prevTop = area.scrollTop;
                pendingScrollRestore.current = true;
                setLoadingOlder( true );
                setVisibleCount( c => c + 50 );
                setTimeout( () => {
                    area.scrollTop = prevTop + ( area.scrollHeight - prevH );
                    pendingScrollRestore.current = false;
                    setLoadingOlder( false );
                }, 60 );
            }
        };
        area.addEventListener( 'scroll', onScroll, { passive: true } );
        return () => area.removeEventListener( 'scroll', onScroll );
    }, [ selected, thread.length, visibleCount ] );

    // Native WhatsApp typing indicator + read receipt while composing (throttled ~20s).
    useEffect( () => {
        if ( replyChannel !== 'whatsapp' || !replyText.trim() || !selected ) return;
        const lastInbound = [ ...thread ].reverse().find( m => ( m.direction || '' ).toUpperCase() === 'INBOUND' && ( m as any ).whatsappMessageId );
        const wamid = lastInbound && ( lastInbound as any ).whatsappMessageId;
        if ( !wamid ) return;
        const now = Date.now();
        if ( lastTypingRef.current.id === selected && now - lastTypingRef.current.at < 20000 ) return;
        lastTypingRef.current = { id: selected, at: now };
        // The wamid belongs to the thread's own WABA, so the indicator must go out
        // on that one regardless of the dropdown — a mismatch is the code-100
        // "Message ID … does not exist" that produced 12 errors in 30 days.
        api.sendTypingIndicator( replyTarget.waba || selectedWaba, wamid ).catch( () => { } );
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ replyText, selected, replyChannel ] );

    const content = (
        <>
            <div className="ui-wrap">

                <PageHeader title="Unified Inbox" subtitle="All channels in one place — WhatsApp, SMS, Email, RCS, Voice" icon="message" />

                <div className="ui-toolbar">
                    <input className="ui-search" placeholder="Search conversations…" value={ search } onChange={ e => setSearch( e.target.value ) } />
                    { /* The first control migrated in this file, in batch 2b. Four of the six
                         that remained followed in 2c - the WABA chooser, the India
                         TRANSACTIONAL/PROMOTIONAL SMS class, and the two voice pickers - and the
                         last two followed in 2f: the send-from number and the GST rate in the
                         "Request payment" panel are money controls on an India payment path, so
                         they waited for the payment batch rather than riding along with the
                         filters. No native select is left in this file. */ }
                    <Select ariaLabel="Channel" value={ channelFilter }
                        onChange={ v => setChannelFilter( v ) }
                        options={ CHANNEL_FILTER_OPTIONS } style={ { width: 170 } } />
                </div>

                <div className={ `ui-panes ${selected ? 'has-selection' : ''}` }>
                    <div className="ui-list">
                        { loading ? (
                            <div className="ui-empty">Loading…</div>
                        ) : loadFailure && messages.length === 0 ? (
                            /*
                             * The load failed AND we have nothing cached to show. This is
                             * the case that used to render as "No conversations": three
                             * different problems (session expired, 8s timeout, route not
                             * deployed) presented as an empty table, so the only visible
                             * remedy was the wrong one. Say which it is, and offer the
                             * remedy that matches.
                             *
                             * A failure with messages still on screen is deliberately
                             * NOT surfaced here - a failed 15s poll should not blank a
                             * working thread list.
                             */
                            <div className="ui-empty">
                                { loadFailure.kind === 'unauthenticated' ? 'Your session has expired.' : 'Could not load the inbox.' }
                                <br />
                                <span style={ { color: colors.textMuted } }>{ loadFailure.message }</span>
                                <br />
                                { loadFailure.kind === 'unauthenticated' ? (
                                    /*
                                     * There is no /login route - every protected page is
                                     * wrapped in the Amplify Authenticator by _app.tsx, so
                                     * the way back to a sign-in form is to remount it.
                                     * Reloading does that and re-runs the session check.
                                     */
                                    <button type="button" className="ui-link-btn" onClick={ () => window.location.reload() }>
                                        Reload to sign in
                                    </button>
                                ) : (
                                    <button type="button" className="ui-link-btn" onClick={ () => { setLoading( true ); loadData(); } }>
                                        { loadFailure.retryable ? 'Retry' : 'Try again' }
                                    </button>
                                ) }
                            </div>
                        ) : conversations.length === 0 ? (
                            /*
                             * "No conversations" on its own is indistinguishable from a
                             * failed load, and that ambiguity is what made a working
                             * inbox look broken. When a channel filter is narrowing
                             * everything away, say which channel, say how much is
                             * sitting on the others, and offer the way back. Email
                             * currently has zero rows in the table, so this is the
                             * expected state there rather than a fault.
                             */
                            <div className="ui-empty">
                                { channelFilter !== 'ALL' ? (
                                    <>
                                        No { chMeta( channelFilter ).label } conversations.
                                        { messages.length > 0 && (
                                            <>
                                                <br />{ messages.length } message{ messages.length === 1 ? '' : 's' } on other channels.
                                                <br />
                                                <button type="button" className="ui-link-btn" onClick={ () => setChannelFilter( 'ALL' ) }>
                                                    Show all channels
                                                </button>
                                            </>
                                        ) }
                                    </>
                                ) : 'No conversations' }
                            </div>
                        ) : conversations.map( c => {
                            const m = chMeta( c.lastChannel );
                            return (
                                <button key={ c.contactId } className={ `ui-conv ${selected === c.contactId ? 'active' : ''} ${unreadIds.has( c.contactId ) ? 'unread' : ''}` } onClick={ () => setSelected( c.contactId ) }>
                                    <div className="ui-conv-top">
                                        <span className="ui-conv-name">{ unreadIds.has( c.contactId ) && <span className="ui-unread-dot" /> }{ c.name }</span>
                                        <span className="ui-conv-time">{ fmtTime( c.lastTs ) }</span>
                                    </div>
                                    <div className="ui-conv-bottom">
                                        <span className="ui-conv-preview">{ prettyMsg( c.lastContent, c.lastType ).slice( 0, 48 ) }</span>
                                        <span className="ui-badges">
                                            { Array.from( c.channels ).map( ch => {
                                                const cm = chMeta( ch );
                                                return <span key={ ch } className="ui-badge" style={ { color: cm.fg, background: cm.bg } }>{ cm.label }</span>;
                                            } ) }
                                        </span>
                                    </div>
                                </button>
                            );
                        } ) }
                    </div>

                    <div className="ui-thread">
                        { !selected ? (
                            <div className="ui-empty">Select a conversation</div>
                        ) : (
                            <>
                                <div className="ui-thread-head">
                                    <button className="ui-back" onClick={ () => setSelected( null ) } title="Back to conversations">←</button>
                                    <span className="ui-avatar">{ ( selectedConv?.name || '?' ).trim().slice( 0, 2 ).toUpperCase() }</span>
                                    <div className="ui-thread-id">
                                        <span className="ui-thread-name">{ selectedConv?.name }</span>
                                        <span className="ui-thread-sub">
                                            { [
                                                // Prefer the WhatsApp username in the profile; fall back to the phone number only when no username exists.
                                                selected && contactDir[ selected ]?.username
                                                    ? `@${contactDir[ selected ]!.username!.replace( /^@/, '' )}`
                                                    : replyTarget.phone,
                                                `${thread.length} message${thread.length === 1 ? '' : 's'}`,
                                            ].filter( Boolean ).join( ' · ' ) }
                                            { selected && contactDir[ selected ]?.bsuid && (
                                                <span className="ui-id-chip" title={ `WhatsApp BSUID: ${contactDir[ selected ]!.bsuid}` }>ID { contactDir[ selected ]!.bsuid!.slice( 0, 8 ) }…</span>
                                            ) }
                                        </span>
                                    </div>
                                    <span className="ui-badges">
                                        { selectedConv && Array.from( selectedConv.channels ).map( ch => {
                                            const cm = chMeta( ch );
                                            return <span key={ ch } className="ui-badge" style={ { color: cm.fg, background: cm.bg } }>{ cm.label }</span>;
                                        } ) }
                                    </span>
                                    <button className="ui-icon-btn" onClick={ () => loadData() } title="Refresh"><Icon name="refresh" size={ 16 } /></button>
                                    { replyTarget.phone && (
                                        <button className="ui-icon-btn" onClick={ handleCall } disabled title="Click-to-call is retired. PSTN voice is now Plivo; outbound calling arrives with the Plivo browser softphone."><Icon name="phone" size={ 16 } /></button>
                                    ) }
                                    <button className="ui-icon-btn" onClick={ markUnread } title="Mark unread"><Icon name="mail" size={ 16 } /></button>
                                    { replyChannel === 'whatsapp' && (
                                        <button className="ui-icon-btn ui-icon-danger" disabled={ blocking } onClick={ () => handleBlockToggle( true ) } title="Block contact (only if they messaged in last 24h)"><Icon name="block" size={ 16 } /></button>
                                    ) }
                                    <button className="ui-summarize" disabled={ summarizing } onClick={ handleSummarize } title="AI summary of this conversation"><Icon name="sparkle" size={ 14 } /> { summarizing ? '…' : 'Summarize' }</button>
                                </div>
                                { summary && (
                                    <div className="ui-summary">
                                        <span className="ui-summary-text">{ summary }</span>
                                        <button className="ui-summary-x" onClick={ () => setSummary( '' ) }>✕</button>
                                    </div>
                                ) }
                                <div className="ui-thread-body" ref={ threadBodyRef }>
                                    { thread.length > visibleCount && (
                                        <button className="ui-load-more" onClick={ () => setVisibleCount( v => v + 50 ) }>{ loadingOlder ? 'Loading…' : `↑ Load older (${thread.length - visibleCount})` }</button>
                                    ) }
                                    { thread.slice( -visibleCount ).map( m => {
                                        const ch = ( m.channel || 'whatsapp' ).toLowerCase();
                                        const cm = chMeta( ch );
                                        const out = ( m.direction || '' ).toUpperCase() === 'OUTBOUND';
                                        const revoked = ( m as any ).isRevoked === true;
                                        // A revoke that RESOLVED is already shown on the message it deleted
                                        // (struck through, below), so rendering its own bubble as well is a
                                        // double render. When revokesMessageId is absent the revoke never
                                        // resolved, so it still renders as its own line and nothing becomes
                                        // invisible. Ported from whatsapp/inbox.tsx, which was reduced to a
                                        // wrapper over this renderer - the marking is server-side and already
                                        // on the row (api/client.ts), so without this the fields arrive and
                                        // nothing reads them.
                                        if ( ( m as any ).revokesMessageId ) return null;
                                        if ( ( m.messageType || '' ).toLowerCase() === 'reaction' )
                                        {
                                            const emoji = ( m.content || '' ).replace( /\[reaction\]?/i, '' ).trim() || '👍';
                                            return (
                                                <div key={ m.messageId } className={ `ui-react ${out ? 'out' : 'in'}` }>
                                                    <span className="ui-react-pill">{ out ? 'You reacted' : 'Reacted' } { emoji }</span>
                                                </div>
                                            );
                                        }
                                        return (
                                            <div key={ m.messageId } className={ `ui-msg ${out ? 'out' : 'in'}` }>
                                                <div className="ui-msg-bubble">
                                                    <span className="ui-badge" style={ { color: cm.fg, background: cm.bg } }>{ cm.label }</span>
                                                    { ( () => {
                                                        const mt = ( m.messageType || '' ).toLowerCase();
                                                        const url = m.mediaUrl || '';
                                                        if ( url && ( mt === 'image' || mt === 'sticker' ) ) return <img className="ui-msg-img" src={ url } alt="image" />;
                                                        if ( url && mt === 'video' ) return <video className="ui-msg-img" src={ url } controls />;
                                                        if ( url && ( mt === 'audio' || mt === 'voice' ) ) return <audio src={ url } controls style={ { maxWidth: '100%' } } />;
                                                        if ( url && mt === 'document' ) return <a className="ui-msg-doc" href={ url } target="_blank" rel="noopener noreferrer">📄 { ( m as any ).displayFilename || 'Document' }</a>;
                                                        return null;
                                                    } )() }
                                                    { ( () => {
                                                        // A shared contact card renders as a real card with a tel: link and a
                                                        // copy button. The emptiness test is here rather than in the component
                                                        // because a JSX element is always truthy, so `<C/> || fallback` could
                                                        // never fall back. No payload → the prettyMsg span below, which is the
                                                        // path rows stored before ingest captured the payload keep using.
                                                        if ( ( m.messageType || '' ).toLowerCase() !== 'contacts' ) return null;
                                                        const cards = ( m as any ).contactsPayload;
                                                        if ( !Array.isArray( cards ) || cards.length === 0 ) return null;
                                                        return <ContactCardBubble contacts={ cards } fallbackLabel="Contact card" />;
                                                    } )() }
                                                    { !( ( m.messageType || '' ).toLowerCase() === 'contacts' && Array.isArray( ( m as any ).contactsPayload ) && ( m as any ).contactsPayload.length > 0 )
                                                        && ( ( m.content && !isSysLabel( m.content ) ) || !m.mediaUrl ) && (
                                                        <span
                                                            className="ui-msg-text"
                                                            style={ revoked ? { textDecoration: 'line-through', opacity: 0.55 } : undefined }
                                                        >{ prettyMsg( m.content, m.messageType ) }</span>
                                                    ) }
                                                    { revoked && (
                                                        // An inferred match is a guess, and an unlabelled guess shown as
                                                        // fact is the failure to avoid - so the qualifier is in the
                                                        // visible text, not only in the tooltip.
                                                        <span
                                                            className="ui-msg-revoked"
                                                            title={ ( m as any ).revokeResolution === 'inferred'
                                                                ? 'Matched by timing — WhatsApp does not say which message was deleted.'
                                                                : undefined }
                                                            style={ { fontSize: 11, fontStyle: 'italic', opacity: 0.7, marginTop: 2 } }
                                                        >
                                                            Deleted by sender{ ( m as any ).revokeResolution === 'inferred' ? ' · matched by timing' : '' }
                                                        </span>
                                                    ) }
                                                    { m.transcription && <span className="ui-msg-transcript">📝 { m.transcription }</span> }
                                                    <span className="ui-msg-meta">
                                                        { fmtTime( m.timestamp ) } · { ( () => {
                                                            const st = ( m.status || '' ).toLowerCase();
                                                            const failed = st === 'failed' || st === 'undelivered';
                                                            if ( !failed )
                                                            {
                                                                // `accepted` is the status a row carries between Meta acknowledging the
                                                            // send and the first `sent` webhook. Before 2026-09-21 the backend
                                                            // wrote `sent` immediately, so this state did not exist; without its
                                                            // own class it falls through to the `sent` tick and claims a delivery
                                                            // signal Meta has not given yet.
                                                            const cls = st === 'read' ? 'read' : st === 'delivered' ? 'delivered' : st === 'accepted' ? 'accepted' : 'sent';
                                                                return <span className={ `ui-st ui-st-${cls}` }>{ st || 'sent' }</span>;
                                                            }
                                                            let rawErr = '';
                                                            try { rawErr = m.errorDetails ? ( JSON.parse( m.errorDetails )?.message || '' ) : ''; } catch { rawErr = ( m as any ).errorDetails || ''; }
                                                            const tip = waErrorTooltip( ( m as any ).errorCode, rawErr ) || 'Send failed';
                                                            return <span className="ui-st ui-st-failed" title={ tip }>failed ⓘ</span>;
                                                        } )() }
                                                        <button className="ui-msg-act" title="Reply" onClick={ () => setReplyingTo( m ) }>↩</button>
                                                        <button className="ui-msg-act" title="Delete" disabled={ deletingId === m.messageId } onClick={ () => handleDelete( m ) }>🗑</button>
                                                        { ch === 'whatsapp' && ( m as any ).whatsappMessageId && (
                                                            <span className="ui-react-wrap">
                                                                <button className="ui-msg-act" title="React" onClick={ () => setReactFor( reactFor === m.messageId ? null : m.messageId ) }>☺</button>
                                                                { reactFor === m.messageId && (
                                                                    <span className="ui-react-pop">
                                                                        { REACT_EMOJIS.map( em => (
                                                                            <button key={ em } type="button" className="ui-react-em" onClick={ () => handleReact( m, em ) }>{ em }</button>
                                                                        ) ) }
                                                                    </span>
                                                                ) }
                                                            </span>
                                                        ) }
                                                    </span>
                                                </div>
                                            </div>
                                        );
                                    } ) }
                                    <div ref={ threadEndRef } />
                                </div>
                                <div className="ui-reply">
                                    { replyChannel === 'voice' ? (
                                        <div className="ui-reply-voice">
                                            <span>This is a call — reply by calling back.</span>
                                            <Link href={ chMeta( 'voice' ).reply } className="ui-reply-link">Open Voice →</Link>
                                        </div>
                                    ) : (
                                        <>
                                            { replyingTo && (
                                                <div className="ui-replying">
                                                    <span className="ui-replying-text">↩ { ( replyingTo.content || '' ).slice( 0, 60 ) }</span>
                                                    <button className="ui-replying-x" onClick={ () => setReplyingTo( null ) }>✕</button>
                                                </div>
                                            ) }
                                            { replyChannel === 'whatsapp' && (
                                                <div className="ui-wa-bar">
                                                    <span className="ui-wa-from">Send from:</span>
                                                    { /* `.ui-wa-waba` SKINNED the native control, so it is dropped rather
                                                         than forwarded - className on a Select lands on the wrapper and
                                                         would paint a box around the whole field. Only its width survives,
                                                         as layout, because `.ui-wa-bar` is a flex row.
                                                         `setWabaOverridden( true )` stays FIRST, as it was on the native
                                                         control: it is what makes `sendWaba` honour the operator's pick
                                                         instead of the thread's inferred WABA. */ }
                                                    <Select ariaLabel="Send from" value={ selectedWaba }
                                                        onChange={ v => { setWabaOverridden( true ); setSelectedWaba( v ); } }
                                                        options={ WABA_OPTIONS } style={ WABA_SELECT_STYLE } />
                                                    <button className="ui-tpl-btn" onClick={ () => setShowTemplateSender( true ) }>Send template ▾</button>
                                                </div>
                                            ) }
                                            { replyChannel === 'rcs' && (
                                                <div className="ui-wa-bar">
                                                    <span className="ui-wa-from" style={ { color: chMeta( 'rcs' ).fg } }>RCS · { replyTarget.phone || '—' }</span>
                                                    <button className="ui-tpl-btn" onClick={ () => setShowRcsTemplates( s => !s ) }>RCS templates ▾</button>
                                                </div>
                                            ) }
                                            { showRcsTemplates && replyChannel === 'rcs' && (
                                                <div className="ui-tpl-list">
                                                    { rcsTemplates.length === 0 ? <div className="ui-tpl-empty">No RCS templates</div> :
                                                        rcsTemplates.map( ( t: any, i: number ) => (
                                                            <button key={ t.name || t.id || i } className="ui-tpl-item" disabled={ sending } onClick={ () => handleSendRcsTemplate( t.name || t.id ) }>
                                                                <span className="ui-tpl-name">{ t.name || t.id }</span>
                                                                <span className="ui-tpl-cat">{ t.type || 'rcs' }</span>
                                                            </button>
                                                        ) ) }
                                                </div>
                                            ) }
                                            { replyChannel === 'sms' && (
                                                <div className="ui-wa-bar">
                                                    <span className="ui-wa-from" style={ { color: chMeta( 'sms' ).fg } }>SMS · { replyTarget.phone || '—' }</span>
                                                    { /* The cast is preserved verbatim, and the two option values are
                                                         exactly the two members of that union - this is the India
                                                         TRANSACTIONAL/PROMOTIONAL DLT classification on an outbound SMS,
                                                         so the value contract may not be loosened. */ }
                                                    <Select ariaLabel="SMS type" value={ smsType }
                                                        onChange={ v => setSmsType( v as 'TRANSACTIONAL' | 'PROMOTIONAL' ) }
                                                        options={ SMS_TYPE_OPTIONS } style={ SMS_TYPE_SELECT_STYLE } />
                                                </div>
                                            ) }
                                            { replyChannel === 'email' && (
                                                <div className="ui-wa-bar">
                                                    <span className="ui-wa-from" style={ { color: chMeta( 'email' ).fg } }>Email</span>
                                                    <input className="ui-email-subject" placeholder="Subject…" value={ emailSubject } onChange={ e => setEmailSubject( e.target.value ) } />
                                                </div>
                                            ) }
                                            { replyChannel === 'whatsapp' && mediaFiles.length > 0 && (
                                                <div className="ui-media-stage">
                                                    { mediaPreview && <img className="ui-media-thumb" src={ mediaPreview } alt="preview" /> }
                                                    { mediaFiles.map( ( f, i ) => (
                                                        <span key={ i } className="ui-media-chip">
                                                            <span className="ui-media-name">{ f.name }</span>
                                                            <span className="ui-media-size">{ formatBytes( f.size ) }</span>
                                                            <button type="button" className="ui-media-x" onClick={ () => removeMediaAt( i ) }>✕</button>
                                                        </span>
                                                    ) ) }
                                                </div>
                                            ) }
                                            <textarea
                                                className="ui-reply-input"
                                                placeholder={ `Reply via ${chMeta( replyChannel ).label}…` }
                                                value={ replyText }
                                                onChange={ e => setReplyText( e.target.value ) }
                                                onKeyDown={ e => { if ( e.key === 'Enter' && !e.shiftKey ) { e.preventDefault(); handleReply(); } } }
                                                rows={ 2 }
                                            />
                                            { showEmoji && (
                                                <div className="ui-emoji-pop">
                                                    <input className="ui-emoji-search" placeholder="Search emoji (smile, heart, money, car…)" value={ emojiSearch } onChange={ e => setEmojiSearch( e.target.value ) } autoFocus />
                                                    <div className="ui-emoji-scroll">
                                                        { searchEmojiCategories( emojiSearch ).map( cat => (
                                                            <div key={ cat.name } className="ui-emoji-cat">
                                                                <div className="ui-emoji-cat-label">{ cat.name }</div>
                                                                <div className="ui-emoji-grid">
                                                                    { cat.emojis.map( ( em, i ) => (
                                                                        <button key={ cat.name + i } type="button" className="ui-emoji" onClick={ () => setReplyText( t => t + em ) }>{ em }</button>
                                                                    ) ) }
                                                                </div>
                                                            </div>
                                                        ) ) }
                                                    </div>
                                                </div>
                                            ) }
                                            { showQuick && (
                                                <div className="ui-quick-list">
                                                    { quickReplies.map( ( q, i ) => (
                                                        <button key={ i } type="button" className="ui-quick-item" onClick={ () => { setReplyText( q ); setShowQuick( false ); } }>{ q.slice( 0, 80 ) }</button>
                                                    ) ) }
                                                </div>
                                            ) }
                                            <div className="ui-tools">
                                                <button type="button" className="ui-tool-btn" onClick={ () => setShowEmoji( s => !s ) } title="Emoji"><Icon name="emoji" /></button>
                                                { quickReplies.length > 0 && (
                                                    <button type="button" className="ui-tool-btn" onClick={ () => setShowQuick( s => !s ) } title="Quick replies"><Icon name="chat" /></button>
                                                ) }
                                                { replyChannel === 'whatsapp' && (
                                                    <>
                                                        <button type="button" className="ui-tool-btn" onClick={ () => fileRef.current?.click() } title="Attach image / document / video / audio (multiple)"><Icon name="attach" /></button>
                                                        { replyTarget.contactId && (
                                                            <>
                                                                <button type="button" className="ui-tool-btn" onClick={ () => setComposer( 'interactive' ) } title="Interactive: list / buttons / CTA / flow"><Icon name="list" /></button>
                                                                <button type="button" className="ui-tool-btn" onClick={ () => setComposer( 'location' ) } title="Send location"><Icon name="pin" /></button>
                                                                <button type="button" className="ui-tool-btn" onClick={ () => setComposer( 'contact' ) } title="Send contact card"><Icon name="user" /></button>
                                                                <button type="button" className="ui-tool-btn" onClick={ openTts } title="Send as voice note (TTS)"><Icon name="mic" /></button>
                                                                <button type="button" className="ui-tool-btn" onClick={ () => setComposer( 'pay' ) } title="Request payment"><Icon name="pay" /></button>
                                                                <button type="button" className="ui-tool-btn" onClick={ () => setComposer( 'catalog' ) } title="Send catalog product"><Icon name="cart" /></button>
                                                            </>
                                                        ) }
                                                    </>
                                                ) }
                                            </div>
                                            <div className="ui-send-row">
                                                <span className="ui-reply-via" style={ { color: chMeta( replyChannel ).fg, background: chMeta( replyChannel ).bg } }>via { chMeta( replyChannel ).label }</span>
                                                { replyChannel === 'sms' && (
                                                    <span className="ui-fmt-hint">{ replyText.length } chars · { Math.max( 1, Math.ceil( replyText.length / 160 ) ) } seg</span>
                                                ) }
                                                <button className="ui-ai-btn" disabled={ aiSuggesting } onClick={ handleSuggest } title="AI suggest reply"><Icon name="sparkle" size={ 15 } /> { aiSuggesting ? '…' : 'Suggest' }</button>
                                                <button className="ui-reply-btn" disabled={ sending || !replyText.trim() } onClick={ handleReply }>{ sending ? 'Sending…' : 'Send' }</button>
                                            </div>
                                            { replyChannel === 'whatsapp' && (
                                                <input ref={ fileRef } type="file" hidden multiple accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt" onChange={ handleMediaSelect } />
                                            ) }
                                        </>
                                    ) }
                                </div>
                            </>
                        ) }
                    </div>
                </div>
            </div>

            { composer && replyTarget.contactId && (
                <div className="ui-modal-backdrop" onClick={ () => setComposer( null ) }>
                    <div className="ui-modal" onClick={ e => e.stopPropagation() }>
                        { composer === 'interactive' && (
                            <InteractiveMessageComposer contactId={ replyTarget.contactId } phoneNumberId={ selectedWaba }
                                onClose={ () => setComposer( null ) }
                                onSent={ () => { setComposer( null ); toast.success( 'Interactive message sent' ); setTimeout( loadData, 800 ); } }
                                onError={ ( m: string ) => toast.error( m ) } />
                        ) }
                        { composer === 'location' && (
                            <LocationSendComposer contactId={ replyTarget.contactId } phoneNumberId={ selectedWaba }
                                onClose={ () => setComposer( null ) }
                                onSent={ () => { setComposer( null ); toast.success( 'Location sent' ); setTimeout( loadData, 800 ); } }
                                onError={ ( m: string ) => toast.error( m ) } />
                        ) }
                        { composer === 'contact' && (
                            <ContactMessageComposer contactId={ replyTarget.contactId } phoneNumberId={ selectedWaba }
                                onClose={ () => setComposer( null ) }
                                onSent={ () => { setComposer( null ); toast.success( 'Contact card sent' ); setTimeout( loadData, 800 ); } }
                                onError={ ( m: string ) => toast.error( m ) } />
                        ) }
                        { composer === 'pay' && ( () => {
                            const phoneObj = PAYMENT_PHONES.find( p => p.id === payPhone );
                            const locked = !!( phoneObj?.paymentProtected && !payUnlocked );
                            const subtotal = payItems.reduce( ( s, it ) => s + ( parseFloat( it.amount ) || 0 ) * ( parseInt( it.quantity ) || 1 ), 0 );
                            const gst = payItems.reduce( ( s, it ) => s + ( parseFloat( it.amount ) || 0 ) * ( parseInt( it.quantity ) || 1 ) * ( parseInt( it.gstRate ) || 0 ) / 100, 0 );
                            const grand = subtotal + gst + ( parseFloat( payDelivery ) || 0 ) - ( parseFloat( payPromo ) || 0 );
                            return (
                                <div className="ui-pay">
                                    <div className="ui-pay-title">Request payment</div>
                                    { /* TWO STATEMENTS, IN THIS ORDER, AND THE SECOND ONE IS THE
                                         WHOLE REASON THIS SITE IS NAMED IN THE BATCH. Changing
                                         the sender RE-LOCKS the admin-verification gate: a
                                         protected number requires `Verify Admin access` before
                                         the panel will send, and a handler that lost
                                         `setPayUnlocked( false )` would leave the panel unlocked
                                         after the sender changed - so a verification granted for
                                         one number would carry over to another. Pinned by
                                         src/test/InboxPaymentSender.test.tsx, behaviourally and
                                         in source order, rather than left to a diff review.
                                         `.ui-pay-in` SKINNED the native control, so it is dropped
                                         rather than forwarded: a className on a Select lands on
                                         the field wrapper and would paint a box around the whole
                                         field. The control is full width either way. */ }
                                    <label className="ui-pay-label">Send from</label>
                                    <Select ariaLabel="Send from" value={ payPhone }
                                        onChange={ v => { setPayPhone( v ); setPayUnlocked( false ); } }
                                        options={ PAY_PHONE_OPTIONS } />
                                    { locked && (
                                        <div className="ui-pay-lock">
                                            <button className="ui-pay-unlock" onClick={ unlockPayPhone }>Verify Admin access</button>
                                        </div>
                                    ) }
                                    <label className="ui-pay-label">Items</label>
                                    { payItems.map( ( it, i ) => (
                                        <div key={ i } className="ui-pay-item">
                                            <input className="ui-pay-in" placeholder="Item / service" value={ it.name } onChange={ e => updatePayItem( i, 'name', e.target.value ) } />
                                            <div className="ui-pay-row">
                                                <input className="ui-pay-in" type="number" min="0" step="0.01" placeholder="₹ Amount" value={ it.amount } onChange={ e => updatePayItem( i, 'amount', e.target.value ) } />
                                                <input className="ui-pay-in ui-pay-qty" type="number" min="1" placeholder="Qty" value={ it.quantity } onChange={ e => updatePayItem( i, 'quantity', e.target.value ) } />
                                                { /* The GST rate applied to this line's amount.
                                                     It had NO accessible name at all - no
                                                     caption, no aria-label - so `ariaLabel` adds
                                                     one and changes nothing on screen. The value
                                                     stays a string and `updatePayItem` receives
                                                     exactly what the native handler passed it. */ }
                                                <Select ariaLabel="GST rate" value={ it.gstRate }
                                                    onChange={ v => updatePayItem( i, 'gstRate', v ) }
                                                    options={ PAY_GST_OPTIONS } style={ PAY_GST_SELECT_STYLE } />
                                                { payItems.length > 1 && <button type="button" className="ui-pay-rm" onClick={ () => removePayItem( i ) }>✕</button> }
                                            </div>
                                        </div>
                                    ) ) }
                                    <button type="button" className="ui-pay-additem" onClick={ addPayItem }>+ Add item</button>
                                    <div className="ui-pay-row">
                                        <div><label className="ui-pay-label">Discount (₹)</label><input className="ui-pay-in" type="number" min="0" step="0.01" value={ payPromo } onChange={ e => setPayPromo( e.target.value ) } /></div>
                                        <div><label className="ui-pay-label">Delivery (₹)</label><input className="ui-pay-in" type="number" min="0" step="0.01" value={ payDelivery } onChange={ e => setPayDelivery( e.target.value ) } /></div>
                                    </div>
                                    <div className="ui-pay-row">
                                        <div style={ { flex: 1 } }><label className="ui-pay-label">GSTIN</label><input className="ui-pay-in" placeholder="GSTIN" value={ payGstin } onChange={ e => setPayGstin( e.target.value ) } /></div>
                                        <div style={ { flex: 1 } }><label className="ui-pay-label">Order ID</label><input className="ui-pay-in" placeholder="Offline" value={ payOrderId } onChange={ e => setPayOrderId( e.target.value ) } /></div>
                                    </div>
                                    <div className="ui-pay-total">Subtotal ₹{ subtotal.toFixed( 2 ) } · GST ₹{ gst.toFixed( 2 ) } · <strong>Total ₹{ grand.toFixed( 2 ) }</strong></div>
                                    <div className="ui-pay-actions">
                                        <button className="ui-pay-cancel" onClick={ () => setComposer( null ) }>Cancel</button>
                                        <button className="ui-pay-send" disabled={ sending || locked } onClick={ handleSendPayment }>{ sending ? 'Sending…' : 'Send payment request' }</button>
                                    </div>
                                </div>
                            );
                        } )() }
                        { composer === 'tts' && ( () => {
                            const fallbackLangs: Record<string, { id: string; gender: string; engine: string }[]> = {
                                'en-IN': [ { id: 'Kajal', gender: 'Female', engine: 'neural' } ],
                                'en-US': [ { id: 'Joanna', gender: 'Female', engine: 'neural' }, { id: 'Matthew', gender: 'Male', engine: 'neural' } ],
                                'hi-IN': [ { id: 'Kajal', gender: 'Female', engine: 'neural' } ],
                            };
                            const voicesMap = Object.keys( pollyVoices ).length ? pollyVoices : fallbackLangs;
                            const langs = Object.keys( voicesMap );
                            const voices = voicesMap[ ttsLang ] || voicesMap[ langs[ 0 ] ] || [];
                            /*
                             * Built here rather than memoised: this block is an IIFE inside JSX, so no hook is
                             * available to it, and both lists are already derived per render from `pollyVoices`.
                             * Same order, same values, same visible text as the <option> rows they replaced.
                             */
                            const langOptions: SelectOption[] = langs.map( l => ( { value: l, label: l } ) );
                            const voiceOptions: SelectOption[] = voices.map(
                                v => ( { value: v.id, label: `${ v.id } (${ v.gender }, ${ v.engine })` } )
                            );
                            return (
                                <div className="ui-pay">
                                    <div className="ui-pay-title">Send voice note (text-to-speech)</div>
                                    <textarea className="ui-pay-in" rows={ 3 } placeholder="Text to speak…" value={ ttsText } onChange={ e => setTtsText( e.target.value ) } />
                                    <div className="ui-pay-row">
                                        <div style={ { flex: 1 } }>
                                            { /* The `.ui-pay-label` captions are UNASSOCIATED labels - no `for`, no
                                                 wrapped control - so they were never a name source and these two had
                                                 no accessible name at all. They stay where they are, keeping their own
                                                 type and spacing, and the controls take `ariaLabel`. Both handlers keep
                                                 every statement and their order: the language change also resets the
                                                 voice and engine to the first voice of the new language. */ }
                                            <label className="ui-pay-label">Language</label>
                                            <Select ariaLabel="Voice language" value={ ttsLang }
                                                onChange={ value => { setTtsLang( value ); const v = ( voicesMap[ value ] || [] )[ 0 ]; if ( v ) { setTtsVoice( v.id ); setTtsEngine( v.engine ); } } }
                                                options={ langOptions } />
                                        </div>
                                        <div style={ { flex: 1 } }>
                                            <label className="ui-pay-label">Voice</label>
                                            <Select ariaLabel="Voice" value={ ttsVoice }
                                                onChange={ value => { setTtsVoice( value ); const v = voices.find( x => x.id === value ); if ( v ) setTtsEngine( v.engine ); } }
                                                options={ voiceOptions } />
                                        </div>
                                    </div>
                                    <div className="ui-pay-actions">
                                        <button className="ui-pay-cancel" onClick={ () => setComposer( null ) }>Cancel</button>
                                        <button className="ui-pay-send" disabled={ sending || !ttsText.trim() } onClick={ handleSendTTS }>{ sending ? 'Sending…' : 'Send voice note' }</button>
                                    </div>
                                </div>
                            );
                        } )() }
                        { composer === 'catalog' && (
                            <div className="ui-pay">
                                <div className="ui-pay-title">Send catalog product</div>
                                <label className="ui-pay-label">Catalog ID</label>
                                { /* No 'Load products' button and no picker grid: /catalog/products has no
                                     live route, so browsing is not available on this deployment. Sending is,
                                     over WA_BIZ_BASE, which is why the id fields below stay. */ }
                                <input className="ui-pay-in" placeholder="Meta catalog ID" value={ catalogId } onChange={ e => setCatalogId( e.target.value ) } />
                                <label className="ui-pay-label">Product retailer ID(s) — comma-separated</label>
                                <input className="ui-pay-in" placeholder="SKU_1, SKU_2, …" value={ catalogProducts } onChange={ e => setCatalogProducts( e.target.value ) } />
                                <label className="ui-pay-label">Message (optional)</label>
                                <textarea className="ui-pay-in" rows={ 2 } placeholder="Body text…" value={ catalogBody } onChange={ e => setCatalogBody( e.target.value ) } />
                                <div className="ui-pay-actions">
                                    <button className="ui-pay-cancel" onClick={ () => setComposer( null ) }>Cancel</button>
                                    <button className="ui-pay-send" disabled={ sending } onClick={ handleSendCatalog }>{ sending ? 'Sending…' : 'Send products' }</button>
                                </div>
                            </div>
                        ) }
                    </div>
                </div>
            ) }

            { showTemplateSender && replyChannel === 'whatsapp' && (
                <TemplateSender
                    contactId={ replyTarget.contactId || undefined }
                    contactName={ selectedConv?.name || '' }
                    phoneNumberId={ selectedWaba }
                    recipientPhone={ !replyTarget.contactId ? ( replyTarget.phone || undefined ) : undefined }
                    enableManualRecipient
                    onClose={ () => setShowTemplateSender( false ) }
                    onSent={ () => { setShowTemplateSender( false ); toast.success( 'Template sent' ); setTimeout( loadData, 800 ); } }
                    onError={ ( m: string ) => toast.error( m ) }
                />
            ) }

            <style jsx>{ `
        .ui-wrap { padding: 12px 18px; max-width: 1360px; margin: 0 auto; width: 100%; box-sizing: border-box; }
        .ui-toolbar { display: flex; gap: 12px; margin: 10px 0; flex-shrink: 0; }
        .ui-search { flex: 1; padding: 9px 14px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 14px; }
        .ui-filter { padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 13px; background: #fff; }
        .ui-panes { display: grid; grid-template-columns: 340px 1fr; gap: 16px; height: calc(100vh - 168px); min-height: 460px; overflow: hidden; }
        .ui-list { border: 1px solid ${colors.border}; border-radius: 12px; overflow-y: auto; background: #fff; min-height: 0; }
        .ui-conv { display: block; width: 100%; text-align: left; padding: 12px 14px; border: none; border-bottom: 1px solid ${colors.borderLight}; background: #fff; cursor: pointer; }
        .ui-conv:hover { background: ${colors.bgHover}; }
        .ui-conv.active { background: ${colors.bgActive}; }
        .ui-conv-top { display: flex; justify-content: space-between; align-items: center; }
        .ui-conv-name { font-weight: 600; font-size: 14px; color: ${colors.text}; }
        .ui-conv-time { font-size: 11px; color: ${colors.textMuted}; }
        .ui-conv-bottom { display: flex; justify-content: space-between; align-items: center; margin-top: 4px; gap: 8px; }
        .ui-conv-preview { font-size: 12px; color: ${colors.textSecondary}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ui-badges { display: flex; gap: 4px; flex-shrink: 0; }
        .ui-badge { font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 9999px; white-space: nowrap; }
        .ui-thread { border: 1px solid ${colors.border}; border-radius: 12px; display: flex; flex-direction: column; background: #fff; overflow: hidden; min-height: 0; }
        .ui-thread-head { padding: 12px 16px; border-bottom: 1px solid ${colors.border}; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
        .ui-back { display: none; align-items: center; justify-content: center; width: 32px; height: 32px; border: 1px solid ${colors.border}; border-radius: 8px; background: #fff; color: ${colors.primary}; font-size: 18px; cursor: pointer; flex-shrink: 0; }
        .ui-thread-name { font-weight: 700; font-size: 15px; color: ${colors.text}; }
        .ui-avatar { width: 38px; height: 38px; border-radius: 50%; background: ${colors.primary}; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; flex-shrink: 0; }
        .ui-thread-id { display: flex; flex-direction: column; min-width: 0; }
        .ui-thread-sub { font-size: 11px; color: ${colors.textMuted}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ui-id-chip { display: inline-block; margin-left: 6px; font-size: 10px; font-weight: 600; color: ${colors.primary}; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 9999px; padding: 1px 7px; cursor: help; }
        .ui-icon-btn { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: 1px solid ${colors.border}; border-radius: 8px; background: #fff; color: ${colors.primary}; cursor: pointer; flex-shrink: 0; }
        .ui-icon-btn:hover { background: ${colors.bgHover}; border-color: ${colors.primary}; }
        .ui-icon-danger { color: #b91c1c; }
        .ui-icon-danger:hover { background: #fef2f2; border-color: #b91c1c; }
        .ui-unread-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${colors.primary}; margin-right: 6px; vertical-align: middle; }
        .ui-conv.unread .ui-conv-name { font-weight: 800; }
        .ui-conv.unread { background: #f7fee7; }
        /* The six .ui-cat-* rules were here. They styled only the removed product picker,
           and nothing else in the tree references them. Lint does not flag dead CSS, so
           they would have survived the TSX deletion silently. */
        .ui-summarize { display: inline-flex; align-items: center; gap: 5px; margin-left: auto; background: #f0fdf4; color: ${colors.primary}; border: 1px solid #bbf7d0; padding: 6px 12px; border-radius: 9px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .ui-summarize:disabled { opacity: 0.6; cursor: not-allowed; }
        .ui-summary { display: flex; gap: 8px; align-items: flex-start; background: #faf5ff; border: 1px solid #e9d5ff; border-radius: 10px; padding: 10px 12px; margin: 8px 16px 0; }
        .ui-summary-text { font-size: 13px; color: ${colors.text}; white-space: pre-wrap; flex: 1; }
        .ui-summary-x { background: none; border: none; cursor: pointer; color: ${colors.textMuted}; }
        .ui-meta-bar { display: flex; gap: 8px; align-items: center; padding: 8px 16px; border-bottom: 1px solid ${colors.borderLight}; flex-wrap: wrap; }
        .ui-meta-status { padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 12px; background: #fff; }
        .ui-meta-assignee { width: 130px; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 12px; }
        .ui-meta-tags { flex: 1; min-width: 120px; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 12px; }
        .ui-meta-notes-btn { padding: 6px 12px; border: 1px solid ${colors.border}; border-radius: 8px; background: #fff; font-size: 12px; cursor: pointer; }
        .ui-notes { padding: 10px 16px; border-bottom: 1px solid ${colors.borderLight}; background: ${colors.bgSecondary}; display: flex; flex-direction: column; gap: 6px; max-height: 200px; overflow-y: auto; }
        .ui-note { display: flex; flex-direction: column; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 6px 10px; }
        .ui-note-text { font-size: 13px; color: ${colors.text}; }
        .ui-note-by { font-size: 10px; color: ${colors.textMuted}; margin-top: 2px; }
        .ui-note-add { display: flex; gap: 8px; }
        .ui-note-input { flex: 1; padding: 7px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 13px; }
        .ui-note-btn { padding: 7px 14px; background: ${colors.primary}; color: #fff; border: none; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .ui-note-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .ui-thread-body { flex: 1; overflow-y: auto; scroll-behavior: smooth; padding: 16px; display: flex; flex-direction: column; gap: 10px; background: ${colors.bgSecondary}; min-height: 200px; }
        .ui-msg { display: flex; }
        .ui-msg.out { justify-content: flex-end; }
        .ui-msg-bubble { max-width: 70%; background: #fff; border: 1px solid ${colors.border}; border-radius: 12px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
        .ui-msg.out .ui-msg-bubble { background: ${colors.lime}; border-color: ${colors.lime}; }
        .ui-msg-text { font-size: 14px; color: ${colors.text}; white-space: pre-wrap; word-break: break-word; }
        .ui-msg-img { max-width: 220px; max-height: 220px; border-radius: 8px; object-fit: cover; }
        .ui-msg-doc { font-size: 13px; color: ${colors.primary}; text-decoration: none; font-weight: 600; }
        .ui-msg-transcript { font-size: 12px; color: ${colors.textSecondary}; font-style: italic; border-left: 2px solid ${colors.border}; padding-left: 6px; }
        .ui-react { display: flex; padding: 2px 0; }
        .ui-react.out { justify-content: flex-end; }
        .ui-react-pill { font-size: 11px; color: ${colors.textMuted}; background: ${colors.bgSecondary}; border: 1px solid ${colors.borderLight}; border-radius: 9999px; padding: 2px 10px; }
        .ui-msg-meta { font-size: 10px; color: ${colors.textMuted}; display: flex; align-items: center; gap: 8px; }
        .ui-st { font-weight: 600; }
        .ui-st-sent { color: ${colors.textMuted}; }
        /* Meta has acknowledged the send but has not yet reported it as sent.
           Dimmer than the sent tick on purpose: a weaker claim, not a failure. */
        .ui-st-accepted { color: ${colors.textMuted}; opacity: 0.65; }
        .ui-st-delivered { color: #2563eb; }
        .ui-st-read { color: #15803d; }
        .ui-st-failed { color: #b91c1c; cursor: help; }
        .ui-msg-act { background: none; border: none; cursor: pointer; font-size: 11px; opacity: 0.5; padding: 0 2px; }
        .ui-msg-act:hover { opacity: 1; }
        .ui-msg-act:disabled { opacity: 0.2; cursor: not-allowed; }
        .ui-load-more { align-self: center; background: #fff; border: 1px solid ${colors.border}; border-radius: 9999px; padding: 6px 16px; font-size: 12px; cursor: pointer; color: ${colors.textSecondary}; }
        .ui-load-more:hover { background: ${colors.bgHover}; }
        .ui-replying { display: flex; align-items: center; justify-content: space-between; background: ${colors.bgSecondary}; border-left: 3px solid ${colors.primary}; border-radius: 6px; padding: 6px 10px; }
        .ui-replying-text { font-size: 12px; color: ${colors.textSecondary}; }
        .ui-replying-x { background: none; border: none; cursor: pointer; color: ${colors.textMuted}; font-size: 12px; }
        .ui-wa-bar { display: flex; align-items: center; gap: 8px; }
        .ui-wa-from { font-size: 12px; color: ${colors.textMuted}; }
        .ui-wa-waba { padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 12px; background: #fff; }
        .ui-email-subject { flex: 1; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 12px; }
        .ui-tpl-btn { margin-left: auto; padding: 6px 12px; border: 1px solid ${colors.border}; border-radius: 8px; background: #fff; font-size: 12px; font-weight: 600; cursor: pointer; color: ${colors.primary}; }
        .ui-tpl-list { max-height: 180px; overflow-y: auto; border: 1px solid ${colors.border}; border-radius: 10px; }
        .ui-tpl-item { display: flex; width: 100%; justify-content: space-between; align-items: center; padding: 8px 12px; border: none; border-bottom: 1px solid ${colors.borderLight}; background: #fff; cursor: pointer; text-align: left; }
        .ui-tpl-item:hover { background: ${colors.bgHover}; }
        .ui-tpl-name { font-size: 13px; font-weight: 600; color: ${colors.text}; }
        .ui-tpl-cat { font-size: 10px; color: ${colors.textMuted}; text-transform: capitalize; }
        .ui-tpl-empty { padding: 14px; text-align: center; font-size: 12px; color: ${colors.textMuted}; }
        .ui-fmt-hint { font-size: 10px; color: ${colors.textLight}; margin-right: auto; }
        .ui-ai-btn { display: inline-flex; align-items: center; gap: 5px; background: #f0fdf4; color: ${colors.primary}; border: 1px solid #bbf7d0; padding: 6px 11px; border-radius: 9px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .ui-ai-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .ui-tool-btn { display: inline-flex; align-items: center; justify-content: center; background: #fff; border: 1px solid ${colors.border}; border-radius: 9px; padding: 7px; color: ${colors.primary}; cursor: pointer; }
        .ui-tool-btn:hover:not(:disabled) { background: ${colors.bgHover}; border-color: ${colors.primary}; }
        .ui-tool-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .ui-emoji-row { display: flex; gap: 4px; flex-wrap: wrap; padding: 6px 0; }
        .ui-emoji { background: ${colors.bgSecondary}; border: 1px solid ${colors.borderLight}; border-radius: 8px; padding: 4px 8px; font-size: 16px; cursor: pointer; }
        .ui-emoji:hover { background: ${colors.bgActive}; }
        .ui-quick-list { display: flex; flex-direction: column; gap: 4px; max-height: 160px; overflow-y: auto; border: 1px solid ${colors.border}; border-radius: 10px; padding: 4px; }
        .ui-quick-item { text-align: left; background: ${colors.bgSecondary}; border: 1px solid ${colors.borderLight}; border-radius: 8px; padding: 6px 10px; font-size: 13px; color: ${colors.text}; cursor: pointer; }
        .ui-quick-item:hover { background: ${colors.bgActive}; }
        .ui-modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1410; padding: 20px; }
        .ui-modal { background: #fff; border-radius: 14px; max-width: 560px; width: 100%; max-height: 85vh; overflow-y: auto; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
        .ui-pay { padding: 20px; display: flex; flex-direction: column; gap: 12px; }
        .ui-pay-title { font-size: 16px; font-weight: 700; color: ${colors.text}; }
        .ui-pay-in { width: 100%; padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 14px; font-family: inherit; }
        .ui-pay-in:focus { outline: none; border-color: ${colors.primary}; box-shadow: ${shadow.focus}; }
        .ui-pay-row { display: flex; gap: 10px; }
        .ui-pay-qty { max-width: 90px; }
        .ui-pay-total { font-size: 14px; font-weight: 600; color: ${colors.primary}; }
        .ui-pay-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 4px; }
        .ui-pay-cancel { background: #fff; border: 1px solid ${colors.border}; border-radius: 10px; padding: 8px 16px; font-size: 13px; cursor: pointer; color: ${colors.textSecondary}; }
        .ui-pay-send { background: ${colors.primary}; color: #fff; border: none; border-radius: 10px; padding: 8px 18px; font-size: 13px; font-weight: 600; cursor: pointer; }
        .ui-pay-send:disabled { opacity: 0.5; cursor: not-allowed; }
        .ui-pay-label { font-size: 11px; font-weight: 600; color: ${colors.textMuted}; margin-top: 2px; }
        .ui-pay-lock { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .ui-pay-lock .ui-pay-in { flex: 1; }
        .ui-pay-unlock { background: ${colors.lime}; color: #1a3a2a; border: none; border-radius: 9px; padding: 8px 14px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .ui-pay-err { color: #b91c1c; font-size: 11px; width: 100%; }
        .ui-pay-item { display: flex; flex-direction: column; gap: 6px; border: 1px dashed ${colors.borderLight}; border-radius: 10px; padding: 8px; }
        .ui-pay-gst { max-width: 110px; }
        .ui-pay-rm { background: #fff; border: 1px solid ${colors.border}; border-radius: 8px; padding: 0 10px; cursor: pointer; color: ${colors.textMuted}; }
        .ui-pay-additem { align-self: flex-start; background: #f0fdf4; color: ${colors.primary}; border: 1px solid #bbf7d0; border-radius: 9px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .ui-tpl-preview { font-size: 13px; color: ${colors.textSecondary}; background: ${colors.bgSecondary}; border-radius: 8px; padding: 8px 10px; white-space: pre-wrap; }
        .ui-tpl-head { display: flex; gap: 8px; align-items: center; padding: 6px; border-bottom: 1px solid ${colors.borderLight}; }
        .ui-tpl-toggle { background: #fff; border: 1px solid ${colors.border}; border-radius: 8px; padding: 5px 10px; font-size: 12px; cursor: pointer; color: ${colors.primary}; }
        .ui-tpl-toggle.on { background: ${colors.lime}; color: #1a3a2a; border-color: ${colors.lime}; }
        .ui-tpl-newnum { flex: 1; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 12px; }
        .ui-tpl-var { color: ${colors.primary}; font-weight: 600; }
        .ui-media-stage { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 4px 0; }
        .ui-media-thumb { width: 44px; height: 44px; object-fit: cover; border-radius: 8px; border: 1px solid ${colors.border}; }
        .ui-media-chip { display: inline-flex; align-items: center; gap: 6px; background: ${colors.bgSecondary}; border: 1px solid ${colors.borderLight}; border-radius: 9px; padding: 4px 8px; font-size: 12px; max-width: 220px; }
        .ui-media-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px; color: ${colors.text}; }
        .ui-media-size { color: ${colors.textMuted}; font-size: 10px; }
        .ui-media-x { background: none; border: none; cursor: pointer; color: ${colors.textMuted}; font-size: 12px; }
        .ui-emoji-pop { border: 1px solid ${colors.border}; border-radius: 10px; background: #fff; display: flex; flex-direction: column; max-height: 260px; }
        .ui-emoji-search { margin: 8px; padding: 7px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: 13px; }
        .ui-emoji-scroll { overflow-y: auto; padding: 0 8px 8px; }
        .ui-emoji-cat-label { font-size: 10px; font-weight: 700; color: ${colors.textMuted}; text-transform: uppercase; margin: 6px 2px 4px; }
        .ui-emoji-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(30px, 1fr)); gap: 2px; }
        /* The two rules that styled the on-demand transcribe button went with the button.
           Lint does not flag dead CSS, so an unreferenced rule has to be removed by hand.
           .ui-msg-transcript above STAYS: a transcription stored on the message is still shown. */
        .ui-react-wrap { position: relative; display: inline-flex; }
        .ui-react-pop { position: absolute; bottom: 130%; right: 0; display: flex; gap: 2px; background: #fff; border: 1px solid ${colors.border}; border-radius: 9999px; padding: 4px 6px; box-shadow: 0 4px 14px rgba(0,0,0,0.12); z-index: 20; }
        .ui-react-em { background: none; border: none; cursor: pointer; font-size: 16px; padding: 2px; line-height: 1; }
        .ui-react-em:hover { transform: scale(1.25); }
        .ui-reply { padding: 10px 14px; border-top: 1px solid ${colors.border}; display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
        .ui-reply-input { width: 100%; resize: vertical; padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: 14px; font-family: inherit; }
        .ui-reply-input:focus { outline: none; border-color: ${colors.primary}; box-shadow: ${shadow.focus}; }
        .ui-reply-actions { display: flex; align-items: center; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
        .ui-tools { display: flex; align-items: center; gap: 6px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
        .ui-tools::-webkit-scrollbar { height: 6px; }
        .ui-send-row { display: flex; align-items: center; gap: 10px; }
        .ui-reply-via { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 9999px; margin-right: auto; }
        .ui-reply-link { font-size: 12px; color: ${colors.textMuted}; text-decoration: none; }
        .ui-reply-link:hover { color: ${colors.primary}; }
        .ui-reply-voice { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: ${colors.textMuted}; width: 100%; }
        .ui-reply-btn { background: ${colors.primary}; color: #fff; padding: 8px 18px; border: none; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; }
        .ui-reply-btn:hover:not(:disabled) { background: ${colors.primaryHover}; }
        .ui-reply-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        /* Column, not row: the channel-filtered empty state is three lines and a
           button, and the original row layout laid them out side by side. Every
           single-line use of .ui-empty renders identically either way. */
        .ui-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; height: 100%; padding: 0 16px; text-align: center; line-height: 1.5; color: ${colors.textMuted}; font-size: 14px; }
        .ui-link-btn { background: none; border: none; padding: 0; font: inherit; color: ${colors.primary}; text-decoration: underline; cursor: pointer; }
        .ui-link-btn:hover { color: ${colors.primaryHover}; }
        @media (max-width: 800px) {
          .ui-wrap { height: calc(100vh - 56px); padding: 10px 12px; }
          .ui-toolbar { margin: 8px 0; }
          .ui-panes { grid-template-columns: 1fr; height: calc(100vh - 120px); min-height: 0; }
          /* Master/detail: show the list OR the thread, not both. */
          .ui-panes .ui-thread { display: none; }
          .ui-panes .ui-list { display: block; }
          .ui-panes.has-selection .ui-list { display: none; }
          .ui-panes.has-selection .ui-thread { display: flex; }
          .ui-back { display: inline-flex; }
          .ui-msg-bubble { max-width: 85%; }
          .ui-meta-bar { gap: 6px; }
          .ui-meta-assignee, .ui-meta-tags { width: auto; flex: 1; min-width: 90px; }
        }
      ` }</style>
        </>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default UnifiedInbox;
