import React, { useEffect, useMemo, useRef, useState } from 'react';

const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY || '';

type Layer = 'air' | 'weather';

interface CityMeta {
  id: string;
  name: string;
  lat: number;
  lon: number;
  marker: string;
}

interface CityData {
  air?: { aqi?: number; category?: string; dominantPollutant?: string };
  weather?: { temperatureC?: number; condition?: string; humidity?: number; precipitationPercent?: number };
  fetchedAt?: number;
  error?: boolean;
}

interface DotPoint {
  x: number;
  y: number;
  z: number;
  color: string;
  size: number;
}

const DELHI: CityMeta = { id: 'delhi', name: 'Delhi', lat: 28.6139, lon: 77.2090, marker: '#f0a818' };
const BENGALURU: CityMeta = { id: 'bengaluru', name: 'Bengaluru', lat: 12.9716, lon: 77.5946, marker: '#9849e8' };

// VayuLok keeps the page-level no-true-red owner constraint. The seventh warm data
// hue is the already-approved terracotta instead of #dc2626.
const DOT_PALETTE = [ '#d1f470', '#1a3a2a', '#3da35a', '#2563eb', '#9849e8', '#f0a818', '#c2591b' ];

const HOME_YAW = 10 * Math.PI / 180;
const HOME_TILT = -14 * Math.PI / 180;
const TILT_MIN = -58 * Math.PI / 180;
const TILT_MAX = 42 * Math.PI / 180;

function seededRandomFactory( seedStart: number ): () => number {
  let seed = seedStart >>> 0;
  return () => {
    seed = ( seed * 1664525 + 1013904223 ) >>> 0;
    return seed / 4294967296;
  };
}

function latLonToVec( lat: number, lon: number ): [ number, number, number ] {
  const la = lat * Math.PI / 180;
  const lo = lon * Math.PI / 180;
  return [ Math.cos( la ) * Math.cos( lo ), Math.sin( la ), Math.cos( la ) * Math.sin( lo ) ];
}

function airAccent( aqi?: number ): string {
  if ( !Number.isFinite( aqi ) ) return '#3da35a';
  if ( ( aqi as number ) <= 50 ) return '#3da35a';
  if ( ( aqi as number ) <= 100 ) return '#d1f470';
  if ( ( aqi as number ) <= 200 ) return '#f0a818';
  if ( ( aqi as number ) <= 300 ) return '#c2591b';
  return '#9849e8';
}

function weatherAccent( condition?: string ): string {
  const text = String( condition || '' ).toLowerCase();
  if ( /rain|storm|thunder|snow|sleet/.test( text ) ) return '#2563eb';
  if ( /cloud|fog|haze|mist/.test( text ) ) return '#9849e8';
  return '#f0a818';
}

function readingText( layer: Layer, data?: CityData ): string {
  if ( !data ) return MAPS_KEY ? 'Loading live data…' : 'Live key required';
  if ( data.error ) return 'Live data unavailable';
  if ( layer === 'air' ) {
    const aqi = data.air?.aqi;
    if ( !Number.isFinite( aqi ) ) return 'AIR · unavailable';
    const bits = [ 'AQI ' + Math.round( aqi as number ) ];
    if ( data.air?.category ) bits.push( data.air.category );
    if ( data.air?.dominantPollutant ) bits.push( data.air.dominantPollutant.toUpperCase() );
    return bits.join( ' · ' );
  }
  const w = data.weather || {};
  const bits: string[] = [];
  if ( Number.isFinite( w.temperatureC ) ) bits.push( Math.round( w.temperatureC as number ) + '°C' );
  if ( w.condition ) bits.push( w.condition );
  if ( Number.isFinite( w.humidity ) ) bits.push( 'RH ' + Math.round( w.humidity as number ) + '%' );
  if ( Number.isFinite( w.precipitationPercent ) ) bits.push( 'Rain ' + Math.round( w.precipitationPercent as number ) + '%' );
  return bits.length ? bits.join( ' · ' ) : 'WEATHER · unavailable';
}

function ageText( fetchedAt?: number ): string {
  if ( !fetchedAt ) return MAPS_KEY ? 'LIVE · CONNECTING' : 'LIVE · KEY REQUIRED';
  const mins = Math.floor( Math.max( 0, Date.now() - fetchedAt ) / 60000 );
  return mins < 1 ? 'LIVE · UPDATED NOW' : 'LIVE · UPDATED ' + mins + 'M AGO';
}

function pointColorForLocation( lat: number, lon: number ): string {
  const n = Math.abs( Math.round( lat * 100 ) * 31 + Math.round( lon * 100 ) * 17 );
  return DOT_PALETTE[ n % DOT_PALETTE.length ];
}

function currentAqiFromPayload( payload: Record<string, any> ): CityData['air'] {
  const indexes = Array.isArray( payload?.indexes ) ? payload.indexes : [];
  const idx = indexes.find( ( item: any ) => item?.code === 'ind_cpcb' )
    || indexes.find( ( item: any ) => item?.code === 'uaqi' )
    || indexes[ 0 ]
    || {};
  return {
    aqi: Number.isFinite( Number( idx?.aqi ) ) ? Number( idx.aqi ) : undefined,
    category: typeof idx?.category === 'string' ? idx.category : undefined,
    dominantPollutant: typeof idx?.dominantPollutant === 'string' ? idx.dominantPollutant : undefined,
  };
}

function currentWeatherFromPayload( payload: Record<string, any> ): CityData['weather'] {
  const temp = Number( payload?.temperature?.degrees );
  const humidity = Number( payload?.relativeHumidity );
  const precipitation = Number( payload?.precipitation?.probability?.percent );
  return {
    temperatureC: Number.isFinite( temp ) ? temp : undefined,
    condition: payload?.weatherCondition?.description?.text || payload?.weatherCondition?.type || undefined,
    humidity: Number.isFinite( humidity ) ? humidity : undefined,
    precipitationPercent: Number.isFinite( precipitation ) ? precipitation : undefined,
  };
}

async function fetchAir( city: CityMeta ): Promise<CityData['air']> {
  const response = await fetch(
    'https://airquality.googleapis.com/v1/currentConditions:lookup?key=' + encodeURIComponent( MAPS_KEY ),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify( {
        location: { latitude: city.lat, longitude: city.lon },
        extraComputations: [ 'LOCAL_AQI', 'POLLUTANT_CONCENTRATION', 'DOMINANT_POLLUTANT_CONCENTRATION' ],
        languageCode: 'en',
        universalAqi: true,
      } ),
    }
  );
  if ( !response.ok ) throw new Error( 'Air API ' + response.status );
  return currentAqiFromPayload( await response.json() );
}

async function fetchWeather( city: CityMeta ): Promise<CityData['weather']> {
  const url = new URL( 'https://weather.googleapis.com/v1/currentConditions:lookup' );
  url.searchParams.set( 'key', MAPS_KEY );
  url.searchParams.set( 'location.latitude', String( city.lat ) );
  url.searchParams.set( 'location.longitude', String( city.lon ) );
  url.searchParams.set( 'unitsSystem', 'METRIC' );
  url.searchParams.set( 'languageCode', 'en' );
  const response = await fetch( url.toString(), { headers: { Accept: 'application/json' } } );
  if ( !response.ok ) throw new Error( 'Weather API ' + response.status );
  return currentWeatherFromPayload( await response.json() );
}

function loadMapsNamespace(): Promise<any> {
  if ( typeof window === 'undefined' || !MAPS_KEY ) return Promise.reject( new Error( 'Maps key unavailable' ) );
  const w = window as Window & { google?: any };
  if ( w.google?.maps?.Geocoder ) return Promise.resolve( w.google.maps );
  const existing = document.getElementById( 'gmaps-js' );
  if ( !existing ) {
    const script = document.createElement( 'script' );
    script.id = 'gmaps-js';
    script.async = true;
    script.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent( MAPS_KEY ) + '&loading=async';
    document.head.appendChild( script );
  }
  return new Promise( ( resolve, reject ) => {
    let tries = 0;
    const id = window.setInterval( () => {
      tries += 1;
      if ( w.google?.maps?.Geocoder ) {
        window.clearInterval( id );
        resolve( w.google.maps );
      } else if ( tries > 120 ) {
        window.clearInterval( id );
        reject( new Error( 'Maps namespace timeout' ) );
      }
    }, 50 );
  } );
}

async function reverseGeocode( lat: number, lon: number ): Promise<string> {
  try {
    const maps = await loadMapsNamespace();
    const geocoder = new maps.Geocoder();
    const result = await geocoder.geocode( { location: { lat, lng: lon } } );
    const first = result?.results?.[ 0 ];
    const components = Array.isArray( first?.address_components ) ? first.address_components : [];
    const wanted = [ 'locality', 'postal_town', 'administrative_area_level_2', 'administrative_area_level_1' ];
    for ( const type of wanted ) {
      const hit = components.find( ( c: any ) => Array.isArray( c?.types ) && c.types.includes( type ) );
      if ( hit?.long_name ) return String( hit.long_name );
    }
    if ( first?.formatted_address ) return String( first.formatted_address ).split( ',' )[ 0 ];
  } catch {
    // Coordinates are the honest fallback when reverse geocoding is unavailable.
  }
  return lat.toFixed( 2 ) + '°, ' + lon.toFixed( 2 ) + '°';
}

const VayuLokHeroGlobe: React.FC = () => {
  const stageRef = useRef<HTMLDivElement | null>( null );
  const canvasRef = useRef<HTMLCanvasElement | null>( null );
  const markerRefs = useRef<Record<string, HTMLDivElement | null>>( {} );
  const layerRef = useRef<Layer>( 'air' );
  const yawRef = useRef( HOME_YAW );
  const tiltRef = useRef( HOME_TILT );
  const viewYawRef = useRef( HOME_YAW );
  const viewTiltRef = useRef( HOME_TILT );
  const dragRef = useRef( { active: false, moved: false, x: 0, y: 0, vx: 0, vy: 0, last: 0 } );
  const autoResumeAtRef = useRef( 0 );
  const citiesRef = useRef<CityMeta[]>( [ DELHI, BENGALURU ] );
  const [ layer, setLayer ] = useState<Layer>( 'air' );
  const [ selected, setSelected ] = useState<CityMeta | null>( null );
  const [ live, setLive ] = useState<Record<string, CityData>>( {} );

  const cities = useMemo( () => selected ? [ DELHI, BENGALURU, selected ] : [ DELHI, BENGALURU ], [ selected ] );

  useEffect( () => {
    citiesRef.current = cities;
  }, [ cities ] );

  const setMode = ( next: Layer ) => {
    layerRef.current = next;
    setLayer( next );
  };

  useEffect( () => {
    if ( !MAPS_KEY ) {
      setLive( { delhi: { error: true }, bengaluru: { error: true } } );
      return;
    }
    let cancelled = false;
    const load = async ( city: CityMeta ) => {
      const [ air, weather ] = await Promise.allSettled( [ fetchAir( city ), fetchWeather( city ) ] );
      if ( cancelled ) return;
      setLive( current => ( {
        ...current,
        [ city.id ]: {
          air: air.status === 'fulfilled' ? air.value : undefined,
          weather: weather.status === 'fulfilled' ? weather.value : undefined,
          fetchedAt: Date.now(),
          error: air.status === 'rejected' && weather.status === 'rejected',
        },
      } ) );
    };
    void load( DELHI );
    void load( BENGALURU );
    const interval = window.setInterval( () => {
      void load( DELHI );
      void load( BENGALURU );
      const dynamic = citiesRef.current.find( c => c.id === 'selected' );
      if ( dynamic ) void load( dynamic );
    }, 10 * 60 * 1000 );
    return () => {
      cancelled = true;
      window.clearInterval( interval );
    };
  }, [] );

  useEffect( () => {
    if ( !selected || !MAPS_KEY ) return;
    let cancelled = false;
    const load = async () => {
      const [ air, weather ] = await Promise.allSettled( [ fetchAir( selected ), fetchWeather( selected ) ] );
      if ( cancelled ) return;
      setLive( current => ( {
        ...current,
        selected: {
          air: air.status === 'fulfilled' ? air.value : undefined,
          weather: weather.status === 'fulfilled' ? weather.value : undefined,
          fetchedAt: Date.now(),
          error: air.status === 'rejected' && weather.status === 'rejected',
        },
      } ) );
    };
    void load();
    return () => { cancelled = true; };
  }, [ selected ] );

  useEffect( () => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    if ( !stage || !canvas ) return;
    const ctx = canvas.getContext( '2d' );
    if ( !ctx ) return;

    const reduceMotion = window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
    const rand = seededRandomFactory( 0x51a0c3 );
    const dotCount = window.innerWidth < 680 ? 3400 : 5200;
    const dots: DotPoint[] = [];
    const golden = Math.PI * ( 3 - Math.sqrt( 5 ) );

    for ( let i = 0; i < dotCount; i += 1 ) {
      const y = 1 - ( i / Math.max( 1, dotCount - 1 ) ) * 2;
      const radius = Math.sqrt( Math.max( 0, 1 - y * y ) );
      const theta = golden * i + ( rand() - 0.5 ) * 0.04;
      const paletteIndex = Math.min( DOT_PALETTE.length - 1, Math.floor( rand() * DOT_PALETTE.length ) );
      dots.push( {
        x: Math.cos( theta ) * radius,
        y,
        z: Math.sin( theta ) * radius,
        color: DOT_PALETTE[ paletteIndex ],
        size: 0.68 + rand() * 0.92,
      } );
    }

    const halo = Array.from( { length: 620 }, () => ( {
      angle: rand() * Math.PI * 2,
      radius: 1.01 + Math.pow( rand(), 2 ) * 0.34,
      alpha: 0.08 + rand() * 0.25,
      size: 0.55 + rand() * 1.2,
      color: DOT_PALETTE[ Math.floor( rand() * DOT_PALETTE.length ) ],
    } ) );

    let width = 1;
    let height = 1;
    let dpr = 1;
    let cx = 0;
    let cy = 0;
    let sphereRadius = 1;
    let frameId = 0;

    const resize = () => {
      const rect = stage.getBoundingClientRect();
      width = Math.max( 1, rect.width );
      height = Math.max( 1, rect.height );
      dpr = Math.min( window.devicePixelRatio || 1, 2 );
      canvas.width = Math.round( width * dpr );
      canvas.height = Math.round( height * dpr );
      cx = canvas.width * 0.50;
      cy = canvas.height * 0.52;
      sphereRadius = Math.min( canvas.width, canvas.height ) * 0.405;
    };

    const rotate = ( p: [ number, number, number ], yaw: number, tilt: number ) => {
      let x = p[ 0 ];
      let y = p[ 1 ];
      let z = p[ 2 ];
      let c = Math.cos( yaw );
      let s = Math.sin( yaw );
      const x1 = x * c + z * s;
      const z1 = -x * s + z * c;
      x = x1;
      z = z1;
      c = Math.cos( tilt );
      s = Math.sin( tilt );
      const y1 = y * c - z * s;
      const z2 = y * s + z * c;
      y = y1;
      z = z2;
      return { x, y, z };
    };

    const nearestHomeYaw = ( angle: number ) => {
      const turn = Math.PI * 2;
      return HOME_YAW + Math.round( ( angle - HOME_YAW ) / turn ) * turn;
    };

    const positionMarkers = () => {
      const yaw = viewYawRef.current;
      const tilt = viewTiltRef.current;
      for ( const city of citiesRef.current ) {
        const el = markerRefs.current[ city.id ];
        if ( !el ) continue;
        const p = rotate( latLonToVec( city.lat, city.lon ), yaw, tilt );
        const visible = p.z > 0.05;
        el.style.opacity = visible ? '1' : '0';
        if ( !visible ) continue;
        const x = ( cx + p.x * sphereRadius ) / dpr;
        const y = ( cy - p.y * sphereRadius ) / dpr;
        el.style.left = x + 'px';
        el.style.top = y + 'px';
        el.dataset.side = x > width * 0.55 ? 'left' : 'right';
        el.dataset.vertical = y < height * 0.30 ? 'below' : 'above';
      }
    };

    const draw = ( now: number ) => {
      resize();
      const drag = dragRef.current;
      if ( !drag.active && !reduceMotion ) {
        if ( Math.abs( drag.vx ) + Math.abs( drag.vy ) > 0.00002 ) {
          yawRef.current += drag.vx;
          tiltRef.current += drag.vy;
          drag.vx *= 0.91;
          drag.vy *= 0.91;
          tiltRef.current = Math.max( TILT_MIN, Math.min( TILT_MAX, tiltRef.current ) );
        }
        if ( now >= autoResumeAtRef.current ) {
          const targetYaw = nearestHomeYaw( yawRef.current );
          yawRef.current += ( targetYaw - yawRef.current ) * 0.008;
          tiltRef.current += ( HOME_TILT - tiltRef.current ) * 0.008;
        }
      }
      const passive = !reduceMotion && !drag.active && now >= autoResumeAtRef.current;
      viewYawRef.current = yawRef.current + ( passive ? Math.sin( now * 0.00018 ) * 7 * Math.PI / 180 : 0 );
      viewTiltRef.current = tiltRef.current + ( passive ? Math.sin( now * 0.00013 ) * 2.2 * Math.PI / 180 : 0 );

      ctx.clearRect( 0, 0, canvas.width, canvas.height );
      const glow = ctx.createRadialGradient(
        cx - sphereRadius * 0.26, cy - sphereRadius * 0.22, sphereRadius * 0.08,
        cx, cy, sphereRadius * 1.10
      );
      glow.addColorStop( 0, 'rgba(25,123,174,.40)' );
      glow.addColorStop( 0.58, 'rgba(8,70,103,.38)' );
      glow.addColorStop( 0.90, 'rgba(0,26,42,.92)' );
      glow.addColorStop( 1, 'rgba(0,11,18,.98)' );
      ctx.beginPath();
      ctx.arc( cx, cy, sphereRadius, 0, Math.PI * 2 );
      ctx.fillStyle = glow;
      ctx.fill();

      const atmosphere = ctx.createRadialGradient( cx, cy, sphereRadius * 0.86, cx, cy, sphereRadius * 1.18 );
      atmosphere.addColorStop( 0, 'rgba(24,169,255,0)' );
      atmosphere.addColorStop( 0.78, 'rgba(24,169,255,.12)' );
      atmosphere.addColorStop( 1, 'rgba(24,169,255,0)' );
      ctx.beginPath();
      ctx.arc( cx, cy, sphereRadius * 1.18, 0, Math.PI * 2 );
      ctx.fillStyle = atmosphere;
      ctx.fill();

      ctx.globalCompositeOperation = 'lighter';
      for ( const h of halo ) {
        const x = cx + Math.cos( h.angle ) * sphereRadius * h.radius;
        const y = cy + Math.sin( h.angle ) * sphereRadius * h.radius;
        ctx.beginPath();
        ctx.arc( x, y, h.size * dpr, 0, Math.PI * 2 );
        ctx.globalAlpha = h.alpha;
        ctx.fillStyle = h.color;
        ctx.fill();
      }

      const weather = layerRef.current === 'weather';
      for ( const dot of dots ) {
        const p = rotate( [ dot.x, dot.y, dot.z ], viewYawRef.current, viewTiltRef.current );
        if ( p.z < -0.12 ) continue;
        const depth = Math.max( 0, Math.min( 1, ( p.z + 1 ) * 0.5 ) );
        let alpha = 0.15 + depth * depth * 0.78;
        if ( weather ) {
          if ( dot.color === '#2563eb' || dot.color === '#9849e8' || dot.color === '#f0a818' ) alpha *= 1.08;
          if ( dot.color === '#3da35a' || dot.color === '#1a3a2a' ) alpha *= 0.78;
        } else {
          if ( dot.color === '#3da35a' || dot.color === '#1a3a2a' || dot.color === '#d1f470' ) alpha *= 1.07;
          if ( dot.color === '#2563eb' ) alpha *= 0.82;
        }
        ctx.beginPath();
        ctx.arc(
          cx + p.x * sphereRadius,
          cy - p.y * sphereRadius,
          dot.size * dpr * ( 0.55 + depth * 0.88 ),
          0,
          Math.PI * 2
        );
        ctx.globalAlpha = Math.min( 1, alpha );
        ctx.fillStyle = dot.color;
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
      positionMarkers();
      frameId = window.requestAnimationFrame( draw );
    };

    resize();
    frameId = window.requestAnimationFrame( draw );
    window.addEventListener( 'resize', resize );
    return () => {
      window.cancelAnimationFrame( frameId );
      window.removeEventListener( 'resize', resize );
    };
  }, [] );

  const pickLocation = async ( clientX: number, clientY: number ) => {
    const stage = stageRef.current;
    if ( !stage ) return;
    const rect = stage.getBoundingClientRect();
    const cx = rect.width * 0.50;
    const cy = rect.height * 0.52;
    const radius = Math.min( rect.width, rect.height ) * 0.405;
    const x1 = ( clientX - rect.left - cx ) / radius;
    const y2 = -( clientY - rect.top - cy ) / radius;
    const r2 = x1 * x1 + y2 * y2;
    if ( r2 > 1 ) return;
    const z2 = Math.sqrt( Math.max( 0, 1 - r2 ) );

    const tilt = viewTiltRef.current;
    const yaw = viewYawRef.current;
    let c = Math.cos( tilt );
    let s = Math.sin( tilt );
    const y = c * y2 + s * z2;
    const z1 = -s * y2 + c * z2;
    c = Math.cos( yaw );
    s = Math.sin( yaw );
    const x = c * x1 - s * z1;
    const z = s * x1 + c * z1;
    const lat = Math.asin( Math.max( -1, Math.min( 1, y ) ) ) * 180 / Math.PI;
    const lon = Math.atan2( z, x ) * 180 / Math.PI;

    const pending: CityMeta = {
      id: 'selected',
      name: 'Selected location',
      lat,
      lon,
      marker: pointColorForLocation( lat, lon ),
    };
    setSelected( pending );
    setLive( current => {
      const next = { ...current };
      delete next.selected;
      return next;
    } );
    autoResumeAtRef.current = performance.now() + 15000;

    const name = await reverseGeocode( lat, lon );
    setSelected( current => current && current.lat === lat && current.lon === lon ? { ...current, name } : current );
  };

  const onPointerDown = ( event: React.PointerEvent<HTMLDivElement> ) => {
    const target = event.target as HTMLElement;
    if ( target.closest( '[data-globe-control]' ) ) return;
    const drag = dragRef.current;
    drag.active = true;
    drag.moved = false;
    drag.x = event.clientX;
    drag.y = event.clientY;
    drag.vx = 0;
    drag.vy = 0;
    drag.last = performance.now();
    autoResumeAtRef.current = performance.now() + 5200;
    event.currentTarget.setPointerCapture( event.pointerId );
  };

  const onPointerMove = ( event: React.PointerEvent<HTMLDivElement> ) => {
    const drag = dragRef.current;
    if ( !drag.active ) return;
    const now = performance.now();
    const dt = Math.max( 8, Math.min( 40, now - drag.last ) );
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if ( Math.abs( dx ) + Math.abs( dy ) > 1 ) drag.moved = true;
    yawRef.current += dx * 0.0042;
    tiltRef.current = Math.max( TILT_MIN, Math.min( TILT_MAX, tiltRef.current + dy * 0.0035 ) );
    drag.vx = ( dx * 0.0042 ) / ( dt / 16.67 );
    drag.vy = ( dy * 0.0035 ) / ( dt / 16.67 );
    drag.x = event.clientX;
    drag.y = event.clientY;
    drag.last = now;
  };

  const onPointerUp = ( event: React.PointerEvent<HTMLDivElement> ) => {
    const drag = dragRef.current;
    const wasClick = !drag.moved;
    drag.active = false;
    autoResumeAtRef.current = performance.now() + 5200;
    try { event.currentTarget.releasePointerCapture( event.pointerId ); } catch { /* pointer capture already gone */ }
    if ( wasClick ) void pickLocation( event.clientX, event.clientY );
  };

  const resetView = () => {
    yawRef.current = HOME_YAW;
    tiltRef.current = HOME_TILT;
    dragRef.current.vx = 0;
    dragRef.current.vy = 0;
    autoResumeAtRef.current = 0;
  };

  return (
    <section className="vlg-wrap" aria-label="Interactive VayuLok air and weather globe">
      <div
        ref={ stageRef }
        className="vlg-stage"
        onPointerDown={ onPointerDown }
        onPointerMove={ onPointerMove }
        onPointerUp={ onPointerUp }
        onPointerCancel={ onPointerUp }
        onDoubleClick={ resetView }
      >
        <canvas
          ref={ canvasRef }
          className="vlg-canvas"
          role="img"
          aria-label="Interactive 360 degree data globe centred on India with live air and weather city markers"
        />

        <div className="vlg-toggle" role="group" aria-label="Environmental layer" data-globe-control>
          <button type="button" className={ layer === 'air' ? 'is-active' : '' } aria-pressed={ layer === 'air' } onClick={ () => setMode( 'air' ) }>
            <i className="is-air" aria-hidden="true" />AIR
          </button>
          <button type="button" className={ layer === 'weather' ? 'is-active' : '' } aria-pressed={ layer === 'weather' } onClick={ () => setMode( 'weather' ) }>
            <i className="is-weather" aria-hidden="true" />WEATHER
          </button>
        </div>

        { cities.map( city => {
          const data = live[ city.id ];
          const accent = layer === 'air' ? airAccent( data?.air?.aqi ) : weatherAccent( data?.weather?.condition );
          return (
            <div
              key={ city.id }
              ref={ el => { markerRefs.current[ city.id ] = el; } }
              className="vlg-city"
              style={ { '--city-marker': city.marker, '--reading-accent': accent } as React.CSSProperties }
            >
              <span className="vlg-city-pin" aria-hidden="true" />
              <span className="vlg-city-leader" aria-hidden="true" />
              <span className="vlg-city-card">
                <strong>{ city.name }</strong>
                <span className="vlg-city-layer"><i aria-hidden="true" />{ layer === 'air' ? 'AIR' : 'WEATHER' }</span>
                <span className="vlg-city-reading">{ readingText( layer, data ) }</span>
                <span className="vlg-city-meta">{ ageText( data?.fetchedAt ) }</span>
              </span>
            </div>
          );
        } ) }

        <span className="vlg-hint" data-globe-control>Drag 360° · click globe for local live data</span>
      </div>

      <style jsx>{`
        .vlg-wrap{width:100%;min-width:0}
        .vlg-stage{position:relative;isolation:isolate;width:100%;aspect-ratio:1472/1048;overflow:hidden;border-radius:34px;background:radial-gradient(circle at 50% 48%,rgba(6,18,18,.52) 0 18%,rgba(2,8,8,.52) 52%,rgba(0,0,0,.98) 100%);box-shadow:0 18px 46px rgba(0,0,0,.16);touch-action:none;user-select:none;cursor:grab}
        .vlg-stage:active{cursor:grabbing}
        .vlg-stage::before,.vlg-stage::after{content:'';position:absolute;z-index:20;background:#fff;pointer-events:none}
        .vlg-stage::before{left:-1px;top:-1px;width:9.2%;height:20.2%;border-bottom-right-radius:42px}
        .vlg-stage::after{right:-1px;bottom:-1px;width:22.2%;height:15.2%;border-top-left-radius:42px}
        .vlg-canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
        .vlg-toggle{position:absolute;z-index:24;top:4.2%;right:4%;display:grid;grid-template-columns:1fr 1.2fr;gap:4px;width:clamp(176px,31%,230px);height:50px;padding:4px;border:1px solid rgba(209,244,112,.48);border-radius:999px;background:linear-gradient(135deg,rgba(209,244,112,.16),rgba(209,244,112,.055));box-shadow:0 12px 34px rgba(0,0,0,.25),inset 0 1px 0 rgba(255,255,255,.13);backdrop-filter:blur(16px) saturate(130%);-webkit-backdrop-filter:blur(16px) saturate(130%)}
        .vlg-toggle button{border:0;border-radius:999px;background:transparent;color:rgba(244,255,207,.70);display:flex;align-items:center;justify-content:center;gap:7px;font:800 11px/1 'Inter',sans-serif;letter-spacing:.08em;cursor:pointer;transition:background .2s,color .2s,transform .2s,box-shadow .2s}
        .vlg-toggle button i{width:7px;height:7px;border-radius:50%;display:block}
        .vlg-toggle .is-air{background:#3da35a}.vlg-toggle .is-weather{background:#2563eb}
        .vlg-toggle button.is-active{color:#f8ffdf;background:rgba(209,244,112,.23);transform:translateY(-1px);box-shadow:0 5px 18px rgba(0,0,0,.24),inset 0 0 0 1px rgba(209,244,112,.38)}
        .vlg-toggle button:focus-visible{outline:3px solid #d1f470;outline-offset:2px}
        .vlg-city{position:absolute;z-index:12;width:1px;height:1px;opacity:0;pointer-events:none;transition:opacity .18s ease;--city-marker:#f0a818;--reading-accent:#d1f470}
        .vlg-city-pin{position:absolute;left:0;top:0;width:11px;height:11px;transform:translate(-50%,-50%);border-radius:50%;background:var(--city-marker);border:2px solid rgba(255,255,255,.96);box-shadow:0 0 0 5px color-mix(in srgb,var(--city-marker) 30%,transparent),0 0 18px color-mix(in srgb,var(--city-marker) 58%,transparent);animation:vlgPulse 2.8s ease-out infinite}
        .vlg-city-leader{position:absolute;left:-1px;top:-46px;width:1.5px;height:46px;border-radius:2px;background:linear-gradient(to top,rgba(255,255,255,.72),rgba(255,255,255,.10))}
        .vlg-city-card{position:absolute;right:15px;bottom:14px;min-width:150px;max-width:220px;padding:9px 12px 10px;border:1px solid color-mix(in srgb,var(--city-marker) 42%,rgba(255,255,255,.14));border-radius:17px;background:linear-gradient(135deg,rgba(3,7,8,.30),rgba(3,7,8,.13));box-shadow:0 10px 26px rgba(0,0,0,.18),inset 0 1px 0 rgba(255,255,255,.10);backdrop-filter:blur(5px) saturate(116%);-webkit-backdrop-filter:blur(5px) saturate(116%);color:#fff;text-align:right}
        .vlg-city[data-side='right'] .vlg-city-card{left:15px;right:auto;text-align:left}
        .vlg-city[data-side='left'] .vlg-city-card{right:15px;left:auto;text-align:right}
        .vlg-city[data-vertical='below'] .vlg-city-card{bottom:auto;top:16px}
        .vlg-city[data-vertical='below'] .vlg-city-leader{top:0;height:38px;background:linear-gradient(to bottom,rgba(255,255,255,.72),rgba(255,255,255,.10))}
        .vlg-city-card strong{display:block;font-size:14px;font-weight:800;line-height:1.08}
        .vlg-city-layer{display:inline-flex;align-items:center;gap:6px;margin-top:5px;color:rgba(255,255,255,.67);font-size:9px;font-weight:800;letter-spacing:.08em;line-height:1}
        .vlg-city-layer i{width:7px;height:7px;border-radius:50%;background:var(--city-marker)}
        .vlg-city-reading{display:block;margin-top:5px;color:var(--reading-accent);font-size:11px;font-weight:800;line-height:1.22}
        .vlg-city-meta{display:block;margin-top:4px;color:rgba(255,255,255,.42);font-size:8px;font-weight:750;letter-spacing:.07em}
        .vlg-hint{position:absolute;z-index:22;left:4%;bottom:4%;padding:7px 10px;border:1px solid rgba(255,255,255,.12);border-radius:999px;background:rgba(2,6,6,.30);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);color:rgba(255,255,255,.64);font-size:9px;font-weight:750;letter-spacing:.05em;text-transform:uppercase;pointer-events:none}
        @keyframes vlgPulse{0%,100%{box-shadow:0 0 0 5px color-mix(in srgb,var(--city-marker) 30%,transparent),0 0 18px color-mix(in srgb,var(--city-marker) 58%,transparent)}50%{box-shadow:0 0 0 10px transparent,0 0 26px color-mix(in srgb,var(--city-marker) 64%,transparent)}}
        @media(max-width:767px){.vlg-stage{border-radius:24px;aspect-ratio:1/1}.vlg-stage::before{width:10.5%;height:18.5%;border-bottom-right-radius:30px}.vlg-stage::after{width:20%;height:13.5%;border-top-left-radius:30px}.vlg-toggle{top:3%;right:3%;width:168px;height:44px}.vlg-city-card{min-width:120px;max-width:170px;padding:7px 9px 8px;border-radius:14px}.vlg-hint{left:3%;bottom:3%;font-size:8px;padding:6px 8px}}
        @media(prefers-reduced-motion:reduce){.vlg-city-pin{animation:none}.vlg-city,.vlg-toggle button{transition:none}}
      `}</style>
    </section>
  );
};

export default VayuLokHeroGlobe;
