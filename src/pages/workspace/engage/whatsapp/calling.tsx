/**
 * WhatsApp Calling Page
 * WhatsApp Business Calling API — VoIP calls within WhatsApp threads
 * Signaling: Graph API + Webhooks (HTTPS) or SIP (TLS) | Media: WebRTC (OPUS)
 * Ref: https://developers.facebook.com/docs/whatsapp/cloud-api/calling
 */
import React, { useMemo, useState } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { acquireAudioStream } from '../../../../lib/pstn/mediaCapability';
import { safeHttpHref } from '../../../../lib/randomToken';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const PHONE_NUMBERS = [
  { id: 'phone-number-id-waba1-direct-1016149501586345', metaId: '1016149501586345', display: '+91 93309 94400', name: 'WECARE.DIGITAL', wabaId: '2094615664435155', country: 'IN', tier: 'TIER_1K', quality: 'GREEN', callingReady: true, directApi: true },
  { id: 'phone-number-id-waba-t-direct-1055232054343117', metaId: '1055232054343117', display: '+91 99033 00044', name: 'Manish Agarwal', wabaId: '2513394156072604', country: 'IN', tier: 'TIER_10K', quality: 'GREEN', callingReady: true, directApi: true },
];

const OUTBOUND_PHONE_OPTIONS: SelectOption[] = PHONE_NUMBERS.map( p => ( {
  value: p.metaId,
  label: `${ p.display } (${ p.name })`,
} ) );

// Webhook configuration — LIVE (Direct API, all WABAs use same endpoint)
const WEBHOOK_CONFIG = {
  callbackUrl: 'https://wecare.digital/api/whatsapp',
  subscribedFields: [ 'messages', 'calls' ],
  // `lambda` and `table` were here until 2026-09-23. Neither was ever rendered —
  // they were dead metadata shipping a function name and a table name into the
  // browser bundle. Infrastructure names belong on the Technical Details surfaces,
  // which are allowlisted in scripts/check_ui_labels.py.
  status: 'verified',
};

// Meta Access Token info — all WABAs use WECARE.DIGITAL app (Direct API)
const META_TOKEN = {
  appId: '2238810740192680',
  appName: 'WECARE.DIGITAL',
  secretName: 'wecare/meta-system-user-token',
  scopes: [ 'whatsapp_business_messaging', 'whatsapp_business_management', 'public_profile' ],
  wabaAccess: [ '2094615664435155', '2513394156072604' ],
  tokenType: 'System User',
  status: 'active',
};

// Signaling & Media configurations from Meta docs
const SIGNAL_CONFIGS = [
  { config: 'Default (after enabling)', signaling: 'Graph APIs + Webhooks', transport: 'HTTPS', media: 'WebRTC (ICE + DTLS + SRTP)', codec: 'OPUS' },
  { config: 'SIP with WebRTC', signaling: 'SIP (explicit enablement)', transport: 'TLS', media: 'WebRTC (ICE + DTLS + SRTP)', codec: 'OPUS' },
  { config: 'SIP with SDES media', signaling: 'SIP (explicit enablement)', transport: 'TLS', media: 'SDES SRTP (explicit enablement)', codec: 'OPUS' },
];

const SETUP_STEPS = [
  {
    step: 1, done: true,
    title: 'Prerequisites',
    desc: 'Cloud API ✓ | whatsapp_business_messaging permission ✓ | System User token created ✓ | +919330994400 TIER_2K+ ✓ calling enabled ✓ | +919903300044 TIER_10K ✓ calling enabled ✓',
  },
  {
    step: 2, done: true,
    title: 'Enable Calling on Phone Number',
    desc: 'POST to /{phone-number-id}/settings with the calling object. Configure call icon visibility, business call hours, and callback request settings.',
    code: `POST /{phone-number-id}/settings
{
  "calling": {
    "call_icon_visibility": "default",
    "call_hours": {
      "timezone": "Asia/Kolkata",
      "sun": [{ "from": "09:00", "to": "21:00" }],
      "mon": [{ "from": "09:00", "to": "21:00" }],
      "tue": [{ "from": "09:00", "to": "21:00" }],
      "wed": [{ "from": "09:00", "to": "21:00" }],
      "thu": [{ "from": "09:00", "to": "21:00" }],
      "fri": [{ "from": "09:00", "to": "21:00" }],
      "sat": [{ "from": "09:00", "to": "21:00" }]
    }
  }
}`,
  },
  {
    step: 3, done: false,
    title: 'Configure Call Control (Optional)',
    desc: 'Inbound call control: prevent users from placing calls. Business call hours: avoid missed calls, direct users to message when closed. Callback requests: offer users the option to request a callback when you don\'t pick up.',
    code: `// Disable inbound calls (outbound only)
POST /{phone-number-id}/settings
{ "calling": { "call_icon_visibility": "disable_all" } }

// Restrict call icon to specific countries
POST /{phone-number-id}/settings
{ "calling": { "restrict_to_user_countries": ["IN", "AE"] } }`,
  },
  {
    step: 4, done: false,
    title: 'Handle User-Initiated Calls (Inbound)',
    desc: 'When a user calls, you receive a "connect" webhook with SDP offer. Respond with pre-accept → accept (with SDP answer) to establish WebRTC media. If you don\'t respond, the call times out and you get a "terminate" webhook.',
    code: `// Webhook: call connection event
{
  "entry": [{
    "changes": [{
      "value": {
        "event": "connect",
        "call_id": "wamid.xxx",
        "from": "919330994400",
        "sdp_offer": "v=0\\r\\no=..."
      }
    }]
  }]
}

// Respond: pre-accept then accept
POST /{phone-number-id}/calls
{ "action": "pre_accept", "call_id": "wamid.xxx" }

POST /{phone-number-id}/calls
{ "action": "accept", "call_id": "wamid.xxx", "sdp_answer": "..." }`,
  },
  {
    step: 5, done: false,
    title: 'Request Call Permission (for Outbound)',
    desc: 'Send an interactive message with type "call_permission_request" or use a template. Limits: 1 request per 24h, 2 per 7 days per user. Once granted: up to 100 connected calls/day per user (updated Dec 2025).',
    code: `POST /{phone-number-id}/messages
{
  "messaging_product": "whatsapp",
  "to": "919330994400",
  "type": "interactive",
  "interactive": {
    "type": "call_permission_request",
    "body": { "text": "Can we call you to discuss your query?" }
  }
}`,
  },
  {
    step: 6, done: false,
    title: 'Make Business-Initiated Calls (Outbound)',
    desc: 'After permission is granted, initiate a call with an SDP offer. The user receives a ringing notification in WhatsApp. You get a "connect" webhook with their SDP answer when they pick up. Note: Business-initiated calling is NOT available in USA, Canada, Egypt, Vietnam, Nigeria.',
    code: `POST /{phone-number-id}/calls
{
  "action": "create",
  "to": "919330994400",
  "sdp_offer": "v=0\\r\\no=..."
}`,
  },
  {
    step: 7, done: false,
    title: 'Deploy Call Handler Lambda',
    desc: 'Lambda processes call webhooks (connect, terminate), manages WebRTC signaling, integrates Amazon Polly for IVR prompts, and logs calls to DynamoDB.',
  },
];

const AWS_RESOURCES = [
  { service: 'API Gateway', resource: 'wecare.digital/api', purpose: 'Webhook endpoint for Meta call events + messaging', status: 'active' },
  { service: 'Lambda', resource: 'wecare-whatsapp-calling', purpose: 'Unified webhook handler (calls + messages + all Meta events)', status: 'active' },
  { service: 'Lambda', resource: 'wecare-whatsapp-voice', purpose: 'TTS generation, media upload, audio messages', status: 'active' },
  { service: 'DynamoDB', resource: 'WhatsAppCallingTable', purpose: 'Call event logs (connect, terminate, permission)', status: 'active' },
  { service: 'DynamoDB', resource: 'WhatsAppVoiceTable', purpose: 'TTS logs, voice note logs', status: 'active' },
  { service: 'Amazon Polly', resource: 'SynthesizeSpeech', purpose: 'Neural TTS for IVR prompts and voice notes (OPUS)', status: 'active' },
  { service: 'S3', resource: 'wecare-digital-get/o/whatsapp-media/whatsapp-calling/', purpose: 'TTS audio files, call recordings', status: 'active' },
  { service: 'Secrets Manager', resource: 'wecare/meta-app-secret', purpose: 'Meta App Secret for webhook verification', status: 'active' },
];

const CALL_LIMITS = [
  { limit: 'Messaging limit required', value: '2,000+ business-initiated conversations / 24h rolling window' },
  { limit: 'Permission requests', value: '1 per 24h, 2 per 7 days per user' },
  { limit: 'Connected calls (after permission)', value: '100 per day per user (updated Dec 2025)' },
  { limit: 'Unanswered call threshold', value: '2 consecutive → warning, 4 consecutive → permission revoked' },
  { limit: 'Audio codec', value: 'OPUS (G.711 coming soon — Alpha for select partners)' },
  { limit: 'Call icon visibility', value: '"default" (show), "disable_all" (hide), or restrict_to_user_countries' },
  { limit: 'Signaling protocol', value: 'Graph API + Webhooks (HTTPS) or SIP (TLS)' },
  { limit: 'Media protocol', value: 'WebRTC (ICE + DTLS + SRTP) or SDES SRTP' },
];

const BLOCKED_COUNTRIES = [ 'USA', 'Canada', 'Egypt', 'Vietnam', 'Nigeria' ];

const CHANGELOG = [
  { date: 'Dec 19, 2025', title: 'Business-initiated call limit increased', desc: 'Up to 100 calls/day per user (from 10/day)' },
  { date: 'Dec 10, 2025', title: 'restrict_to_user_countries', desc: 'Control which countries see the call icon' },
  { date: 'Oct 13, 2025', title: 'Limit increase + Sandbox docs', desc: 'Calls increased to 10/day. Testing & Sandbox section added' },
  { date: 'Sep 29, 2025', title: 'Asterisk integration guide', desc: 'New guide to integrate with Asterisk PBX' },
  { date: 'Sep 24, 2025', title: 'Context propagation', desc: 'Opaque string in call buttons/deep links for tracking call origin' },
  { date: 'Sep 8, 2025', title: 'Health Status API update', desc: 'New can_receive_call_sip field for SIP setup diagnostics' },
  { date: 'Sep 5, 2025', title: 'Low call pickup restrictions', desc: 'Restrictions for low call pickup rates now in effect' },
  { date: 'Jul 21, 2025', title: 'Account settings webhooks', desc: 'Get webhooks when calling settings are updated' },
];

const WhatsAppCallingPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const [ activeTab, setActiveTab ] = useState<'overview' | 'live' | 'webhook' | 'setup' | 'resources' | 'settings'>( 'overview' );
  const [ expandedStep, setExpandedStep ] = useState<number | null>( null );
  const [ autoPickup, setAutoPickup ] = useState( true );
  const [ autoPickupLoading, setAutoPickupLoading ] = useState( false );
  const [ autoPickupMode, setAutoPickupMode ] = useState<'manual' | 'ivr'>( 'ivr' );
  const [ ivrUrl, setIvrUrl ] = useState( 'https://wecare.digital/get/o/stream/media/ivr/incoming_welcome.sln16' );
  // The only value ever placed in the Test Play `href`. `null` disables the control.
  // Derived here rather than at the JSX site so the check and the rendered string cannot
  // drift apart, which is the bug the previous version had.
  const ivrHref = useMemo( () => safeHttpHref( ivrUrl ), [ ivrUrl ] );

  // IVR SMS state
  const [ smsOnCall, setSmsOnCall ] = useState( true );
  // Post-call WhatsApp notification toggle. Sends plain text since 2026-10-02;
  // the wd_menu video template it used to send was deleted at Meta.
  const [ postCallWa, setPostCallWa ] = useState( true );

  // Auto 👍 reaction toggle (all messages, templates & call notifications)
  const [ autoThumb, setAutoThumb ] = useState( true );
  const [ smsTestPhone, setSmsTestPhone ] = useState( '+919903300044' );
  const [ smsTestSending, setSmsTestSending ] = useState<'idle' | 'aws'>( 'idle' );
  const [ smsTestResult, setSmsTestResult ] = useState<{ aws?: string } | null>( null );
  const [ activeCalls, setActiveCalls ] = useState<any[]>( [] );
  const [ callLogs, setCallLogs ] = useState<any[]>( [] );
  const [ loadingCalls, setLoadingCalls ] = useState( false );
  const toast = useToastContext();

  const API_BASE = 'https://wecare.digital/api';

  // Calling settings state
  const [ settingsPhone, setSettingsPhone ] = useState( PHONE_NUMBERS[ 1 ] ); // default to calling-ready number
  const [ callingVisibility, setCallingVisibility ] = useState<'default' | 'disable_all'>( 'default' );
  const [ restrictCountries, setRestrictCountries ] = useState( 'IN' );
  const [ audioCodecs, setAudioCodecs ] = useState<Array<'PCMA' | 'PCMU'>>( [] );
  const [ callbackPermission, setCallbackPermission ] = useState<'ENABLED' | 'DISABLED'>( 'ENABLED' );
  const [ voicemailJson, setVoicemailJson ] = useState( '' );
  const [ voicemailError, setVoicemailError ] = useState( '' );
  // Call hours are always disabled (24/7) — no UI state needed
  const [ savingSettings, setSavingSettings ] = useState( false );
  const [ callingSettingsResult, setCallingSettingsResult ] = useState<any>( null );
  const [ loadingSettings, setLoadingSettings ] = useState( false );

  // Outbound call state
  const [ outboundPhone, setOutboundPhone ] = useState( '' );
  const [ outboundPhoneNumberId, setOutboundPhoneNumberId ] = useState( PHONE_NUMBERS[ 1 ].metaId );
  const [ outboundPermissionText, setOutboundPermissionText ] = useState( 'Can we call you to discuss your query?' );
  const [ outboundStep, setOutboundStep ] = useState<'idle' | 'requesting_permission' | 'permission_sent' | 'calling' | 'connected' | 'ended' | 'failed'>( 'idle' );
  const [ outboundLoading, setOutboundLoading ] = useState( false );
  const [ outboundError, setOutboundError ] = useState( '' );
  const [ outboundCallDuration, setOutboundCallDuration ] = useState( 0 );
  const outboundDurationRef = React.useRef<ReturnType<typeof setInterval> | null>( null );
  const outboundPcRef = React.useRef<RTCPeerConnection | null>( null );
  const outboundStreamRef = React.useRef<MediaStream | null>( null );
  const [ outboundMuted, setOutboundMuted ] = useState( false );

  // Outbound: Request call permission
  const requestOutboundPermission = async () => {
    if ( !outboundPhone.trim() ) { toast.error( 'Enter a phone number' ); return; }
    setOutboundLoading( true );
    setOutboundError( '' );
    try
    {
      const res = await fetch( `${API_BASE}/whatsapp/outbound`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( {
          phoneNumberId: outboundPhoneNumberId,
          to: outboundPhone.trim(),
          action: 'permission_request',
          bodyText: outboundPermissionText,
        } ),
      } );
      const data = await res.json();
      const alreadyGranted = data?.result?.errorCode === 138017 || JSON.stringify( data?.result || '' ).includes( '138017' );
      if ( data.success || alreadyGranted )
      {
        setOutboundStep( 'permission_sent' );
        if ( alreadyGranted )
        {
          setOutboundPermStatus( 'permanent' );
          toast.success( 'Already approved by this user — you can Call Now' );
        } else
        {
          toast.success( 'Permission request sent — waiting for user to accept' );
        }
      } else
      {
        setOutboundError( JSON.stringify( data.error || data.result || 'Failed' ) );
        toast.error( 'Permission request failed' );
      }
    } catch ( e: any )
    {
      setOutboundError( e.message );
      toast.error( 'Permission request failed' );
    }
    setOutboundLoading( false );
  };

  // Outbound: Check current call-permission state for the target number
  const [ outboundPermStatus, setOutboundPermStatus ] = useState<string>( '' );
  const checkOutboundPermission = async () => {
    if ( !outboundPhone.trim() ) { toast.error( 'Enter a phone number' ); return; }
    setOutboundLoading( true );
    try
    {
      const res = await fetch( `${API_BASE}/whatsapp/outbound`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( {
          phoneNumberId: outboundPhoneNumberId,
          to: outboundPhone.trim(),
          action: 'check_permission',
        } ),
      } );
      const data = await res.json();
      const st = data.permissionStatus || 'no_permission';
      setOutboundPermStatus( st );
      if ( data.canCall || st === 'temporary' || st === 'permanent' )
      {
        toast.success( `Permission: ${st} — you can call now` );
      } else
      {
        toast.info( `Permission: ${st} — user has not granted call permission yet` );
      }
    } catch ( e: any )
    {
      toast.error( 'Failed to check permission' );
    }
    setOutboundLoading( false );
  };

  // Outbound: Send the approved call_permission_request TEMPLATE (works for cold numbers
  // outside the 24h customer service window). Template 'wd_call_permission' must be APPROVED.
  const sendPermissionTemplate = async () => {
    if ( !outboundPhone.trim() ) { toast.error( 'Enter a phone number' ); return; }
    setOutboundLoading( true );
    setOutboundError( '' );
    try
    {
      const res = await fetch( `${API_BASE}/whatsapp/outbound`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( {
          phoneNumberId: outboundPhoneNumberId,
          to: outboundPhone.trim(),
          action: 'send_permission_template',
          templateName: 'wd_call_permission',
        } ),
      } );
      const data = await res.json();
      const alreadyGranted = data?.result?.errorCode === 138017 || JSON.stringify( data?.result || '' ).includes( '138017' );
      if ( data.success || alreadyGranted )
      {
        setOutboundStep( 'permission_sent' );
        if ( alreadyGranted )
        {
          setOutboundPermStatus( 'permanent' );
          toast.success( 'Already approved by this user — you can Call Now' );
        } else
        {
          toast.success( 'Permission template sent — waiting for user to accept' );
        }
      } else
      {
        const detail = JSON.stringify( data.result || data.error || 'Failed' );
        setOutboundError( detail );
        toast.error( detail.includes( '132001' ) || detail.toLowerCase().includes( 'does not exist' )
          ? 'Template not approved yet — try again once wd_call_permission is approved'
          : 'Permission template failed' );
      }
    } catch ( e: any )
    {
      setOutboundError( e.message );
      toast.error( 'Permission template failed' );
    }
    setOutboundLoading( false );
  };

  // Outbound: Initiate call with WebRTC SDP offer
  const initiateOutboundCall = async () => {
    setOutboundLoading( true );
    setOutboundError( '' );
    setOutboundStep( 'calling' );
    try
    {
      // 1. Get microphone. Guarded, because an unguarded call in a container with
      // no navigator.mediaDevices throws a TypeError about reading a property of
      // undefined, and that string goes straight to setOutboundError.
      const stream = await acquireAudioStream( {
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      } );
      outboundStreamRef.current = stream;

      // 2. Create RTCPeerConnection
      const pc = new RTCPeerConnection( {
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' },
        ],
      } );
      outboundPcRef.current = pc;

      // Add audio tracks
      stream.getTracks().forEach( track => pc.addTrack( track, stream ) );

      // Handle remote audio
      pc.ontrack = ( event ) => {
        const audioEl = document.getElementById( 'remoteAudioOutbound' ) as HTMLAudioElement;
        if ( audioEl && event.streams[ 0 ] )
        {
          audioEl.srcObject = event.streams[ 0 ];
          audioEl.play().catch( () => { } );
        }
      };

      pc.onconnectionstatechange = () => {
        if ( pc.connectionState === 'connected' )
        {
          setOutboundStep( 'connected' );
          toast.success( 'Outbound call connected' );
          setOutboundCallDuration( 0 );
          outboundDurationRef.current = setInterval( () => setOutboundCallDuration( prev => prev + 1 ), 1000 );
        } else if ( pc.connectionState === 'failed' )
        {
          setOutboundStep( 'failed' );
          setOutboundError( 'WebRTC connection failed' );
          cleanupOutbound();
        }
      };

      // 3. Create SDP offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription( offer );

      // 4. Wait for ICE gathering
      const sdpOffer = await new Promise<string>( ( resolve ) => {
        if ( pc.iceGatheringState === 'complete' )
        {
          resolve( pc.localDescription?.sdp || offer.sdp || '' );
          return;
        }
        const timeout = setTimeout( () => resolve( pc.localDescription?.sdp || offer.sdp || '' ), 3000 );
        pc.onicegatheringstatechange = () => {
          if ( pc.iceGatheringState === 'complete' )
          {
            clearTimeout( timeout );
            resolve( pc.localDescription?.sdp || offer.sdp || '' );
          }
        };
      } );

      // 5. Send to backend → Meta
      const res = await fetch( `${API_BASE}/whatsapp/outbound`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( {
          phoneNumberId: outboundPhoneNumberId,
          to: outboundPhone.trim(),
          action: 'create',
          sdpOffer,
        } ),
      } );
      const data = await res.json();

      if ( !data.success )
      {
        throw new Error( JSON.stringify( data.error || data.result || 'Call initiation failed' ) );
      }

      toast.info( 'Calling... waiting for user to pick up' );
    } catch ( e: any )
    {
      setOutboundError( e.message );
      setOutboundStep( 'failed' );
      toast.error( `Outbound call failed: ${e.message}` );
      cleanupOutbound();
    }
    setOutboundLoading( false );
  };

  // Outbound: Hang up
  const hangupOutbound = async () => {
    try
    {
      // We don't have the call_id from Meta for outbound yet, so terminate via cleanup
      // If we had it, we'd POST to /hangup
      cleanupOutbound();
      setOutboundStep( 'ended' );
      toast.success( 'Outbound call ended' );
    } catch ( e: any )
    {
      toast.error( 'Failed to hang up' );
    }
  };

  // Outbound: Toggle mute
  const toggleOutboundMute = () => {
    if ( outboundStreamRef.current )
    {
      const track = outboundStreamRef.current.getAudioTracks()[ 0 ];
      if ( track )
      {
        track.enabled = !track.enabled;
        setOutboundMuted( !track.enabled );
      }
    }
  };

  // Outbound: Cleanup
  const cleanupOutbound = () => {
    if ( outboundPcRef.current ) { outboundPcRef.current.close(); outboundPcRef.current = null; }
    if ( outboundStreamRef.current ) { outboundStreamRef.current.getTracks().forEach( t => t.stop() ); outboundStreamRef.current = null; }
    if ( outboundDurationRef.current ) { clearInterval( outboundDurationRef.current ); outboundDurationRef.current = null; }
    const audioEl = document.getElementById( 'remoteAudioOutbound' ) as HTMLAudioElement;
    if ( audioEl ) audioEl.srcObject = null;
    setOutboundMuted( false );
  };

  // Outbound: Reset to idle
  const resetOutbound = () => {
    cleanupOutbound();
    setOutboundStep( 'idle' );
    setOutboundError( '' );
    setOutboundCallDuration( 0 );
  };

  // Format seconds to mm:ss
  const fmtDuration = ( sec: number ) => {
    const m = Math.floor( sec / 60 );
    const s = sec % 60;
    return `${m.toString().padStart( 2, '0' )}:${s.toString().padStart( 2, '0' )}`;
  };

  // Load calling settings for selected phone
  const loadCallingSettings = async () => {
    setLoadingSettings( true );
    try
    {
      const data = await api.getCallingSettings( settingsPhone.metaId );
      if ( data?.calling )
      {
        const c = data.calling;
        if ( c.call_icon_visibility ) setCallingVisibility( c.call_icon_visibility );
        if ( c.restrict_to_user_countries ) setRestrictCountries( c.restrict_to_user_countries.join( ', ' ) );
        if ( c.call_icons?.restrict_to_user_countries ) setRestrictCountries( c.call_icons.restrict_to_user_countries.join( ', ' ) );
        if ( c.audio?.additional_codecs ) setAudioCodecs( c.audio.additional_codecs.filter( ( x: string ) => x === 'PCMA' || x === 'PCMU' ) );
        if ( c.callback_permission_status ) setCallbackPermission( c.callback_permission_status );
        if ( c.voicemail ) setVoicemailJson( JSON.stringify( c.voicemail, null, 2 ) );
      }
      setCallingSettingsResult( data );
    } catch ( e ) { console.error( 'Load calling settings error:', e ); }
    setLoadingSettings( false );
  };

  // Save calling settings
  const saveCallingSettings = async () => {
    setSavingSettings( true );
    try
    {
      const settings: any = { callIconVisibility: callingVisibility };
      if ( restrictCountries.trim() )
      {
        settings.restrictToCountries = restrictCountries.split( ',' ).map( ( c: string ) => c.trim() ).filter( Boolean );
      }
      if ( audioCodecs.length ) settings.audioCodecs = audioCodecs;
      settings.callbackPermissionStatus = callbackPermission;
      // Voicemail (advanced passthrough): parse the raw JSON if provided.
      setVoicemailError( '' );
      if ( voicemailJson.trim() )
      {
        try
        {
          const parsed = JSON.parse( voicemailJson );
          if ( typeof parsed !== 'object' || Array.isArray( parsed ) || parsed === null )
          {
            setVoicemailError( 'Voicemail must be a JSON object' );
            toast.error( 'Voicemail must be a JSON object' );
            setSavingSettings( false );
            return;
          }
          settings.voicemail = parsed;
        } catch ( err )
        {
          setVoicemailError( 'Invalid JSON in voicemail config' );
          toast.error( 'Invalid JSON in voicemail config' );
          setSavingSettings( false );
          return;
        }
      }
      // Call hours disabled at Meta → calls accepted 24/7, every day.
      // Meta's schema still requires timezone_id + weekly_operating_hours even when DISABLED.
      settings.callHours = {
        status: 'DISABLED',
        timezone_id: 'Asia/Kolkata',
        weekly_operating_hours: [ 'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY' ]
          .map( d => ( { day_of_week: d, open_time: '0000', close_time: '2359' } ) ),
      };
      const ok = await api.updateCallingSettings( settingsPhone.metaId, settings );
      if ( ok ) { toast.success( 'Calling settings updated' ); loadCallingSettings(); }
      else toast.error( 'Failed to update calling settings' );
    } catch ( e ) { toast.error( 'Failed to update calling settings' ); }
    setSavingSettings( false );
  };

  // Load auto-pickup config
  const loadConfig = async () => {
    try
    {
      const res = await fetch( `${API_BASE}/whatsapp/config` );
      if ( res.ok )
      {
        const data = await res.json();
        setAutoPickup( data.autoPickup !== false ); // default true
        if ( data.ivrUrl ) setIvrUrl( data.ivrUrl );
        if ( data.autoPickupMode && [ 'manual', 'ivr' ].includes( data.autoPickupMode ) )
        {
          setAutoPickupMode( data.autoPickupMode );
        }
        if ( data.smsOnCall !== undefined ) setSmsOnCall( data.smsOnCall !== false );
        if ( data.postCallWa !== undefined ) setPostCallWa( data.postCallWa !== false );
        if ( data.autoThumb !== undefined ) setAutoThumb( data.autoThumb !== false );
      }
    } catch ( e ) { console.error( 'Config load error:', e ); }
  };

  // Toggle auto-pickup
  const toggleAutoPickup = async () => {
    setAutoPickupLoading( true );
    try
    {
      const newVal = !autoPickup;
      const res = await fetch( `${API_BASE}/whatsapp/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { autoPickup: newVal } ),
      } );
      if ( res.ok )
      {
        setAutoPickup( newVal );
        toast.success( `Auto-pickup ${newVal ? 'enabled' : 'disabled'}` );
      }
    } catch ( e ) { toast.error( 'Failed to update config' ); }
    setAutoPickupLoading( false );
  };

  // Send test IVR SMS
  // One provider, so no provider argument. The retired second branch posted a raw
  // DLT template id and sender header to select a prohibited provider; both the
  // provider choice and the raw regulatory ids are now resolved server-side from
  // a template key.
  const sendTestSms = async ( provider: 'aws' = 'aws' ) => {
    if ( !smsTestPhone ) { toast.error( 'Enter a phone number' ); return; }
    setSmsTestSending( provider );
    setSmsTestResult( prev => ( { ...prev, [ provider ]: undefined } ) );
    try
    {
      const endpoint = '/sms-aws/send';
      const body = {
        phoneNumber: smsTestPhone,
        content: "Thanks for contacting WECARE.DIGITAL!\n\nSubmit your request here: https://wecare.digital/submit-request/ or send us a message / voice note on WhatsApp: https://wecare.digital/r/wa.\n\nWe'll review it and follow up if needed.",
        messageType: 'TRANSACTIONAL',
        dltTemplateKey: 'ivr-default',
      };
      const res = await fetch( `${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( body ),
      } );
      const data = await res.json();
      if ( res.ok && ( data.success || data.messageId ) )
      {
        setSmsTestResult( prev => ( { ...prev, [ provider ]: `✓ Sent (${data.messageId || data.providerMessageId || 'ok'})` } ) );
        toast.success( 'Test SMS sent via AWS End User Messaging' );
      } else
      {
        setSmsTestResult( prev => ( { ...prev, [ provider ]: `✗ ${data.error || 'Failed'}` } ) );
        toast.error( `Test SMS failed: ${data.error || 'unknown'}` );
      }
    } catch ( e: any )
    {
      setSmsTestResult( prev => ( { ...prev, [ provider ]: `✗ ${e.message}` } ) );
      toast.error( `SMS error: ${e.message}` );
    }
    setSmsTestSending( 'idle' );
  };

  // Load active calls
  const loadActiveCalls = async () => {
    try
    {
      const res = await fetch( `${API_BASE}/whatsapp/active` );
      if ( res.ok )
      {
        const data = await res.json();
        setActiveCalls( data.calls || [] );
      }
    } catch ( e ) { console.error( 'Active calls error:', e ); }
  };

  // Load call logs
  const loadCallLogs = async () => {
    setLoadingCalls( true );
    try
    {
      const res = await fetch( `${API_BASE}/whatsapp/logs` );
      if ( res.ok )
      {
        const data = await res.json();
        setCallLogs( data.logs || [] );
      }
    } catch ( e ) { console.error( 'Logs error:', e ); }
    setLoadingCalls( false );
  };

  // Reject a ringing call
  const rejectCall = async ( callId: string, phoneNumberId: string ) => {
    try
    {
      await fetch( `${API_BASE}/whatsapp/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { callId, phoneNumberId } ),
      } );
      toast.success( 'Call rejected' );
      loadActiveCalls();
    } catch ( e ) { toast.error( 'Failed to reject call' ); }
  };

  // Hangup an active call
  const hangupCall = async ( callId: string, phoneNumberId: string ) => {
    try
    {
      await fetch( `${API_BASE}/whatsapp/hangup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { callId, phoneNumberId } ),
      } );
      toast.success( 'Call ended' );
      loadActiveCalls();
    } catch ( e ) { toast.error( 'Failed to hang up' ); }
  };

  // WebRTC state
  const peerConnectionRef = React.useRef<RTCPeerConnection | null>( null );
  const localStreamRef = React.useRef<MediaStream | null>( null );

  // Answer a call using WebRTC — sets up peer connection, generates SDP answer, sends to backend
  const answerCallWebRTC = async ( call: any ) => {
    const { callId, phoneNumberId, sdpOffer } = call;

    if ( !sdpOffer )
    {
      // No SDP in the call record — just do server-side accept (auto-pickup style)
      toast.info( 'No SDP offer available — sending server-side accept' );
      try
      {
        const res = await fetch( `${API_BASE}/whatsapp/accept`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( { callId, phoneNumberId, sdpAnswer: '' } ),
        } );
        const data = await res.json();
        if ( data.success ) toast.success( 'Call accepted (server-side)' );
        else toast.error( `Accept failed: ${JSON.stringify( data.error || data )}` );
      } catch ( e ) { toast.error( 'Failed to accept call' ); }
      loadActiveCalls();
      return;
    }

    try
    {
      // 1. Get microphone access
      toast.info( 'Requesting microphone access...' );
      const localStream = await acquireAudioStream( { audio: true } );
      localStreamRef.current = localStream;

      // 2. Create RTCPeerConnection
      const pc = new RTCPeerConnection( {
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' },
        ],
      } );
      peerConnectionRef.current = pc;

      // 3. Add local audio tracks
      localStream.getTracks().forEach( track => pc.addTrack( track, localStream ) );

      // 4. Handle remote audio stream
      pc.ontrack = ( event ) => {
        const audioEl = document.getElementById( 'remoteAudio' ) as HTMLAudioElement;
        if ( audioEl && event.streams[ 0 ] )
        {
          audioEl.srcObject = event.streams[ 0 ];
        }
      };

      // 5. Log ICE candidates
      pc.onicecandidate = ( event ) => {
        if ( event.candidate )
        {
          console.log( 'ICE candidate:', event.candidate.candidate );
        }
      };

      pc.onconnectionstatechange = () => {
        console.log( 'WebRTC connection state:', pc.connectionState );
        if ( pc.connectionState === 'connected' )
        {
          toast.success( 'WebRTC audio connected' );
        } else if ( pc.connectionState === 'failed' || pc.connectionState === 'disconnected' )
        {
          toast.error( `WebRTC ${pc.connectionState}` );
        }
      };

      // 6. Set remote description (SDP offer from Meta)
      await pc.setRemoteDescription( { type: 'offer', sdp: sdpOffer } );

      // 7. Create SDP answer
      const answer = await pc.createAnswer();
      await pc.setLocalDescription( answer );

      // 8. Wait for ICE gathering to complete (or timeout after 3s)
      const sdpAnswer = await new Promise<string>( ( resolve ) => {
        if ( pc.iceGatheringState === 'complete' )
        {
          resolve( pc.localDescription?.sdp || answer.sdp || '' );
          return;
        }
        const timeout = setTimeout( () => resolve( pc.localDescription?.sdp || answer.sdp || '' ), 3000 );
        pc.onicegatheringstatechange = () => {
          if ( pc.iceGatheringState === 'complete' )
          {
            clearTimeout( timeout );
            resolve( pc.localDescription?.sdp || answer.sdp || '' );
          }
        };
      } );

      // 9. Send pre_accept + accept with SDP answer to backend → Meta
      toast.info( 'Sending SDP answer to Meta...' );
      const res = await fetch( `${API_BASE}/whatsapp/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { callId, phoneNumberId, sdpAnswer } ),
      } );
      const data = await res.json();

      if ( data.success )
      {
        toast.success( 'Call connected — audio active' );
      } else
      {
        toast.error( `Accept failed: ${data.step || 'unknown'} — ${data.hint || JSON.stringify( data.error || {} )}` );
        cleanupWebRTC();
      }
      loadActiveCalls();

    } catch ( err: any )
    {
      console.error( 'WebRTC answer error:', err );
      toast.error( `WebRTC error: ${err.message || err}` );
      cleanupWebRTC();
    }
  };

  // Cleanup WebRTC resources
  const cleanupWebRTC = () => {
    if ( peerConnectionRef.current )
    {
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;
    }
    if ( localStreamRef.current )
    {
      localStreamRef.current.getTracks().forEach( t => t.stop() );
      localStreamRef.current = null;
    }
    const audioEl = document.getElementById( 'remoteAudio' ) as HTMLAudioElement;
    if ( audioEl ) audioEl.srcObject = null;
  };

  // Track which calls we've already auto-answered to avoid duplicates
  const autoAnsweredRef = React.useRef<Set<string>>( new Set() );

  // Helper: play audio URL into a WebRTC peer connection's audio track
  const playAudioIntoPeer = ( pc: RTCPeerConnection, audioUrl: string ): Promise<void> => {
    return new Promise( ( resolve, reject ) => {
      const audio = new Audio();
      audio.crossOrigin = 'anonymous';
      audio.src = audioUrl;
      const ctx = new AudioContext();
      audio.oncanplaythrough = () => {
        try
        {
          const source = ctx.createMediaElementSource( audio );
          const dest = ctx.createMediaStreamDestination();
          source.connect( dest );
          // Replace the silent/mic track with the audio track
          const audioTrack = dest.stream.getAudioTracks()[ 0 ];
          const sender = pc.getSenders().find( s => s.track?.kind === 'audio' );
          if ( sender && audioTrack ) sender.replaceTrack( audioTrack );
          audio.play();
          audio.onended = () => { ctx.close(); resolve(); };
        } catch ( e ) { reject( e ); }
      };
      audio.onerror = () => reject( new Error( 'Failed to load audio' ) );
      // Timeout after 30s
      setTimeout( () => { audio.pause(); ctx.close(); resolve(); }, 30000 );
    } );
  };

  // Auto-answer: when autoPickup is ON and a ringing call with SDP arrives, answer it automatically
  const autoAnswerCall = React.useCallback( async ( call: any ) => {
    const { callId, phoneNumberId, sdpOffer } = call;
    if ( !callId || !phoneNumberId || !sdpOffer ) return;
    if ( autoAnsweredRef.current.has( callId ) ) return;
    autoAnsweredRef.current.add( callId );

    const mode = autoPickupMode;
    console.log( `[AUTO-ANSWER] mode=${mode} call=${callId} from=${call.fromNumber || 'unknown'}` );
    toast.info( `Auto-answering (${mode}) call from ${call.callerName || call.fromNumber || 'unknown'}...` );

    try
    {
      // 1. Get microphone or create silent stream
      let localStream: MediaStream;
      try
      {
        localStream = await navigator.mediaDevices.getUserMedia( { audio: true } );
      } catch
      {
        const ctx = new AudioContext();
        const oscillator = ctx.createOscillator();
        oscillator.frequency.value = 0; // silent
        const dest = ctx.createMediaStreamDestination();
        oscillator.connect( dest );
        oscillator.start();
        localStream = dest.stream;
      }
      localStreamRef.current = localStream;

      // 2. Create RTCPeerConnection
      const pc = new RTCPeerConnection( {
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' },
        ],
      } );
      peerConnectionRef.current = pc;

      // 3. Add local audio tracks
      localStream.getTracks().forEach( track => pc.addTrack( track, localStream ) );

      // 4. Handle remote audio
      pc.ontrack = ( event ) => {
        const audioEl = document.getElementById( 'remoteAudio' ) as HTMLAudioElement;
        if ( audioEl && event.streams[ 0 ] ) audioEl.srcObject = event.streams[ 0 ];
      };

      pc.onconnectionstatechange = () => {
        console.log( `[AUTO-ANSWER] WebRTC state: ${pc.connectionState}` );
      };

      // 5. Set remote SDP offer
      await pc.setRemoteDescription( { type: 'offer', sdp: sdpOffer } );

      // 6. Create SDP answer
      const answer = await pc.createAnswer();
      await pc.setLocalDescription( answer );

      // 7. Wait for ICE gathering (max 3s)
      const sdpAnswer = await new Promise<string>( ( resolve ) => {
        if ( pc.iceGatheringState === 'complete' )
        {
          resolve( pc.localDescription?.sdp || answer.sdp || '' );
          return;
        }
        const timeout = setTimeout( () => resolve( pc.localDescription?.sdp || answer.sdp || '' ), 3000 );
        pc.onicegatheringstatechange = () => {
          if ( pc.iceGatheringState === 'complete' )
          {
            clearTimeout( timeout );
            resolve( pc.localDescription?.sdp || answer.sdp || '' );
          }
        };
      } );

      // 8. Send accept with SDP answer
      const res = await fetch( `${API_BASE}/whatsapp/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify( { callId, phoneNumberId, sdpAnswer } ),
      } );
      const data = await res.json();

      if ( !data.success )
      {
        toast.error( `Auto-answer failed: ${data.step || 'unknown'}` );
        cleanupWebRTC();
        autoAnsweredRef.current.delete( callId );
        return;
      }

      toast.success( `Call connected (${mode} mode)` );

      // 9. Mode-specific behavior after call is connected
      if ( mode === 'ivr' )
      {
        // IVR mode: play greeting audio → hang up
        try
        {
          await playAudioIntoPeer( pc, ivrUrl );
          toast.info( 'IVR audio finished — disconnecting' );
        } catch ( e )
        {
          console.error( '[IVR] Audio play error:', e );
        }
        // Hang up after audio
        await fetch( `${API_BASE}/whatsapp/hangup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( { callId, phoneNumberId } ),
        } );
        cleanupWebRTC();
        toast.info( 'IVR call completed' );

      }
      // mode === 'manual': just connect, don't play anything — human takes over

    } catch ( err: any )
    {
      console.error( '[AUTO-ANSWER] Error:', err );
      toast.error( `Auto-answer error: ${err.message || err}` );
      cleanupWebRTC();
      autoAnsweredRef.current.delete( callId );
    }
  }, [ autoPickupMode, ivrUrl ] );

  // Load on mount + poll active calls every 5s when on Live tab
  // When autoPickup is ON, auto-answer ringing calls with SDP offers
  React.useEffect( () => {
    loadConfig();
    loadCallLogs();
    return () => { cleanupWebRTC(); cleanupOutbound(); };
  }, [] );

  React.useEffect( () => {
    if ( activeTab === 'live' )
    {
      loadActiveCalls();
      const interval = setInterval( async () => {
        try
        {
          const res = await fetch( `${API_BASE}/whatsapp/active` );
          if ( res.ok )
          {
            const data = await res.json();
            const calls = data.calls || [];
            setActiveCalls( calls );

            // Auto-answer: if enabled, pick up ringing calls with SDP offers
            if ( autoPickup )
            {
              const ringing = calls.filter(
                ( c: any ) => ( c.status === 'ringing' || c.status === 'pre_accepted' ) && c.sdpOffer && !autoAnsweredRef.current.has( c.callId )
              );
              if ( ringing.length > 0 )
              {
                autoAnswerCall( ringing[ 0 ] ); // answer one at a time
              }
            }
          }
        } catch ( e ) { console.error( 'Active calls poll error:', e ); }
      }, 3000 ); // poll every 3s for faster pickup
      return () => clearInterval( interval );
    }
  }, [ activeTab, autoPickup, autoAnswerCall ] );

  const copyCode = ( code: string ) => {
    navigator.clipboard.writeText( code );
    toast.success( 'Copied to clipboard' );
  };

  const s = {
    page: { padding: '24px', maxWidth: '1400px', margin: '0 auto', background: '#fff' } as React.CSSProperties,
    header: {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' as const,
      marginBottom: '24px', padding: '20px 24px', gap: '12px',
      background: 'linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%)',
      borderRadius: '12px', border: '1px solid #e5e7eb',
    } as React.CSSProperties,
    tabs: {
      display: 'flex', gap: '4px', marginBottom: '20px', background: '#f9fafb',
      padding: '4px', borderRadius: '10px', border: '1px solid #f3f4f6', flexWrap: 'wrap' as const,
    } as React.CSSProperties,
    card: {
      background: '#fff', border: '1px solid #e5e7eb', borderRadius: '10px',
      padding: '16px 20px', marginBottom: '12px',
    } as React.CSSProperties,
  };

  const tab = ( active: boolean ): React.CSSProperties => ( {
    padding: '8px 20px', border: 'none', borderRadius: '8px', cursor: 'pointer',
    fontSize: '13px', fontWeight: active ? 600 : 500,
    background: active ? '#1a3a2a' : 'transparent', color: active ? '#fff' : '#0f2a1d',
  } );

  const badge = ( status: string ): React.CSSProperties => ( {
    display: 'inline-block', padding: '2px 10px', borderRadius: '12px', fontSize: '11px', fontWeight: 600,
    background: status === 'active' || status === 'available' ? '#f9fafb' : status === 'planned' ? '#f9fafb' : '#f3f4f6',
    color: status === 'active' || status === 'available' ? '#0f2a1d' : status === 'planned' ? '#0f2a1d' : '#6b7280',
    border: `1px solid ${status === 'active' || status === 'available' ? '#e5e7eb' : status === 'planned' ? '#e5e7eb' : '#e5e7eb'}`,
  } );

  const thStyle: React.CSSProperties = { padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: '#374151', fontSize: '12px', whiteSpace: 'nowrap' };
  const tdStyle: React.CSSProperties = { padding: '8px 12px', fontSize: '12px', color: '#6b7280' };

  const content = (
    <>
      <SEO title="WhatsApp Calling" description="WhatsApp Business Calling API" />
      <div style={ s.page }>
        {/* Header */ }
        <div style={ s.header }>
          <div>
            <h2 style={ { margin: 0, fontSize: '20px', color: '#0f2a1d' } }>WhatsApp Business Calling</h2>
            <p style={ { margin: '6px 0 0', fontSize: '13px', color: '#0f2a1d' } }>
              VoIP calls in WhatsApp threads — Graph API/SIP signaling + WebRTC media (OPUS) + Amazon Polly IVR
            </p>
          </div>
          <span style={ badge( 'active' ) }>Webhook Deployed</span>
        </div>

        {/* Tabs */ }
        <div style={ s.tabs }>
          <button style={ tab( activeTab === 'overview' ) } onClick={ () => setActiveTab( 'overview' ) }>Overview</button>
          <button style={ tab( activeTab === 'live' ) } onClick={ () => setActiveTab( 'live' ) }>Live Calls</button>
          <button style={ tab( activeTab === 'webhook' ) } onClick={ () => setActiveTab( 'webhook' ) }>Webhook Config</button>
          <button style={ tab( activeTab === 'setup' ) } onClick={ () => setActiveTab( 'setup' ) }>Setup Guide</button>
          <button style={ tab( activeTab === 'resources' ) } onClick={ () => setActiveTab( 'resources' ) }>AWS Resources</button>
          <button style={ tab( activeTab === 'settings' ) } onClick={ () => { setActiveTab( 'settings' ); loadCallingSettings(); } }>Calling Settings</button>
        </div>

        {/* LIVE CALLS TAB — WebRTC Call Handling */ }
        { activeTab === 'live' && (
          <div>
            {/* Auto-pickup toggle */ }
            <div style={ { ...s.card, background: '#f9fafb', border: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' } }>
              <div>
                <h3 style={ { margin: 0, fontSize: '15px', color: '#0f2a1d' } }>Live Call Dashboard</h3>
                <p style={ { margin: '4px 0 0', fontSize: '12px', color: '#0f2a1d' } }>
                  Auto-pickup is ON by default. Incoming calls are answered, IVR plays, then disconnects.
                </p>
              </div>
              <div style={ { display: 'flex', alignItems: 'center', gap: '12px' } }>
                <button onClick={ loadActiveCalls } style={ { padding: '6px 14px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                  Refresh
                </button>
                <label style={ { display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#0f2a1d', cursor: 'pointer' } }>
                  <input type="checkbox" checked={ autoPickup } onChange={ toggleAutoPickup } disabled={ autoPickupLoading }
                    style={ { width: '16px', height: '16px', accentColor: '#1a3a2a' } } />
                  Auto-pickup
                </label>
              </div>
            </div>

            {/* Auto-pickup Mode Selector */ }
            { autoPickup && (
              <div style={ { ...s.card, marginTop: '12px', border: '1px solid #e5e7eb', background: '#f9fafb' } }>
                <div style={ { display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' } }>
                  <label style={ { fontSize: '13px', fontWeight: 600, color: '#0f2a1d' } }>Auto-pickup Mode:</label>
                  { ( [
                    { value: 'manual' as const, label: 'Manual', desc: 'Connect call, human answers' },
                    { value: 'ivr' as const, label: 'IVR', desc: 'Play audio greeting, then hang up' },
                  ] ).map( ( m ) => (
                    <button key={ m.value } onClick={ async () => {
                      setAutoPickupMode( m.value );
                      try
                      {
                        await fetch( `${API_BASE}/whatsapp/config`, {
                          method: 'POST', headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify( { autoPickupMode: m.value } ),
                        } );
                        toast.success( `Mode: ${m.label}` );
                      } catch { toast.error( 'Failed to save mode' ); }
                    } } style={ {
                      padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600,
                      border: autoPickupMode === m.value ? '2px solid #1a3a2a' : '1px solid #d1d5db',
                      background: autoPickupMode === m.value ? '#f9fafb' : '#fff',
                      color: autoPickupMode === m.value ? '#0f2a1d' : '#374151',
                    } } title={ m.desc }>
                      { m.label }
                    </button>
                  ) ) }
                  <span style={ { fontSize: '11px', color: '#6b7280', marginLeft: '4px' } }>
                    { autoPickupMode === 'manual' ? 'Call connects, you talk' : 'Plays IVR audio → disconnects' }
                  </span>
                </div>
              </div>
            ) }

            {/* IVR Audio Config */ }
            <div style={ { ...s.card, marginTop: '12px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' } }>
              <div style={ { flex: 1, minWidth: '200px' } }>
                <label style={ { display: 'block', fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '4px' } }>IVR Audio URL</label>
                <input value={ ivrUrl } onChange={ e => setIvrUrl( e.target.value ) } placeholder="https://wecare.digital/get/o/stream/media/ivr/incoming_welcome.sln16"
                  style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: '8px', fontSize: '12px', fontFamily: 'monospace' } } />
              </div>
              <div style={ { display: 'flex', gap: '8px', alignItems: 'flex-end', paddingTop: '18px' } }>
                <button onClick={ async () => {
                  try
                  {
                    const res = await fetch( `${API_BASE}/whatsapp/config`, {
                      method: 'POST', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify( { ivrUrl } ),
                    } );
                    if ( res.ok ) toast.success( 'IVR URL saved' );
                    else toast.error( 'Failed to save IVR URL' );
                  } catch ( e ) { toast.error( 'Failed to save IVR URL' ); }
                } } style={ { padding: '8px 14px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                  Save URL
                </button>
                {/* `ivrUrl` is typed by an operator and persisted, so `javascript:alert(1)`
                    here would execute on click for whoever opened the page next — a stored
                    XSS, which is what CodeQL's `js/xss-through-dom` was pointing at.
                    The href is now the value `safeHttpHref` returned, not the raw input:
                    the previous version checked one string and rendered another, which
                    meant `//evil.com` passed the check (it resolved against a base) and
                    then rendered as a protocol-relative link. A non-http(s) value renders
                    as a disabled span rather than vanishing, so a mistyped URL is visible
                    instead of silently doing nothing. */}
                { ivrHref
                  ? <a href={ ivrHref } target="_blank" rel="noopener noreferrer"
                    style={ { padding: '8px 14px', background: '#f3f4f6', border: '1px solid #e5e7eb', borderRadius: '8px', fontSize: '12px', textDecoration: 'none', color: '#374151' } }>
                    ▶ Test Play
                  </a>
                  : <span title="Enter an absolute http(s) URL to enable playback"
                    style={ { padding: '8px 14px', background: '#f3f4f6', border: '1px solid #e5e7eb', borderRadius: '8px', fontSize: '12px', color: '#9ca3af', cursor: 'not-allowed' } }>
                    ▶ Test Play
                  </span> }
              </div>
            </div>

            {/* IVR SMS Configuration + Test */ }
            <div style={ { ...s.card, marginTop: '12px', border: '1px solid #e5e7eb', background: '#f9fafb' } }>
              <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' } }>
                <h4 style={ { margin: 0, fontSize: '13px', color: '#0f2a1d' } }>IVR SMS (sent once on incoming call, 10-min dedup)</h4>
                <label style={ { display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#374151', cursor: 'pointer' } }>
                  <input type="checkbox" checked={ smsOnCall } onChange={ async () => {
                    const newVal = !smsOnCall;
                    setSmsOnCall( newVal );
                    try
                    {
                      await fetch( `${API_BASE}/whatsapp/config`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify( { smsOnCall: newVal } ),
                      } );
                      toast.success( `SMS on call ${newVal ? 'enabled' : 'disabled'}` );
                    } catch { toast.error( 'Failed to save' ); }
                  } }
                    style={ { width: '14px', height: '14px', accentColor: '#1a3a2a' } } />
                  SMS on call
                </label>
              </div>
              <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' } }>
                <div style={ { background: '#fff', padding: '10px', borderRadius: '6px', border: '1px solid #e5e7eb' } }>
                  <div style={ { fontWeight: 600, color: '#1a1a1a', marginBottom: '4px' } }>🇮🇳 Indian Numbers (+91)</div>
                  <div style={ { color: '#6b7280', fontSize: '11px' } }>AWS End User Messaging, ap-south-1</div>
                  <div style={ { color: '#6b7280', fontSize: '11px' } }>Sender: WDBEEP (DLT-registered)</div>
                  <div style={ { color: '#6b7280', fontSize: '11px' } }>Template key: ivr-default</div>
                  <div style={ { color: '#6b7280', fontSize: '11px' } }>Lambda: wecare-sms-aws</div>
                  <span style={ { display: 'inline-block', marginTop: '4px', padding: '2px 6px', background: '#dcfce7', color: '#166534', borderRadius: '4px', fontSize: '10px' } }>TRAI DLT ENFORCED</span>
                </div>
                <div style={ { background: '#fff', padding: '10px', borderRadius: '6px', border: '1px solid #e5e7eb' } }>
                  <div style={ { fontWeight: 600, color: '#1a1a1a', marginBottom: '4px' } }>🌍 International Numbers</div>
                  <div style={ { color: '#6b7280', fontSize: '11px' } }>AWS End User Messaging, us-east-1</div>
                  <div style={ { color: '#6b7280', fontSize: '11px' } }>Origination: pinned toll-free identity</div>
                  <div style={ { color: '#6b7280', fontSize: '11px' } }>Lambda: wecare-sms-aws</div>
                  <span style={ { display: 'inline-block', marginTop: '4px', padding: '2px 6px', background: '#dbeafe', color: '#1e40af', borderRadius: '4px', fontSize: '10px' } }>NO DLT FIELDS</span>
                </div>
              </div>
              <div style={ { marginTop: '8px', padding: '8px', background: '#fff', borderRadius: '6px', border: '1px solid #e5e7eb', fontFamily: 'monospace', fontSize: '11px', color: '#374151', whiteSpace: 'pre-line' } }>
                { `Thanks for contacting WECARE.DIGITAL!\n\nSubmit your request here: https://wecare.digital/submit-request/ or send us a message / voice note on WhatsApp: https://wecare.digital/r/wa.\n\nWe'll review it and follow up if needed.` }
              </div>
              {/* Test SMS Controls */ }
              <div style={ { marginTop: '10px', padding: '10px', background: '#fff', borderRadius: '6px', border: '1px solid #e5e7eb' } }>
                <div style={ { fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '6px' } }>Send Test SMS</div>
                <div style={ { display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' } }>
                  <input value={ smsTestPhone } onChange={ e => setSmsTestPhone( e.target.value ) } placeholder="+919903300044"
                    style={ { flex: 1, minWidth: '160px', padding: '6px 10px', border: '1px solid #d1d5db', borderRadius: '6px', fontSize: '12px', fontFamily: 'monospace' } } />
                  <button onClick={ () => sendTestSms() } disabled={ smsTestSending !== 'idle' }
                    style={ { padding: '6px 12px', background: '#dbeafe', border: '1px solid #93c5fd', borderRadius: '6px', fontSize: '11px', fontWeight: 600, color: '#1e40af', cursor: 'pointer' } }>
                    { smsTestSending === 'aws' ? '...' : 'Send test SMS' }
                  </button>
                </div>
                { smsTestResult?.aws && (
                  <div style={ { marginTop: '6px', fontSize: '11px', fontFamily: 'monospace' } }>
                    <div style={ { color: smsTestResult.aws.startsWith( '✓' ) ? '#1e40af' : '#dc2626' } }>{ smsTestResult.aws }</div>
                  </div>
                ) }
              </div>
            </div>

            {/* Post-call WhatsApp notification toggle */ }
            <div style={ { ...s.card, marginTop: '12px', border: '1px solid #e5e7eb', background: '#f9fafb' } }>
              <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between' } }>
                <div>
                  <h4 style={ { margin: 0, fontSize: '13px', color: '#0f2a1d' } }>Post-call WhatsApp message</h4>
                  <p style={ { margin: '4px 0 0', fontSize: '11px', color: '#6b7280' } }>After a call ends, send a short WhatsApp follow-up message. Disable to skip the post-call WhatsApp follow-up.</p>
                </div>
                <label style={ { display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#374151', cursor: 'pointer', whiteSpace: 'nowrap' } }>
                  <input type="checkbox" checked={ postCallWa } onChange={ async () => {
                    const newVal = !postCallWa;
                    setPostCallWa( newVal );
                    try
                    {
                      await fetch( `${API_BASE}/whatsapp/config`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify( { postCallWa: newVal } ),
                      } );
                      toast.success( `Post-call WhatsApp ${newVal ? 'enabled' : 'disabled'}` );
                    } catch { toast.error( 'Failed to save' ); }
                  } }
                    style={ { width: '14px', height: '14px', accentColor: '#1a3a2a' } } />
                  Post-call WhatsApp
                </label>
              </div>
            </div>

            {/* Auto 👍 reaction toggle (global: all messages, templates & calls) */ }
            <div style={ { ...s.card, marginTop: '12px', border: '1px solid #e5e7eb', background: '#f9fafb' } }>
              <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between' } }>
                <div>
                  <h4 style={ { margin: 0, fontSize: '13px', color: '#0f2a1d' } }>Auto 👍 reaction</h4>
                  <p style={ { margin: '4px 0 0', fontSize: '11px', color: '#6b7280' } }>Send a thumbs-up reaction on every WhatsApp message and template — inbound (received), outbound (sent), and call notifications — from the same number. Applies across both WABA numbers. Changes take effect within ~5 minutes.</p>
                </div>
                <label style={ { display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#374151', cursor: 'pointer', whiteSpace: 'nowrap' } }>
                  <input type="checkbox" checked={ autoThumb } onChange={ async () => {
                    const newVal = !autoThumb;
                    setAutoThumb( newVal );
                    try
                    {
                      await fetch( `${API_BASE}/whatsapp/config`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify( { autoThumb: newVal } ),
                      } );
                      toast.success( `Auto 👍 reaction ${newVal ? 'enabled' : 'disabled'}` );
                    } catch { toast.error( 'Failed to save' ); }
                  } }
                    style={ { width: '14px', height: '14px', accentColor: '#1a3a2a' } } />
                  Auto 👍
                </label>
              </div>
            </div>
            <div style={ { ...s.card, marginTop: '12px' } }>
              <h4 style={ { margin: '0 0 12px', fontSize: '14px', color: '#1a1a1a' } }>
                Active Calls { activeCalls.length > 0 && <span style={ { ...badge( 'active' ), marginLeft: '8px' } }>{ activeCalls.length }</span> }
              </h4>
              { activeCalls.length === 0 ? (
                <div style={ { textAlign: 'center', padding: '32px 16px', color: '#9ca3af' } }>
                  <div style={ { fontSize: '36px', marginBottom: '8px' } }>-</div>
                  <p style={ { margin: 0, fontSize: '14px' } }>No active calls</p>
                  <p style={ { margin: '4px 0 0', fontSize: '12px' } }>Incoming calls will appear here when a user calls your WhatsApp number</p>
                </div>
              ) : (
                <div style={ { display: 'flex', flexDirection: 'column', gap: '10px' } }>
                  { activeCalls.map( ( call: any, i: number ) => (
                    <div key={ call.callId || i } style={ {
                      padding: '14px 16px', borderRadius: '10px',
                      background: call.status === 'ringing' ? '#f9fafb' : call.status === 'connected' ? '#f9fafb' : '#f3f4f6',
                      border: `1px solid ${call.status === 'ringing' ? '#e5e7eb' : call.status === 'connected' ? '#e5e7eb' : '#e5e7eb'}`,
                    } }>
                      <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' } }>
                        <div>
                          <span style={ { fontWeight: 600, fontSize: '14px', color: '#1a1a1a' } }>
                            { call.callerName || call.fromNumber || 'Unknown' }
                          </span>
                          { call.callerName && <span style={ { fontSize: '12px', color: '#6b7280', marginLeft: '8px' } }>{ call.fromNumber }</span> }
                          { call.fromBsuid && <span style={ { fontSize: '11px', color: '#9ca3af', marginLeft: '6px' } } title={ `BSUID: ${call.fromBsuid}` }>🆔</span> }
                          <span style={ { ...badge( call.status === 'ringing' ? 'planned' : call.status === 'connected' ? 'active' : 'default' ), marginLeft: '8px' } }>
                            { call.status === 'ringing' ? 'Ringing' : call.status === 'connected' ? 'Connected' : call.status }
                          </span>
                        </div>
                        <div style={ { display: 'flex', gap: '8px' } }>
                          { call.status === 'ringing' && (
                            <>
                              <button onClick={ () => answerCallWebRTC( call ) }
                                style={ { padding: '6px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                                Answer
                              </button>
                              <button onClick={ () => rejectCall( call.callId, call.phoneNumberId ) }
                                style={ { padding: '6px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                                Reject
                              </button>
                            </>
                          ) }
                          { call.status === 'connected' && (
                            <button onClick={ () => { hangupCall( call.callId, call.phoneNumberId ); cleanupWebRTC(); } }
                              style={ { padding: '6px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                              Hang Up
                            </button>
                          ) }
                        </div>
                      </div>
                      <div style={ { marginTop: '6px', fontSize: '11px', color: '#6b7280' } }>
                        Call ID: <code style={ { fontSize: '10px' } }>{ call.callId }</code>
                        { call.displayPhone && <> | To: { call.displayPhone }</> }
                        { call.direction && <> | { call.direction }</> }
                        { call.timestamp && <> | { new Date( parseInt( call.timestamp ) * 1000 ).toLocaleTimeString() }</> }
                      </div>
                    </div>
                  ) ) }
                </div>
              ) }
            </div>

            {/* Outbound Call — Business-Initiated */ }
            <div style={ { ...s.card, marginTop: '12px', border: '1px solid #e5e7eb', background: outboundStep === 'connected' ? '#f9fafb' : outboundStep === 'calling' ? '#f9fafb' : '#f9fafb' } }>
              <h4 style={ { margin: '0 0 12px', fontSize: '14px', color: '#0f2a1d' } }>Outbound Call (Business-Initiated)</h4>

              { outboundStep === 'idle' && (
                <div>
                  <p style={ { margin: '0 0 12px', fontSize: '12px', color: '#6b7280' } }>
                    Step 1: Get call permission. Step 2: After user accepts, initiate the call with WebRTC.
                    Use <strong>Request Permission</strong> if the user messaged you in the last 24h, or <strong>Send Template</strong> for brand-new numbers (needs the approved <code>wd_call_permission</code> template).
                    Limits: 1 permission request per 24h, 2 per 7 days per user. Not available in USA, Canada, Egypt, Vietnam, Nigeria.
                  </p>
                  <div style={ { display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'flex-end' } }>
                    <div style={ { flex: '0 0 180px' } }>
                      <label style={ { display: 'block', fontSize: '11px', fontWeight: 600, color: '#374151', marginBottom: '4px' } }>From (WABA Number)</label>
                      <Select ariaLabel="From (WABA Number)" value={ outboundPhoneNumberId }
                        onChange={ v => setOutboundPhoneNumberId( v ) }
                        options={ OUTBOUND_PHONE_OPTIONS } />
                    </div>
                    <div style={ { flex: '1 1 200px' } }>
                      <label style={ { display: 'block', fontSize: '11px', fontWeight: 600, color: '#374151', marginBottom: '4px' } }>To (WhatsApp Number with country code)</label>
                      <input value={ outboundPhone } onChange={ e => setOutboundPhone( e.target.value ) } placeholder="919876543210"
                        style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: '8px', fontSize: '13px', fontFamily: 'monospace' } } />
                    </div>
                    <div style={ { flex: '1 1 250px' } }>
                      <label style={ { display: 'block', fontSize: '11px', fontWeight: 600, color: '#374151', marginBottom: '4px' } }>Permission Message</label>
                      <input value={ outboundPermissionText } onChange={ e => setOutboundPermissionText( e.target.value ) }
                        style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: '8px', fontSize: '12px' } } />
                    </div>
                    <button onClick={ requestOutboundPermission } disabled={ outboundLoading || !outboundPhone.trim() }
                      style={ { padding: '8px 18px', background: outboundPhone.trim() ? '#1a3a2a' : '#d1d5db', color: '#fff', border: 'none', borderRadius: '8px', cursor: outboundPhone.trim() ? 'pointer' : 'not-allowed', fontSize: '12px', fontWeight: 600, whiteSpace: 'nowrap' } }>
                      { outboundLoading ? 'Sending...' : 'Request Permission' }
                    </button>
                    <button onClick={ sendPermissionTemplate } disabled={ outboundLoading || !outboundPhone.trim() } title="For brand-new numbers outside the 24h window (uses approved wd_call_permission template)"
                      style={ { padding: '8px 18px', background: '#fff', color: '#1a3a2a', border: '1px solid #1a3a2a', borderRadius: '8px', cursor: outboundPhone.trim() ? 'pointer' : 'not-allowed', fontSize: '12px', fontWeight: 600, whiteSpace: 'nowrap' } }>
                      { outboundLoading ? '...' : 'Send Template' }
                    </button>
                  </div>
                </div>
              ) }

              { outboundStep === 'permission_sent' && (
                <div>
                  <div style={ { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' } }>
                    <span style={ { fontSize: '20px' } }>-</span>
                    <div>
                      <div style={ { fontWeight: 600, fontSize: '14px', color: '#0f2a1d' } }>Permission request sent to { outboundPhone }</div>
                      <div style={ { fontSize: '12px', color: '#6b7280', marginTop: '2px' } }>
                        Waiting for user to tap &quot;Allow&quot; in WhatsApp. Once granted, click &quot;Call Now&quot; to initiate.
                      </div>
                    </div>
                  </div>
                  <div style={ { display: 'flex', gap: '8px' } }>
                    <button onClick={ initiateOutboundCall } disabled={ outboundLoading }
                      style={ { padding: '8px 20px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 } }>
                      { outboundLoading ? 'Connecting...' : 'Call Now' }
                    </button>
                    <button onClick={ checkOutboundPermission } disabled={ outboundLoading }
                      style={ { padding: '8px 16px', background: '#fff', color: '#1a3a2a', border: '1px solid #1a3a2a', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                      Check permission
                    </button>
                    <button onClick={ resetOutbound }
                      style={ { padding: '8px 16px', background: '#f3f4f6', color: '#374151', border: '1px solid #e5e7eb', borderRadius: '8px', cursor: 'pointer', fontSize: '12px' } }>
                      Cancel
                    </button>
                  </div>
                  { outboundPermStatus && (
                    <div style={ { marginTop: '8px', fontSize: '12px', color: ( outboundPermStatus === 'temporary' || outboundPermStatus === 'permanent' ) ? '#166534' : '#92400e' } }>
                      Permission status: <strong>{ outboundPermStatus }</strong>
                      { outboundPermStatus === 'no_permission' && ' — ask the user to tap Allow, or have them call/message you first.' }
                    </div>
                  ) }
                </div>
              ) }

              { outboundStep === 'calling' && (
                <div style={ { display: 'flex', alignItems: 'center', gap: '12px' } }>
                  <span style={ { fontSize: '24px' } }>-</span>
                  <div style={ { flex: 1 } }>
                    <div style={ { fontWeight: 600, fontSize: '14px', color: '#0f2a1d' } }>Calling { outboundPhone }...</div>
                    <div style={ { fontSize: '12px', color: '#6b7280' } }>Ringing — waiting for user to pick up</div>
                  </div>
                  <button onClick={ hangupOutbound }
                    style={ { padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                    Cancel
                  </button>
                </div>
              ) }

              { outboundStep === 'connected' && (
                <div>
                  <div style={ { display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '10px' } }>
                    <span style={ { fontSize: '24px' } }>-</span>
                    <div style={ { flex: 1 } }>
                      <div style={ { fontWeight: 600, fontSize: '14px', color: '#0f2a1d' } }>Connected to { outboundPhone }</div>
                      <div style={ { fontSize: '20px', fontWeight: 700, color: '#1a1a1a', fontFamily: 'monospace' } }>{ fmtDuration( outboundCallDuration ) }</div>
                    </div>
                    <div style={ { display: 'flex', gap: '8px' } }>
                      <button onClick={ toggleOutboundMute }
                        style={ { padding: '8px 14px', background: outboundMuted ? '#f9fafb' : '#f3f4f6', color: outboundMuted ? '#0f2a1d' : '#374151', border: `1px solid ${outboundMuted ? '#e5e7eb' : '#e5e7eb'}`, borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                        { outboundMuted ? 'Unmute' : 'Mute' }
                      </button>
                      <button onClick={ hangupOutbound }
                        style={ { padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                        Hang Up
                      </button>
                    </div>
                  </div>
                </div>
              ) }

              { ( outboundStep === 'ended' || outboundStep === 'failed' ) && (
                <div style={ { display: 'flex', alignItems: 'center', gap: '12px' } }>
                  <span style={ { fontSize: '20px' } }>{ outboundStep === 'ended' ? 'Done' : 'Failed' }</span>
                  <div style={ { flex: 1 } }>
                    <div style={ { fontWeight: 600, fontSize: '14px', color: outboundStep === 'ended' ? '#0f2a1d' : '#0f2a1d' } }>
                      { outboundStep === 'ended' ? 'Call ended' : 'Call failed' }
                    </div>
                    { outboundError && <div style={ { fontSize: '12px', color: '#1a3a2a', marginTop: '2px', wordBreak: 'break-all' } }>{ outboundError }</div> }
                    { outboundCallDuration > 0 && <div style={ { fontSize: '12px', color: '#6b7280' } }>Duration: { fmtDuration( outboundCallDuration ) }</div> }
                  </div>
                  <button onClick={ resetOutbound }
                    style={ { padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 } }>
                    New Call
                  </button>
                </div>
              ) }

              { outboundError && outboundStep !== 'ended' && outboundStep !== 'failed' && (
                <div style={ { marginTop: '8px', padding: '8px 12px', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '8px', fontSize: '12px', color: '#0f2a1d', wordBreak: 'break-all' } }>
                  { outboundError }
                </div>
              ) }

              {/* Hidden audio element for outbound remote stream */ }
              <audio id="remoteAudioOutbound" autoPlay style={ { display: 'none' } } />
            </div>

            {/* WebRTC Status */ }
            <div style={ { ...s.card, marginTop: '12px' } }>
              <h4 style={ { margin: '0 0 10px', fontSize: '14px', color: '#1a1a1a' } }>WebRTC Status</h4>
              <div style={ { fontSize: '13px', color: '#6b7280', lineHeight: 1.8 } }>
                <div>Browser WebRTC: <span style={ { color: typeof window !== 'undefined' && ( window as any ).RTCPeerConnection ? '#1a3a2a' : '#1a3a2a', fontWeight: 600 } }>
                  { typeof window !== 'undefined' && ( window as any ).RTCPeerConnection ? '✓ Supported' : '✗ Not supported' }
                </span></div>
                <div>Microphone: <span style={ { fontWeight: 500 } }>Will request permission when answering a call</span></div>
                <div>Audio codec: <span style={ { fontWeight: 500 } }>OPUS (required by Meta)</span></div>
                <div>ICE servers: <span style={ { fontFamily: 'monospace', fontSize: '12px' } }>stun:stun.l.google.com:19302</span></div>
              </div>
              {/* Hidden audio element for remote stream */ }
              <audio id="remoteAudio" autoPlay style={ { display: 'none' } } />
            </div>

            {/* Recent Call Logs */ }
            <div style={ { ...s.card, marginTop: '12px' } }>
              <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' } }>
                <h4 style={ { margin: 0, fontSize: '14px', color: '#1a1a1a' } }>Recent Call Logs</h4>
                <button onClick={ loadCallLogs } style={ { padding: '4px 12px', background: '#f3f4f6', border: '1px solid #e5e7eb', borderRadius: '6px', cursor: 'pointer', fontSize: '11px' } }>
                  { loadingCalls ? 'Loading...' : 'Refresh' }
                </button>
              </div>
              { callLogs.length === 0 ? (
                <p style={ { margin: 0, fontSize: '13px', color: '#9ca3af', textAlign: 'center', padding: '16px' } }>No call logs yet</p>
              ) : (
                <div style={ { overflowX: 'auto' } }>
                  <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '12px' } }>
                    <thead>
                      <tr style={ { background: '#f9fafb', borderBottom: '2px solid #e5e7eb' } }>
                        <th style={ thStyle }>Time</th>
                        <th style={ thStyle }>From</th>
                        <th style={ thStyle }>BSUID</th>
                        <th style={ thStyle }>Event</th>
                        <th style={ thStyle }>Status</th>
                        <th style={ thStyle }>Reason</th>
                        <th style={ thStyle }>Duration</th>
                      </tr>
                    </thead>
                    <tbody>
                      { callLogs.slice( 0, 20 ).map( ( log: any, i: number ) => (
                        <tr key={ log.id || i } style={ { borderBottom: '1px solid #f3f4f6' } }>
                          <td style={ { ...tdStyle, whiteSpace: 'nowrap' } }>
                            { log.createdAt ? new Date( parseFloat( log.createdAt ) * 1000 ).toLocaleString() : '-' }
                          </td>
                          <td style={ tdStyle }>{ log.callerName || log.fromNumber || '-' }{ log.callerUsername ? ` (${log.callerUsername})` : '' }</td>
                          <td style={ { ...tdStyle, fontSize: '11px', color: '#6b7280', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' } } title={ log.fromBsuid || '' }>{ log.fromBsuid || '-' }</td>
                          <td style={ tdStyle }>{ log.eventType || '-' }</td>
                          <td style={ tdStyle }>
                            <span style={ badge( log.status === 'connected' ? 'active' : log.status === 'ringing' ? 'planned' : 'default' ) }>
                              { log.status || '-' }
                            </span>
                          </td>
                          <td style={ { ...tdStyle, fontSize: '11px', color: log.errorCode ? '#dc2626' : '#6b7280' } } title={ log.errorCode ? `Meta error ${log.errorCode}` : '' }>
                            { log.terminateReason || log.errorCode || '-' }
                          </td>
                          <td style={ tdStyle }>{ log.duration ? `${log.duration}s` : '-' }</td>
                        </tr>
                      ) ) }
                    </tbody>
                  </table>
                </div>
              ) }
            </div>
          </div>
        ) }

        {/* OVERVIEW TAB */ }
        { activeTab === 'overview' && (
          <div>
            <div style={ { ...s.card, background: '#f9fafb', border: '1px solid #e5e7eb' } }>
              <h3 style={ { margin: '0 0 8px', fontSize: '15px', color: '#0f2a1d' } }>How it works</h3>
              <p style={ { margin: 0, fontSize: '13px', color: '#0f2a1d', lineHeight: 1.6 } }>
                The WhatsApp Business Calling API (launched July 2025) enables bidirectional VoIP calls
                within WhatsApp conversation threads. Default signaling uses Graph APIs + HTTPS webhooks.
                SIP signaling is available with explicit enablement. Media uses WebRTC with OPUS codec
                (G.711 coming soon). Calls appear in the same chat thread as messages.
              </p>
            </div>

            {/* Signaling Configurations Table */ }
            <div style={ { ...s.card, marginTop: '16px' } }>
              <h4 style={ { margin: '0 0 10px', fontSize: '14px', color: '#1a1a1a' } }>Signaling & Media Configurations</h4>
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '12px' } }>
                  <thead>
                    <tr style={ { background: '#f9fafb', borderBottom: '2px solid #e5e7eb' } }>
                      <th style={ thStyle }>Configuration</th>
                      <th style={ thStyle }>Signaling</th>
                      <th style={ thStyle }>Transport</th>
                      <th style={ thStyle }>Media</th>
                      <th style={ thStyle }>Codec</th>
                    </tr>
                  </thead>
                  <tbody>
                    { SIGNAL_CONFIGS.map( ( c, i ) => (
                      <tr key={ i } style={ { borderBottom: '1px solid #f3f4f6' } }>
                        <td style={ { ...tdStyle, fontWeight: 500, color: '#1a1a1a' } }>{ c.config }</td>
                        <td style={ tdStyle }>{ c.signaling }</td>
                        <td style={ tdStyle }>{ c.transport }</td>
                        <td style={ { ...tdStyle, fontFamily: 'monospace', fontSize: '11px' } }>{ c.media }</td>
                        <td style={ tdStyle }>{ c.codec }</td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
              <p style={ { margin: '8px 0 0', fontSize: '11px', color: '#9ca3af' } }>
                Note: You can use SDES instead of ICE+DTLS with Graph API + Webhook signaling too.
              </p>
            </div>

            {/* Call Flow Diagram */ }
            <div style={ { ...s.card, marginTop: '16px' } }>
              <h4 style={ { margin: '0 0 12px', fontSize: '14px', color: '#1a1a1a' } }>Call Flow (User-Initiated)</h4>
              <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px' } }>
                { [
                  { icon: 'Call', label: 'User calls', desc: 'User taps call icon in WhatsApp' },
                  { icon: 'Hook', label: 'Webhook: connect', desc: 'Meta sends call event + SDP offer' },
                  { icon: 'OK', label: 'Pre-accept → Accept', desc: 'Business responds with SDP answer' },
                  { icon: 'RTC', label: 'WebRTC call', desc: 'Audio via OPUS codec' },
                  { icon: 'End', label: 'Webhook: terminate', desc: 'Call ends, log to DynamoDB' },
                ].map( ( f, i ) => (
                  <div key={ i } style={ { padding: '12px', background: '#f9fafb', borderRadius: '8px', textAlign: 'center' } }>
                    <div style={ { fontSize: '24px', marginBottom: '6px' } }>{ f.icon }</div>
                    <div style={ { fontWeight: 600, fontSize: '12px', color: '#1a1a1a', marginBottom: '2px' } }>{ f.label }</div>
                    <div style={ { fontSize: '11px', color: '#6b7280' } }>{ f.desc }</div>
                  </div>
                ) ) }
              </div>
            </div>

            {/* Limits */ }
            <div style={ { ...s.card, marginTop: '16px' } }>
              <h4 style={ { margin: '0 0 10px', fontSize: '14px', color: '#1a1a1a' } }>Limits & Configuration</h4>
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '13px' } }>
                  <tbody>
                    { CALL_LIMITS.map( ( l, i ) => (
                      <tr key={ i } style={ { borderBottom: '1px solid #f3f4f6' } }>
                        <td style={ { padding: '8px 12px', fontWeight: 500, color: '#374151', whiteSpace: 'nowrap' } }>{ l.limit }</td>
                        <td style={ { padding: '8px 12px', color: '#6b7280', fontFamily: 'monospace', fontSize: '12px' } }>{ l.value }</td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            </div>

            {/* Availability */ }
            <div style={ { ...s.card, marginTop: '16px' } }>
              <h4 style={ { margin: '0 0 8px', fontSize: '14px', color: '#1a1a1a' } }>Availability</h4>
              <div style={ { fontSize: '13px', color: '#6b7280', lineHeight: 1.6 } }>
                <p style={ { margin: '0 0 8px' } }>
                  <span style={ { fontWeight: 500, color: '#0f2a1d' } }>User-initiated calling:</span> Available everywhere Cloud API is available.
                </p>
                <p style={ { margin: '0 0 8px' } }>
                  <span style={ { fontWeight: 500, color: '#0f2a1d' } }>Business-initiated calling:</span> Available everywhere Cloud API is available, except:
                </p>
                <div style={ { display: 'flex', gap: '6px', flexWrap: 'wrap' } }>
                  { BLOCKED_COUNTRIES.map( ( c, i ) => (
                    <span key={ i } style={ { padding: '2px 10px', background: '#f9fafb', color: '#0f2a1d', borderRadius: '12px', fontSize: '11px', fontWeight: 500, border: '1px solid #e5e7eb' } }>{ c }</span>
                  ) ) }
                </div>
                <p style={ { margin: '8px 0 0', fontSize: '12px', color: '#9ca3af' } }>
                  The business phone number&apos;s country code must be in the supported list. Consumer phone can be from any Cloud API country.
                  Our numbers (+91) are eligible for both user-initiated and business-initiated calling.
                </p>
              </div>
            </div>

            {/* Phone Numbers */ }
            <div style={ { ...s.card, marginTop: '16px' } }>
              <h4 style={ { margin: '0 0 10px', fontSize: '14px', color: '#1a1a1a' } }>WABA Phone Numbers</h4>
              { PHONE_NUMBERS.map( ( p, i ) => (
                <div key={ i } style={ { display: 'flex', alignItems: 'center', gap: '12px', padding: '8px 0', borderBottom: i < PHONE_NUMBERS.length - 1 ? '1px solid #f3f4f6' : 'none', flexWrap: 'wrap' } }>
                  <span style={ { fontWeight: 600, fontSize: '14px', color: '#1a1a1a' } }>{ p.display }</span>
                  <span style={ { fontSize: '12px', color: '#6b7280' } }>{ p.name }</span>
                  <span style={ badge( 'available' ) }>{ p.country }</span>
                  <span style={ { ...badge( p.quality === 'GREEN' ? 'active' : 'planned' ), fontSize: '10px' } }>Quality: { p.quality }</span>
                  <span style={ { ...badge( p.tier === 'TIER_10K' || p.tier === 'TIER_UNLIMITED' ? 'active' : 'planned' ), fontSize: '10px' } }>Tier: { p.tier }</span>
                  <span style={ { ...badge( p.callingReady ? 'active' : 'planned' ), fontSize: '10px' } }>{ p.callingReady ? 'Calling Ready' : 'Needs 2K Tier' }</span>
                  <code style={ { fontSize: '10px', color: '#9ca3af', marginLeft: 'auto', wordBreak: 'break-all' } }>Meta: { p.metaId }</code>
                </div>
              ) ) }
            </div>

            {/* Changelog */ }
            <div style={ { ...s.card, marginTop: '16px' } }>
              <h4 style={ { margin: '0 0 10px', fontSize: '14px', color: '#1a1a1a' } }>Changelog (Meta)</h4>
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '12px' } }>
                  <thead>
                    <tr style={ { background: '#f9fafb', borderBottom: '2px solid #e5e7eb' } }>
                      <th style={ { ...thStyle, width: '110px' } }>Date</th>
                      <th style={ thStyle }>Update</th>
                      <th style={ thStyle }>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    { CHANGELOG.map( ( c, i ) => (
                      <tr key={ i } style={ { borderBottom: '1px solid #f3f4f6' } }>
                        <td style={ { ...tdStyle, whiteSpace: 'nowrap', fontWeight: 500, color: '#374151' } }>{ c.date }</td>
                        <td style={ { ...tdStyle, fontWeight: 500, color: '#1a1a1a' } }>{ c.title }</td>
                        <td style={ tdStyle }>{ c.desc }</td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            </div>

            {/* Docs */ }
            <div style={ { ...s.card, marginTop: '16px' } }>
              <h4 style={ { margin: '0 0 8px', fontSize: '14px', color: '#1a1a1a' } }>Documentation</h4>
              <div style={ { display: 'flex', gap: '16px', flexWrap: 'wrap' } }>
                { [
                  { label: 'Meta Calling API', url: 'https://developers.facebook.com/docs/whatsapp/cloud-api/calling' },
                  { label: 'Getting Started (Access Token)', url: 'https://developers.facebook.com/docs/business-messaging/whatsapp/get-started' },
                  { label: 'Webhooks Overview', url: 'https://developers.facebook.com/docs/business-messaging/whatsapp/webhooks/overview' },
                  { label: 'User-Initiated Calls', url: 'https://developers.facebook.com/docs/whatsapp/cloud-api/calling/receive-calls' },
                  { label: 'Business-Initiated Calls', url: 'https://developers.facebook.com/docs/whatsapp/cloud-api/calling/place-calls' },
                  { label: 'Call Control Settings', url: 'https://developers.facebook.com/docs/whatsapp/cloud-api/calling/call-control' },
                  { label: 'SIP Integration', url: 'https://developers.facebook.com/docs/whatsapp/cloud-api/calling/sip' },
                  { label: 'Asterisk Guide', url: 'https://developers.facebook.com/docs/whatsapp/cloud-api/calling/asterisk' },
                  { label: 'Sandbox Testing', url: 'https://developers.facebook.com/docs/whatsapp/cloud-api/calling/sandbox' },
                ].map( ( d, i ) => (
                  <a key={ i } href={ d.url } target="_blank" rel="noopener noreferrer"
                    style={ { fontSize: '13px', color: '#1a3a2a', textDecoration: 'none' } }>
                    { d.label } ↗
                  </a>
                ) ) }
              </div>
            </div>
          </div>
        ) }

        {/* WEBHOOK CONFIG TAB */ }
        { activeTab === 'webhook' && (
          <div>
            {/* Webhook Status */ }
            <div style={ { ...s.card, background: '#f9fafb', border: '1px solid #e5e7eb', marginBottom: '16px' } }>
              <div style={ { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' } }>
                <span style={ { fontSize: '18px' } }>-</span>
                <h3 style={ { margin: 0, fontSize: '15px', color: '#0f2a1d' } }>Webhook Endpoint — Deployed & Verified</h3>
                <span style={ badge( 'active' ) }>live</span>
              </div>
              <p style={ { margin: 0, fontSize: '13px', color: '#0f2a1d', lineHeight: 1.6 } }>
                Lambda <code style={ { background: '#f3f4f6', padding: '1px 6px', borderRadius: '4px', fontSize: '12px' } }>wecare-whatsapp-calling</code> handles
                webhook verification (GET hub.challenge) and call events (POST connect/terminate/permission).
                Logs stored in DynamoDB <code style={ { background: '#f3f4f6', padding: '1px 6px', borderRadius: '4px', fontSize: '12px' } }>WhatsAppCallingTable</code>.
              </p>
            </div>

            {/* Callback URL + Verify Token */ }
            <div style={ s.card }>
              <h4 style={ { margin: '0 0 12px', fontSize: '14px', color: '#1a1a1a' } }>Meta Dashboard Configuration</h4>
              <p style={ { margin: '0 0 12px', fontSize: '12px', color: '#6b7280' } }>
                Enter these values in <a href="https://developers.facebook.com/apps/891766673609917/whatsapp-business/wa-dev-console/" target="_blank" rel="noopener noreferrer" style={ { color: '#1a3a2a' } }>Meta App Dashboard → WhatsApp → Configuration</a>
              </p>
              <div style={ { display: 'flex', flexDirection: 'column', gap: '12px' } }>
                <div>
                  <label style={ { display: 'block', fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '4px' } }>Verify Token</label>
                  <div style={ { background: '#f3f4f6', color: '#374151', padding: '10px 14px', borderRadius: '8px', fontSize: '12px' } }>Configured server-side; never displayed or copied in the browser.</div>
                </div>
                <div>
                  <label style={ { display: 'block', fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '4px' } }>Webhook Fields to Subscribe</label>
                  <div style={ { display: 'flex', gap: '6px', flexWrap: 'wrap' } }>
                    { [ 'calls', 'messages', 'message_template_status_update', 'account_update' ].map( ( field, i ) => (
                      <span key={ i } style={ {
                        padding: '4px 12px', borderRadius: '6px', fontSize: '12px', fontWeight: 500,
                        background: field === 'calls' ? '#f9fafb' : '#f3f4f6',
                        color: field === 'calls' ? '#0f2a1d' : '#6b7280',
                        border: `1px solid ${field === 'calls' ? '#e5e7eb' : '#e5e7eb'}`,
                      } }>
                        { field } { field === 'calls' && '← required for calling' }
                      </span>
                    ) ) }
                  </div>
                </div>
              </div>
            </div>

            {/* Meta Access Token Info */ }
            <div style={ { ...s.card, marginTop: '12px' } }>
              <h4 style={ { margin: '0 0 10px', fontSize: '14px', color: '#1a1a1a' } }>Meta Access Token</h4>
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '13px' } }>
                  <tbody>
                    { [
                      { label: 'App', value: `${META_TOKEN.appId} (${META_TOKEN.appName})` },
                      { label: 'Secrets Manager', value: META_TOKEN.secretName },
                      { label: 'Token Type', value: META_TOKEN.tokenType },
                      { label: 'Status', value: META_TOKEN.status },
                      { label: 'Scopes', value: META_TOKEN.scopes.join( ', ' ) },
                      { label: 'WABA Access', value: META_TOKEN.wabaAccess.join( ', ' ) },
                    ].map( ( row, i ) => (
                      <tr key={ i } style={ { borderBottom: '1px solid #f3f4f6' } }>
                        <td style={ { padding: '8px 12px', fontWeight: 500, color: '#374151', whiteSpace: 'nowrap', width: '140px' } }>{ row.label }</td>
                        <td style={ { padding: '8px 12px', color: '#6b7280', fontFamily: 'monospace', fontSize: '12px' } }>{ row.value }</td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            </div>

            {/* Step-by-step: How to configure in Meta Dashboard */ }
            <div style={ { ...s.card, marginTop: '12px' } }>
              <h4 style={ { margin: '0 0 12px', fontSize: '14px', color: '#1a1a1a' } }>How to Configure Webhook in Meta Dashboard</h4>
              <ol style={ { margin: 0, paddingLeft: '20px', fontSize: '13px', color: '#374151', lineHeight: 1.8 } }>
                <li>Go to <a href="https://developers.facebook.com/apps/891766673609917/whatsapp-business/wa-dev-console/" target="_blank" rel="noopener noreferrer" style={ { color: '#1a3a2a' } }>developers.facebook.com → Your App → WhatsApp → Configuration</a></li>
                <li>Under &quot;Webhook&quot;, click &quot;Edit&quot; (or &quot;Configure&quot; if first time)</li>
                <li>Paste the Callback URL above</li>
                <li>Paste the Verify Token above</li>
                <li>Click &quot;Verify and Save&quot; — Meta will send a GET request with hub.challenge, our Lambda responds correctly</li>
                <li>After verification, click &quot;Manage&quot; next to Webhook fields</li>
                <li>Subscribe to: <strong>calls</strong> (required), optionally messages, account_update</li>
                <li>Important: If app is unpublished, only test webhooks from dashboard will work. Publish the app for production data.</li>
              </ol>
            </div>

            {/* Phone Number Readiness */ }
            <div style={ { ...s.card, marginTop: '12px' } }>
              <h4 style={ { margin: '0 0 10px', fontSize: '14px', color: '#1a1a1a' } }>Phone Number Calling Readiness</h4>
              { PHONE_NUMBERS.map( ( p, i ) => (
                <div key={ i } style={ { padding: '10px 0', borderBottom: i < PHONE_NUMBERS.length - 1 ? '1px solid #f3f4f6' : 'none' } }>
                  <div style={ { display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' } }>
                    <span style={ { fontWeight: 600, fontSize: '14px', color: '#1a1a1a' } }>{ p.display }</span>
                    <span style={ { fontSize: '12px', color: '#6b7280' } }>{ p.name }</span>
                    <span style={ badge( p.callingReady ? 'active' : 'planned' ) }>{ p.callingReady ? 'Ready' : 'Not Ready' }</span>
                  </div>
                  <div style={ { marginTop: '6px', fontSize: '12px', color: '#6b7280' } }>
                    Tier: <strong>{ p.tier }</strong> | Quality: <strong>{ p.quality }</strong> | Meta ID: <code style={ { fontSize: '11px' } }>{ p.metaId }</code>
                    { !p.callingReady && <span style={ { color: '#1a3a2a', marginLeft: '8px' } }>Needs TIER_2K+ (currently { p.tier })</span> }
                  </div>
                </div>
              ) ) }
            </div>

            {/* Documentation Links */ }
            <div style={ { ...s.card, marginTop: '12px' } }>
              <h4 style={ { margin: '0 0 10px', fontSize: '14px', color: '#1a1a1a' } }>Documentation</h4>
              <div style={ { display: 'flex', gap: '12px', flexWrap: 'wrap' } }>
                { [
                  { label: 'Getting Started (Access Token)', url: 'https://developers.facebook.com/docs/business-messaging/whatsapp/get-started' },
                  { label: 'Webhooks Overview', url: 'https://developers.facebook.com/docs/business-messaging/whatsapp/webhooks/overview' },
                  { label: 'Calling API Docs', url: 'https://developers.facebook.com/docs/whatsapp/cloud-api/calling' },
                  { label: 'App Dashboard', url: 'https://developers.facebook.com/apps/891766673609917/whatsapp-business/wa-dev-console/' },
                  { label: 'Meta Business Settings', url: 'https://business.facebook.com/settings' },
                ].map( ( d, i ) => (
                  <a key={ i } href={ d.url } target="_blank" rel="noopener noreferrer"
                    style={ { fontSize: '13px', color: '#1a3a2a', textDecoration: 'none' } }>
                    { d.label } ↗
                  </a>
                ) ) }
              </div>
            </div>
          </div>
        ) }

        {/* SETUP TAB */ }
        { activeTab === 'setup' && (
          <div>
            <div style={ { ...s.card, background: '#f9fafb', border: '1px solid #e5e7eb', marginBottom: '20px' } }>
              <p style={ { margin: 0, fontSize: '13px', color: '#0f2a1d' } }>
                Follow these steps to enable WhatsApp Business Calling. Default: Graph API + Webhooks (HTTPS) signaling with WebRTC media. SIP available with explicit enablement.
              </p>
            </div>
            { SETUP_STEPS.map( ( step ) => (
              <div key={ step.step } style={ { ...s.card, cursor: step.code ? 'pointer' : 'default' } }
                onClick={ () => step.code && setExpandedStep( expandedStep === step.step ? null : step.step ) }>
                <div style={ { display: 'flex', gap: '16px', alignItems: 'flex-start' } }>
                  <div style={ {
                    width: '32px', height: '32px', borderRadius: '50%', flexShrink: 0,
                    background: step.done ? '#1a3a2a' : '#e5e7eb', color: step.done ? '#fff' : '#6b7280',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '14px', fontWeight: 700,
                  } }>
                    { step.done ? '✓' : step.step }
                  </div>
                  <div style={ { flex: 1, minWidth: 0 } }>
                    <div style={ { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' } }>
                      <span style={ { fontWeight: 600, fontSize: '14px', color: '#1a1a1a' } }>{ step.title }</span>
                      { step.code && (
                        <span style={ { fontSize: '11px', color: '#9ca3af' } }>
                          { expandedStep === step.step ? '▼' : '▶' } code
                        </span>
                      ) }
                    </div>
                    <div style={ { fontSize: '13px', color: '#6b7280', lineHeight: 1.5 } }>{ step.desc }</div>
                  </div>
                </div>
                { step.code && expandedStep === step.step && (
                  <div style={ { marginTop: '12px', marginLeft: '48px' } }>
                    <div style={ { position: 'relative' } }>
                      <pre style={ {
                        background: '#000', color: '#e2e8f0', padding: '14px 16px',
                        borderRadius: '8px', fontSize: '12px', lineHeight: 1.5,
                        overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                      } }>
                        { step.code }
                      </pre>
                      <button
                        onClick={ ( e ) => { e.stopPropagation(); copyCode( step.code! ); } }
                        style={ {
                          position: 'absolute', top: '8px', right: '8px',
                          background: '#334155', border: 'none', color: 'rgba(255, 255, 255, 0.72)',
                          padding: '4px 8px', borderRadius: '4px', fontSize: '11px', cursor: 'pointer',
                        } }
                      >
                        Copy
                      </button>
                    </div>
                  </div>
                ) }
              </div>
            ) ) }

            {/* Sandbox Testing Info */ }
            <div style={ { ...s.card, marginTop: '8px', background: '#f9fafb', border: '1px solid #e5e7eb' } }>
              <h4 style={ { margin: '0 0 8px', fontSize: '14px', color: '#0f2a1d' } }>Sandbox Testing</h4>
              <p style={ { margin: '0 0 8px', fontSize: '13px', color: '#0f2a1d', lineHeight: 1.5 } }>
                Sandbox accounts (Tech Partners only) and public test numbers have relaxed limits for integration testing.
                No 2,000 messaging limit requirement for test numbers.
              </p>
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '12px' } }>
                  <tbody>
                    <tr style={ { borderBottom: '1px solid #e5e7eb' } }>
                      <td style={ { padding: '6px 10px', fontWeight: 500, color: '#0f2a1d' } }>Permission requests</td>
                      <td style={ { padding: '6px 10px', color: '#1a3a2a', fontFamily: 'monospace' } }>25/day, 100/week (vs 1/day, 2/week prod)</td>
                    </tr>
                    <tr style={ { borderBottom: '1px solid #e5e7eb' } }>
                      <td style={ { padding: '6px 10px', fontWeight: 500, color: '#0f2a1d' } }>Unanswered → warning</td>
                      <td style={ { padding: '6px 10px', color: '#1a3a2a', fontFamily: 'monospace' } }>5 consecutive (vs 2 prod)</td>
                    </tr>
                    <tr>
                      <td style={ { padding: '6px 10px', fontWeight: 500, color: '#0f2a1d' } }>Unanswered → revoke</td>
                      <td style={ { padding: '6px 10px', color: '#1a3a2a', fontFamily: 'monospace' } }>10 consecutive (vs 4 prod)</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) }

        {/* RESOURCES TAB */ }
        { activeTab === 'resources' && (
          <div>
            <div style={ { ...s.card, background: '#f9fafb', border: '1px solid #e5e7eb', marginBottom: '20px' } }>
              <p style={ { margin: 0, fontSize: '13px', color: '#0f2a1d' } }>
                AWS resources for WhatsApp Calling + TTS integration. Region: us-east-1.
              </p>
            </div>
            <div style={ { overflowX: 'auto' } }>
              <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: '13px' } }>
                <thead>
                  <tr style={ { background: '#f9fafb', borderBottom: '2px solid #e5e7eb' } }>
                    <th style={ { padding: '10px 14px', textAlign: 'left', fontWeight: 600, color: '#374151' } }>Service</th>
                    <th style={ { padding: '10px 14px', textAlign: 'left', fontWeight: 600, color: '#374151' } }>Resource</th>
                    <th style={ { padding: '10px 14px', textAlign: 'left', fontWeight: 600, color: '#374151' } }>Purpose</th>
                    <th style={ { padding: '10px 14px', textAlign: 'left', fontWeight: 600, color: '#374151' } }>Status</th>
                  </tr>
                </thead>
                <tbody>
                  { AWS_RESOURCES.map( ( r, i ) => (
                    <tr key={ i } style={ { borderBottom: '1px solid #f3f4f6' } }>
                      <td style={ { padding: '10px 14px', fontWeight: 500, color: '#1a1a1a' } }>{ r.service }</td>
                      <td style={ { padding: '10px 14px', color: '#6b7280', fontFamily: 'monospace', fontSize: '12px', wordBreak: 'break-all' } }>{ r.resource }</td>
                      <td style={ { padding: '10px 14px', color: '#6b7280' } }>{ r.purpose }</td>
                      <td style={ { padding: '10px 14px' } }><span style={ badge( r.status ) }>{ r.status }</span></td>
                    </tr>
                  ) ) }
                </tbody>
              </table>
            </div>
          </div>
        ) }

        {/* CALLING SETTINGS TAB */ }
        { activeTab === 'settings' && (
          <div>
            <div style={ { ...s.card, background: '#f9fafb', border: '1px solid #e5e7eb', marginBottom: '16px' } }>
              <h3 style={ { margin: '0 0 6px', fontSize: '15px', color: '#0f2a1d' } }>Enable & Configure Calling</h3>
              <p style={ { margin: 0, fontSize: '13px', color: '#0f2a1d' } }>
                Use this to enable the call icon on your WhatsApp number, set business hours, and restrict calling to specific countries.
                This sends a POST to <code style={ { background: '#f3f4f6', padding: '1px 4px', borderRadius: 3, fontSize: 12 } }>/{ '{phone-number-id}' }/settings</code> with the calling configuration.
              </p>
            </div>

            {/* Phone selector */ }
            <div style={ { ...s.card } }>
              <div style={ { fontSize: 13, fontWeight: 600, marginBottom: 10 } }>Select Phone Number</div>
              <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap' } }>
                { PHONE_NUMBERS.map( ( p, i ) => (
                  <button key={ i } onClick={ () => { setSettingsPhone( p ); } }
                    style={ { padding: '8px 16px', borderRadius: 6, border: settingsPhone.metaId === p.metaId ? '2px solid #1a3a2a' : '1px solid #ddd', background: settingsPhone.metaId === p.metaId ? '#f9fafb' : '#fff', cursor: 'pointer', fontSize: 13 } }>
                    { p.name } ({ p.display })
                    { p.callingReady && <span style={ { marginLeft: 6, fontSize: 11, color: '#1a3a2a' } }>Ready</span> }
                    { !p.callingReady && <span style={ { marginLeft: 6, fontSize: 11, color: '#1a3a2a' } }>Needs 2K</span> }
                  </button>
                ) ) }
              </div>
              <div style={ { marginTop: 8, fontSize: 12, color: '#6b7280' } }>
                Meta Phone ID: <code style={ { fontSize: 11 } }>{ settingsPhone.metaId }</code> | Tier: { settingsPhone.tier } | Quality: { settingsPhone.quality }
              </div>
            </div>

            {/* Settings Form */ }
            <div style={ { ...s.card, marginTop: 12 } }>
              <h4 style={ { margin: '0 0 14px', fontSize: 14 } }>Calling Configuration</h4>
              <div style={ { display: 'grid', gap: 16 } }>
                {/* Call Icon Visibility */ }
                <div>
                  <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 } }>Call Icon Visibility</label>
                  <div style={ { display: 'flex', gap: 12 } }>
                    <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' } }>
                      <input type="radio" name="visibility" checked={ callingVisibility === 'default' } onChange={ () => setCallingVisibility( 'default' ) } style={ { accentColor: '#1a3a2a' } } />
                      <span>Default (show call icon)</span>
                    </label>
                    <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' } }>
                      <input type="radio" name="visibility" checked={ callingVisibility === 'disable_all' } onChange={ () => setCallingVisibility( 'disable_all' ) } style={ { accentColor: '#1a3a2a' } } />
                      <span>Disable All (hide call icon)</span>
                    </label>
                  </div>
                </div>

                {/* Country Restriction */ }
                <div>
                  <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 } }>Restrict to Countries (comma-separated ISO codes)</label>
                  <input value={ restrictCountries } onChange={ e => setRestrictCountries( e.target.value ) } placeholder="IN, AE, GB"
                    style={ { width: '100%', padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 } } />
                  <div style={ { fontSize: 11, color: '#9ca3af', marginTop: 4 } }>Only users in these countries will see the call icon. Leave empty for all countries.</div>
                </div>

                {/* Callback Permission */ }
                <div>
                  <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 } }>Callback Permission Request</label>
                  <div style={ { display: 'flex', gap: 12 } }>
                    <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' } }>
                      <input type="radio" name="callbackPerm" checked={ callbackPermission === 'ENABLED' } onChange={ () => setCallbackPermission( 'ENABLED' ) } style={ { accentColor: '#1a3a2a' } } />
                      <span>Enabled (auto-show permission UI when a user calls)</span>
                    </label>
                    <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' } }>
                      <input type="radio" name="callbackPerm" checked={ callbackPermission === 'DISABLED' } onChange={ () => setCallbackPermission( 'DISABLED' ) } style={ { accentColor: '#1a3a2a' } } />
                      <span>Disabled</span>
                    </label>
                  </div>
                  <div style={ { fontSize: 11, color: '#9ca3af', marginTop: 4 } }>Calling a user requires explicit permission. Enable to request it automatically when a user calls your business.</div>
                </div>

                {/* Audio Codecs */ }
                <div>
                  <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 } }>Audio Codecs</label>
                  <div style={ { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', background: '#f0fdf4', border: '1px solid #86efac', borderRadius: 8, marginBottom: 8 } }>
                    <span style={ { fontSize: 12, fontWeight: 700, color: '#166534' } }>Opus</span>
                    <span style={ { fontSize: 12, color: '#166534' } }>Default codec (best quality, lowest bandwidth) — always enabled.</span>
                  </div>
                  <div style={ { display: 'flex', gap: 16 } }>
                    { ( [ 'PCMA', 'PCMU' ] as const ).map( codec => (
                      <label key={ codec } style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' } }>
                        <input type="checkbox" checked={ audioCodecs.includes( codec ) }
                          onChange={ e => setAudioCodecs( prev => e.target.checked ? [ ...prev, codec ] : prev.filter( x => x !== codec ) ) }
                          style={ { accentColor: '#1a3a2a' } } />
                        <span>G.711 { codec }</span>
                      </label>
                    ) ) }
                  </div>
                  <div style={ { fontSize: 11, color: '#9ca3af', marginTop: 4 } }>Enable G.711 only for interoperability with legacy telephony / PSTN gateways. Adds transcoding latency and uses more bandwidth.</div>
                </div>

                {/* Voicemail (advanced passthrough) */ }
                <details style={ { border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 12px' } }>
                  <summary style={ { fontSize: 13, fontWeight: 500, cursor: 'pointer' } }>Voicemail (advanced)</summary>
                  <div style={ { marginTop: 10 } }>
                    <div style={ { display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 10px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, marginBottom: 10 } }>
                      <span style={ { fontSize: 11, color: '#92400e', lineHeight: 1.5 } }>
                        Voicemail is not part of Meta&apos;s published Calling API reference (as of Nov 2025).
                        This editor passes a raw JSON <code>voicemail</code> object straight through to
                        <code> POST /{ '{phone-number-id}' }/settings</code>. Use only with a schema confirmed by your Meta contact.
                      </span>
                    </div>
                    <textarea
                      value={ voicemailJson }
                      onChange={ e => { setVoicemailJson( e.target.value ); setVoicemailError( '' ); } }
                      placeholder={ '{\n  "status": "ENABLED",\n  "timeout_seconds": 30\n}' }
                      rows={ 7 }
                      style={ { width: '100%', padding: '8px 12px', border: `1px solid ${voicemailError ? '#ef4444' : '#ddd'}`, borderRadius: 6, fontSize: 12, fontFamily: 'monospace' } } />
                    { voicemailError && <div style={ { fontSize: 11, color: '#ef4444', marginTop: 4 } }>{ voicemailError }</div> }
                    <div style={ { fontSize: 11, color: '#9ca3af', marginTop: 4 } }>Leave empty to omit voicemail settings. Must be a valid JSON object.</div>
                  </div>
                </details>

                {/* Call availability — always 24/7 (call_hours disabled at Meta) */ }
                <div>
                  <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 8 } }>
                    Call Availability
                  </label>
                  <div style={ { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', background: '#f0fdf4', border: '1px solid #86efac', borderRadius: 8 } }>
                    <span style={ { fontSize: 12, fontWeight: 700, color: '#166534', background: '#dcfce7', padding: '2px 8px', borderRadius: 9999 } }>24 / 7</span>
                    <span style={ { fontSize: 12, color: '#166534' } }>Calls accepted at any time, every day. Business call hours are disabled.</span>
                  </div>
                </div>
              </div>

              {/* Save Button */ }
              <div style={ { display: 'flex', gap: 12, alignItems: 'center', marginTop: 20 } }>
                <button onClick={ saveCallingSettings } disabled={ savingSettings }
                  style={ { padding: '10px 24px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 14, fontWeight: 600 } }>
                  { savingSettings ? 'Saving...' : 'Enable Calling / Save Settings' }
                </button>
                <button onClick={ loadCallingSettings } disabled={ loadingSettings }
                  style={ { padding: '10px 16px', background: '#fff', border: '1px solid #d1d5db', borderRadius: 8, cursor: 'pointer', fontSize: 13 } }>
                  { loadingSettings ? 'Loading...' : 'Refresh Current Settings' }
                </button>
              </div>
            </div>

            {/* Current Settings Response */ }
            { callingSettingsResult && (
              <div style={ { ...s.card, marginTop: 12 } }>
                <h4 style={ { margin: '0 0 8px', fontSize: 14 } }>Current Settings (from Meta API)</h4>
                <pre style={ { background: '#000', color: '#e2e8f0', padding: 14, borderRadius: 8, fontSize: 12, overflow: 'auto', maxHeight: 250 } }>
                  { JSON.stringify( callingSettingsResult, null, 2 ) }
                </pre>
              </div>
            ) }

            {/* API Reference */ }
            <div style={ { ...s.card, marginTop: 12 } }>
              <h4 style={ { margin: '0 0 8px', fontSize: 14 } }>API Reference</h4>
              <div style={ { fontSize: 13, color: '#666', lineHeight: 1.8 } }>
                <div>Enable calling: <code style={ { fontSize: 12, background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 } }>POST /{ '{phone-number-id}' }/settings</code> with <code>calling</code> object</div>
                <div>call_icon_visibility: <code style={ { fontSize: 12 } }>&quot;default&quot;</code> (show) or <code style={ { fontSize: 12 } }>&quot;disable_all&quot;</code> (hide)</div>
                <div>restrict_to_user_countries: Array of ISO country codes (e.g. [&quot;IN&quot;, &quot;AE&quot;])</div>
                <div>callback_permission_status: <code style={ { fontSize: 12 } }>&quot;ENABLED&quot;</code> / <code style={ { fontSize: 12 } }>&quot;DISABLED&quot;</code></div>
                <div>audio.additional_codecs: <code style={ { fontSize: 12 } }>[&quot;PCMA&quot;,&quot;PCMU&quot;]</code> (G.711; Opus is always default)</div>
                <div>call_hours: status + timezone_id + weekly_operating_hours (max 2/day, no overlap) + holiday_schedule</div>
                <div>Docs: <a href="https://developers.facebook.com/docs/whatsapp/cloud-api/calling/call-control" target="_blank" rel="noopener noreferrer" style={ { color: '#1a3a2a' } }>Call Control Settings ↗</a></div>
              </div>
            </div>
          </div>
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

export default WhatsAppCallingPage;
