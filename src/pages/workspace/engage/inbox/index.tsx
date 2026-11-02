/**
 * Unified Inbox — conversation-grouped view across ALL channels.
 *
 * Reads the single canonical MessagesTable (via api.listMessages channel=ALL), groups
 * by contact, and shows a threaded conversation with per-message channel badges.
 * Sending is channel-specific, so replies deep-link to the channel's own tool.
 *
 * WhatsApp's dedicated inbox ([retired public path]/whatsapp) stays as-is for full WhatsApp send features.
 */

import FlowResponseDetails, { flowResponseTitle } from '../../../../components/FlowResponseDetails';
import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import PageHeader from '../../../../components/PageHeader';
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
import { resolveWaMime, validateWaMediaSize, formatBytes, waMediaCategory, WA_ACCEPT_STRING } from '../../../../lib/wa-media';
import { waErrorTooltip } from '../../../../lib/wa-errors';
import { scrollToEnd } from '../../../../lib/scroll-to-end';
import { addressFieldsFromContact, contactDeliveryAddress, formatAddress } from '../../../../lib/address-format';

type ProfileGroup = { title: string; note: string; rows: [ string, string ][] };

/**
 * The Inbox customer profile, grouped so staff can tell WhatsApp/system identity (never
 * customer-editable) from what the customer entered in F001 Subscribe or on the website.
 * The canonical structured address wins; an older address is shown only when no canonical
 * one exists, and is labelled as not yet confirmed by the customer.
 */
function profileGroups ( contact: api.Contact, fallbackPhone: string, whatsAppName = '' ): ProfileGroup[] {
    const dash = ( value?: string ) => ( value && value.trim() ) || '—';
    const canonical = contact.checkoutDeliveryAddress ? formatAddress( contact.checkoutDeliveryAddress ) : '';
    const anyAddress = canonical || contactDeliveryAddress( contact );
    const address = anyAddress ? addressFieldsFromContact( contact ) : null;
    return [
        {
            title: 'Identity (WhatsApp and system)',
            note: 'Set by WhatsApp or WECARE.DIGITAL. Customers cannot change these.',
            rows: [
                [ 'Customer ID', dash( contact.customerDisplayId || contact.customerUuid ) ],
                [ 'Phone', dash( contact.phone || fallbackPhone ) ],
                [ 'WhatsApp display name', dash( whatsAppName ) ],
                [ 'Meta WhatsApp username', contact.username ? `@${contact.username.replace( /^@/, '' )}` : '—' ],
                [ 'WhatsApp BSUID', contact.bsuid ? `${contact.bsuid.slice( 0, 8 )}…` : '—' ],
            ],
        },
        {
            title: 'Customer-entered profile',
            note: 'From F001 Subscribe or the website.',
            rows: [
                [ 'Name', dash( contact.name ) ],
                [ 'WECARE.DIGITAL profile name', dash( contact.profileUsername ) ],
                [ 'Organization', dash( contact.companyName ) ],
                [ 'Job title', dash( contact.designation ) ],
            ],
        },
        {
            title: 'Address',
            note: canonical ? 'Customer-entered, shared with website checkout.'
                : address ? 'Older record, not yet confirmed by the customer.' : 'No address saved.',
            rows: [
                [ 'Street address', dash( address?.addressLine1 ) ],
                [ 'Apartment / suite / unit', dash( address?.addressLine2 ) ],
                [ 'Landmark / neighborhood', dash( address?.locality ) ],
                [ 'City', dash( address?.city ) ],
                [ 'State / region', dash( address?.state ) ],
                [ 'Postal code', dash( address?.postalCode ) ],
                [ 'Country', dash( address?.country ) ],
            ],
        },
    ];
}

/**
 * Inbound WhatsApp media lives under the gated `secure/` prefix, which cannot be
 * served through CloudFront, so messages-read hands us a presigned S3 URL with a
 * finite TTL. If a thread is left open past that TTL the URL 403s and the <img>
 * goes blank — which is exactly how inbound images "stopped showing" once inbound
 * media moved into secure/. The signature is now 1h (see messages-read), but a
 * thread can outlive even that, so on a load error we re-fetch the single message
 * once to mint a fresh URL rather than leaving a dead tile. One retry only: a
 * genuinely missing object must still fail visibly rather than loop.
 */
const GatedMedia: React.FC<{ messageId?: string; url: string; kind: 'image' | 'video' | 'audio' | 'document'; filename?: string }>
    = ( { messageId, url, kind, filename } ) => {
        const [ src, setSrc ] = useState( url );
        const [ dead, setDead ] = useState( false );
        const retried = useRef( false );
        useEffect( () => { setSrc( url ); setDead( false ); retried.current = false; }, [ url ] );

        const refresh = useCallback( async () => {
            if ( retried.current || !messageId ) { setDead( true ); return; }
            retried.current = true;
            const fresh = await api.getMessage( messageId );
            if ( fresh?.mediaUrl ) setSrc( fresh.mediaUrl ); else setDead( true );
        }, [ messageId ] );

        if ( dead ) return <span className="ui-msg-doc">⚠️ Media unavailable</span>;
        if ( kind === 'image' ) return <img className="ui-msg-img" src={ src } alt="image" onError={ refresh } />;
        if ( kind === 'video' ) return <video className="ui-msg-img" src={ src } controls onError={ refresh } />;
        if ( kind === 'audio' ) return <audio src={ src } controls style={ { maxWidth: '100%' } } onError={ refresh } />;
        return <a className="ui-msg-doc" href={ src } target="_blank" rel="noopener noreferrer">📄 { filename || 'Document' }</a>;
    };

const WABAS = [
    { id: WHATSAPP_PHONES.primary.id, name: WHATSAPP_PHONES.primary.name, display: WHATSAPP_PHONES.primary.display, metaPhoneId: WHATSAPP_PHONES.primary.metaPhoneId },
    { id: WHATSAPP_PHONES.secondary.id, name: WHATSAPP_PHONES.secondary.name, display: WHATSAPP_PHONES.secondary.display, metaPhoneId: WHATSAPP_PHONES.secondary.metaPhoneId },
];

// The media picker's accept list: every WhatsApp-supported MIME from WA_ACCEPT_STRING
// (the one source of truth in wa-media.ts), plus the image/video/audio wildcards for a
// friendlier OS dialog. Type and size are still gated by validateWaMediaSize on select,
// so the wildcards can never let an unsupported file actually be sent.
const MEDIA_ACCEPT = `image/*,video/*,audio/*,${WA_ACCEPT_STRING}`;

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
    whatsapp: { label: 'WhatsApp', fg: '#15803d', bg: '#f0fdf4', reply: '/workspace/communications?view=inbox&channel=whatsapp' },
    sms: { label: 'SMS', fg: '#1d4ed8', bg: '#eff6ff', reply: '/workspace/engage/channels?tab=sms' },
    email: { label: 'Email', fg: '#b45309', bg: '#fffbeb', reply: '/workspace/engage/channels?tab=email' },
    rcs: { label: 'RCS', fg: '#0f766e', bg: '#f0fdfa', reply: '/workspace/engage/channels?tab=rcs' },
    voice: { label: 'Voice', fg: '#6d28d9', bg: '#f5f3ff', reply: '/workspace/engage/channels?tab=voice' },
};

const chMeta = ( c?: string ) => CHANNEL[ ( c || 'whatsapp' ).toLowerCase() ] || { label: c || '?', fg: colors.textMuted, bg: colors.bgSecondary, reply: '/workspace/communications?view=inbox' };

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
// Filter by the receiving WABA independently of the outbound Send from chooser.
// Both accounts are visible by default. Older rows can use a Meta id or phone.
const WABA_FILTER_OPTIONS: SelectOption[] = [
    { value: 'ALL', label: 'Both WhatsApp accounts' },
    ...WABAS.map( w => ( { value: w.id, label: `${ w.name } (${ w.display })` } ) ),
];

const messageWabaId = ( m: api.Message ): string => {
    if ( ( m.channel || '' ).toLowerCase() !== 'whatsapp' ) return '';
    const id = m.awsPhoneNumberId || '';
    const stored = WABAS.find( w => w.id === id || w.metaPhoneId === id );
    if ( stored ) return stored.id;
    const receivingDigits = ( m.receivingPhone || '' ).replace( /\D/g, '' );
    return WABAS.find( w => receivingDigits && w.display.replace( /\D/g, '' ) === receivingDigits )?.id || '';
};
const wabaDisplay = ( id: string ): string => WABAS.find( w => w.id === id )?.display || '';

// Show a provider-supplied name only when it is not the read API's phone fallback.
const realWhatsAppName = ( m: api.Message ): string => {
    if ( ( m.channel || '' ).toLowerCase() !== 'whatsapp' ) return '';
    const name = ( m.senderName || '' ).trim();
    if ( !name || name.toLowerCase() === 'unknown' || /^[+\d\s()-]+$/.test( name ) ) return '';
    return name;
};
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
const paymentGstRate = ( value: string ): number => {
    const rate = Number.parseInt( value, 10 );
    return Number.isFinite( rate ) ? rate : 18;
};
const PAY_GST_OPTIONS: SelectOption[] = GST_RATES.map(
    g => ( { value: String( g.value ), label: `GST ${ g.label }` } )
);
/* LAYOUT ONLY - `.ui-pay-gst` capped the native control at 110px inside `.ui-pay-row`. */
const PAY_GST_SELECT_STYLE: React.CSSProperties = { flex: '0 0 110px' };

// Friendly label for a message — avoids showing bare "[unknown]" / "[whatsapp]".
const TYPE_LABELS: Record<string, string> = {
    // `text`, `call`, `template` and `interactive_list` are here so an empty-content
    // row stops falling through to a bare "Message" — 234 outbound rows did.
    text: 'Message', call: 'Call', template: 'Template message', interactive_list: 'List reply',
    image: 'Photo', video: 'Video', audio: 'Voice message', voice: 'Voice message',
    document: 'Document', sticker: 'Sticker', location: 'Location', contacts: 'Contact card',
    order: 'Order', poll: 'Poll', reaction: 'Reaction', button: 'Button reply',
    interactive: 'Interactive reply', request_welcome: 'Started conversation', system: 'System update',
    referral: 'Ad referral', ad_click: 'Ad click', flow_response: 'Flow response', unsupported: 'Message content unavailable from WhatsApp', unknown: 'Message',
};
const prettyMsg = ( content?: string, messageType?: string ): string => {
    const raw = ( content || '' ).trim();
    const mt = ( messageType || '' ).toLowerCase();
    if ( mt === 'flow_response' && /customer.idea|wd_idea/i.test( raw ) ) return 'Leave Review · Flow response';
    if ( raw.startsWith( '[Flow Response:' ) ) return 'Flow response';
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
    wabas: Set<string>;
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

const UnifiedInbox: React.FC<PageProps> = ( { user, channel } ) => {
    const toast = useToastContext();
    const [ messages, setMessages ] = useState<api.Message[]>( [] );
    const [ contactNames, setContactNames ] = useState<Record<string, string>>( {} );
    const [ contactDir, setContactDir ] = useState<Record<string, api.Contact>>( {} );
    const [ selected, setSelected ] = useState<string | null>( null );
    // Seeded from the `channel` prop, else `?channel=`. Lowercased because the
    // comparisons below lowercase each message's own channel, and 'ALL' is the
    // only value that is not a channel name.
    const router = useRouter();
    const presetChannel = ( channel || '' ).toLowerCase();
    const [ channelFilter, setChannelFilter ] = useState<string>(
        presetChannel && presetChannel in CHANNEL ? presetChannel : 'ALL' );
    const [ wabaFilter, setWabaFilter ] = useState<string>( 'ALL' );
    const [ search, setSearch ] = useState( '' );
    const [ loading, setLoading ] = useState( true );
    const [ replyText, setReplyText ] = useState( '' );
    const [ sending, setSending ] = useState( false );
    const [ replyingTo, setReplyingTo ] = useState<api.Message | null>( null );
    const [ visibleCount, setVisibleCount ] = useState( 50 );
    const [ selectedWaba, setSelectedWaba ] = useState( WABAS[ 0 ].id );
    // True once the agent has changed "Send from" for the conversation that is
    // currently open. Reset on every thread change, so the default is always the
    // thread's own WABA and a deliberate override is per-conversation rather than
    // sticky across threads. State rather than a ref: it is read during render.
    const [ wabaOverridden, setWabaOverridden ] = useState( false );
    const [ showTemplateSender, setShowTemplateSender ] = useState( false );
    const [ quickReplies, setQuickReplies ] = useState<string[]>( [] );
    const [ showQuick, setShowQuick ] = useState( false );
    const [ meta, setMeta ] = useState<api.ConversationMeta | null>( null );
    const [ noteText, setNoteText ] = useState( '' );
    const [ showNotes, setShowNotes ] = useState( false );
    const [ showEmoji, setShowEmoji ] = useState( false );
    const [ composer, setComposer ] = useState<null | 'contact' | 'location' | 'pay' | 'tts'>( null );
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
    // Full TTS picker
    const [ ttsText, setTtsText ] = useState( '' );
    const [ ttsLang, setTtsLang ] = useState( 'en-IN' );
    const [ ttsVoice, setTtsVoice ] = useState( 'Kajal' );
    const [ ttsEngine, setTtsEngine ] = useState( 'neural' );
    const [ pollyVoices, setPollyVoices ] = useState<Record<string, { id: string; gender: string; engine: string }[]>>( {} );
    // Full payment form
    const [ payPhone, setPayPhone ] = useState( PAYMENT_CONFIG.phoneNumberId );
    const [ payItems, setPayItems ] = useState<{ name: string; amount: string; quantity: string; gstRate: string }[]>( [ { name: '', amount: '', quantity: '1', gstRate: '18' } ] );
    const [ payInvoiceDraft, setPayInvoiceDraft ] = useState<{ key: string; contactId: string; invoice: api.CreateInvoiceEngineResponse } | null>( null );
    const payGoodsType = 'physical-goods' as const;
    const [ payDelivery, setPayDelivery ] = useState( '0' );
    const [ payGstin, setPayGstin ] = useState( DEFAULT_GSTIN );
    const [ payOrderId, setPayOrderId ] = useState( '' );
    const [ payUnlocked, setPayUnlocked ] = useState( false );
    // Block + mark-unread
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
            const dir: Record<string, api.Contact> = {};
            contacts.forEach( c => {
                names[ c.contactId ] = c.name || c.email || '';
                dir[ c.contactId ] = c;
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
        setWabaFilter( 'ALL' );
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
        setReplyingTo( null ); setReplyText( '' ); setVisibleCount( 50 ); setShowTemplateSender( false ); setShowRcsTemplates( false ); setEmailSubject( '' ); setMediaFiles( [] ); setMediaPreview( null ); setEmojiSearch( '' ); setShowEmoji( false );
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

    // Multi-file media staging: validate per-type size, then queue for send.
    const handleMediaSelect = useCallback( ( e: React.ChangeEvent<HTMLInputElement> ) => {
        const files = Array.from( e.target.files || [] );
        if ( e.target ) e.target.value = '';
        if ( !files.length ) return;
        const accepted: File[] = [];
        for ( const file of files )
        {
            const ftype = resolveWaMime( file );
            const check = validateWaMediaSize( { size: file.size, name: file.name, type: ftype }, ftype );
            if ( !check.ok )
            {
                toast.error( check.limit > 0
                    ? `${file.name} too large. Max: ${formatBytes( check.limit )}`
                    : `${file.name}: ${check.message || 'Unsupported WhatsApp file type'}` );
                continue;
            }
            accepted.push( file );
        }
        if ( !accepted.length ) return;
        setMediaFiles( prev => [ ...prev, ...accepted ] );
        const firstImage = accepted.find( f => resolveWaMime( f ).startsWith( 'image/' ) );
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
            const waba = messageWabaId( m );
            if ( wabaFilter !== 'ALL' && waba !== wabaFilter ) continue;
            const cid = m.contactId || m.senderPhone || m.receivingPhone || 'unknown';
            const ts = new Date( m.timestamp ).getTime() || 0;
            const existing = map.get( cid );
            if ( !existing )
            {
                map.set( cid, {
                    contactId: cid,
                    name: contactNames[ cid ] || realWhatsAppName( m ) || m.senderPhone || m.receivingPhone || cid,
                    channels: new Set( [ ch ] ),
                    wabas: new Set<string>( waba ? [ waba ] : [] ),
                    lastContent: m.content || `[${m.messageType || ch}]`,
                    lastType: m.messageType || '',
                    lastTs: ts,
                    lastChannel: ch,
                } );
            } else
            {
                existing.channels.add( ch );
                if ( waba ) existing.wabas.add( waba );
                if ( !contactNames[ cid ] && /^[+\d\s()-]+$/.test( existing.name ) && realWhatsAppName( m ) )
                    existing.name = realWhatsAppName( m );
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
    }, [ messages, contactNames, channelFilter, wabaFilter, search ] );

    // Thread for the selected conversation (chronological).
    const thread = useMemo( () => {
        if ( !selected ) return [];
        return messages
            .filter( m => ( m.contactId || m.senderPhone || m.receivingPhone || 'unknown' ) === selected )
            .filter( m => channelFilter === 'ALL' || ( m.channel || 'whatsapp' ).toLowerCase() === channelFilter )
            .filter( m => wabaFilter === 'ALL' || messageWabaId( m ) === wabaFilter )
            .sort( ( a, b ) => ( new Date( a.timestamp ).getTime() || 0 ) - ( new Date( b.timestamp ).getTime() || 0 ) );
    }, [ messages, selected, channelFilter, wabaFilter ] );

    const selectedConv = conversations.find( c => c.contactId === selected );
    const selectedContact = selected ? contactDir[ selected ] : undefined;
    const whatsAppName = [ ...thread ].reverse().map( realWhatsAppName ).find( Boolean ) || '';
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
    }, [ selected, wabaFilter ] );

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
                    // Send each staged file as its own WhatsApp media message — Meta
                    // carries one media object per message, so N files is N sends.
                    // The caption (and the native reply context) ride the FIRST message
                    // that actually goes out, not a fixed index: if the first file fails
                    // to upload, the caption must not vanish with it. Audio and sticker
                    // captions are dropped server-side by Meta's rules, so warn once if
                    // the user typed text alongside a lone audio/sticker.
                    let sent = 0;
                    const failed: string[] = [];
                    // Whether the typed text can ride the attachments as a caption at all:
                    // only image/video/document carry captions in Meta's API. Audio and
                    // sticker cannot, so the text must not simply vanish.
                    const captionCapable = !!waText
                        && [ 'image', 'video', 'document' ].includes(
                            waMediaCategory( resolveWaMime( mediaFiles[ 0 ] ) ) );
                    // When the text cannot be a caption (e.g. a lone audio/sticker), send
                    // it as its own message FIRST so it still reaches the recipient rather
                    // than being dropped. It also claims the native reply context.
                    let captionPlaced = false;
                    let contextClaimed = false;
                    if ( waText && !captionCapable )
                    {
                        const textResult = await api.sendWhatsAppMessage( {
                            contactId, content: waText, phoneNumberId: sendWaba || undefined,
                            recipientBsuid: bsuid, contextMessageId: waContext,
                        } );
                        if ( textResult ) { sent++; contextClaimed = true; }
                    }
                    for ( let i = 0; i < mediaFiles.length; i++ )
                    {
                        const file = mediaFiles[ i ];
                        const type = resolveWaMime( file );
                        const s3Key = await api.uploadMediaForSend( file, type, file.name );
                        if ( !s3Key ) { failed.push( file.name ); continue; }
                        // The typed text rides the FIRST media that actually goes out, but
                        // only when it can carry a caption (image/video/document). If the
                        // text was already sent as its own message above (audio/sticker),
                        // captionCapable is false and no media claims it again.
                        const giveCaption = captionCapable && !captionPlaced;
                        // The first message to leave claims the native reply context —
                        // unless the separate text message above already took it.
                        const giveContext = !contextClaimed;
                        const r = await api.sendWhatsAppMessage( {
                            contactId,
                            content: giveCaption ? waText : '',
                            phoneNumberId: sendWaba || undefined,
                            recipientBsuid: bsuid,
                            mediaFile: s3Key,
                            mediaType: type,
                            mediaFileName: file.name,
                            contextMessageId: giveContext ? waContext : undefined,
                        } );
                        if ( r ) { sent++; contextClaimed = true; if ( giveCaption ) captionPlaced = true; }
                        else { failed.push( file.name ); }
                    }
                    ok = sent > 0;
                    // Keep only the files that failed, so the user can retry them without
                    // re-picking the whole set; clear the preview only when all went out.
                    if ( failed.length )
                    {
                        setMediaFiles( prev => prev.filter( f => failed.includes( f.name ) ) );
                        toast.error( sent > 0
                            ? `Sent ${sent} of ${mediaFiles.length} — failed: ${failed.join( ', ' )}`
                            : `Could not send: ${failed.join( ', ' )}` );
                    } else if ( ok )
                    {
                        setMediaFiles( [] ); setMediaPreview( null );
                        if ( waText && !captionCapable ) toast.info( 'Your text was sent as a separate message — WhatsApp does not allow captions on audio or stickers' );
                    }
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

    const updatePayItem = ( i: number, field: 'name' | 'amount' | 'quantity' | 'gstRate', val: string ) =>
        setPayItems( p => p.map( ( it, idx ) => idx === i ? { ...it, [ field ]: val } : it ) );
    const addPayItem = () => setPayItems( p => [ ...p, { name: '', amount: '', quantity: '1', gstRate: '18' } ] );
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

    /**
     * Raise an invoice, then ask the server to send its payment request.
     *
     * This browser composes NO payment. It used to build the whole Meta `order_details` here and
     * POST it to `/whatsapp/send`, which had two defects no server-side gate can reach:
     *
     *   - the `reference_id` was minted in the browser as `WD-PAY-${Date.now()}` and reserved
     *     nowhere, so it had no `PAYREF#` row — and a capture against an unreserved reference
     *     resolves to nothing and quarantines as PAID_BUT_NO_ORDER, the exact failure the
     *     reservation module exists to prevent;
     *   - the payment configuration name fell back to a client-side literal.
     *
     * Both close by going through the invoice path instead: `POST /invoices` reserves the
     * reference before anything is sent, the per-invoice interlock applies, the convenience fee
     * is computed once on the server, and both readiness gates apply. It is the same two calls
     * the staff invoice flow already makes.
     */
    const handleSendPayment = useCallback( async () => {
        const { contactId, phone } = replyTarget;
        if ( !contactId ) { toast.error( 'Payment needs a saved contact' ); return; }
        if ( !phone ) { toast.error( 'Payment needs the customer phone' ); return; }
        const phoneObj = PAYMENT_PHONES.find( p => p.id === payPhone );
        if ( phoneObj?.paymentProtected && !payUnlocked ) { toast.error( 'Unlock this number first' ); return; }
        const valid = payItems.filter( i => i.name.trim() && parseFloat( i.amount ) > 0 );
        if ( !valid.length ) { toast.error( 'Add at least one item with an amount' ); return; }
        const draftKey = JSON.stringify( { contactId, items: valid, delivery: payDelivery, goodsType: payGoodsType, orderId: payOrderId, gstin: payGstin } );
        if ( payInvoiceDraft?.contactId === contactId && payInvoiceDraft.key !== draftKey )
        {
            toast.error( 'An invoice already exists for this draft. Resolve it in Pay → Invoices before changing the request.' ); return;
        }
        setSending( true );
        try
        {
            // Rupees, not paise: `CreateInvoiceEngineRequest.items[].amount` is a rupee figure
            // and the server converts with exact integer arithmetic. No total, no tax and no fee
            // is computed here — every figure on the invoice is the server's.
            const addr = selectedContact ? addressFieldsFromContact( selectedContact ) : {
                addressLine1: '', addressLine2: '', city: '', state: '', postalCode: '', countryCode: 'IN',
            };
            if ( payGoodsType === 'physical-goods'
                && [ addr.addressLine1, addr.city, addr.state, addr.postalCode ].some( v => !String( v || '' ).trim() ) )
            {
                toast.error( 'This contact needs Street address, City, State / region, Postal code and Country before a physical payment can be raised.' );
                return;
            }

            let invoice = payInvoiceDraft?.key === draftKey ? payInvoiceDraft.invoice : null;
            if ( !invoice )
            {
                const created = await api.createInvoiceEngineResult( {
                    customerPhone: phone,
                    customerEmail: '',
                    shippingAddress: selectedContact ? contactDeliveryAddress( selectedContact ) : '',
                    billingAddress: selectedContact ? contactDeliveryAddress( selectedContact ) : '',
                    contactId,
                    items: valid.map( it => ( {
                        name: it.name.trim(),
                        amount: parseFloat( it.amount ),
                        quantity: parseInt( it.quantity ) || 1,
                        gstRate: paymentGstRate( it.gstRate ),
                    } ) ),
                    goodsType: payGoodsType,
                    shipping: parseFloat( payDelivery || '0' ) || 0,
                    gstin: payGstin || DEFAULT_GSTIN,
                    orderId: payOrderId || 'Offline',
                    entryPoint: 'inbox',
                    addressLine1: addr.addressLine1,
                    addressLine2: addr.addressLine2,
                    city: addr.city,
                    state: addr.state,
                    postalCode: addr.postalCode,
                    countryCode: addr.countryCode || 'IN',
                } );
                if ( !created.ok )
                {
                    const messages: Record<string, string> = {
                        DELIVERY_REQUIRED: 'Complete the customer delivery address before creating a physical invoice.',
                        INVALID_PIN: 'The saved postal code is not payable for WhatsApp payment. Update the customer address.',
                        INVALID_AMOUNT: 'Check the item amount, quantity, GST and delivery values.',
                        REQUEST_FAILED: 'Invoice service could not be reached. Try again once.',
                        CREATE_FAILED: 'Invoice creation was refused. Open Pay → Invoices for the current state before retrying.',
                    };
                    toast.error( messages[ created.errorCode ] || `Invoice create failed: ${created.errorCode}` );
                    return;
                }
                invoice = created.invoice;
            }
            setPayInvoiceDraft( { key: draftKey, contactId, invoice } );
            // The configuration name is NOT defaulted here. Omitted, the server resolves it from
            // the invoice row and then from its own proven expectation.
            const sent = await api.sendPaymentLinkResult( invoice.invoiceId, payPhone );
            // `payment_link_sent` is the ONLY success. A 2xx can also answer rejected or already in
            // progress, and reporting either as "sent" would have staff chasing a payment request
            // that never went out.
            if ( sent.ok && sent.data.status === 'payment_link_sent' )
            {
                toast.success( `Payment request sent (invoice ${invoice.invoiceNumber})` );
                setComposer( null );
                setPayInvoiceDraft( null );
                setPayItems( [ { name: '', amount: '', quantity: '1', gstRate: '18' } ] );
                setPayDelivery( '0' ); setPayOrderId( '' );
                setTimeout( loadData, 800 );
            }
            else
            {
                // "Not confirmed", never "not sent": a timeout can still have reached Meta.
                const why = sent.ok ? sent.data.status : sent.failure.message;
                toast.error( `Payment request not confirmed${ why ? ` (${ why })` : '' }. Invoice ${invoice.invoiceNumber} is retained; check it in Pay → Invoices before resending.` );
            }
        } catch { toast.error( 'Payment request not confirmed. Check Pay → Invoices before creating another invoice.' ); }
        finally { setSending( false ); }
    }, [ replyTarget, selectedContact, payPhone, payUnlocked, payItems, payGoodsType, payInvoiceDraft, payDelivery, payGstin, payOrderId, toast, loadData ] );

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
                        onChange={ v => { setChannelFilter( v ); setWabaFilter( 'ALL' ); setSelected( null ); } }
                        options={ CHANNEL_FILTER_OPTIONS } style={ { width: 170 } } />
                    { ( channelFilter === 'ALL' || channelFilter === 'whatsapp' ) && (
                        <Select ariaLabel="WhatsApp business account" value={ wabaFilter }
                            onChange={ v => { setWabaFilter( v ); if ( v !== 'ALL' ) setChannelFilter( 'whatsapp' ); setSelected( null ); setReplyingTo( null ); } }
                            options={ WABA_FILTER_OPTIONS } style={ { width: 260 } } />
                    ) }
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
                                        No { wabaFilter !== 'ALL' ? `WhatsApp conversations for ${ wabaDisplay( wabaFilter ) }` : `${ chMeta( channelFilter ).label } conversations` }.
                                        { messages.length > 0 && (
                                            <>
                                                <br />{ messages.length } message{ messages.length === 1 ? '' : 's' } on other channels.
                                                <br />
                                                <button type="button" className="ui-link-btn" onClick={ () => { setChannelFilter( 'ALL' ); setWabaFilter( 'ALL' ); } }>
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
                                            { Array.from( c.wabas ).map( id => <span key={ id } className="ui-badge ui-waba-badge">{ wabaDisplay( id ) }</span> ) }
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
                                                selectedContact?.username
                                                    ? `@${selectedContact.username.replace( /^@/, '' )}`
                                                    : replyTarget.phone,
                                                selectedContact?.profileUsername ? `WECARE.DIGITAL profile: ${selectedContact.profileUsername}` : '',
                                                selectedContact?.customerDisplayId || '',
                                                `${thread.length} message${thread.length === 1 ? '' : 's'}`,
                                            ].filter( Boolean ).join( ' · ' ) }
                                            { selectedContact?.bsuid && (
                                                <span className="ui-id-chip" title={ `WhatsApp BSUID: ${selectedContact!.bsuid}` }>WhatsApp ID { selectedContact!.bsuid!.slice( 0, 8 ) }…</span>
                                            ) }
                                        </span>
                                    </div>
                                    <span className="ui-badges">
                                        { selectedConv && Array.from( selectedConv.channels ).map( ch => {
                                            const cm = chMeta( ch );
                                            return <span key={ ch } className="ui-badge" style={ { color: cm.fg, background: cm.bg } }>{ cm.label }</span>;
                                        } ) }
                                        { selectedConv && Array.from( selectedConv.wabas ).map( id => <span key={ id } className="ui-badge ui-waba-badge">{ wabaDisplay( id ) }</span> ) }
                                    </span>
                                    <button className="ui-icon-btn" onClick={ () => loadData() } title="Refresh"><Icon name="refresh" size={ 16 } /></button>
                                    <button className="ui-icon-btn" onClick={ markUnread } title="Mark unread"><Icon name="mail" size={ 16 } /></button>
                                    { replyChannel === 'whatsapp' && (
                                        <button className="ui-icon-btn ui-icon-danger" disabled={ blocking } onClick={ () => handleBlockToggle( true ) } title="Block contact (only if they messaged in last 24h)"><Icon name="block" size={ 16 } /></button>
                                    ) }
                                </div>
                                { selectedContact && (
                                    <details className="ui-customer-profile" aria-label="Customer profile">
                                        <summary className="ui-customer-profile-heading">WECARE.DIGITAL customer profile</summary>
                                        <div className="ui-customer-profile-scroll">
                                            <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 12 } }>
                                                { profileGroups( selectedContact, replyTarget.phone, whatsAppName ).map( group => (
                                                    <tbody key={ group.title }>
                                                        <tr>
                                                            <th colSpan={ 2 } scope="colgroup" style={ { textAlign: 'left', padding: '8px 10px 4px', borderBottom: '1px solid var(--border)', fontWeight: 700 } }>
                                                                { group.title }
                                                                <span style={ { display: 'block', fontWeight: 400, color: 'var(--text-muted)' } }>{ group.note }</span>
                                                            </th>
                                                        </tr>
                                                        { group.rows.map( ( [ label, value ] ) => <tr key={ label }>
                                                            <th scope="row" style={ { textAlign: 'left', padding: '6px 10px', width: '34%', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontWeight: 600 } }>{ label }</th>
                                                            <td style={ { padding: '6px 10px', borderBottom: '1px solid var(--border)', wordBreak: 'break-word' } }>{ value }</td>
                                                        </tr> ) }
                                                    </tbody>
                                                ) ) }
                                            </table>
                                        </div>
                                    </details>
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
                                                    { messageWabaId( m ) && <span className="ui-badge ui-waba-badge">{ wabaDisplay( messageWabaId( m ) ) }</span> }
                                                    { ( () => {
                                                        const mt = ( m.messageType || '' ).toLowerCase();
                                                        const url = m.mediaUrl || '';
                                                        const mid = m.messageId || ( m as any ).id;
                                                        if ( url && ( mt === 'image' || mt === 'sticker' ) ) return <GatedMedia messageId={ mid } url={ url } kind="image" />;
                                                        if ( url && mt === 'video' ) return <GatedMedia messageId={ mid } url={ url } kind="video" />;
                                                        if ( url && ( mt === 'audio' || mt === 'voice' ) ) return <GatedMedia messageId={ mid } url={ url } kind="audio" />;
                                                        if ( url && mt === 'document' ) return <GatedMedia messageId={ mid } url={ url } kind="document" filename={ ( m as any ).displayFilename } />;
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
                                                    { ( m.messageType || '' ).toLowerCase() === 'flow_response' && (
                                                        <div className="ui-flow-response">
                                                            <details className="ui-flow-details">
                                                                <summary className="ui-flow-summary">
                                                                    <strong>{ flowResponseTitle( m ) } · Flow response</strong>
                                                                    <span className="ui-flow-count">
                                                                        { m.flowAnswers?.length || 0 } answers
                                                                        { m.flowAttachments?.length ? ` · ${m.flowAttachments.length} attachments` : '' }
                                                                    </span>
                                                                </summary>
                                                                <div className="ui-flow-data">
                                                                    <FlowResponseDetails flowAnswers={ m.flowAnswers } flowAttachments={ m.flowAttachments } />
                                                                </div>
                                                            </details>
                                                        </div>
                                                    ) }
                                                    { !( ( m.messageType || '' ).toLowerCase() === 'contacts' && Array.isArray( ( m as any ).contactsPayload ) && ( m as any ).contactsPayload.length > 0 )
                                                        && ( m.messageType || '' ).toLowerCase() !== 'flow_response' && ( ( m.content && !isSysLabel( m.content ) ) || !m.mediaUrl ) && (
                                                        ( () => {
                                                            const value = prettyMsg( m.content, m.messageType );
                                                            const revokedStyle = revoked ? { textDecoration: 'line-through' as const, opacity: 0.55 } : undefined;
                                                            if ( value.length <= 900 ) return <span className="ui-msg-text" style={ revokedStyle }>{ value }</span>;
                                                            return <details className="ui-long-message">
                                                                <summary>
                                                                    <span className="ui-long-preview" style={ revokedStyle }>{ value.slice( 0, 300 ).trimEnd() }…</span>
                                                                    <span className="ui-long-more">Show full message</span>
                                                                    <span className="ui-long-less">Hide full message</span>
                                                                </summary>
                                                                <span className="ui-msg-text" style={ revokedStyle }>{ value }</span>
                                                            </details>;
                                                        } )()
                                                    ) }
                                                    { ( ( m.messageType || '' ).toLowerCase() === 'unsupported' || ( m.content || '' ).toLowerCase().startsWith( '[unsupported: ' ) ) && (
                                                        <span className="ui-msg-meta">Meta did not include readable message content; this is not an inbox loading error.</span>
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
                                                            style={ { fontSize: 'var(--text-xs)', fontStyle: 'italic', opacity: 0.7, marginTop: 2 } }
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
                                                    { replyTarget.contactId && (
                                                        <button
                                                            className="ui-tpl-btn"
                                                            onClick={ () => {
                                                                setPayPhone( PAYMENT_CONFIG.phoneNumberId );
                                                                setPayUnlocked( false );
                                                                setComposer( 'pay' );
                                                            } }
                                                            title="Create an invoice and send the approved Review and Pay template"
                                                        >
                                                            Request payment
                                                        </button>
                                                    ) }
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
                                                                <button type="button" className="ui-tool-btn" onClick={ () => setComposer( 'location' ) } title="Send location"><Icon name="pin" /></button>
                                                                <button type="button" className="ui-tool-btn" onClick={ () => setComposer( 'contact' ) } title="Send contact card"><Icon name="user" /></button>
                                                                <button type="button" className="ui-tool-btn" onClick={ openTts } title="Send as voice note (TTS)"><Icon name="mic" /></button>
                                                                <button type="button" className="ui-tool-btn" onClick={ () => setComposer( 'pay' ) } title="Request payment"><Icon name="pay" /></button>
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
                                                <button className="ui-reply-btn" disabled={ sending || ( !replyText.trim() && !( replyChannel === 'whatsapp' && mediaFiles.length > 0 ) ) } onClick={ handleReply }>{ sending ? 'Sending…' : 'Send' }</button>
                                            </div>
                                            { replyChannel === 'whatsapp' && (
                                                <input ref={ fileRef } type="file" hidden multiple accept={ MEDIA_ACCEPT } onChange={ handleMediaSelect } />
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
                            const gst = payItems.reduce( ( s, it ) => s + ( parseFloat( it.amount ) || 0 ) * ( parseInt( it.quantity ) || 1 ) * paymentGstRate( it.gstRate ) / 100, 0 );
                            const grand = subtotal + gst + ( parseFloat( payDelivery ) || 0 );
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
                                        <div><label className="ui-pay-label">Goods type</label><span>Physical goods — confirmed delivery address required</span></div>
                                        <div><label className="ui-pay-label">Delivery (₹)</label><input className="ui-pay-in" type="number" min="0" step="0.01" value={ payDelivery } onChange={ e => setPayDelivery( e.target.value ) } /></div>
                                    </div>
                                    <div className="ui-pay-row">
                                        <div style={ { flex: 1 } }><label className="ui-pay-label">GSTIN</label><input className="ui-pay-in" placeholder="GSTIN" value={ payGstin } onChange={ e => setPayGstin( e.target.value ) } /></div>
                                        <div style={ { flex: 1 } }><label className="ui-pay-label">Order ID</label><input className="ui-pay-in" placeholder="Offline" value={ payOrderId } onChange={ e => setPayOrderId( e.target.value ) } /></div>
                                    </div>
                                    <div className="ui-pay-total">Subtotal ₹{ subtotal.toFixed( 2 ) } · GST ₹{ gst.toFixed( 2 ) } · <strong>Before checkout adjustments ₹{ grand.toFixed( 2 ) }</strong></div>
                                    <p className="ui-pay-label">The invoice calculates eligible Delight and fees. Physical goods need complete delivery details saved on the contact before payment.</p>
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
                    </div>
                </div>
            ) }

            { showTemplateSender && replyChannel === 'whatsapp' && (
                <TemplateSender
                    contactId={ replyTarget.contactId || undefined }
                    contactName={ selectedConv?.name || '' }
                    phoneNumberId={ selectedWaba }
                    recipientPhone={ !replyTarget.contactId ? ( replyTarget.phone || undefined ) : undefined }
                    customerPhone={ replyTarget.phone || undefined }
                    enableManualRecipient
                    onRequestPayment={ () => {
                        setShowTemplateSender( false );
                        setPayPhone( PAYMENT_CONFIG.phoneNumberId );
                        setPayUnlocked( false );
                        setComposer( 'pay' );
                    } }
                    onClose={ () => setShowTemplateSender( false ) }
                    onSent={ () => { setShowTemplateSender( false ); toast.success( 'Template sent' ); setTimeout( loadData, 800 ); } }
                    onError={ ( m: string ) => toast.error( m ) }
                />
            ) }

            <style jsx>{ `
        .ui-wrap { padding: 10px 12px; max-width: 1360px; margin: 0 auto; width: 100%; box-sizing: border-box; container-type: inline-size; container-name: inbox; }
        .ui-toolbar { display: flex; gap: 8px; margin: 6px 0 8px; flex-shrink: 0; }
        .ui-search { flex: 1; padding: 9px 14px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: var(--text-md); }
        .ui-filter { padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: var(--text-sm); background: #fff; }
        .ui-panes { display: grid; grid-template-columns: minmax(0, 280px) minmax(0, 1fr); gap: 10px; height: calc(100dvh - 160px); min-height: 0; overflow: hidden; }
        .ui-list { border: 1px solid ${colors.border}; border-radius: 12px; overflow-y: auto; background: #fff; min-height: 0; }
        .ui-conv { display: block; width: 100%; text-align: left; padding: 12px 14px; border: none; border-bottom: 1px solid ${colors.borderLight}; background: #fff; cursor: pointer; }
        .ui-conv:hover { background: ${colors.bgHover}; }
        .ui-conv.active { background: ${colors.bgActive}; }
        .ui-conv-top { display: flex; justify-content: space-between; align-items: center; }
        .ui-conv-name { font-weight: 600; font-size: var(--text-md); color: ${colors.text}; }
        .ui-conv-time { font-size: var(--text-xs); color: ${colors.textMuted}; }
        .ui-conv-bottom { display: flex; justify-content: space-between; align-items: center; margin-top: 4px; gap: 8px; }
        .ui-conv-preview { font-size: var(--text-xs); color: ${colors.textSecondary}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ui-badges { display: flex; gap: 4px; flex-shrink: 1; flex-wrap: wrap; }
        .ui-badge { font-size: var(--text-xs); font-weight: 600; padding: 2px 7px; border-radius: 9999px; white-space: nowrap; }
        .ui-waba-badge { border: 1px solid var(--border); background: var(--bg-secondary); color: var(--text-muted); }
        .ui-thread { border: 1px solid ${colors.border}; border-radius: 12px; display: flex; flex-direction: column; background: #fff; overflow: hidden; min-height: 0; min-width: 0; }
        .ui-thread-head { padding: 8px 10px; border-bottom: 1px solid ${colors.border}; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
        .ui-back { display: none; align-items: center; justify-content: center; width: 44px; height: 44px; min-width:44px; min-height:44px; border: 1px solid ${colors.border}; border-radius: 8px; background: #fff; color: ${colors.primary}; font-size: var(--h4); cursor: pointer; flex-shrink: 0; }
        .ui-thread-name { font-weight: 700; font-size: var(--text-md); color: ${colors.text}; }
        .ui-avatar { width: 38px; height: 38px; border-radius: 50%; background: ${colors.primary}; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: var(--text-sm); font-weight: 700; flex-shrink: 0; }
        .ui-thread-id { display: flex; flex: 1 1 170px; flex-direction: column; min-width: 0; }
        .ui-thread-sub { font-size: var(--text-xs); color: ${colors.textMuted}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ui-id-chip { display: inline-block; margin-left: 6px; font-size: var(--text-xs); font-weight: 600; color: ${colors.primary}; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 9999px; padding: 1px 7px; cursor: help; }
        .ui-icon-btn { display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; min-width:44px; min-height:44px; border: 1px solid ${colors.border}; border-radius: 8px; background: #fff; color: ${colors.primary}; cursor: pointer; flex-shrink: 0; }
        .ui-icon-btn:hover { background: ${colors.bgHover}; border-color: ${colors.primary}; }
        .ui-icon-danger { color: #b91c1c; }
        .ui-icon-danger:hover { background: #fef2f2; border-color: #b91c1c; }
        .ui-unread-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${colors.primary}; margin-right: 6px; vertical-align: middle; }
        .ui-conv.unread .ui-conv-name { font-weight: 800; }
        .ui-conv.unread { background: #f7fee7; }
        /* The six .ui-cat-* rules were here. They styled only the removed product picker,
           and nothing else in the tree references them. Lint does not flag dead CSS, so
           they would have survived the TSX deletion silently. */
        .ui-summarize { min-height:44px; display: inline-flex; align-items: center; gap: 5px; margin-left: auto; background: #f0fdf4; color: ${colors.primary}; border: 1px solid #bbf7d0; padding: 6px 12px; border-radius: 9px; font-size: var(--text-xs); font-weight: 600; cursor: pointer; }
        .ui-summarize:disabled { opacity: 0.6; cursor: not-allowed; }
        .ui-summary { display: flex; gap: 8px; align-items: flex-start; background: #faf5ff; border: 1px solid #e9d5ff; border-radius: 10px; padding: 10px 12px; margin: 8px 16px 0; }
        .ui-summary-text { font-size: var(--text-sm); color: ${colors.text}; white-space: pre-wrap; flex: 1; }
        .ui-summary-x { background: none; border: none; cursor: pointer; color: ${colors.textMuted}; }
        .ui-meta-bar { display: flex; gap: 8px; align-items: center; padding: 8px 16px; border-bottom: 1px solid ${colors.borderLight}; flex-wrap: wrap; }
        .ui-meta-status { padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: var(--text-xs); background: #fff; }
        .ui-meta-assignee { width: 130px; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: var(--text-xs); }
        .ui-meta-tags { flex: 1; min-width: 120px; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: var(--text-xs); }
        .ui-meta-notes-btn { min-height:44px; padding: 8px 12px; border: 1px solid ${colors.border}; border-radius: 8px; background: #fff; font-size: var(--text-xs); cursor: pointer; }
        .ui-notes { padding: 10px 16px; border-bottom: 1px solid ${colors.borderLight}; background: ${colors.bgSecondary}; display: flex; flex-direction: column; gap: 6px; max-height: 200px; overflow-y: auto; }
        .ui-note { display: flex; flex-direction: column; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 6px 10px; }
        .ui-note-text { font-size: var(--text-sm); color: ${colors.text}; }
        .ui-note-by { font-size: var(--text-xs); color: ${colors.textMuted}; margin-top: 2px; }
        .ui-note-add { display: flex; gap: 8px; }
        .ui-note-input { flex: 1; padding: 7px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: var(--text-sm); }
        .ui-note-btn { min-height:44px; padding: 8px 14px; background: ${colors.primary}; color: #fff; border: none; border-radius: 8px; font-size: var(--text-xs); font-weight: 600; cursor: pointer; }
        .ui-note-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .ui-thread-body { flex: 1; overflow-y: auto; scroll-behavior: smooth; padding: 12px; display: flex; flex-direction: column; gap: 8px; background: ${colors.bgSecondary}; min-height: 0; }
        .ui-msg { display: flex; }
        .ui-msg.out { justify-content: flex-end; }
        .ui-msg-bubble { max-width: min(90%, 760px); min-width: 0; box-sizing: border-box; background: #fff; border: 1px solid ${colors.border}; border-radius: 12px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
        .ui-msg.out .ui-msg-bubble { background: ${colors.lime}; border-color: ${colors.lime}; }
        .ui-msg-text { font-size: var(--text-md); color: ${colors.text}; white-space: pre-wrap; word-break: break-word; }
        /* Keep customer data accessible without stealing the viewport on every thread open. */
        .ui-customer-profile { flex: 0 0 auto; margin: 5px 10px; border: 1px solid ${colors.border}; border-radius: 8px; background: ${colors.bgSecondary}; overflow: hidden; }
        .ui-customer-profile-heading { padding: 7px 10px; font-size: var(--text-xs); font-weight: 700; color: ${colors.primary}; cursor: pointer; }
        .ui-customer-profile-heading:focus-visible, .ui-flow-summary:focus-visible, .ui-long-message > summary:focus-visible { outline: 2px solid ${colors.primary}; outline-offset: -2px; }
        .ui-customer-profile-scroll { overflow: auto; max-height: min(25dvh, 230px); border-top: 1px solid ${colors.borderLight}; }
        .ui-flow-response { width: 100%; min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
        .ui-flow-details { min-width: 0; }
        .ui-flow-summary { padding: 3px 0; cursor: pointer; font-size: var(--text-sm); line-height: 1.5; }
        .ui-flow-summary strong { font-weight: 700; }
        .ui-flow-count { display: block; color: ${colors.textMuted}; font-size: var(--text-xs); font-weight: 400; }
        .ui-flow-data { max-width: 100%; overflow-x: auto; padding-top: 6px; }
        .ui-long-message { width: 100%; min-width: 0; overflow-wrap: anywhere; }
        .ui-long-message > summary { padding: 2px 0; cursor: pointer; list-style: none; }
        .ui-long-message > summary::-webkit-details-marker { display: none; }
        .ui-long-preview { display: block; font-size: var(--text-md); color: ${colors.text}; white-space: pre-wrap; }
        .ui-long-more, .ui-long-less { display: block; margin-top: 5px; font-size: var(--text-xs); color: ${colors.primary}; font-weight: 700; text-decoration: underline; }
        .ui-long-less, .ui-long-message[open] .ui-long-preview, .ui-long-message[open] .ui-long-more { display: none; }
        .ui-long-message[open] .ui-long-less { display: block; }
        .ui-long-message > .ui-msg-text { display: block; padding-top: 4px; }
        .ui-msg-img { max-width: 220px; max-height: 220px; border-radius: 8px; object-fit: cover; }
        .ui-msg-doc { font-size: var(--text-sm); color: ${colors.primary}; text-decoration: none; font-weight: 600; }
        .ui-msg-transcript { font-size: var(--text-xs); color: ${colors.textSecondary}; font-style: italic; border-left: 2px solid ${colors.border}; padding-left: 6px; }
        .ui-react { display: flex; padding: 2px 0; }
        .ui-react.out { justify-content: flex-end; }
        .ui-react-pill { font-size: var(--text-xs); color: ${colors.textMuted}; background: ${colors.bgSecondary}; border: 1px solid ${colors.borderLight}; border-radius: 9999px; padding: 2px 10px; }
        .ui-msg-meta { font-size: var(--text-xs); color: ${colors.textMuted}; display: flex; align-items: center; gap: 8px; }
        .ui-st { font-weight: 600; }
        .ui-st-sent { color: ${colors.textMuted}; }
        /* Meta has acknowledged the send but has not yet reported it as sent.
           Dimmer than the sent tick on purpose: a weaker claim, not a failure. */
        .ui-st-accepted { color: ${colors.textMuted}; opacity: 0.65; }
        .ui-st-delivered { color: #2563eb; }
        .ui-st-read { color: #15803d; }
        .ui-st-failed { color: #b91c1c; cursor: help; }
        .ui-msg-act { background: none; border: none; cursor: pointer; font-size: var(--text-xs); opacity: 0.5; padding: 0 2px; }
        .ui-msg-act:hover { opacity: 1; }
        .ui-msg-act:disabled { opacity: 0.2; cursor: not-allowed; }
        .ui-load-more { align-self: center; background: #fff; border: 1px solid ${colors.border}; border-radius: 9999px; padding: 6px 16px; font-size: var(--text-xs); cursor: pointer; color: ${colors.textSecondary}; }
        .ui-load-more:hover { background: ${colors.bgHover}; }
        .ui-replying { display: flex; align-items: center; justify-content: space-between; background: ${colors.bgSecondary}; border-left: 3px solid ${colors.primary}; border-radius: 6px; padding: 6px 10px; }
        .ui-replying-text { font-size: var(--text-xs); color: ${colors.textSecondary}; }
        .ui-replying-x { background: none; border: none; cursor: pointer; color: ${colors.textMuted}; font-size: var(--text-xs); }
        .ui-wa-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
        .ui-wa-from { font-size: var(--text-xs); color: ${colors.textMuted}; }
        .ui-wa-waba { padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: var(--text-xs); background: #fff; }
        .ui-email-subject { flex: 1; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: var(--text-xs); }
        .ui-tpl-btn { margin-left: auto; padding: 6px 12px; border: 1px solid ${colors.border}; border-radius: 8px; background: #fff; font-size: var(--text-xs); font-weight: 600; cursor: pointer; color: ${colors.primary}; }
        .ui-tpl-list { max-height: 180px; overflow-y: auto; border: 1px solid ${colors.border}; border-radius: 10px; }
        .ui-tpl-item { display: flex; width: 100%; justify-content: space-between; align-items: center; padding: 8px 12px; border: none; border-bottom: 1px solid ${colors.borderLight}; background: #fff; cursor: pointer; text-align: left; }
        .ui-tpl-item:hover { background: ${colors.bgHover}; }
        .ui-tpl-name { font-size: var(--text-sm); font-weight: 600; color: ${colors.text}; }
        .ui-tpl-cat { font-size: var(--text-xs); color: ${colors.textMuted}; text-transform: capitalize; }
        .ui-tpl-empty { padding: 14px; text-align: center; font-size: var(--text-xs); color: ${colors.textMuted}; }
        .ui-fmt-hint { font-size: var(--text-xs); color: ${colors.textLight}; margin-right: auto; }
        .ui-ai-btn { display: inline-flex; align-items: center; gap: 5px; background: #f0fdf4; color: ${colors.primary}; border: 1px solid #bbf7d0; padding: 6px 11px; border-radius: 9px; font-size: var(--text-xs); font-weight: 600; cursor: pointer; }
        .ui-ai-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .ui-tool-btn { display: inline-flex; align-items: center; justify-content: center; background: #fff; border: 1px solid ${colors.border}; border-radius: 9px; padding: 7px; color: ${colors.primary}; cursor: pointer; }
        .ui-tool-btn:hover:not(:disabled) { background: ${colors.bgHover}; border-color: ${colors.primary}; }
        .ui-tool-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .ui-emoji-row { display: flex; gap: 4px; flex-wrap: wrap; padding: 6px 0; }
        .ui-emoji { background: ${colors.bgSecondary}; border: 1px solid ${colors.borderLight}; border-radius: 8px; padding: 4px 8px; font-size: var(--text-base); cursor: pointer; }
        .ui-emoji:hover { background: ${colors.bgActive}; }
        .ui-quick-list { display: flex; flex-direction: column; gap: 4px; max-height: 160px; overflow-y: auto; border: 1px solid ${colors.border}; border-radius: 10px; padding: 4px; }
        .ui-quick-item { text-align: left; background: ${colors.bgSecondary}; border: 1px solid ${colors.borderLight}; border-radius: 8px; padding: 6px 10px; font-size: var(--text-sm); color: ${colors.text}; cursor: pointer; }
        .ui-quick-item:hover { background: ${colors.bgActive}; }
        .ui-modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1410; padding: 20px; }
        .ui-modal { background: #fff; border-radius: 14px; max-width: 560px; width: 100%; max-height: 85vh; overflow-y: auto; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
        .ui-pay { padding: 20px; display: flex; flex-direction: column; gap: 12px; }
        .ui-pay-title { font-size: var(--text-base); font-weight: 700; color: ${colors.text}; }
        .ui-pay-in { width: 100%; padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: var(--text-md); font-family: inherit; }
        .ui-pay-in:focus { outline: none; border-color: ${colors.primary}; box-shadow: ${shadow.focus}; }
        .ui-pay-row { display: flex; gap: 10px; }
        .ui-pay-qty { max-width: 90px; }
        .ui-pay-total { font-size: var(--text-md); font-weight: 600; color: ${colors.primary}; }
        .ui-pay-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 4px; }
        .ui-pay-cancel { background: #fff; border: 1px solid ${colors.border}; border-radius: 10px; padding: 8px 16px; font-size: var(--text-sm); cursor: pointer; color: ${colors.textSecondary}; }
        .ui-pay-send { background: ${colors.primary}; color: #fff; border: none; border-radius: 10px; padding: 8px 18px; font-size: var(--text-sm); font-weight: 600; cursor: pointer; }
        .ui-pay-send:disabled { opacity: 0.5; cursor: not-allowed; }
        .ui-pay-label { font-size: var(--text-xs); font-weight: 600; color: ${colors.textMuted}; margin-top: 2px; }
        .ui-pay-lock { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .ui-pay-lock .ui-pay-in { flex: 1; }
        .ui-pay-unlock { background: ${colors.lime}; color: var(--accent); border: none; border-radius: 9px; padding: 8px 14px; font-size: var(--text-xs); font-weight: 600; cursor: pointer; }
        .ui-pay-err { color: #b91c1c; font-size: var(--text-xs); width: 100%; }
        .ui-pay-item { display: flex; flex-direction: column; gap: 6px; border: 1px dashed ${colors.borderLight}; border-radius: 10px; padding: 8px; }
        .ui-pay-gst { max-width: 110px; }
        .ui-pay-rm { background: #fff; border: 1px solid ${colors.border}; border-radius: 8px; padding: 0 10px; cursor: pointer; color: ${colors.textMuted}; }
        .ui-pay-additem { align-self: flex-start; background: #f0fdf4; color: ${colors.primary}; border: 1px solid #bbf7d0; border-radius: 9px; padding: 6px 12px; font-size: var(--text-xs); font-weight: 600; cursor: pointer; }
        .ui-tpl-preview { font-size: var(--text-sm); color: ${colors.textSecondary}; background: ${colors.bgSecondary}; border-radius: 8px; padding: 8px 10px; white-space: pre-wrap; }
        .ui-tpl-head { display: flex; gap: 8px; align-items: center; padding: 6px; border-bottom: 1px solid ${colors.borderLight}; }
        .ui-tpl-toggle { background: #fff; border: 1px solid ${colors.border}; border-radius: 8px; padding: 5px 10px; font-size: var(--text-xs); cursor: pointer; color: ${colors.primary}; }
        .ui-tpl-toggle.on { background: ${colors.lime}; color: var(--accent); border-color: ${colors.lime}; }
        .ui-tpl-newnum { flex: 1; padding: 6px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: var(--text-xs); }
        .ui-tpl-var { color: ${colors.primary}; font-weight: 600; }
        .ui-media-stage { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 4px 0; }
        .ui-media-thumb { width: 44px; height: 44px; object-fit: cover; border-radius: 8px; border: 1px solid ${colors.border}; }
        .ui-media-chip { display: inline-flex; align-items: center; gap: 6px; background: ${colors.bgSecondary}; border: 1px solid ${colors.borderLight}; border-radius: 9px; padding: 4px 8px; font-size: var(--text-xs); max-width: 220px; }
        .ui-media-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px; color: ${colors.text}; }
        .ui-media-size { color: ${colors.textMuted}; font-size: var(--text-xs); }
        .ui-media-x { background: none; border: none; cursor: pointer; color: ${colors.textMuted}; font-size: var(--text-xs); }
        .ui-emoji-pop { border: 1px solid ${colors.border}; border-radius: 10px; background: #fff; display: flex; flex-direction: column; max-height: 260px; }
        .ui-emoji-search { margin: 8px; padding: 7px 10px; border: 1px solid ${colors.border}; border-radius: 8px; font-size: var(--text-sm); }
        .ui-emoji-scroll { overflow-y: auto; padding: 0 8px 8px; }
        .ui-emoji-cat-label { font-size: var(--text-xs); font-weight: 700; color: ${colors.textMuted}; text-transform: uppercase; margin: 6px 2px 4px; }
        .ui-emoji-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(30px, 1fr)); gap: 2px; }
        /* The two rules that styled the on-demand transcribe button went with the button.
           Lint does not flag dead CSS, so an unreferenced rule has to be removed by hand.
           .ui-msg-transcript above STAYS: a transcription stored on the message is still shown. */
        .ui-react-wrap { position: relative; display: inline-flex; }
        .ui-react-pop { position: absolute; bottom: 130%; right: 0; display: flex; gap: 2px; background: #fff; border: 1px solid ${colors.border}; border-radius: 9999px; padding: 4px 6px; box-shadow: 0 4px 14px rgba(0,0,0,0.12); z-index: 20; }
        .ui-react-em { background: none; border: none; cursor: pointer; font-size: var(--text-base); padding: 2px; line-height: 1; }
        .ui-react-em:hover { transform: scale(1.25); }
        .ui-reply { padding: 8px 10px; border-top: 1px solid ${colors.border}; display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; }
        .ui-reply-input { width: 100%; resize: vertical; padding: 9px 12px; border: 1px solid ${colors.border}; border-radius: 10px; font-size: var(--text-md); font-family: inherit; }
        .ui-reply-input:focus { outline: none; border-color: ${colors.primary}; box-shadow: ${shadow.focus}; }
        .ui-reply-actions { display: flex; align-items: center; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
        .ui-tools { display: flex; align-items: center; gap: 6px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
        .ui-tools::-webkit-scrollbar { height: 6px; }
        .ui-send-row { display: flex; align-items: center; gap: 10px; }
        .ui-reply-via { font-size: var(--text-xs); font-weight: 600; padding: 3px 9px; border-radius: 9999px; margin-right: auto; }
        .ui-reply-link { font-size: var(--text-xs); color: ${colors.textMuted}; text-decoration: none; }
        .ui-reply-link:hover { color: ${colors.primary}; }
        .ui-reply-voice { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); color: ${colors.textMuted}; width: 100%; }
        .ui-reply-btn { background: ${colors.primary}; color: #fff; padding: 8px 18px; border: none; border-radius: 10px; font-size: var(--text-sm); font-weight: 600; cursor: pointer; }
        .ui-reply-btn:hover:not(:disabled) { background: ${colors.primaryHover}; }
        .ui-reply-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        /* Column, not row: the channel-filtered empty state is three lines and a
           button, and the original row layout laid them out side by side. Every
           single-line use of .ui-empty renders identically either way. */
        .ui-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; height: 100%; padding: 0 16px; text-align: center; line-height: 1.5; color: ${colors.textMuted}; font-size: var(--text-md); }
        .ui-link-btn { background: none; border: none; padding: 0; font: inherit; color: ${colors.primary}; text-decoration: underline; cursor: pointer; }
        .ui-link-btn:hover { color: ${colors.primaryHover}; }
        @media (max-width: 800px) {
          .ui-wrap {
            height: calc(100dvh - 56px - env(safe-area-inset-top,0px));
            padding:
              10px max(12px,env(safe-area-inset-right,0px))
              calc(76px + env(safe-area-inset-bottom,0px))
              max(12px,env(safe-area-inset-left,0px));
          }
          .ui-toolbar { margin: 8px 0; flex-wrap:wrap; }
          .ui-toolbar > * { min-width:0; }
          .ui-search { flex:1 1 180px; min-width:0; }
          .ui-panes { grid-template-columns: 1fr; height: calc(100dvh - 196px - env(safe-area-inset-bottom,0px)); min-height: 0; }
          /* Master/detail: show the list OR the thread, not both. */
          .ui-panes .ui-thread { display: none; }
          .ui-panes .ui-list { display: block; }
          .ui-panes.has-selection .ui-list { display: none; }
          .ui-panes.has-selection .ui-thread { display: flex; }
          .ui-back { display: inline-flex; }
          .ui-msg-bubble { max-width: 96%; }
          .ui-meta-bar { gap: 6px; padding-inline:12px; }
          .ui-meta-assignee, .ui-meta-tags { width: auto; flex: 1 1 120px; min-width: 0; }
          .ui-thread-head{padding:8px 10px}
          .ui-msg-bubble{overflow-wrap:anywhere;word-break:break-word}
          .ui-note-add{flex-wrap:wrap}
          .ui-note-input{flex:1 1 160px;min-width:0}
          .ui-pay-row{flex-wrap:wrap}
          .ui-pay-row > *{min-width:0}
        }
        /* Embedded workspaces can be narrow despite a wide browser viewport. */
        @container inbox (max-width: 860px) {
          .ui-panes { grid-template-columns: minmax(0, 1fr); }
          .ui-panes .ui-thread { display: none; }
          .ui-panes .ui-list { display: block; }
          .ui-panes.has-selection .ui-list { display: none; }
          .ui-panes.has-selection .ui-thread { display: flex; }
          .ui-back { display: inline-flex; }
        }
        @media(max-width:340px){
          .ui-wrap{padding-inline:8px}
          .ui-toolbar{gap:8px}
          .ui-search{flex-basis:100%}
          .ui-thread-head{gap:6px}
          .ui-avatar{width:34px;height:34px}
          .ui-msg-bubble{max-width:98%}
        }
      ` }</style>
        </>
    );

    return content;
};

export default UnifiedInbox;
