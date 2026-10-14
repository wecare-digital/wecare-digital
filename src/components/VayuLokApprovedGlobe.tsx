import React from 'react';

const VayuLokApprovedGlobe: React.FC = () => (
  <div className="vag-shell">
    <iframe
      className="vag-frame"
      src="/vayulok-globe.html"
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

export default VayuLokApprovedGlobe;
