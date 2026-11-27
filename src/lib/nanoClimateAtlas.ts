export type AtlasLayer = 'air' | 'AQI' | 'PM25' | 'weather';
export type AtlasPerspective = 'conditions' | 'forecast' | 'history';

/** Inspect only actual returned rows; do not synthesize timestamps. */
export function clampAtlasIndex( count: number, selected: number | null, latest: boolean ): number | null {
  if ( !Number.isInteger( count ) || count < 1 ) return null;
  if ( selected == null || !Number.isFinite( selected ) ) return latest ? count - 1 : 0;
  return Math.max( 0, Math.min( count - 1, Math.trunc( selected ) ) );
}
