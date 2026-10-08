import { useEffect, useRef, useState } from 'react';

/**
 * The /orders copy-id behaviour, as a hook, for the Requests panel (Phase O-1).
 *
 * Behaviour is identical to src/pages/orders.tsx's own copy control, which is deliberately NOT
 * refactored onto this: the value comes from React state (never the DOM, which the translator
 * rewrites); the control exists only where `navigator.clipboard && window.isSecureContext`,
 * computed in an effect so the server render and first paint agree; success reads "Copied" for
 * 2s; a refused write SELECTS the id and leaves "Press your copy key" until the next success.
 */
export function useCopyFeedback ( successMessage: string, refusedMessage: string ) {
  const [ copiedKey, setCopiedKey ] = useState<string | null>( null );
  const [ failedKey, setFailedKey ] = useState<string | null>( null );
  const [ liveMessage, setLiveMessage ] = useState( '' );
  const [ canCopy, setCanCopy ] = useState( false );
  const timer = useRef<ReturnType<typeof setTimeout> | null>( null );

  useEffect( () => {
    setCanCopy( typeof navigator !== 'undefined' && !!navigator.clipboard && window.isSecureContext );
  }, [] );
  useEffect( () => () => { if ( timer.current ) clearTimeout( timer.current ); }, [] );

  const copy = async ( key: string, value: string, element: HTMLElement | null ) => {
    try
    {
      await navigator.clipboard.writeText( value );
      setCopiedKey( key );
      setFailedKey( null );
      setLiveMessage( successMessage );
      if ( timer.current ) clearTimeout( timer.current );
      timer.current = setTimeout( () => { setCopiedKey( null ); setLiveMessage( '' ); }, 2000 );
    }
    catch
    {
      try
      {
        if ( element )
        {
          const range = document.createRange();
          range.selectNodeContents( element );
          const selection = window.getSelection?.();
          if ( selection ) { selection.removeAllRanges(); selection.addRange( range ); }
        }
      }
      catch { /* selection unavailable; the hint still carries the recovery */ }
      setFailedKey( key );
      setCopiedKey( null );
      setLiveMessage( refusedMessage );
    }
  };

  return { canCopy, copiedKey, failedKey, liveMessage, copy };
}
