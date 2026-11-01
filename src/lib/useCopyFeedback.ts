import { useEffect, useState } from 'react';
import { usePublicToast } from '../components/public/PublicToastProvider';

/**
 * Clipboard support for the dormant Requests panel.
 *
 * This is only a copy helper, NOT another notification system. Successful
 * copies use the same one-at-a-time public toast as Orders and Share.
 * On clipboard refusal, keep one contextual keyboard-copy instruction
 * alongside the selected ID so recovery does not vanish after a timer.
 */
export function useCopyFeedback () {
  const { showToast } = usePublicToast();
  const [ failedKey, setFailedKey ] = useState<string | null>( null );
  const [ canCopy, setCanCopy ] = useState( false );

  useEffect( () => {
    setCanCopy( typeof navigator !== 'undefined' && !!navigator.clipboard && window.isSecureContext );
  }, [] );

  const copy = async ( key: string, value: string, element: HTMLElement | null ) => {
    try {
      await navigator.clipboard.writeText( value );
      setFailedKey( null );
      showToast( 'success' );
    } catch {
      let selected = false;
      try {
        if ( element ) {
          const range = document.createRange();
          range.selectNodeContents( element );
          const selection = window.getSelection?.();
          if ( selection ) {
            selection.removeAllRanges();
            selection.addRange( range );
            selected = true;
          }
        }
      } catch { /* Clipboard recovery is best-effort. */ }
      // This is a local keyboard instruction, never a second success popup.
      setFailedKey( selected ? key : null );
      if ( !selected ) showToast( 'failure', { durationMs: 6500 } );
    }
  };

  return { canCopy, failedKey, copy };
}
