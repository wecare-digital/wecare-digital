import React, { useCallback, useEffect, useRef, useState } from 'react';

export const VOICE_SEARCH_MIC_PATH = 'M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z';

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
  const [ feedback, setFeedback ] = useState( '' );
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
    try { recognition = new Recognition(); }
    catch { setSupportChecked( true ); return; }
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => { setListening( true ); setFeedback( '' ); };
    recognition.onend = () => setListening( false );
    recognition.onerror = event => {
      setListening( false );
      if ( event.error !== 'aborted' ) setFeedback( 'Voice search unavailable. Type your search instead.' );
    };
    recognition.onresult = event => {
      const transcript = String( event.results?.[ 0 ]?.[ 0 ]?.transcript || '' ).trim();
      if ( transcript ) { setFeedback( '' ); transcriptHandlerRef.current( transcript ); }
    };
    recognitionRef.current = recognition;
    setSupported( true );
    setSupportChecked( true );

    return () => {
      recognition.onstart = null;
      recognition.onend = null;
      recognition.onerror = null;
      recognition.onresult = null;
      try { recognition.abort?.(); } catch { /* browser may already have ended recognition */ }
      if ( recognitionRef.current === recognition ) recognitionRef.current = null;
    };
  }, [] );

  const toggle = useCallback( () => {
    const recognition = recognitionRef.current;
    if ( !recognition ) return;
    if ( listening ) {
      try { recognition.stop?.(); } catch { setListening( false ); }
      return;
    }
    setFeedback( '' );
    try {
      recognition.lang = pageVoiceLocale();
      recognition.start();
    } catch {
      setListening( false );
      setFeedback( 'Voice search unavailable. Type your search instead.' );
    }
  }, [ listening ] );

  if ( !supportChecked ) return null;
  if ( !supported && !showUnsupportedState ) return null;

  const unavailable = !supported;
  const controlLabel = unavailable
    ? 'Voice search unavailable in this browser'
    : listening ? `Stop ${ariaLabel.toLowerCase()}` : ariaLabel;

  return (
    <>
      <button
        type="button"
        className={ `voice-search-mic ${listening ? 'is-listening' : ''} ${unavailable ? 'is-unavailable' : ''}`.trim() }
        aria-label={ controlLabel }
        title={ controlLabel }
        aria-pressed={ supported ? listening : undefined }
        data-voice-search-mic="true"
        disabled={ unavailable }
        onClick={ supported ? toggle : undefined }
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path className="voice-search-mic-glyph" d={ VOICE_SEARCH_MIC_PATH } />
        </svg>
      </button>
      <span className="voice-search-feedback" role="status" aria-live="polite">{ feedback }</span>
      <style jsx>{`
        .voice-search-feedback{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
        .voice-search-mic{
          position:absolute;inset-inline-end:-2px;bottom:0;top:auto;z-index:2;
          display:inline-grid;place-items:center;width:46px;height:46px;min-width:46px;min-height:46px;padding:0;
          border:0;border-radius:0;background:transparent;color:#3da35a;
          transform:none;cursor:pointer;
          transition:color .14s ease,transform .14s ease,opacity .14s ease;
        }
        .voice-search-mic svg{width:23px;height:23px;display:block;overflow:visible}
        .voice-search-mic-glyph{fill:currentColor}
        .voice-search-mic:not(:disabled):hover{color:#2f9e44}
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
