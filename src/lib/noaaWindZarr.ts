import { get, open, root, slice } from 'zarrita';

export interface NoaaWindGridSegment {
  latStart: number;
  latStep: number;
  latCount: number;
  lonStart: number;
  lonStep: number;
  lonCount: number;
  u: Float32Array;
  v: Float32Array;
}

interface NoaaWindGridRequest {
  baseUrl: string;
  north: number;
  south: number;
  west: number;
  east: number;
  gridDegrees: number;
  targetRows: number;
  targetCols: number;
  signal: AbortSignal;
}

/**
 * Read only the visible NOAA GFS 10 m U/V chunks.
 *
 * This module intentionally uses named Zarrita imports so the browser chunk does not
 * pull optional ReferenceStore/ZipStore code that VayuLok never uses.
 */
type ByteRange =
  | { offset: number; length: number }
  | { suffixLength: number };

function joinStoreUrl( baseUrl: string, key: string ): string {
  return `${baseUrl.replace( /\/$/, '' )}/${key.replace( /^\/+/, '' )}`;
}

/**
 * Minimal HTTP Zarr store for this one public dataset.
 *
 * Keeping transport local avoids bundling optional ReferenceStore/ZipStore code.
 * Sharded GFS arrays still use real byte-range reads through getRange().
 */
function createHttpRangeStore( baseUrl: string, signal: AbortSignal ) {
  const read = async ( key: string, range?: ByteRange ): Promise<Uint8Array | undefined> => {
    const headers = new Headers();
    if ( range ) {
      if ( 'suffixLength' in range ) headers.set( 'Range', `bytes=-${range.suffixLength}` );
      else headers.set( 'Range', `bytes=${range.offset}-${range.offset + Math.max( 0, range.length - 1 )}` );
    }
    const response = await fetch( joinStoreUrl( baseUrl, key ), {
      headers,
      signal,
      cache: 'no-store',
    } );
    if ( response.status === 404 ) return undefined;
    if ( !response.ok ) throw new Error( `NOAA wind data request failed (${response.status})` );
    const bytes = new Uint8Array( await response.arrayBuffer() );
    if ( range && response.status === 200 ) {
      if ( 'suffixLength' in range ) return bytes.slice( Math.max( 0, bytes.length - range.suffixLength ) );
      return bytes.slice( range.offset, range.offset + range.length );
    }
    return bytes;
  };

  return {
    get( key: string ) {
      return read( key );
    },
    getRange( key: string, range: ByteRange ) {
      return read( key, range );
    },
  };
}

export async function loadNoaaWindGrid( request: NoaaWindGridRequest ): Promise<NoaaWindGridSegment[]> {
  const store = createHttpRangeStore( request.baseUrl, request.signal );
  const group = root( store );
  const uArr = await open( group.resolve( 'wind_u_10m' ), { kind: 'array' } );
  const vArr = await open( group.resolve( 'wind_v_10m' ), { kind: 'array' } );

  const initIndex = uArr.shape[ 0 ] - 1;
  const leadIndex = 0;
  const latMin = Math.min( request.north, request.south );
  const latMax = Math.max( request.north, request.south );
  const latStartIdx = Math.max( 0, Math.floor( ( latMin + 90 ) / request.gridDegrees ) );
  const latStopIdx = Math.min( 721, Math.ceil( ( latMax + 90 ) / request.gridDegrees ) + 1 );
  const rawLatCount = Math.max( 1, latStopIdx - latStartIdx );
  const latStride = Math.max( 1, Math.ceil( rawLatCount / request.targetRows ) );

  const lonIntervals: Array<[number, number]> = request.west <= request.east
    ? [ [ request.west, request.east ] ]
    : [ [ request.west, 179.75 ], [ -180, request.east ] ];

  const segments: NoaaWindGridSegment[] = [];
  for ( const [ lonMin, lonMax ] of lonIntervals ) {
    const lonStartIdx = Math.max( 0, Math.floor( ( lonMin + 180 ) / request.gridDegrees ) );
    const lonStopIdx = Math.min( 1440, Math.ceil( ( lonMax + 180 ) / request.gridDegrees ) + 1 );
    const rawLonCount = Math.max( 1, lonStopIdx - lonStartIdx );
    const lonStride = Math.max( 1, Math.ceil( rawLonCount / request.targetCols ) );
    const selection: ( number | ReturnType<typeof slice> | null )[] = [
      initIndex,
      leadIndex,
      slice( latStartIdx, latStopIdx, latStride ),
      slice( lonStartIdx, lonStopIdx, lonStride ),
    ];
    const [ uView, vView ] = await Promise.all( [
      get( uArr, selection ),
      get( vArr, selection ),
    ] );
    const latCount = uView.shape[ 0 ];
    const lonCount = uView.shape[ 1 ];
    segments.push( {
      latStart: -90 + latStartIdx * request.gridDegrees,
      latStep: request.gridDegrees * latStride,
      latCount,
      lonStart: -180 + lonStartIdx * request.gridDegrees,
      lonStep: request.gridDegrees * lonStride,
      lonCount,
      u: Float32Array.from( uView.data as ArrayLike<number> ),
      v: Float32Array.from( vView.data as ArrayLike<number> ),
    } );
  }
  return segments;
}
