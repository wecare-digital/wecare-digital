import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { voiceSearchFailureMessage } from '../lib/publicVoiceSearch';

const VOICE_SEARCH_MIC_PATH = 'M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z';

interface VoiceRecognitionEventLike {
  results?: ArrayLike<ArrayLike<{ transcript?: string }>>;
}
interface VoiceRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop?: () => void;
  abort?: () => void;
  onstart: ( () => void ) | null;
  onend: ( () => void ) | null;
  onerror: ( ( event: { error?: string } ) => void ) | null;
  onresult: ( ( event: VoiceRecognitionEventLike ) => void ) | null;
}
type VoiceRecognitionConstructor = new () => VoiceRecognitionLike;

const VOICE_LOCALE_BY_BASE: Record<string, string> = {
  en: 'en-IN', hi: 'hi-IN', bn: 'bn-IN', ta: 'ta-IN', te: 'te-IN',
  mr: 'mr-IN', gu: 'gu-IN', kn: 'kn-IN', ml: 'ml-IN', pa: 'pa-IN', ur: 'ur-IN',
};

function pageVoiceLocale (): string {
  if ( typeof document === 'undefined' ) return 'en-IN';
  const lang = ( document.documentElement.lang || navigator.language || 'en' ).trim();
  const base = lang.toLowerCase().split( /[-_]/ )[ 0 ];
  return VOICE_LOCALE_BY_BASE[ base ] || lang || 'en-IN';
}

interface VoiceSearchMicProps {
  onTranscript: ( transcript: string ) => void;
  ariaLabel?: string;
  /** Keep a disabled mic visible when the browser has no SpeechRecognition implementation. */
  showUnsupportedState?: boolean;
}

const VoiceSearchMic: React.FC<VoiceSearchMicProps> = ( {
  onTranscript,
  ariaLabel = 'Search by voice',
  showUnsupportedState = false,
} ) => {
  const [ supportChecked, setSupportChecked ] = useState( false );
  const [ supported, setSupported ] = useState( false );
  const [ listening, setListening ] = useState( false );
  const [ starting, setStarting ] = useState( false );
  const [ feedback, setFeedback ] = useState( '' );
  const statusId = useId();
  // SpeechRecognition.start is asynchronous: lock immediately, before onstart.
  const activeRef = useRef( false );
  const cancelledRef = useRef( false );
  const resultRef = useRef( false );
  const recognitionRef = useRef<VoiceRecognitionLike | null>( null );
  const transcriptHandlerRef = useRef( onTranscript );

  useEffect( () => {
    transcriptHandlerRef.current = onTranscript;
  }, [ onTranscript ] );

  useEffect( () => {
    if ( typeof window === 'undefined' ) return;
    const speechWindow = window as typeof window & {
      SpeechRecognition?: VoiceRecognitionConstructor;
      webkitSpeechRecognition?: VoiceRecognitionConstructor;
    };
    const Recognition = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    if ( !Recognition ) {
      setSupportChecked( true );
      return;
    }

    let recognition: VoiceRecognitionLike;
    try {
      recognition = new Recognition();
    } catch {
      // Some embedded browsers expose the constructor but cannot instantiate it.
      setSupportChecked( true );
      return;
    }
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => {
      if ( cancelledRef.current ) return;
      setStarting( false );
      setListening( true );
    };
    recognition.onend = () => {
      if ( activeRef.current && !cancelledRef.current && !resultRef.current ) {
        setFeedback( previous => previous || voiceSearchFailureMessage( 'no-speech' ) );
      }
      activeRef.current = false;
      setStarting( false );
      setListening( false );
    };
    recognition.onerror = event => {
      activeRef.current = false;
      setStarting( false );
      setListening( false );
      if ( !cancelledRef.current && event.error !== 'aborted' ) {
        setFeedback( voiceSearchFailureMessage( event.error ) );
      }
    };
    recognition.onresult = event => {
      if ( cancelledRef.current ) return;
      const transcript = String( event.results?.[ 0 ]?.[ 0 ]?.transcript || '' ).trim();
      if ( transcript ) {
        resultRef.current = true;
        setFeedback( '' );
        transcriptHandlerRef.current( transcript );
      } else {
        setFeedback( voiceSearchFailureMessage( 'nomatch' ) );
      }
    };
    recognitionRef.current = recognition;
    setSupported( true );
    setSupportChecked( true );

    return () => {
      recognition.onstart = null;
      recognition.onend = null;
      recognition.onerror = null;
      recognition.onresult = null;
      activeRef.current = false;
      try { recognition.abort?.(); } catch { /* already ended */ }
      if ( recognitionRef.current === recognition ) recognitionRef.current = null;
    };
  }, [] );

  const toggle = useCallback( () => {
    const recognition = recognitionRef.current;
    if ( !recognition ) return;
    if ( activeRef.current ) {
      // A second tap cancels even while permission/start is pending.
      cancelledRef.current = true;
      try {
        if ( recognition.abort ) recognition.abort();
        else if ( recognition.stop ) recognition.stop();
        else activeRef.current = false;
      } catch {
        activeRef.current = false;
      }
      setStarting( false );
      setListening( false );
      return;
    }
    activeRef.current = true;
    cancelledRef.current = false;
    resultRef.current = false;
    setFeedback( '' );
    setStarting( true );
    try {
      recognition.lang = pageVoiceLocale();
      recognition.start();
    } catch ( error ) {
      activeRef.current = false;
      setStarting( false );
      setListening( false );
      setFeedback( voiceSearchFailureMessage( error instanceof Error ? error.name : undefined ) );
    }
  }, [] );

  if ( !supportChecked ) return null;
  if ( !supported && !showUnsupportedState ) return null;

  const unavailable = !supported;
  const controlLabel = unavailable
    ? 'Voice search unavailable in this browser'
    : listening || starting ? `Stop ${ariaLabel.toLowerCase()}` : ariaLabel;

  return (
    <>
      <button
        type="button"
        className={ `voice-search-mic ${listening || starting ? 'is-listening' : ''} ${unavailable ? 'is-unavailable' : ''}${feedback ? ' has-feedback' : ''}`.trim() }
        aria-label={ controlLabel }
        title={ unavailable ? 'Voice search unavailable. Type your search instead.' : controlLabel }
        aria-pressed={ supported ? listening || starting : undefined }
        aria-describedby={ feedback ? statusId : undefined }
        data-voice-search-mic="true"
        disabled={ unavailable }
        onClick={ supported ? toggle : undefined }
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path className="voice-search-mic-glyph" d={ VOICE_SEARCH_MIC_PATH } />
        </svg>
      </button>
      <span id={ statusId } className={ `voice-search-status${feedback ? ' is-visible' : ''}` } role="status" aria-live="polite" aria-atomic="true">
        { feedback || ( starting ? 'Starting voice search' : listening ? 'Listening for your search' : '' ) }
      </span>
      <style jsx>{`
        .voice-search-mic{
          position:absolute;inset-inline-end:-2px;bottom:0;top:auto;z-index:2;
          display:inline-grid;place-items:center;width:46px;height:46px;min-width:46px;min-height:46px;padding:0;
          border:0;border-radius:var(--public-hover-radius);background:transparent;color:var(--public-brand-green);
          transform:none;cursor:pointer;
          transition:background-color .14s ease,color .14s ease,transform .14s ease,opacity .14s ease;
        }
        /* The shared search field uses normal-flow controls; legacy fields
           retain their existing positioning. Only actual failures occupy a row. */
        .voice-search-mic.has-feedback{top:0;bottom:auto}
        .voice-search-status{position:absolute;inline-size:1px;block-size:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
        .voice-search-status.is-visible{position:static;display:block;flex:0 0 100%;inline-size:100%;block-size:auto;margin:4px 0 0;padding:6px 2px;clip:auto;overflow:visible;white-space:normal;overflow-wrap:anywhere;box-sizing:border-box;color:var(--public-brand-green);font:600 var(--public-supporting-size)/1.4 var(--font-sans)}
        .voice-search-mic svg{width:23px;height:23px;display:block;overflow:visible}
        .voice-search-mic-glyph{fill:currentColor}
        @media (hover:hover) and (pointer:fine){.voice-search-mic:not(:disabled):not(.is-unavailable):hover{background:var(--public-hover-surface);color:var(--public-brand-green)}}
        .voice-search-mic:not(:disabled):active{transform:scale(.94)}
        .voice-search-mic:focus-visible{outline:2px solid #1a3a2a;outline-offset:2px}
        .voice-search-mic.is-unavailable{color:#8a9288;opacity:.72;cursor:not-allowed}
        .voice-search-mic.is-listening{color:#3da35a;animation:voice-search-pulse 1.1s ease-in-out infinite}
        @keyframes voice-search-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}
        @media(prefers-reduced-motion:reduce){.voice-search-mic{transition:none}.voice-search-mic.is-listening{animation:none}}
      `}</style>
    </>
  );
};

export default VoiceSearchMic;
