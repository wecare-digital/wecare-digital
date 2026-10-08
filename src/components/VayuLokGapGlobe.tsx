/**
 * VayuLokGapGlobe — the "Filling the Gap" section for the public /vayulok page.
 *
 * WHAT THIS IS. A SELF-STYLING, self-contained section ported from the approved
 * mock docs/mocks/vayulok-gap-customgl-mock.html (Option B). It renders a two-column
 * "Filling the Gap" block: a left copy column and a right dark panel holding a
 * dot-matrix Earth globe drawn in RAW WebGL — no library, no dependency, no image.
 * The globe surface is generated entirely in code: a Fibonacci-lattice sphere of
 * gl.POINTS whose land dots come from a code-generated landmass mask forming the
 * continents, with the far hemisphere depth-dimmed so it reads as a solid sphere,
 * plus brighter lime/green marker dots clustered over India. It auto-spins, centred
 * on Bharat at rest.
 *
 * WHY SELF-STYLING. styled-jsx does not scope a composite component from its parent's
 * <style jsx>; a page cannot reach into this component's markup. So this component
 * carries BOTH its markup and its own <style jsx> under a `vlg-` scope, the same
 * pattern RotatingHero, BrandBadge and the other brand components use. Every selector
 * is `vlg-` prefixed and the design tokens are declared on the section root
 * (.vlg-fillgap) rather than :root, because the host page owns the document.
 *
 * WHY THE MARKUP STAYS INLINE IN THE RETURN. styled-jsx only attaches its scoping
 * class to elements it can statically see in the return tree, so the whole section's
 * markup is written inline here (never lifted into a variable or child), exactly as
 * the VayuLok hero documents for itself. The ONLY dynamic DOM is inside the <canvas>,
 * which WebGL owns and styled-jsx never needs to touch.
 *
 * LAYOUT CONTRACT — avoids the earlier overlap bug. This renders as a NORMAL in-flow
 * block below the hero's <main>. The section's own background is white (--paper) so it
 * sits cleanly under the hero; only the globe PANEL is dark. There is NO absolute or
 * fixed positioning that escapes the section, NO negative margins, and NO 100vh / viewport
 * tricks. All `position:absolute` inside the component is confined to the globe stage,
 * which is `position:relative` and `overflow:hidden`, so nothing can leak onto the hero.
 *
 * DEGRADE. If WebGL is unavailable or a shader fails to compile/link, a short static
 * fallback message is shown inside the panel — never a crash, never a blank panel. With
 * prefers-reduced-motion the globe is drawn once as a static frame and does not spin.
 *
 * COPY NOTICE. All headline / body copy and the station figures in the left column are
 * ON-BRAND PLACEHOLDER carried over verbatim from the mock. They state the real VayuLok
 * premise (sparse air-quality monitoring across Bharat; VayuLok adds a denser mesh) but
 * the exact wording and numbers must be confirmed with the owner before shipping.
 *
 * NO toggle, NO tabs, NO pills, NO buttons: the panel holds ONLY the globe and a static
 * (non-interactive) legend caption, per the approved design.
 *
 * Colours track src/lib/design-tokens.ts: lime #d1f470, forest green #1a3a2a,
 * ink #1a1a1a, bgSecondary #f9fafb. NO RED anywhere (owner hard rule).
 */

import React, { useEffect, useRef } from 'react';

const VayuLokGapGlobe: React.FC = () => {
  const stageRef = useRef<HTMLDivElement | null>( null );
  const canvasRef = useRef<HTMLCanvasElement | null>( null );
  const fallbackRef = useRef<HTMLDivElement | null>( null );

  useEffect( () => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    const fallback = fallbackRef.current;
    if ( !stage || !canvas ) return;

    // --- cleanup bookkeeping: every listener / RAF / GL resource is torn down
    //     on unmount so a route change cannot leak a context or keep spinning.
    let rafId = 0;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    let loseExt: { loseContext: () => void } | null = null;

    const showFallback = () => {
      if ( fallback ) fallback.classList.add( 'is-on' );
      canvas.style.display = 'none';
    };

    let gl: WebGLRenderingContext | null = null;
    try {
      gl = ( canvas.getContext( 'webgl', { alpha: true, antialias: true, premultipliedAlpha: false } )
        || canvas.getContext( 'experimental-webgl', { alpha: true, antialias: true } ) ) as WebGLRenderingContext | null;
    } catch {
      gl = null;
    }
    if ( !gl ) { showFallback(); return; }
    const glc: WebGLRenderingContext = gl;

    const reduce = typeof window.matchMedia === 'function'
      && window.matchMedia( '(prefers-reduced-motion:reduce)' ).matches;

    /* ---- lat/long helpers ------------------------------------------------- */
    const toRad = ( d: number ) => d * Math.PI / 180;
    // Unit vector for lat/long. Longitude 0 at +Z so phi rotation about Y spins
    // east/west; +Y is north.
    const latLonToXYZ = ( latDeg: number, lonDeg: number ): [ number, number, number ] => {
      const lat = toRad( latDeg ), lon = toRad( lonDeg );
      const cl = Math.cos( lat );
      return [ cl * Math.sin( lon ), Math.sin( lat ), cl * Math.cos( lon ) ];
    };

    /* ---- CODE-GENERATED landmass mask ------------------------------------
       Schematic continent polygons in lat/long; a point-in-polygon test decides
       land. Recognisable India wedge included. NO image is ever loaded. */
    const LAND_POLYS: number[][][] = [
      // Africa
      [ [ 37, -10 ], [ 35, 10 ], [ 31, 33 ], [ 12, 44 ], [ -2, 42 ], [ -18, 36 ], [ -35, 20 ], [ -30, 14 ], [ -6, 9 ], [ 5, -5 ], [ 16, -17 ], [ 30, -16 ], [ 36, -6 ] ],
      // Europe
      [ [ 71, 22 ], [ 60, 55 ], [ 55, 30 ], [ 46, 16 ], [ 36, -9 ], [ 43, -9 ], [ 52, -5 ], [ 60, 5 ], [ 70, 10 ] ],
      // Asia bulk
      [ [ 72, 55 ], [ 75, 105 ], [ 72, 160 ], [ 55, 170 ], [ 40, 140 ], [ 22, 120 ], [ 8, 105 ], [ 20, 80 ], [ 35, 65 ], [ 55, 55 ] ],
      // India wedge (recognisable)
      [ [ 34, 70 ], [ 31, 76 ], [ 27, 80 ], [ 23, 90 ], [ 16, 82 ], [ 8, 78 ], [ 12, 73 ], [ 20, 69 ], [ 27, 68 ] ],
      // Arabian peninsula
      [ [ 30, 35 ], [ 25, 50 ], [ 13, 45 ], [ 12, 43 ], [ 20, 38 ], [ 28, 34 ] ],
      // N America
      [ [ 71, -168 ], [ 72, -95 ], [ 68, -62 ], [ 48, -54 ], [ 30, -82 ], [ 18, -98 ], [ 32, -116 ], [ 55, -130 ], [ 66, -158 ] ],
      // S America
      [ [ 12, -72 ], [ 6, -50 ], [ -10, -35 ], [ -34, -54 ], [ -52, -70 ], [ -38, -73 ], [ -18, -76 ], [ 2, -80 ] ],
      // Australia
      [ [ -12, 113 ], [ -11, 142 ], [ -20, 154 ], [ -37, 150 ], [ -39, 130 ], [ -33, 115 ] ],
      // Greenland
      [ [ 83, -55 ], [ 82, -20 ], [ 70, -22 ], [ 60, -45 ], [ 72, -58 ] ],
      // SE-Asia islands (coarse)
      [ [ 6, 95 ], [ 2, 104 ], [ -6, 106 ], [ -8, 120 ], [ 0, 118 ], [ 7, 100 ] ],
    ];
    const pointInPoly = ( lat: number, lon: number, poly: number[][] ): boolean => {
      // poly points are [lat, lon]; ray-cast in lon/lat space.
      let inside = false;
      for ( let i = 0, j = poly.length - 1; i < poly.length; j = i++ ) {
        const yi = poly[ i ][ 0 ], xi = poly[ i ][ 1 ];
        const yj = poly[ j ][ 0 ], xj = poly[ j ][ 1 ];
        const intersect = ( ( yi > lat ) !== ( yj > lat ) )
          && ( lon < ( xj - xi ) * ( lat - yi ) / ( yj - yi ) + xi );
        if ( intersect ) inside = !inside;
      }
      return inside;
    };
    const isLand = ( lat: number, lon: number ): boolean => {
      if ( lat < -60 ) return true;             // Antarctica cap
      for ( let i = 0; i < LAND_POLYS.length; i++ ) {
        if ( pointInPoly( lat, lon, LAND_POLYS[ i ] ) ) return true;
      }
      return false;
    };

    /* ---- build the land dot cloud (Fibonacci sphere) ---------------------
       Density raised from the mock's 36k to 60k samples so the continents read
       crisply rather than soft; the dot SIZE is correspondingly trimmed below so
       the extra samples sharpen edges instead of blurring them together. */
    const N = 60000;                          // lattice samples (dense dot matrix)
    const GA = Math.PI * ( 3 - Math.sqrt( 5 ) ); // golden angle
    const landPos: number[] = [];             // xyz triples
    for ( let i = 0; i < N; i++ ) {
      const y = 1 - ( i / ( N - 1 ) ) * 2;    // 1..-1
      const r = Math.sqrt( Math.max( 0, 1 - y * y ) );
      const th = GA * i;
      const x = Math.cos( th ) * r;
      const z = Math.sin( th ) * r;
      const lat = Math.asin( y ) * 180 / Math.PI;
      const lon = Math.atan2( x, z ) * 180 / Math.PI;
      if ( isLand( lat, lon ) ) {
        landPos.push( x, y, z );
      }
    }

    /* ---- marker dots: Bharat-concentrated + sparse worldwide ------------- */
    const MARKERS: number[][] = [
      [ 28.6, 77.2 ], [ 19.1, 72.9 ], [ 13.1, 80.3 ], [ 22.6, 88.4 ], [ 12.9, 77.6 ], [ 17.4, 78.5 ],
      [ 26.9, 75.8 ], [ 23.0, 72.6 ], [ 21.1, 79.1 ], [ 18.5, 73.9 ], [ 25.6, 85.1 ], [ 30.7, 76.8 ],
      [ 15.3, 74.1 ], [ 11.0, 76.9 ], [ 26.1, 91.7 ], [ 24.6, 80.0 ], [ 20.3, 85.8 ], [ 31.1, 77.2 ],
      // sparse worldwide scatter
      [ 51.5, -0.1 ], [ 40.7, -74.0 ], [ 1.35, 103.8 ], [ 35.7, 139.7 ], [ -33.9, 151.2 ],
      [ -23.5, -46.6 ], [ 48.9, 2.3 ], [ 25.2, 55.3 ],
    ];
    const markerPos: number[] = [];
    for ( let m = 0; m < MARKERS.length; m++ ) {
      const v = latLonToXYZ( MARKERS[ m ][ 0 ], MARKERS[ m ][ 1 ] );
      // lift markers a touch above the surface so they sit "on" the globe
      markerPos.push( v[ 0 ] * 1.012, v[ 1 ] * 1.012, v[ 2 ] * 1.012 );
    }

    /* ---- GL program ------------------------------------------------------- */
    const VERT = [
      'attribute vec3 aPos;',
      'uniform mat3 uRot;',
      'uniform float uScale;',   // ndc radius of the globe
      'uniform float uAspect;',  // width/height
      'uniform float uPointSize;',
      'varying float vFacing;',  // 1 front .. 0 back (camera looks down +Z)
      'void main(){',
      '  vec3 p = uRot * aPos;',
      '  vFacing = (p.z + 1.0) * 0.5;',           // -1..1 -> 0..1
      '  vec2 pos = vec2(p.x/uAspect, p.y) * uScale;',
      '  gl_Position = vec4(pos, p.z*0.5, 1.0);', // z into depth for gl.LESS
      '  float depthScale = 0.55 + 0.45 * vFacing;',
      '  gl_PointSize = uPointSize * depthScale;',
      '}',
    ].join( '\n' );

    const FRAG = [
      'precision mediump float;',
      'uniform vec3 uColorFront;',
      'uniform vec3 uColorBack;',
      'uniform float uIsMarker;',
      'varying float vFacing;',
      'void main(){',
      '  vec2 c = gl_PointCoord - vec2(0.5);',
      '  float d = length(c);',
      '  if(d > 0.5) discard;',                   // round dots
      '  float edge = smoothstep(0.5, 0.12, d);', // soft but tight edge -> crisper dots
      '  vec3 col = mix(uColorBack, uColorFront, vFacing);',
      '  float facingDim = mix(0.16, 1.0, vFacing);', // back hemisphere dimmer
      '  float a = edge * facingDim;',
      '  if(uIsMarker > 0.5){',
      '     float glow = smoothstep(0.5, 0.0, d);',
      '     col = uColorFront + glow*0.25;',
      '     a = max(edge, glow*0.6) * mix(0.35, 1.0, vFacing);',
      '  }',
      '  gl_FragColor = vec4(col * a, a);',        // premultiplied-ish additive feel
      '}',
    ].join( '\n' );

    const compile = ( type: number, src: string ): WebGLShader | null => {
      const s = glc.createShader( type );
      if ( !s ) return null;
      glc.shaderSource( s, src ); glc.compileShader( s );
      if ( !glc.getShaderParameter( s, glc.COMPILE_STATUS ) ) {
        return null;
      }
      return s;
    };
    const vs = compile( glc.VERTEX_SHADER, VERT );
    const fs = compile( glc.FRAGMENT_SHADER, FRAG );
    if ( !vs || !fs ) { showFallback(); return; }
    const prog = glc.createProgram();
    if ( !prog ) { showFallback(); return; }
    glc.attachShader( prog, vs ); glc.attachShader( prog, fs );
    glc.linkProgram( prog );
    if ( !glc.getProgramParameter( prog, glc.LINK_STATUS ) ) { showFallback(); return; }
    glc.useProgram( prog );

    const aPos = glc.getAttribLocation( prog, 'aPos' );
    const uRot = glc.getUniformLocation( prog, 'uRot' );
    const uScale = glc.getUniformLocation( prog, 'uScale' );
    const uAspect = glc.getUniformLocation( prog, 'uAspect' );
    const uPointSize = glc.getUniformLocation( prog, 'uPointSize' );
    const uColorFront = glc.getUniformLocation( prog, 'uColorFront' );
    const uColorBack = glc.getUniformLocation( prog, 'uColorBack' );
    const uIsMarker = glc.getUniformLocation( prog, 'uIsMarker' );

    const landBuf = glc.createBuffer();
    glc.bindBuffer( glc.ARRAY_BUFFER, landBuf );
    glc.bufferData( glc.ARRAY_BUFFER, new Float32Array( landPos ), glc.STATIC_DRAW );

    const markerBuf = glc.createBuffer();
    glc.bindBuffer( glc.ARRAY_BUFFER, markerBuf );
    glc.bufferData( glc.ARRAY_BUFFER, new Float32Array( markerPos ), glc.STATIC_DRAW );

    const landCount = landPos.length / 3;
    const markerCount = markerPos.length / 3;

    // additive-ish blending for glow on dark panel
    glc.enable( glc.BLEND );
    glc.blendFunc( glc.SRC_ALPHA, glc.ONE );
    glc.enable( glc.DEPTH_TEST );
    glc.depthFunc( glc.LEQUAL );
    glc.clearColor( 0, 0, 0, 0 );

    /* ---- rotation matrix (phi about Y, theta tilt about X) --------------- */
    const rotMat = ( phiA: number, thetaA: number ): Float32Array => {
      const cp = Math.cos( phiA ), sp = Math.sin( phiA );
      const ct = Math.cos( thetaA ), st = Math.sin( thetaA );
      // M = Rx(theta) * Ry(phi); WebGL mat3 uniform expects column-major.
      const m00 = cp, m01 = 0, m02 = sp;
      const m10 = st * sp, m11 = ct, m12 = -st * cp;
      const m20 = -ct * sp, m21 = st, m22 = ct * cp;
      return new Float32Array( [
        m00, m10, m20,
        m01, m11, m21,
        m02, m12, m22,
      ] );
    };

    /* ---- sizing (devicePixelRatio-aware) --------------------------------- */
    const dpr = Math.min( window.devicePixelRatio || 1, 2 );
    const resize = () => {
      const w = stage.clientWidth, h = stage.clientHeight;
      if ( !w || !h ) return;
      canvas.width = Math.round( w * dpr );
      canvas.height = Math.round( h * dpr );
      glc.viewport( 0, 0, canvas.width, canvas.height );
    };
    resize();

    // Orient so Bharat (~80E) faces camera at rest, with a slight northern tilt so
    // India sits centred/front rather than on the limb. Longitude 0 is at +Z; to
    // bring +80E to front we rotate by -80 degrees.
    let phi = toRad( -80 );
    const theta = 0.34;

    const drawFrame = () => {
      if ( disposed ) return;
      resize();
      glc.clear( glc.COLOR_BUFFER_BIT | glc.DEPTH_BUFFER_BIT );

      const aspect = canvas.width / canvas.height;
      const R = rotMat( phi, theta );
      glc.uniformMatrix3fv( uRot, false, R );
      glc.uniform1f( uScale, 0.86 );            // globe fills most of the panel
      glc.uniform1f( uAspect, aspect );

      // Dot size tuned down relative to the denser lattice so continents read crisp.
      const basePt = ( canvas.width / 560 ) * 1.9;

      // --- land dots: dim forest green front, near-black back ---
      glc.bindBuffer( glc.ARRAY_BUFFER, landBuf );
      glc.enableVertexAttribArray( aPos );
      glc.vertexAttribPointer( aPos, 3, glc.FLOAT, false, 0, 0 );
      glc.uniform1f( uPointSize, basePt );
      glc.uniform1f( uIsMarker, 0.0 );
      glc.uniform3f( uColorFront, 0.26, 0.52, 0.36 ); // lit green
      glc.uniform3f( uColorBack, 0.05, 0.10, 0.08 );  // near-black green
      glc.drawArrays( glc.POINTS, 0, landCount );

      // --- marker dots: lime, bigger, glowing ---
      glc.bindBuffer( glc.ARRAY_BUFFER, markerBuf );
      glc.enableVertexAttribArray( aPos );
      glc.vertexAttribPointer( aPos, 3, glc.FLOAT, false, 0, 0 );
      glc.uniform1f( uPointSize, basePt * 3.4 );
      glc.uniform1f( uIsMarker, 1.0 );
      glc.uniform3f( uColorFront, 0.82, 0.96, 0.44 ); // lime #d1f470-ish
      glc.uniform3f( uColorBack, 0.40, 0.55, 0.22 );
      glc.drawArrays( glc.POINTS, 0, markerCount );
    };

    const loop = () => {
      if ( disposed ) return;
      drawFrame();
      phi += 0.0045;                            // slow auto-spin
      rafId = window.requestAnimationFrame( loop );
    };

    // First paint; if the context is lost before drawing, fall back.
    try {
      if ( reduce ) {
        // prefers-reduced-motion: a single static frame, no spin.
        drawFrame();
      } else {
        rafId = window.requestAnimationFrame( loop );
      }
    } catch {
      showFallback();
      return;
    }

    // Keep the globe sharp when the panel resizes (column stack, window resize).
    if ( typeof ResizeObserver === 'function' ) {
      resizeObserver = new ResizeObserver( () => {
        if ( disposed ) return;
        // In reduced-motion mode nothing is looping, so redraw once on resize.
        if ( reduce ) drawFrame();
        // Otherwise the running loop picks up the new size on its next frame.
      } );
      resizeObserver.observe( stage );
    }
    const onWinResize = () => {
      if ( disposed ) return;
      if ( reduce ) drawFrame();
    };
    window.addEventListener( 'resize', onWinResize );

    const loseExtRaw = glc.getExtension( 'WEBGL_lose_context' );
    loseExt = loseExtRaw as ( { loseContext: () => void } | null );

    // --- teardown: cancel the RAF, drop listeners, free GL resources, lose ctx.
    return () => {
      disposed = true;
      if ( rafId ) window.cancelAnimationFrame( rafId );
      window.removeEventListener( 'resize', onWinResize );
      if ( resizeObserver ) resizeObserver.disconnect();
      try {
        glc.deleteBuffer( landBuf );
        glc.deleteBuffer( markerBuf );
        glc.deleteProgram( prog );
        glc.deleteShader( vs );
        glc.deleteShader( fs );
      } catch {
        /* context may already be gone; nothing to free. */
      }
      if ( loseExt ) {
        try { loseExt.loseContext(); } catch { /* best effort */ }
      }
    };
  }, [] );

  return (
    <section className="vlg-fillgap" aria-labelledby="vlg-heading">
      <div className="vlg-section">
        <div className="vlg-wrap">
          <div className="vlg-grid">

            {/* LEFT: copy. MOCK COPY — placeholder, confirm wording and figures with
                owner before shipping (carried verbatim from the Option B mock). */}
            <div className="vlg-col-left">
              <p className="vlg-eyebrow">The coverage gap</p>
              <h2 className="vlg-h2" id="vlg-heading">
                Filling the <span className="vlg-h2-accent">gap</span> in Bharat&rsquo;s air
              </h2>
              {/* MOCK COPY — placeholder */}
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

            {/* RIGHT: the custom-WebGL dot-matrix globe (ONLY the globe + static legend) */}
            <div className="vlg-col-right">
              <div className="vlg-stage" ref={ stageRef }>
                <canvas
                  className="vlg-canvas"
                  ref={ canvasRef }
                  role="img"
                  aria-label="A dark dot-matrix globe centred on Bharat, rendered in raw WebGL. Continents are drawn as fine dots on a sphere, with the far side dimmed so it reads as a solid globe; brighter lime and green dots mark air-quality monitoring points concentrated over India with a sparse worldwide scatter. The globe slowly spins."
                />

                {/* Static fallback if WebGL is unavailable */}
                <div
                  className="vlg-fallback"
                  ref={ fallbackRef }
                  role="img"
                  aria-label="Static fallback: the dot-matrix globe cannot be rendered in this browser."
                >
                  <b>Globe preview</b>
                  <span>Your browser can&rsquo;t render WebGL here. On a supported browser this panel shows a slowly spinning dot-matrix globe centred on Bharat with the air-quality coverage dots.</span>
                </div>

                {/* STATIC legend caption (NOT a control — no toggle) */}
                <div className="vlg-legend" aria-hidden="true">
                  <div className="vlg-legend-row">
                    <span className="vlg-legend-dot is-existing" /> Existing monitors
                  </div>
                  <div className="vlg-legend-row">
                    <span className="vlg-legend-dot is-vayulok" /> VayuLok mesh
                  </div>
                </div>
              </div>
              <p className="vlg-cap">
                Illustrative dot-matrix globe (raw WebGL). Data-point positions are schematic, not survey data.
              </p>
            </div>

          </div>
        </div>
      </div>

      <style jsx>{`
        /* ---- SECTION ROOT. Tokens live here, not on :root. --------------- */
        .vlg-fillgap{
          font-family:'Inter',ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          color:#1a1a1a;                      /* colors.text */
          -webkit-font-smoothing:antialiased;

          /* Surfaces */
          --paper:#ffffff;                    /* colors.white — the section sits under the hero */
          --panel:#0a0a0a;                    /* the globe panel is dark (reference look) */
          --panel-edge:#161616;
          --lime:#d1f470;                     /* colors.lime — brand accent */
          --green:#1a3a2a;                    /* colors.primary — brand primary */
          --green-bright:#4ade80;             /* existing-data dot colour, reads on dark */
          --hair:#e5e7eb;                     /* colors.border */

          /* Ink */
          --ink-head:#1a1a1a;                 /* colors.text — headline */
          --ink-body:rgba(0,0,0,.72);         /* body copy */
          --ink-muted:rgba(0,0,0,.54);        /* colors.textSecondary */
          --ink-grey:#6b7280;                 /* colors.textMuted */

          /* Shape — radius.xl from design-tokens.ts */
          --r-panel:14px;
        }

        /* SCOPED box-sizing. Not a bare universal rule: scoped under .vlg-fillgap so
           it cannot reach outside the block. */
        .vlg-fillgap,.vlg-fillgap :global(*){box-sizing:border-box}

        /* ---- container: ~1300px measure, centred ----------------------- */
        .vlg-wrap{width:100%;max-width:1300px;margin:0 auto;padding:0 24px}

        /* ---- the section — light surface, generous vertical padding, in-flow.
             No negative margins, no absolute/fixed positioning, no 100vh: it
             renders cleanly BELOW the hero. ------------------------------- */
        .vlg-section{background:var(--paper);padding:72px 0}

        /* ---- two-column grid: left copy ~40%, right globe ~60% --------- */
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

        /* ---- type ladder ----------------------------------------------- */
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

        /* ---- a quiet stat row under the copy --------------------------- */
        .vlg-stats{
          display:flex;flex-wrap:wrap;gap:28px;margin-top:28px;
          padding-top:24px;border-top:1px solid var(--hair);
        }
        .vlg-stat{min-width:0}
        .vlg-stat b{display:block;font-size:28px;font-weight:700;letter-spacing:-.6px;color:var(--green)}
        .vlg-stat span{display:block;margin-top:2px;font-size:13px;line-height:1.35;color:var(--ink-grey)}

        /* ---- the globe stage — dark rounded panel. position:relative +
             overflow:hidden CONFINES every absolute child to this box, so
             nothing can leak onto the hero above. ----------------------- */
        .vlg-stage{
          position:relative;width:100%;
          aspect-ratio:1/1;max-height:580px;
          border:1px solid var(--panel-edge);border-radius:var(--r-panel);
          background:radial-gradient(70% 70% at 50% 46%,#101512 0%,#0a0a0a 70%);
          overflow:hidden;
          box-shadow:0 8px 40px rgba(0,0,0,.18);
        }
        .vlg-canvas{position:absolute;inset:0;width:100%;height:100%;display:block}

        /* ---- WebGL / load fallback panel (shown if WebGL can't run) ----- */
        .vlg-fallback{
          position:absolute;inset:0;display:none;
          flex-direction:column;align-items:center;justify-content:center;gap:10px;
          padding:32px;text-align:center;color:rgba(255,255,255,.78);
          background:radial-gradient(60% 60% at 50% 46%,#15321f 0%,#0a0a0a 72%);
        }
        .vlg-fallback.is-on{display:flex}
        .vlg-fallback b{font-size:15px;font-weight:700;color:#fff}
        .vlg-fallback span{font-size:13px;line-height:1.5;max-width:34ch;color:rgba(255,255,255,.7)}

        /* ---- static legend caption (NOT interactive — no toggle) ------- */
        .vlg-legend{
          position:absolute;left:16px;bottom:16px;z-index:2;
          display:flex;flex-direction:column;gap:8px;
          padding:12px 14px;
          background:rgba(10,10,10,.55);backdrop-filter:blur(6px);
          border:1px solid rgba(255,255,255,.12);border-radius:12px;
          pointer-events:none;
        }
        .vlg-legend-row{display:flex;align-items:center;gap:9px;font-size:12px;font-weight:600;color:rgba(255,255,255,.86)}
        .vlg-legend-dot{width:10px;height:10px;border-radius:9999px;flex:0 0 auto}
        .vlg-legend-dot.is-existing{background:var(--green-bright);box-shadow:0 0 8px rgba(74,222,128,.7)}
        .vlg-legend-dot.is-vayulok{background:var(--lime);box-shadow:0 0 8px rgba(209,244,112,.75)}

        /* ---- caption under the stage ----------------------------------- */
        .vlg-cap{margin:12px 0 0;font-size:12px;line-height:1.45;color:var(--ink-muted)}
      `}</style>
    </section>
  );
};

export default VayuLokGapGlobe;
