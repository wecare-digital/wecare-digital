import { useEffect, useState } from 'react';
import { API_BASE } from '../config/constants';
import type { PlaceState } from './VayuLokLive.types';

const ENABLED = process.env.NEXT_PUBLIC_VAYULOK_EXTENDED === 'true';
type Row = { label: string; value: string };
export type EnvironmentSection = {
  key: string; title: string; href: string; attribution: string;
  google?: boolean; rows: Row[]; note?: string;
};
type Data = { status: 'loading' | 'unavailable' | 'ready'; sections: EnvironmentSection[] };
const loading: Data = { status: 'loading', sections: [] };
const unavailable: Data = { status: 'unavailable', sections: [] };

function obj( value: unknown ): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray( value ) ? value as Record<string, unknown> : {};
}
function finite( value: unknown ): value is number {
  return typeof value === 'number' && Number.isFinite( value );
}
function str( value: unknown ): string {
  return typeof value === 'string' ? value.slice( 0, 200 ) : '';
}
function number( value: unknown, decimals: number, unit: string ): string {
  return finite( value ) ? value.toLocaleString( 'en-IN', { maximumFractionDigits: decimals } ) + ' ' + unit : '';
}
function add( rows: Row[], label: string, value: string ) {
  if ( value ) rows.push( { label, value } );
}

const definitions = [
  { key: 'elevation', title: 'Elevation', attribution: 'Google Maps', google: true, href: 'https://developers.google.com/maps/documentation/elevation/overview' },
  { key: 'cpcb', title: 'Nearby CPCB monitoring station', attribution: 'CPCB · Open Government Data India', href: 'https://www.data.gov.in/resource/real-time-air-quality-index-various-locations' },
  { key: 'pvgis', title: 'Regional solar potential', attribution: 'Photovoltaic Geographical Information System (PVGIS), European Commission Joint Research Centre', href: 'https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en' },
  { key: 'solar', title: 'Nearest mapped building', attribution: 'Google Maps', google: true, href: 'https://developers.google.com/maps/documentation/solar/building-insights' },
  { key: 'spartan', title: 'SPARTAN research observations', attribution: 'SPARTAN network · CC BY 4.0', href: 'https://www.spartan-network.org/data' },
] as const;

export function formatEnvironmentSections( value: unknown ): EnvironmentSection[] {
  const sources = obj( obj( value ).sources );
  return definitions.flatMap( definition => {
    const data = obj( sources[ definition.key ] );
    const status = str( data.status );
    if ( !status || status === 'disabled' ) return [];
    const rows: Row[] = [];
    let note = '';
    if ( status !== 'ok' ) {
      note = status === 'budget_limited' ? 'Temporarily unavailable within the daily or monthly request budget.'
        : status === 'select_building' ? 'Building-level data requires a precise selected location. The regional estimate is separate.'
        : status === 'no_data' ? 'No supported reading for this location.'
        : 'Source temporarily unavailable.';
    } else if ( definition.key === 'elevation' ) {
      add( rows, 'Above mean sea level', number( data.elevationM, 1, 'm' ) );
      add( rows, 'Provider resolution', number( data.resolutionM, 1, 'm' ) );
    } else if ( definition.key === 'cpcb' ) {
      add( rows, 'Station', str( data.station ) );
      add( rows, 'Distance', number( data.distanceKm, 2, 'km' ) );
      if ( Array.isArray( data.readings ) ) {
        for ( const raw of data.readings ) {
          const reading = obj( raw );
          const label = str( reading.pollutant );
          if ( !['PM2.5', 'PM10'].includes( label ) || !finite( reading.average ) ) continue;
          const unit = str( reading.unit ) || '(source unit not specified)';
          add( rows, label + ' reported average', number( reading.average, 2, unit ) );
          add( rows, label + ' observed (IST)', str( reading.observedAt ).replace( 'T', ' ' ) + ( reading.stale === true ? ' · older reading' : '' ) );
        }
      }
      note = 'Station observations, not the Google modelled AQI for the selected point. Live field instruments may contain errors.';
    } else if ( definition.key === 'pvgis' ) {
      add( rows, 'Annual modeled generation', number( data.annualEnergyKwh, 0, 'kWh/year' ) );
      add( rows, 'Annual plane-of-array irradiation', number( data.annualIrradianceKwhM2, 0, 'kWh/m²/year' ) );
      if ( finite( data.peakPowerKw ) && finite( data.lossPct ) ) {
        add( rows, 'Model assumptions', number( data.peakPowerKw, 1, 'kWp' ) + ', ' + number( data.lossPct, 0, '% losses' ) + ', optimized tilt' );
      }
      if ( finite( data.gridLat ) && finite( data.gridLng ) ) add( rows, 'Regional model coordinates', data.gridLat.toFixed( 2 ) + ', ' + data.gridLng.toFixed( 2 ) );
      note = 'Long-term regional model, not a building survey, electricity bill or production guarantee.';
    } else if ( definition.key === 'solar' ) {
      add( rows, 'Modeled panel count', number( data.panels, 0, 'panels' ) );
      add( rows, 'Panel rating', number( data.panelCapacityW, 0, 'W' ) );
      add( rows, 'Modeled annual DC energy', number( data.annualEnergyDcKwh, 0, 'kWh/year' ) );
      add( rows, 'Building center distance', number( data.distanceM, 1, 'm' ) );
      add( rows, 'Imagery date', str( data.imageryDate ) );
      add( rows, 'Imagery quality', str( data.quality ) );
      note = 'Nearest mapped building; verify that it is the intended property. DC energy is not delivered AC generation.';
    } else if ( definition.key === 'spartan' ) {
      add( rows, 'Research site', str( data.site ) + ( str( data.siteCode ) ? ' · ' + str( data.siteCode ) : '' ) );
      add( rows, 'Distance', number( data.distanceKm, 2, 'km' ) );
      add( rows, data.method === 'estimate' ? 'Estimated PM2.5 mass' : 'Filter PM2.5 mass', number( data.pm25UgM3, 2, 'µg/m³' ) );
      add( rows, 'Sample start (local)', str( data.startDate ) );
      add( rows, 'Sample end (local)', str( data.endDate ) );
      add( rows, 'Sample duration', number( data.hoursSampled, 1, 'hours' ) );
      note = 'Historical scientific observations from supported India research sites, not live pollution or AQI.';
    }
    if ( status === 'ok' && !rows.length ) note = 'Source returned no usable readings.';
    return [{ ...definition, rows, note }];
  } );
}

export function isBuildingCandidate( viewport: PlaceState['viewport'] ): boolean {
  if ( !viewport ) return false;
  const { north, south, east, west } = viewport;
  return [north, south, east, west].every( Number.isFinite )
    && north > south && east > west && north - south <= .003 && east - west <= .003;
}

export function useVayuLokEnvironmentData( enabled: boolean, place: PlaceState ): Data | null {
  const lat = place.lat;
  const lng = place.lng;
  const region = place.regionCode || '';
  const building = isBuildingCandidate( place.viewport );
  const active = ENABLED && enabled && Number.isFinite( lat ) && Number.isFinite( lng );
  const key = active ? [lat, lng, region, building].join( ':' ) : '';
  const [ result, setResult ] = useState<{ key: string; data: Data } | null>( null );
  useEffect( () => {
    if ( !key ) return;
    const controller = new AbortController();
    // Stable selection debounce; no polling and no new request on Air/Weather tab changes.
    const timer = window.setTimeout( () => {
      void ( async () => {
        try {
          const response = await fetch( API_BASE + '/vayulok/environment', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify( { operation: 'location_context', latitude: lat, longitude: lng, regionCode: region, buildingCandidate: building } ),
            signal: controller.signal,
          } );
          if ( !response.ok ) throw new Error( 'unavailable' );
          const data: unknown = await response.json();
          const envelope = obj( data );
          if ( envelope.latitude !== lat || envelope.longitude !== lng || !envelope.sources ) throw new Error( 'wrong location' );
          if ( !controller.signal.aborted ) setResult( { key, data: { status: 'ready', sections: formatEnvironmentSections( data ) } } );
        } catch {
          if ( !controller.signal.aborted ) setResult( { key, data: unavailable } );
        }
      } )();
    }, 350 );
    return () => { window.clearTimeout( timer ); controller.abort(); };
  }, [ key, lat, lng, region, building ] );
  if ( !active ) return null;
  return result?.key === key ? result.data : loading;
}
