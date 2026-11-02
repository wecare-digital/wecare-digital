import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  VayuLokCompactPill,
  VayuLokFreshnessStamp,
  VayuLokSectionHeading,
  VayuLokUiStyles,
} from './VayuLokUiPrimitives';

type Range = '30d' | '1y' | '5y';

interface WeatherInsightsSummary {
  ok?: boolean;
  range: Range;
  coverageStart?: string | null;
  coverageEnd?: string | null;
  gridDistanceKm?: number | null;
  sampleHours: number;
  meanTemperatureC?: number | null;
  minTemperatureC?: number | null;
  maxTemperatureC?: number | null;
  precipitationMm?: number | null;
  meanHumidityPct?: number | null;
  monthly?: Array<{
    month: number;
    meanTemperatureC?: number | null;
    precipitationMm?: number | null;
    meanHumidityPct?: number | null;
  }>;
  cached?: boolean;
  stale?: boolean;
  generatedAt?: string;
}

interface Props {
  lat: number;
  lng: number;
  placeName?: string;
  timeZoneId?: string;
  zoneLabel?: string;
  includeUiStyles?: boolean;
}

const INSIGHTS_URL = ( process.env.NEXT_PUBLIC_VAYULOK_WEATHER_INSIGHTS_URL || '' ).replace( /\/$/, '' );
// Automatic history remains enabled. Use the same 0.1-degree grid as the
// server's BigQuery result cache; browser persistence survives remounts/reloads.
const LOCAL_HISTORY_STORE = 'vayulok-weather-history-cache-v1';
const HISTORY_CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const HISTORY_STALE_FALLBACK_MS = 7 * HISTORY_CACHE_TTL_MS;

type SavedHistory = { ts: number; data: WeatherInsightsSummary };

function readHistoryCache( key: string ): SavedHistory | null {
  if ( typeof window === 'undefined' ) return null;
  try {
    const all = JSON.parse( window.localStorage.getItem( LOCAL_HISTORY_STORE ) || '{}' ) as Record<string, SavedHistory>;
    const item = all[ key ];
    if ( !item || !Number.isFinite( item.ts ) || Date.now() - item.ts >= HISTORY_STALE_FALLBACK_MS
      || item.ts > Date.now() || !item.data || !Number.isFinite( item.data.sampleHours ) ) return null;
    return item;
  } catch { return null; }
}

function saveHistoryCache( key: string, item: SavedHistory ) {
  if ( typeof window === 'undefined' ) return;
  try {
    const stored = JSON.parse( window.localStorage.getItem( LOCAL_HISTORY_STORE ) || '{}' ) as Record<string, SavedHistory>;
    stored[ key ] = item;
    const valid = Object.entries( stored ).filter( ( [ , entry ] ) => entry
      && Number.isFinite( entry.ts ) && Date.now() - entry.ts < HISTORY_STALE_FALLBACK_MS
      && entry.ts <= Date.now() && entry.data && Number.isFinite( entry.data.sampleHours ) );
    // Bound storage space; keep the 48 most recent grid/range summaries.
    const recent = valid.sort( ( a, b ) => b[ 1 ].ts - a[ 1 ].ts ).slice( 0, 48 );
    window.localStorage.setItem( LOCAL_HISTORY_STORE, JSON.stringify( Object.fromEntries( recent ) ) );
  } catch { /* Storage is optional (private browsing, quota, unavailable). */ }
}

function analyticsEvent( event: string, range: Range, status?: string ) {
  if ( typeof window === 'undefined' ) return;
  const w = window as typeof window & { dataLayer?: Array<Record<string, unknown>> };
  w.dataLayer = w.dataLayer || [];
  w.dataLayer.push( {
    event,
    vayulok_range: range,
    ...( status ? { vayulok_status: status } : {} ),
  } );
}

function fmt( value: number | null | undefined, suffix = '', digits = 1 ) {
  if ( !Number.isFinite( value ) ) return '—';
  return Number( value ).toFixed( digits ).replace( /\.0$/, '' ) + suffix;
}

function formatWeatherHistoryStamp( value: number, timeZoneId: string, zoneLabel: string ) {
  try {
    const label = new Intl.DateTimeFormat( 'en-IN', {
      timeZone: timeZoneId,
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    } ).format( new Date( value ) );
    const zoneSuffix = zoneLabel.trim();
    return `${label}${zoneSuffix ? ` ${zoneSuffix}` : ''}`;
  } catch {
    return `${new Date( value ).toISOString().slice( 11, 16 )} UTC`;
  }
}

const RANGE_LABELS: Record<Range, string> = {
  '30d': '30D',
  '1y': '1Y',
  '5y': '5Y',
};

const MONTHS = [ 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec' ];

const VayuLokWeatherInsights: React.FC<Props> = ( {
  lat,
  lng,
  placeName,
  timeZoneId = 'Asia/Kolkata',
  zoneLabel = 'IST',
  includeUiStyles = true,
} ) => {
  const [ range, setRange ] = useState<Range>( '30d' );
  const [ data, setData ] = useState<WeatherInsightsSummary | null>( null );
  const [ fetchedAt, setFetchedAt ] = useState<number | null>( null );
  const [ status, setStatus ] = useState<'idle' | 'loading' | 'ready' | 'unavailable' | 'error'>( 'idle' );
  const [ errorCode, setErrorCode ] = useState( '' );
  const cacheRef = useRef<Record<string, { ts: number; data: WeatherInsightsSummary }>>( {} );


  useEffect( () => {
    if ( !INSIGHTS_URL || !Number.isFinite( lat ) || !Number.isFinite( lng ) ) {
      setStatus( 'unavailable' );
      return;
    }

    const gridLat = Math.round( lat * 10 ) / 10;
    const gridLng = Math.round( lng * 10 ) / 10;
    const key = `${gridLat.toFixed( 1 )},${gridLng.toFixed( 1 )}:${range}`;
    const saved = cacheRef.current[ key ] || readHistoryCache( key );
    if ( saved && Date.now() - saved.ts < HISTORY_CACHE_TTL_MS ) {
      cacheRef.current[ key ] = saved;
      setData( saved.data );
      const generatedAt = Date.parse( saved.data.generatedAt || '' );
      setFetchedAt( Number.isFinite( generatedAt ) ? generatedAt : saved.ts );
      setStatus( 'ready' );
      return;
    }

    const ac = new AbortController();
    setStatus( 'loading' );
    setErrorCode( '' );

    const showStaleOrError = ( code: string, unavailable: boolean ) => {
      if ( saved && Date.now() - saved.ts < HISTORY_STALE_FALLBACK_MS ) {
        setData( { ...saved.data, cached: true, stale: true } );
        const generatedAt = Date.parse( saved.data.generatedAt || '' );
        setFetchedAt( Number.isFinite( generatedAt ) ? generatedAt : saved.ts );
        setStatus( 'ready' );
      } else {
        setData( null );
        setStatus( unavailable ? 'unavailable' : 'error' );
      }
      setErrorCode( code );
      analyticsEvent( 'vayulok_weather_insights_error', range, code );
    };

    const run = async () => {
      try {
        // Until the separate GCP Cloud Run deployment is verified, the old
        // service still permits 15–40GB queries for 1Y/5Y. Fail CLOSED before
        // sending a long-range request unless it advertises the 1GiB guard.
        if ( range !== '30d' ) {
          const guardResponse = await fetch( `${INSIGHTS_URL}/v1/weather-insights/status`, { signal: ac.signal } )
            .catch( () => null );
          if ( ac.signal.aborted ) return;
          if ( !guardResponse ) {
            showStaleOrError( 'query_budget_reached', true );
            return;
          }
          const guard = await guardResponse.json().catch( () => ( {} ) );
          if ( ac.signal.aborted ) return;
          const allowedBytes = Number( guard?.costGuard?.maxBytesBilledByRange?.[ range ] );
          if ( !guardResponse.ok || !Number.isFinite( allowedBytes )
            || allowedBytes <= 0 || allowedBytes > 1_073_741_824 ) {
            showStaleOrError( 'query_budget_reached', true );
            return;
          }
        }
        // Do not trigger a new paid BigQuery query for every nearby street address.
        const url = `${INSIGHTS_URL}/v1/weather-insights?lat=${encodeURIComponent( gridLat )}&lng=${encodeURIComponent( gridLng )}&range=${range}`;
        const res = await fetch( url, { signal: ac.signal } );
        const body = await res.json().catch( () => ( {} ) );
        if ( ac.signal.aborted ) return;

        if ( !res.ok || !body?.ok || !Number.isFinite( body?.sampleHours ) ) {
          const code = String( body?.error || 'unavailable' );
          showStaleOrError( code, [
            'linked_dataset_missing', 'linked_dataset_empty', 'column_configuration_required',
            'table_configuration_required', 'query_cost_cap_exceeded', 'query_budget_reached',
          ].includes( code ) );
          return;
        }

        const next = body as WeatherInsightsSummary;
        const receivedAt = Date.now();
        const fresh = { ts: receivedAt, data: next };
        cacheRef.current[ key ] = fresh;
        saveHistoryCache( key, fresh );
        setData( next );
        const generatedAt = Date.parse( next.generatedAt || '' );
        setFetchedAt( Number.isFinite( generatedAt ) ? generatedAt : receivedAt );
        setStatus( 'ready' );
        analyticsEvent( 'vayulok_weather_insights_viewed', range, 'ready' );
      } catch {
        if ( ac.signal.aborted ) return;
        showStaleOrError( 'network_error', false );
      }
    };

    void run();
    return () => ac.abort();
  }, [ lat, lng, range ] );

  const monthly = useMemo( () => {
    const rows = Array.isArray( data?.monthly ) ? data?.monthly : [];
    return rows
      .filter( row => Number.isInteger( row.month ) && row.month >= 1 && row.month <= 12 )
      .slice()
      .sort( ( a, b ) => a.month - b.month );
  }, [ data ] );

  const maxMonthlyTemp = useMemo( () => {
    const vals = monthly.map( row => Number( row.meanTemperatureC ) ).filter( Number.isFinite );
    return vals.length ? Math.max( ...vals ) : 0;
  }, [ monthly ] );

  const minMonthlyTemp = useMemo( () => {
    const vals = monthly.map( row => Number( row.meanTemperatureC ) ).filter( Number.isFinite );
    return vals.length ? Math.min( ...vals ) : 0;
  }, [ monthly ] );

  if ( !INSIGHTS_URL ) return null;

  return (
    <section className="vl-wi" aria-label="Historical weather model data">
      { includeUiStyles && <VayuLokUiStyles /> }
      <div className="vl-wi-head">
        <div>
          <VayuLokSectionHeading>Historical weather data</VayuLokSectionHeading>
          <p>Past modelled weather for { placeName || 'this place' }</p>
        </div>
        <div className="vl-wi-range" role="group" aria-label="Weather history range">
          { ( Object.keys( RANGE_LABELS ) as Range[] ).map( item => (
            <VayuLokCompactPill
              key={ item }
              className={ range === item ? 'is-active' : '' }
              aria-pressed={ range === item }
              onClick={ () => {
                setRange( item );
                analyticsEvent( 'vayulok_weather_insights_range', item );
              } }
            >
              { RANGE_LABELS[ item ] }
            </VayuLokCompactPill>
          ) ) }
        </div>
      </div>

      <p className="vl-wi-source-note">
        These Google long-term weather records describe modelled forecast conditions,
        not independently verified weather-station observations or official alerts.
      </p>
      { status === 'loading' && <span className="vl-wi-sr" role="status">Loading model data…</span> }

      { status === 'unavailable' && (
        <div className="vl-wi-note" role="status">
          { errorCode === 'query_budget_reached' || errorCode === 'query_cost_cap_exceeded'
            ? 'History paused to protect the data budget. Try again later.'
            : 'No history here yet.' }
        </div>
      ) }

      { status === 'error' && (
        <div className="vl-wi-note" role="status">
          { errorCode === 'query_budget_reached' || errorCode === 'query_cost_cap_exceeded'
            ? 'History paused to protect the data budget. Try again later.'
            : 'History unavailable.' }
        </div>
      ) }

      { status === 'ready' && data && (
        <>
          { data.stale && (
            <div className="vl-wi-note" role="status">
              Showing saved history because fresh data is temporarily unavailable.
            </div>
          ) }
          { data.coverageStart && data.coverageEnd && (
            <p className="vl-wi-coverage" data-wc-no-translate="true">
              Model-data coverage: { new Date( data.coverageStart ).toLocaleDateString( 'en-IN' ) } – { new Date( data.coverageEnd ).toLocaleDateString( 'en-IN' ) }
              { Number.isFinite( data.gridDistanceKm ) ? ` · nearest grid ~${Number( data.gridDistanceKm ).toFixed( 1 )} km` : '' }
            </p>
          ) }
          <div className="vl-wi-grid">
            <div><span>Avg temp</span><strong data-wc-no-translate="true">{ fmt( data.meanTemperatureC, '°C' ) }</strong></div>
            <div><span>Low</span><strong data-wc-no-translate="true">{ fmt( data.minTemperatureC, '°C' ) }</strong></div>
            <div><span>High</span><strong data-wc-no-translate="true">{ fmt( data.maxTemperatureC, '°C' ) }</strong></div>
            <div><span>Rain</span><strong data-wc-no-translate="true">{ fmt( data.precipitationMm, ' mm' ) }</strong></div>
            <div><span>Humidity</span><strong data-wc-no-translate="true">{ fmt( data.meanHumidityPct, '%' ) }</strong></div>
            <div><span>Model hours</span><strong data-wc-no-translate="true">{ Number( data.sampleHours || 0 ).toLocaleString( 'en-IN' ) }</strong></div>
          </div>

          { monthly.length > 1 && (
            <div className="vl-wi-trend">
              <div className="vl-wi-trend-head">
                <strong>{ range === '5y' ? '5-year monthly pattern' : 'Monthly temperature' }</strong>
                <span>{ range === '5y' ? 'Average by calendar month' : 'Monthly average' }</span>
              </div>
              <div className="vl-wi-bars" aria-label="Monthly temperature">
                { monthly.map( row => {
                  const temp = Number( row.meanTemperatureC );
                  const span = Math.max( 1, maxMonthlyTemp - minMonthlyTemp );
                  const height = Number.isFinite( temp ) ? 28 + ( ( temp - minMonthlyTemp ) / span ) * 52 : 12;
                  return (
                    <div className="vl-wi-bar-slot" key={ row.month }>
                      <div className="vl-wi-bar-wrap">
                        <div className="vl-wi-bar" style={ { height: `${height}%` } } aria-hidden="true" />
                      </div>
                      <strong data-wc-no-translate="true">{ fmt( row.meanTemperatureC, '°', 0 ) }</strong>
                      <span>{ MONTHS[ row.month - 1 ] }</span>
                    </div>
                  );
                } ) }
              </div>
            </div>
          ) }

          { fetchedAt && (
            <VayuLokFreshnessStamp
              className="vl-wi-stamp"
              aria-label="Weather history updated time"
              iconPath="m612-292 56-56-148-148v-184h-80v216l172 172ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54 54 127 85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q133 0 226.5-93.5T800-480q0-133-93.5-226.5T480-800q-133 0-226.5 93.5T160-480q0 133 93.5 226.5T480-160Z"
              iconClassName="vl-wi-stamp-icon"
              text={ formatWeatherHistoryStamp( fetchedAt, timeZoneId, zoneLabel ) }
              data-wc-no-translate="true"
            />
          ) }
        </>
      ) }

      <style jsx>{`
        .vl-wi{margin-top:var(--vl-section-gap);padding-top:var(--vl-section-gap);border-top:1px solid var(--hair);font-family:var(--font-sans)}
        .vl-wi-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-4)}
        .vl-wi-head h4{margin:0;color:var(--public-heading);font-size:var(--vl-panel-heading-size,var(--public-data-size));font-weight:var(--vl-panel-heading-weight,700);line-height:var(--vl-panel-heading-lh,1.35);letter-spacing:var(--vl-panel-heading-track,-.18px)}
        .vl-wi-head p{margin:6px 0 0;color:var(--public-muted);font-size:var(--vl-subtext-size,var(--public-supporting-size));font-weight:600;line-height:1.4;letter-spacing:0}
        .vl-wi-range{display:flex;flex:0 0 auto;gap:6px;overflow-x:auto;padding:0;background:transparent;scrollbar-width:thin}
        .vl-wi-range::-webkit-scrollbar{height:6px}
        .vl-wi-note{margin-top:var(--space-3);padding:var(--space-3) var(--space-4);border:1px solid var(--hair);border-radius:var(--radius-lg);background:#fff;color:var(--public-muted);font-size:var(--vl-subtext-size,var(--public-supporting-size));font-weight:600;line-height:1.4;letter-spacing:0}
        .vl-wi-coverage{margin:var(--space-3) 0 0;color:var(--public-muted);font-size:var(--vl-meta-size,var(--public-meta-size));line-height:1.5}
         .vl-wi-source-note{margin:var(--space-3) 0 0;color:var(--public-muted);font-size:var(--vl-meta-size,var(--public-meta-size));line-height:1.5}
        .vl-wi-sr{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
        .vl-wi-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;margin-top:var(--space-3);border:1px solid var(--hair);border-radius:var(--radius-lg);overflow:hidden;background:var(--hair)}
        .vl-wi-grid>div{display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-3);padding:var(--space-4);background:#fff}
        .vl-wi-grid span{color:var(--public-muted);font-size:var(--vl-subtext-size,var(--public-supporting-size));font-weight:600;line-height:1.4}
        .vl-wi-grid strong{color:var(--public-heading);font-size:var(--vl-data-size,var(--public-cta-font-size));font-weight:700;line-height:1.35;font-variant-numeric:tabular-nums;text-align:end}
        .vl-wi-trend{margin-top:var(--space-4)}
        .vl-wi-trend-head{display:flex;justify-content:space-between;gap:var(--space-3);align-items:baseline}
        .vl-wi-trend-head strong{font-size:var(--vl-data-size,var(--public-cta-font-size));font-weight:700;color:var(--public-body)}
        .vl-wi-trend-head span{font-size:var(--vl-meta-size,var(--public-meta-size));font-weight:600;color:var(--public-muted)}
        .vl-wi-bars{display:grid;grid-template-columns:repeat(12,minmax(18px,1fr));gap:4px;align-items:end;height:138px;margin-top:var(--space-2);padding:10px 8px 6px;border:1px solid var(--hair);border-radius:var(--radius-lg);background:#fff}
        .vl-wi-bar-slot{display:grid;grid-template-rows:1fr auto auto;gap:3px;min-width:0;height:100%;text-align:center}
        .vl-wi-bar-wrap{display:flex;align-items:flex-end;justify-content:center;min-height:0}
        .vl-wi-bar{width:min(16px,80%);min-height:6px;border-radius:5px 5px 2px 2px;background:var(--lime)}
        .vl-wi-bar-slot strong{font-size:var(--vl-meta-size,var(--public-meta-size));color:var(--public-heading);font-variant-numeric:tabular-nums}
        .vl-wi-bar-slot span{font-size:var(--vl-meta-size,var(--public-meta-size));color:var(--public-muted)}
        .vl-wi-stamp{display:flex;width:fit-content;align-items:center;gap:6px;margin:var(--space-3) auto 0;padding:6px 12px;border-radius:var(--radius-full);background:var(--public-lime-tint);color:var(--public-brand-green);font-size:var(--vl-meta-size,var(--public-meta-size));font-weight:700;line-height:1.4;white-space:nowrap}
        .vl-wi-stamp-icon{flex:0 0 15px;width:15px;height:15px;fill:var(--public-brand-green)}
        @media(max-width:767px){
          .vl-wi{margin-top:var(--public-mobile-section-gap);padding-top:var(--space-6)}
          .vl-wi-head{flex-direction:column;gap:var(--space-3)}
          .vl-wi-head p{font-size:var(--vl-subtext-size,var(--public-supporting-size));font-weight:600;line-height:1.4}
          .vl-wi-range{width:100%}
          .vl-wi-range :global(.vl-ui-compact-pill){flex:0 0 auto}
          .vl-wi-note{font-size:var(--vl-subtext-size,var(--public-supporting-size))}
          .vl-wi-grid{grid-template-columns:1fr}
          .vl-wi-grid>div{padding:var(--space-4)}
          .vl-wi-grid span{font-size:var(--vl-subtext-size,var(--public-supporting-size))}
          .vl-wi-grid strong{font-size:var(--vl-data-size,var(--public-cta-font-size))}
          .vl-wi-trend-head{align-items:flex-start;flex-direction:column;gap:2px}
          .vl-wi-trend-head strong{font-size:var(--vl-data-size,var(--public-cta-font-size))}
          .vl-wi-trend-head span{font-size:var(--vl-meta-size,var(--public-meta-size))}
          .vl-wi-bars{gap:2px;padding-inline:4px}
          .vl-wi-bar-slot strong{font-size:var(--vl-meta-size,var(--public-meta-size))}
          .vl-wi-bar-slot span{font-size:var(--vl-meta-size,var(--public-meta-size))}
          .vl-wi-stamp{font-size:var(--vl-meta-size,var(--public-meta-size))}
        }
      `}</style>
    </section>
  );
};

export default VayuLokWeatherInsights;
