import React, { useEffect, useRef, useState } from 'react';

/**
 * VayuLok "Filling the Gap" section, rendered on /vayulok/ between the rotating-word
 * hero and the live-wired VayuLokLive block.
 *
 * WHAT THIS IS. The REAL section ported verbatim from docs/mocks/vayulok-filling-gap-mock.html.
 * The mock is a VISUAL reference only; its scoped `vlg-` stylesheet and the Canvas-2D dotted
 * globe are carried over here unchanged in behaviour. The mock's PREVIEW-ONLY pieces are NOT
 * ported: the data-vl-preview-only reset, the .vlg-preview-shell wrapper, the one-line MOCK
 * disclosure note, and the two dashed .vlg-context "out of scope" placeholders that stood in
 * for the hero above and the live section below. On the real page those neighbours are the
 * actual hero and VayuLokLive, so the placeholders are dropped.
 *
 * NO GLOBAL STYLES. Every selector is scoped under the `vlg-` prefix and the custom
 * properties are declared on the SECTION ROOT (.vlg-fillgap), never on :root, exactly as the
 * mock documents, because this component mounts inside a Next.js page that owns the document.
 * No reset, no html/body rule, no bare `*` rule, no page-level background / margin / font.
 * Tokens map onto src/lib/design-tokens.ts (lime #d1f470, forest green #1a3a2a, greys). NO
 * RED anywhere, honouring this page's owner constraint.
 *
 * styled-jsx only attaches its scoping class to markup it can statically see, so every
 * element stays INLINE in this component's return tree, matching the VayuLokLive and the
 * /vayulok hero conventions.
 *
 * THE GLOBE. Pure Canvas 2D, zero network dependency, no images. A fibonacci-sphere land
 * point cloud tested against a coarse lon/lat land mask, rotating about a tilted axis, with
 * two scattered data layers (sparse dark-green "Existing", dense lime "VayuLok") toggled by
 * the pill control. Under prefers-reduced-motion the globe renders a single static frame.
 *
 * COPY IS PLACEHOLDER. The left-column headline, body and station figures are on-brand
 * placeholder from the mock and must be confirmed with the owner before they are treated as
 * fact; they state the real VayuLok premise (sparse official monitoring across Bharat;
 * VayuLok adds a denser mesh) with illustrative numbers.
 */

const VayuLokFillingGap: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement | null>( null );
  // Layer visibility is React state so the pressed pill and the painted globe stay in sync.
  // Mirrors the mock's `show = { existing, vayulok }` with the three-way Existing/VayuLok/Both
  // control. Default: Existing only, matching the mock's aria-pressed defaults.
  const [ show, setShow ] = useState<{ existing: boolean; vayulok: boolean }>( { existing: true, vayulok: false } );
  // The animation loop reads layer visibility through a ref so the long-lived rAF closure
  // always sees the latest value without being torn down and rebuilt on every toggle.
  const showRef = useRef( show );
  // Holds the active frame() painter so a reduced-motion layer toggle can repaint at once.
  const frameRef = useRef<( () => void ) | null>( null );

  // Keep the ref in step with state (writing a ref during render is disallowed).
  useEffect( () => { showRef.current = show; }, [ show ] );

  useEffect( () => {
    const canvas = canvasRef.current;
    if ( !canvas || !canvas.getContext ) return;
    const ctx = canvas.getContext( '2d' );
    if ( !ctx ) return;

    const COL = {
      land: '#1a3a2a',      // continent dots — brand primary
      landFar: '#9bb0a4',   // back-hemisphere land, dimmed
      existing: '#1a3a2a',  // existing monitors — forest green
      vayulok: '#d1f470',   // VayuLok coverage — lime
      vayulokEdge: '#1a3a2a',
    };

    const reduce = typeof window.matchMedia === 'function'
      && window.matchMedia( '(prefers-reduced-motion:reduce)' ).matches;

    // Coarse land mask: rectangles in [lonMin,lonMax,latMin,latMax] degrees. Schematic, not GIS.
    const LAND: number[][] = [
      [ -17, 52, -35, 37 ],    // Africa
      [ -10, 40, 36, 60 ],     // Europe
      [ 5, 30, 55, 71 ],       // Scandinavia
      [ 40, 145, 8, 70 ],      // Asia (bulk)
      [ 68, 90, 7, 32 ],       // India/Bharat
      [ 95, 122, -10, 20 ],    // SE Asia
      [ -168, -52, 15, 72 ],   // N America
      [ -92, -77, 8, 18 ],     // C America
      [ -82, -35, -55, 12 ],   // S America
      [ 113, 154, -39, -11 ],  // Australia
      [ -55, -20, 60, 83 ],    // Greenland
    ];
    function isLand( lon: number, lat: number ): boolean {
      for ( let i = 0; i < LAND.length; i++ ) {
        const b = LAND[ i ];
        if ( lon >= b[ 0 ] && lon <= b[ 1 ] && lat >= b[ 2 ] && lat <= b[ 3 ] ) return true;
      }
      return false;
    }

    interface Vec { x: number; y: number; z: number; lon: number; lat: number; }
    function toVec( lon: number, lat: number ): Vec {
      const la = lat * Math.PI / 180, lo = lon * Math.PI / 180;
      return {
        x: Math.cos( la ) * Math.cos( lo ),
        y: Math.sin( la ),
        z: Math.cos( la ) * Math.sin( lo ),
        lon, lat,
      };
    }

    // Build the land point cloud via a fibonacci sphere.
    const land: Vec[] = [];
    ( function () {
      const N = 2600, gold = Math.PI * ( 3 - Math.sqrt( 5 ) );
      for ( let i = 0; i < N; i++ ) {
        const y = 1 - ( i / ( N - 1 ) ) * 2;
        const r = Math.sqrt( Math.max( 0, 1 - y * y ) );
        const theta = gold * i;
        const x = Math.cos( theta ) * r, z = Math.sin( theta ) * r;
        const lat = Math.asin( y ) * 180 / Math.PI;
        const lon = Math.atan2( z, x ) * 180 / Math.PI;
        if ( isLand( lon, lat ) ) land.push( toVec( lon, lat ) );
      }
    } )();

    // Scatter the two data layers on land.
    function scatter( count: number, biasIndia: boolean ): Vec[] {
      const pts: Vec[] = [];
      let tries = 0;
      while ( pts.length < count && tries < count * 40 ) {
        tries++;
        let lon: number, lat: number;
        if ( biasIndia && Math.random() < 0.55 ) {
          lon = 68 + Math.random() * 22;
          lat = 7 + Math.random() * 25;
        } else {
          lon = -180 + Math.random() * 360;
          lat = -58 + Math.random() * 130;
        }
        if ( isLand( lon, lat ) ) pts.push( toVec( lon, lat ) );
      }
      return pts;
    }
    const existing = scatter( 70, false );   // sparse
    const vayulok = scatter( 360, true );     // dense, India-biased

    // Resize handling (devicePixelRatio aware).
    let W = 0, H = 0, R = 0, dpr = 1;
    function resize() {
      const rect = canvas!.getBoundingClientRect();
      dpr = Math.min( window.devicePixelRatio || 1, 2 );
      W = Math.max( 1, Math.round( rect.width ) );
      H = Math.max( 1, Math.round( rect.height ) );
      canvas!.width = Math.round( W * dpr );
      canvas!.height = Math.round( H * dpr );
      ctx!.setTransform( dpr, 0, 0, dpr, 0, 0 );
      R = Math.min( W, H ) * 0.40;
    }

    // Rotation about a tilted axis.
    const tilt = -18 * Math.PI / 180;         // axial tilt
    let yaw = -( 78 * Math.PI / 180 );        // rest yaw so Bharat (~78°E) faces us
    const cosT = Math.cos( tilt ), sinT = Math.sin( tilt );

    interface Projected { sx: number; sy: number; depth: number; }
    function project( p: Vec ): Projected {
      const cy = Math.cos( yaw ), sy = Math.sin( yaw );
      const x = p.x * cy + p.z * sy;
      const z = -p.x * sy + p.z * cy;
      const y = p.y;
      const y2 = y * cosT - z * sinT;
      const z2 = y * sinT + z * cosT;
      return { sx: W / 2 + x * R, sy: H / 2 - y2 * R, depth: z2 };
    }

    function drawDot( p: Vec, baseR: number, nearCol: string, farCol: string, limeMode: boolean ) {
      const pr = project( p );
      if ( pr.depth < -0.02 ) return;          // back hemisphere: skip
      const t = ( pr.depth + 1 ) / 2;          // 0 back .. 1 front
      const size = baseR * ( 0.55 + 0.65 * t );
      ctx!.globalAlpha = 0.35 + 0.65 * t;
      ctx!.fillStyle = ( t > 0.5 ? nearCol : farCol );
      ctx!.beginPath();
      ctx!.arc( pr.sx, pr.sy, size, 0, Math.PI * 2 );
      ctx!.fill();
      if ( limeMode && t > 0.45 ) {            // lime markers get a green rim
        ctx!.globalAlpha = ( 0.35 + 0.65 * t ) * 0.9;
        ctx!.lineWidth = 0.8;
        ctx!.strokeStyle = COL.vayulokEdge;
        ctx!.stroke();
      }
    }

    function frame() {
      ctx!.clearRect( 0, 0, W, H );

      // Faint sphere disc so the ball reads even where land is sparse.
      ctx!.globalAlpha = 1;
      ctx!.beginPath();
      ctx!.arc( W / 2, H / 2, R * 1.04, 0, Math.PI * 2 );
      ctx!.fillStyle = 'rgba(26,58,42,0.035)';
      ctx!.fill();

      // Land dots.
      for ( let i = 0; i < land.length; i++ ) {
        drawDot( land[ i ], Math.max( 1.1, R * 0.013 ), COL.land, COL.landFar, false );
      }
      // Data layers on top.
      const state = showRef.current;
      if ( state.existing ) {
        for ( let j = 0; j < existing.length; j++ ) {
          drawDot( existing[ j ], Math.max( 2.0, R * 0.028 ), COL.existing, '#4b6b58', false );
        }
      }
      if ( state.vayulok ) {
        for ( let k = 0; k < vayulok.length; k++ ) {
          drawDot( vayulok[ k ], Math.max( 1.8, R * 0.022 ), COL.vayulok, '#aebf7a', true );
        }
      }
      ctx!.globalAlpha = 1;
    }

    let raf = 0;
    function tick() {
      if ( !reduce ) yaw += 0.0022;            // slow rotation
      frame();
      if ( !reduce ) raf = window.requestAnimationFrame( tick );
    }

    // The toggle changes React state; expose a repaint for the reduced-motion case so a
    // layer switch still updates the static frame immediately.
    frameRef.current = frame;

    function onResize() {
      resize();
      if ( reduce ) frame();
    }
    window.addEventListener( 'resize', onResize );

    resize();
    if ( reduce ) frame();
    else tick();

    return () => {
      window.removeEventListener( 'resize', onResize );
      if ( raf ) window.cancelAnimationFrame( raf );
      frameRef.current = null;
    };
  }, [] );

  function setState( existing: boolean, vayulok: boolean ) {
    setShow( { existing, vayulok } );
    showRef.current = { existing, vayulok };
    if ( frameRef.current ) frameRef.current();  // repaint immediately for the static frame
  }

  return (
    <section className="vlg-fillgap" aria-labelledby="vlg-heading">
      <div className="vlg-section">
        <div className="vlg-wrap">
          <div className="vlg-grid">

            {/* LEFT: copy. Placeholder on-brand copy — confirm wording / figures with owner. */}
            <div className="vlg-col-left">
              <p className="vlg-eyebrow">The coverage gap</p>
              <h2 className="vlg-h2" id="vlg-heading">
                Filling the <span className="vlg-h2-accent">gap</span> in Bharat&rsquo;s air
              </h2>
              <p className="vlg-body">
                Across most of Bharat, air-quality truth is <strong>thin on the ground</strong>.
                Official monitoring stations cluster in a handful of metros, leaving whole
                districts, highways and smaller towns with no reading at all &mdash; just estimates
                stretched over hundreds of kilometres.
              </p>
              <p className="vlg-body">
                <strong>VayuLok closes that gap.</strong> A denser mesh of low-cost sensors fills
                in the blank spaces between the official stations, so a street, a school or a
                neighbourhood can finally see its own air instead of a city-wide average.
              </p>

              <div className="vlg-stats">
                <div className="vlg-stat">
                  <b>~1 in 20</b>
                  <span>districts with a reference-grade monitor today</span>
                </div>
                <div className="vlg-stat">
                  <b>10&times;</b>
                  <span>denser coverage targeted by the VayuLok mesh</span>
                </div>
              </div>
            </div>

            {/* RIGHT: the dotted-earth globe visual. */}
            <div className="vlg-col-right">
              <div className="vlg-stage">
                <canvas
                  className="vlg-canvas"
                  ref={ canvasRef }
                  role="img"
                  aria-label="Rotating dot-matrix globe centred on Bharat. Sparse dark-green dots mark today's existing monitors; denser lime dots mark the VayuLok coverage layer."
                />

                {/* TOGGLE: switch / overlay the two data layers. */}
                <div className="vlg-toggle" role="group" aria-label="Data layer">
                  <button
                    type="button"
                    className="vlg-layer"
                    aria-pressed={ show.existing && !show.vayulok }
                    onClick={ () => setState( true, false ) }
                  >Existing</button>
                  <button
                    type="button"
                    className="vlg-layer"
                    aria-pressed={ show.vayulok && !show.existing }
                    onClick={ () => setState( false, true ) }
                  >VayuLok</button>
                  <button
                    type="button"
                    className="vlg-layer"
                    aria-pressed={ show.existing && show.vayulok }
                    onClick={ () => setState( true, true ) }
                  >Both</button>
                </div>

                {/* LEGEND */}
                <div className="vlg-legend" aria-hidden="true">
                  <div className="vlg-legend-row">
                    <span className="vlg-legend-dot is-existing"></span> Existing data
                  </div>
                  <div className="vlg-legend-row">
                    <span className="vlg-legend-dot is-vayulok"></span> VayuLok data
                  </div>
                </div>
              </div>
              <p className="vlg-cap">
                Illustrative dot-matrix globe. Point positions are schematic, not survey data.
              </p>
            </div>

          </div>
        </div>
      </div>

      <style jsx>{`
        /* ========================================================================
           VAYULOK "FILLING THE GAP" SECTION — scoped stylesheet.
           Tokens live on the section root (.vlg-fillgap), not :root. NO RED.
           Values cited to src/lib/design-tokens.ts.
           ===================================================================== */
        .vlg-fillgap{
          font-family:'Inter',ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          color:#1a1a1a;                      /* colors.text */
          -webkit-font-smoothing:antialiased;

          /* Surfaces */
          --paper:#ffffff;                    /* colors.white */
          --ground:#f9fafb;                   /* colors.bgSecondary — this section is LIGHT */
          --lime:#d1f470;                     /* colors.lime — brand accent */
          --lime-hover:#c5e866;               /* colors.limeHover */
          --lime-tint:rgba(209,244,112,.22);  /* lime at low alpha, globe glow */
          --green:#1a3a2a;                    /* colors.primary — primary / continent dots */
          --green-hover:#0f2a1d;              /* colors.primaryHover */
          --hair:#e5e7eb;                     /* colors.border */

          /* Ink */
          --ink-head:#1a1a1a;                 /* colors.text — headline */
          --ink-body:rgba(0,0,0,.72);         /* body copy */
          --ink-muted:rgba(0,0,0,.54);        /* colors.textSecondary */
          --ink-grey:#6b7280;                 /* colors.textMuted */

          /* Shape — radii from design-tokens.ts radius */
          --r-panel:14px;                     /* radius.xl */
          --r-btn:13px;                       /* radius.btn */
          --r-pill:9999px;                    /* radius.full */

          /* Motion — motion.easeOut */
          --e-glide:cubic-bezier(.16,1,.3,1);
        }

        /* Scoped box-sizing — cannot reach outside the block. */
        .vlg-fillgap,.vlg-fillgap :global(*){box-sizing:border-box}

        .vlg-wrap{width:100%;max-width:1300px;margin:0 auto;padding:0 24px}

        /* The section — light surface, generous vertical padding. */
        .vlg-section{background:var(--paper);padding:72px 0}

        /* Two-column grid: left copy ~40%, right globe ~60%. */
        .vlg-grid{
          display:grid;
          grid-template-columns:minmax(0,1fr);
          gap:40px;align-items:center;
        }
        @media(min-width:768px){
          .vlg-grid{grid-template-columns:minmax(0,40%) minmax(0,60%);gap:56px}
        }
        .vlg-col-left{min-width:0}
        .vlg-col-right{min-width:0}

        /* Type ladder. */
        .vlg-eyebrow{
          margin:0 0 16px;font-size:12px;font-weight:700;
          letter-spacing:.08em;text-transform:uppercase;color:var(--green);
        }
        .vlg-h2{
          margin:0 0 20px;
          font-size:clamp(30px,3.4vw,46px);font-weight:700;line-height:1.05;
          letter-spacing:-1.4px;color:var(--ink-head);
        }
        .vlg-h2 .vlg-h2-accent{
          background:linear-gradient(transparent 62%,var(--lime) 62%);
          padding:0 .04em;
        }
        .vlg-body{
          margin:0 0 18px;max-width:52ch;
          font-size:18px;font-weight:400;line-height:1.55;letter-spacing:-.1px;color:var(--ink-body);
        }
        .vlg-body:last-of-type{margin-bottom:0}
        .vlg-body strong{color:var(--ink-head);font-weight:600}

        /* A quiet stat row under the copy. */
        .vlg-stats{
          display:flex;flex-wrap:wrap;gap:28px;margin-top:28px;
          padding-top:24px;border-top:1px solid var(--hair);
        }
        .vlg-stat{min-width:0}
        .vlg-stat b{display:block;font-size:28px;font-weight:700;letter-spacing:-.6px;color:var(--green)}
        .vlg-stat span{display:block;margin-top:2px;font-size:13px;line-height:1.35;color:var(--ink-grey)}

        /* The globe stage. Soft lime radial glow behind a canvas globe; no image loaded. */
        .vlg-stage{
          position:relative;width:100%;
          aspect-ratio:1/1;max-height:560px;
          border:1px solid var(--hair);border-radius:var(--r-panel);
          background:
            radial-gradient(60% 60% at 50% 46%,var(--lime-tint) 0%,rgba(209,244,112,0) 62%),
            var(--ground);
          overflow:hidden;
        }
        .vlg-canvas{position:absolute;inset:0;width:100%;height:100%;display:block}

        /* Legend (bottom-left). */
        .vlg-legend{
          position:absolute;left:16px;bottom:16px;z-index:2;
          display:flex;flex-direction:column;gap:8px;
          padding:12px 14px;
          background:rgba(255,255,255,.86);backdrop-filter:blur(4px);
          border:1px solid var(--hair);border-radius:12px;
        }
        .vlg-legend-row{display:flex;align-items:center;gap:9px;font-size:12px;font-weight:600;color:var(--ink-body)}
        .vlg-legend-dot{width:9px;height:9px;border-radius:9999px;flex:0 0 auto}
        .vlg-legend-dot.is-existing{background:var(--green)}
        .vlg-legend-dot.is-vayulok{background:var(--lime);border:1.5px solid var(--green)}

        /* Toggle control (top-left), role: map control (pill group). */
        .vlg-toggle{
          position:absolute;left:16px;top:16px;z-index:2;
          display:inline-flex;gap:4px;padding:4px;
          background:rgba(255,255,255,.86);backdrop-filter:blur(4px);
          border:1px solid var(--hair);border-radius:var(--r-pill);
        }
        .vlg-layer{
          appearance:none;border:0;background:transparent;cursor:pointer;
          min-height:34px;padding:0 14px;border-radius:var(--r-pill);
          font:inherit;font-size:13px;font-weight:700;line-height:1;letter-spacing:-.1px;
          color:var(--ink-body);
          transition:background-color .18s var(--e-glide),color .18s var(--e-glide);
        }
        .vlg-layer:hover{background:#f5f5f5}
        .vlg-layer[aria-pressed="true"]{
          /* active = lime; dark type keeps contrast #1a3a2a on #d1f470 ≈ 11.8:1. */
          background:var(--lime);color:var(--green);
        }
        .vlg-layer:focus-visible{outline:3px solid var(--green);outline-offset:2px}

        /* Caption under the stage. */
        .vlg-cap{margin:12px 0 0;font-size:12px;line-height:1.45;color:var(--ink-muted)}

        /* Reduced motion: the globe renders a static frame (handled in JS too). */
        @media(prefers-reduced-motion:reduce){
          .vlg-stage{background:
            radial-gradient(60% 60% at 50% 46%,var(--lime-tint) 0%,rgba(209,244,112,0) 62%),
            var(--ground);}
        }
      `}</style>
    </section>
  );
};

export default VayuLokFillingGap;
