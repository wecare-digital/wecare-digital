import React, { useEffect, useMemo, useState } from 'react';

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY || '';

const VayuLokApprovedGlobe: React.FC = () => {
  const [ mounted, setMounted ] = useState( false );

  useEffect( () => {
    setMounted( true );
  }, [] );

  const src = useMemo( () => {
    if ( !mounted ) return '/vayulok-globe.html';
    return MAPS_KEY
      ? `/vayulok-globe.html#key=${encodeURIComponent( MAPS_KEY )}`
      : '/vayulok-globe.html';
  }, [ mounted ] );

  return (
    <div className="vag-shell">
      <iframe
        className="vag-frame"
        src={ src }
        title="VayuLok interactive air and weather globe"
        loading="eager"
        allow="fullscreen"
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
          .vag-shell{border-radius:24px}
        }
      `}</style>
    </div>
  );
};

export default VayuLokApprovedGlobe;
