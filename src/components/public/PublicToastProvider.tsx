import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import { useRouter } from 'next/router';
import PublicNotice from './PublicNotice';
import type { PublicNoticeTone } from './PublicNotice';
import { publicActionText } from '../../lib/publicActionNotices';
import type { PublicActionNoticeKind } from '../../lib/publicActionNotices';

/**
 * Only ONE brief notification can be visible on public/customer pages.
 *
 * Use it for direct action feedback (copy, WhatsApp invitation), never for
 * passive search/weather updates, field errors or ambiguous payments. The
 * caller can pin a pending state with durationMs: 0; the next result replaces it.
 * There is no queue to replay stale confirmations after the user's next action.
 */
export interface PublicToastOptions {
  tone?: PublicNoticeTone;
  /** 0 means keep until the caller replaces or clears it. */
  durationMs?: number;
}

/** WhatsApp failures are deliberately persistent INLINE warnings, not toasts. */
type PublicToastKind = Exclude<PublicActionNoticeKind, 'whatsappFailed'>;

interface PublicToast {
  id: number;
  message: string;
  tone: PublicNoticeTone;
}

interface PublicToastContextValue {
  /** Status keys only: reject raw API/provider text at the shared toast boundary. */
  showToast: ( kind: PublicToastKind, options?: PublicToastOptions ) => number;
  /** Ignore a stale async owner if a newer toast replaced it. */
  hideToast: ( id?: number ) => void;
}

const Context = createContext<PublicToastContextValue | null>( null );

/** PublicShare also renders inside Workspace, where the public host is absent. */
export function useOptionalPublicToast (): PublicToastContextValue | null {
  return useContext( Context );
}

export function usePublicToast (): PublicToastContextValue {
  const value = useOptionalPublicToast();
  if ( !value ) throw new Error( 'usePublicToast requires PublicToastProvider' );
  return value;
}

export default function PublicToastProvider ( { children }: { children: React.ReactNode } ): React.ReactElement {
  const router = useRouter();
  const [ active, setActive ] = useState<PublicToast | null>( null );
  const nextId = useRef( 0 );
  const activeId = useRef( 0 );
  const timer = useRef<ReturnType<typeof setTimeout> | null>( null );

  const stopTimer = useCallback( () => {
    if ( timer.current ) clearTimeout( timer.current );
    timer.current = null;
  }, [] );

  const hideToast = useCallback( ( id?: number ) => {
    if ( id && id !== activeId.current ) return;
    stopTimer();
    activeId.current = 0;
    setActive( null );
  }, [ stopTimer ] );

  const showToast = useCallback( ( kind: PublicToastKind, options: PublicToastOptions = {} ): number => {
    const message = publicActionText( kind );
    if ( !message ) return 0;
    stopTimer();
    const id = ++nextId.current;
    activeId.current = id;
    const tone = options.tone || ( kind === 'success' || kind === 'whatsappAccepted' ? 'success'
      : kind === 'failure' || kind === 'blocked' ? 'error' : 'info' );
    setActive( { id, message, tone } );
    // Action success is brief, pending explicitly stays, and errors never
    // auto-dismiss unless the caller marks a low-risk failure as transient.
    const ms = options.durationMs === undefined ? ( tone === 'error' ? 0 : 2500 )
      : Math.max( 0, options.durationMs );
    if ( ms > 0 ) {
      timer.current = setTimeout( () => {
        if ( activeId.current !== id ) return;
        activeId.current = 0;
        timer.current = null;
        setActive( current => current?.id === id ? null : current );
      }, ms );
    }
    return id;
  }, [ stopTimer ] );

  // A route change invalidates transient feedback; never show the last page's
  // confirmation on the next page.
  useEffect( () => {
    const onRouteChange = () => hideToast();
    router.events.on( 'routeChangeStart', onRouteChange );
    return () => router.events.off( 'routeChangeStart', onRouteChange );
  }, [ router.events, hideToast ] );
  useEffect( () => () => stopTimer(), [ stopTimer ] );

  const value = useMemo( () => ( { showToast, hideToast } ), [ showToast, hideToast ] );

  return (
    <Context.Provider value={ value }>
      { children }
      <div className="wc-public-toast-host wc-action-toast-host" data-wc-public-toast-host="true">
        { active && (
          <PublicNotice key={ active.id } mode="toast" tone={ active.tone } message={ active.message } />
        ) }
      </div>

    </Context.Provider>
  );
}
