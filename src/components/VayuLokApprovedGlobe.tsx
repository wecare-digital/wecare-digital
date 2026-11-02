import React, { useEffect, useLayoutEffect, useMemo, useRef } from 'react';

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_BROWSER_KEY || '';
const GLOBE_ASSET_VERSION = '20261102-india-first-v1';

export interface VayuLokGlobeCity {
  id: string;
  name: string;
  lat: number;
  lng: number;
}

interface VayuLokApprovedGlobeProps {
  mode?: 'air' | 'weather';
  onModeChange?: ( mode: 'air' | 'weather' ) => void;
  onSelectLocation?: ( city: VayuLokGlobeCity ) => void;
}

const VayuLokApprovedGlobe: React.FC<VayuLokApprovedGlobeProps> = ( {
  mode = 'air',
  onModeChange,
  onSelectLocation,
} ) => {
  const frameRef = useRef<HTMLIFrameElement | null>( null );
  // The mode the frame is showing, as far as this page knows: the last one it reported or the
  // last one posted to it. Only a difference is posted, so the frame's own report is never
  // echoed back. Clearing the marker after one skip (the previous approach) left the frame on
  // the stale mode when a second tap was reported before React ran the first commit's effect.
  const frameModeRef = useRef<'air' | 'weather' | null>( null );
  // The standalone globe reads the browser-restricted Maps key from location.hash.
  // Supplying it here restores live Air/Weather data inside the iframe without putting
  // the key in page copy; browser keys are public-by-design and restricted by referrer.
  const src = useMemo( () => {
    const base = `/vayulok-globe.html?v=${encodeURIComponent( GLOBE_ASSET_VERSION )}`;
    return MAPS_KEY ? `${base}#key=${encodeURIComponent( MAPS_KEY )}` : base;
  }, [] );

  useEffect( () => {
    const onMessage = ( event: MessageEvent ) => {
      if ( event.origin !== window.location.origin || event.data?.source !== 'vayulok-globe' ) return;
      if ( event.data?.type === 'mode' && ( event.data.mode === 'air' || event.data.mode === 'weather' ) ) {
        frameModeRef.current = event.data.mode;
        onModeChange?.( event.data.mode );
        return;
      }
      if ( event.data?.type === 'select-location' ) {
        const city = event.data.city as Partial<VayuLokGlobeCity> | undefined;
        if ( city
          && typeof city.id === 'string'
          && typeof city.name === 'string'
          && Number.isFinite( city.lat )
          && Number.isFinite( city.lng ) ) {
          onSelectLocation?.( city as VayuLokGlobeCity );
        }
      }
    };
    window.addEventListener( 'message', onMessage );
    return () => window.removeEventListener( 'message', onMessage );
  }, [ onModeChange, onSelectLocation ] );

  // A layout effect runs in the same task as the commit. A passive effect can run after a newer
  // frame report has been handled, and would then post the older mode.
  useLayoutEffect( () => {
    if ( frameModeRef.current === mode ) return;
    frameModeRef.current = mode;
    frameRef.current?.contentWindow?.postMessage(
      { source: 'vayulok-page', type: 'mode', mode },
      window.location.origin,
    );
  }, [ mode ] );

  useEffect( () => {
    const syncViewport = () => {
      frameRef.current?.contentWindow?.postMessage(
        {
          source: 'vayulok-page',
          type: 'viewport',
          mobile: window.matchMedia( '(max-width: 767px)' ).matches,
        },
        window.location.origin,
      );
    };
    syncViewport();
    window.addEventListener( 'resize', syncViewport );
    return () => window.removeEventListener( 'resize', syncViewport );
  }, [] );

  return (
    <div className="vag-shell">
      <iframe
        ref={ frameRef }
        className="vag-frame"
        src={ src }
        title="VayuLok interactive air and weather globe"
        loading="eager"
        allow="fullscreen"
        onLoad={ () => {
          // A message posted before load arrives before the frame's listener exists, so always resend.
          frameModeRef.current = mode;
          frameRef.current?.contentWindow?.postMessage(
            { source: 'vayulok-page', type: 'mode', mode },
            window.location.origin,
          );
          frameRef.current?.contentWindow?.postMessage(
            {
              source: 'vayulok-page',
              type: 'viewport',
              mobile: window.matchMedia( '(max-width: 767px)' ).matches,
            },
            window.location.origin,
          );
        } }
      />
      <style jsx>{`
        .vag-shell{
          width:100%;
          min-width:0;
          aspect-ratio:1472 / 1048;
          overflow:hidden;
          border-radius:38px;
        }
        .vag-frame{
          display:block;
          width:100%;
          height:100%;
          border:0;
          background:transparent;
        }
        @media(max-width:767px){
          .vag-shell{width:100%;max-width:100%;border-radius:24px}
        }
      `}</style>
    </div>
  );
};

export default VayuLokApprovedGlobe;
