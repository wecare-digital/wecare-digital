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
  onerror: ( () => void ) | null;
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
}

const VoiceSearchMic: React.FC<VoiceSearchMicProps> = ( { onTranscript } ) => {
  const [ supported, setSupported ] = useState( false );
  const [ listening, setListening ] = useState( false );
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
    if ( !Recognition ) return;

    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => setListening( true );
    recognition.onend = () => setListening( false );
    recognition.onerror = () => setListening( false );
    recognition.onresult = event => {
      const transcript = String( event.results?.[ 0 ]?.[ 0 ]?.transcript || '' ).trim();
      if ( transcript ) transcriptHandlerRef.current( transcript );
    };
    recognitionRef.current = recognition;
    setSupported( true );

    return () => {
      recognition.onstart = null;
      recognition.onend = null;
      recognition.onerror = null;
      recognition.onresult = null;
      recognition.abort?.();
      if ( recognitionRef.current === recognition ) recognitionRef.current = null;
    };
  }, [] );

  const toggle = useCallback( () => {
    const recognition = recognitionRef.current;
    if ( !recognition ) return;
    if ( listening ) {
      recognition.stop?.();
      return;
    }
    recognition.lang = pageVoiceLocale();
    try {
      recognition.start();
    } catch {
      setListening( false );
    }
  }, [ listening ] );

  if ( !supported ) return null;

  return (
    <>
      <button
        type="button"
        className={ `voice-search-mic ${listening ? 'is-listening' : ''}`.trim() }
        aria-label={ listening ? 'Stop voice search' : 'Search by voice' }
        title={ listening ? 'Stop voice search' : 'Search by voice' }
        aria-pressed={ listening }
        data-voice-search-mic="true"
        onClick={ toggle }
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path className="voice-search-mic-glyph" d={ VOICE_SEARCH_MIC_PATH } />
        </svg>
      </button>
      <style jsx>{`
        .voice-search-mic{
          position:absolute;right:4px;bottom:6px;top:auto;z-index:2;
          display:inline-grid;place-items:center;width:32px;height:32px;padding:0;
          border:0;border-radius:0;background:transparent;color:#3da35a;
          transform:none;cursor:pointer;
          transition:color .14s ease,transform .14s ease,opacity .14s ease;
        }
        .voice-search-mic svg{width:23px;height:23px;display:block;overflow:visible}
        .voice-search-mic-glyph{fill:currentColor}
        .voice-search-mic:hover{color:#2f9e44}
        .voice-search-mic:active{transform:scale(.94)}
        .voice-search-mic:focus-visible{outline:2px solid #1a3a2a;outline-offset:2px}
        .voice-search-mic.is-listening{color:#3da35a;animation:voice-search-pulse 1.1s ease-in-out infinite}
        @keyframes voice-search-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}
        @media(prefers-reduced-motion:reduce){.voice-search-mic{transition:none}.voice-search-mic.is-listening{animation:none}}
      `}</style>
    </>
  );
};

export default VoiceSearchMic;
