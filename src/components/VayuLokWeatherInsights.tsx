import React, { useEffect, useMemo, useRef, useState } from 'react';

type Range = '30d' | '1y' | '5y';

interface WeatherInsightsSummary {
  ok?: boolean;
  range: Range;
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
  source?: string;
  cached?: boolean;
}

interface Props {
  lat: number;
  lng: number;
  placeName?: string;
}

const INSIGHTS_URL = ( process.env.NEXT_PUBLIC_VAYULOK_INSIGHTS_URL || '' ).replace( /\/$/, '' );

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

const RANGE_LABELS: Record<Range, string> = {
  '30d': '30D',
  '1y': '1Y',
  '5y': '5Y',
};

const MONTHS = [ 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec' ];

const VayuLokWeatherInsights: React.FC<Props> = ( { lat, lng, placeName } ) => {
  const [ range, setRange ] = useState<Range>( '5y' );
  const [ data, setData ] = useState<WeatherInsightsSummary | null>( null );
  const [ status, setStatus ] = useState<'idle' | 'loading' | 'ready' | 'unavailable' | 'error'>( 'idle' );
  const [ errorCode, setErrorCode ] = useState( '' );
  const cacheRef = useRef<Record<string, { ts: number; data: WeatherInsightsSummary }>>( {} );

  useEffect( () => {
    if ( !INSIGHTS_URL || !Number.isFinite( lat ) || !Number.isFinite( lng ) ) {
      setStatus( 'unavailable' );
      return;
    }

    const key = `${lat.toFixed( 2 )},${lng.toFixed( 2 )}:${range}`;
    const cached = cacheRef.current[ key ];
    if ( cached && Date.now() - cached.ts < 6 * 60 * 60 * 1000 ) {
      setData( cached.data );
      setStatus( 'ready' );
      return;
    }

    const ac = new AbortController();
    setStatus( 'loading' );
    setErrorCode( '' );

    const run = async () => {
      try {
        const url = `${INSIGHTS_URL}/v1/weather-insights?lat=${encodeURIComponent( lat )}&lng=${encodeURIComponent( lng )}&range=${range}`;
        const res = await fetch( url, { signal: ac.signal, cache: 'no-store' } );
        const body = await res.json().catch( () => ( {} ) );
        if ( ac.signal.aborted ) return;

        if ( !res.ok || !body?.ok ) {
          const code = String( body?.error || 'unavailable' );
          setErrorCode( code );
          setData( null );
          setStatus( code === 'linked_dataset_missing' || code === 'linked_dataset_empty' || code === 'column_configuration_required' || code === 'table_configuration_required'
            ? 'unavailable'
            : 'error' );
          analyticsEvent( 'vayulok_weather_insights_error', range, code );
          return;
        }

        const next = body as WeatherInsightsSummary;
        cacheRef.current[ key ] = { ts: Date.now(), data: next };
        setData( next );
        setStatus( 'ready' );
        analyticsEvent( 'vayulok_weather_insights_viewed', range, 'ready' );
      } catch {
        if ( ac.signal.aborted ) return;
        setData( null );
        setStatus( 'error' );
        setErrorCode( 'network_error' );
        analyticsEvent( 'vayulok_weather_insights_error', range, 'network_error' );
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
    <section className="vl-wi" aria-label="Long-term Weather Insights">
      <div className="vl-wi-head">
        <div>
          <h4>Long-term Weather Insights</h4>
          <p>Google Weather historical aggregates for { placeName || 'this location' }.</p>
        </div>
        <div className="vl-wi-range" role="group" aria-label="Weather Insights range">
          { ( Object.keys( RANGE_LABELS ) as Range[] ).map( item => (
            <button
              key={ item }
              type="button"
              className={ range === item ? 'is-active' : '' }
              aria-pressed={ range === item }
              onClick={ () => {
                setRange( item );
                analyticsEvent( 'vayulok_weather_insights_range', item );
              } }
            >
              { RANGE_LABELS[ item ] }
            </button>
          ) ) }
        </div>
      </div>

      { status === 'loading' && (
        <div className="vl-wi-loading" role="status">Loading historical weather…</div>
      ) }

      { status === 'unavailable' && (
        <div className="vl-wi-note" role="status">
          Long-term historical weather is being connected for this location.
        </div>
      ) }

      { status === 'error' && (
        <div className="vl-wi-note" role="status">
          Historical weather is temporarily unavailable{ errorCode === 'query_cost_cap_exceeded' ? ' because the query exceeded its safety limit' : '' }.
        </div>
      ) }

      { status === 'ready' && data && (
        <>
          <div className="vl-wi-grid">
            <div><span>Typical temperature</span><strong data-wc-no-translate="true">{ fmt( data.meanTemperatureC, '°C' ) }</strong></div>
            <div><span>Historical low</span><strong data-wc-no-translate="true">{ fmt( data.minTemperatureC, '°C' ) }</strong></div>
            <div><span>Historical high</span><strong data-wc-no-translate="true">{ fmt( data.maxTemperatureC, '°C' ) }</strong></div>
            <div><span>Total precipitation</span><strong data-wc-no-translate="true">{ fmt( data.precipitationMm, ' mm' ) }</strong></div>
            <div><span>Typical humidity</span><strong data-wc-no-translate="true">{ fmt( data.meanHumidityPct, '%' ) }</strong></div>
            <div><span>Hourly samples</span><strong data-wc-no-translate="true">{ Number( data.sampleHours || 0 ).toLocaleString( 'en-IN' ) }</strong></div>
          </div>

          { monthly.length > 1 && (
            <div className="vl-wi-trend">
              <div className="vl-wi-trend-head">
                <strong>Seasonal temperature pattern</strong>
                <span>Month-of-year average</span>
              </div>
              <div className="vl-wi-bars" aria-label="Monthly average temperature">
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

          <div className="vl-wi-source">
            { data.source || 'Google Weather Insights' }
            { Number.isFinite( data.gridDistanceKm ) ? <span data-wc-no-translate="true"> · nearest grid { fmt( data.gridDistanceKm, ' km', 2 ) }</span> : null }
          </div>
        </>
      ) }

      <style jsx>{`
        .vl-wi{margin-top:var(--vl-section-gap);padding-top:var(--vl-section-gap);border-top:1px solid var(--hair)}
        .vl-wi-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}
        .vl-wi-head h4{margin:0;color:#000;font-size:17px;font-weight:700;line-height:1.25;letter-spacing:-.18px}
        .vl-wi-head p{margin:3px 0 0;color:var(--muted);font-size:11.5px;font-weight:600;line-height:1.35}
        .vl-wi-range{display:flex;flex:0 0 auto;border:1px solid var(--hair);border-radius:999px;overflow:hidden;background:#fff}
        .vl-wi-range button{min-height:34px;padding:6px 10px;border:0;border-inline-start:1px solid var(--hair);background:#fff;color:var(--muted);font:inherit;font-size:12px;font-weight:700;cursor:pointer}
        .vl-wi-range button:first-child{border-inline-start:0}
        .vl-wi-range button:hover,.vl-wi-range button.is-active{background:var(--lime-tint);color:var(--green)}
        .vl-wi-loading,.vl-wi-note{margin-top:12px;padding:12px 14px;border:1px solid var(--hair);border-radius:12px;background:#fff;color:var(--muted);font-size:13px;font-weight:600;line-height:1.4}
        .vl-wi-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;margin-top:12px;border:1px solid var(--hair);border-radius:12px;overflow:hidden;background:var(--hair)}
        .vl-wi-grid>div{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:13px;background:#fff}
        .vl-wi-grid span{color:var(--muted);font-size:11.5px;font-weight:600;line-height:1.35}
        .vl-wi-grid strong{color:#000;font-size:16px;font-weight:700;font-variant-numeric:tabular-nums;text-align:end}
        .vl-wi-trend{margin-top:14px}
        .vl-wi-trend-head{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
        .vl-wi-trend-head strong{font-size:13px;color:var(--body)}
        .vl-wi-trend-head span{font-size:11px;color:var(--muted)}
        .vl-wi-bars{display:grid;grid-template-columns:repeat(12,minmax(18px,1fr));gap:4px;align-items:end;height:130px;margin-top:8px;padding:10px 8px 4px;border:1px solid var(--hair);border-radius:12px;background:#fff}
        .vl-wi-bar-slot{display:grid;grid-template-rows:1fr auto auto;gap:2px;min-width:0;height:100%;text-align:center}
        .vl-wi-bar-wrap{display:flex;align-items:flex-end;justify-content:center;min-height:0}
        .vl-wi-bar{width:min(16px,80%);min-height:6px;border-radius:5px 5px 2px 2px;background:var(--lime)}
        .vl-wi-bar-slot strong{font-size:10px;color:#000;font-variant-numeric:tabular-nums}
        .vl-wi-bar-slot span{font-size:9px;color:var(--muted)}
        .vl-wi-source{margin-top:8px;color:var(--muted);font-size:10.5px;font-weight:600;line-height:1.35}
        @media(max-width:560px){
          .vl-wi-head{flex-direction:column}
          .vl-wi-range{width:100%}
          .vl-wi-range button{flex:1}
          .vl-wi-grid{grid-template-columns:1fr}
          .vl-wi-bars{gap:2px;padding-inline:4px}
          .vl-wi-bar-slot strong{font-size:9px}
          .vl-wi-bar-slot span{font-size:8px}
        }
      `}</style>
    </section>
  );
};

export default VayuLokWeatherInsights;
