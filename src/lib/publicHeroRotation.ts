/** Shared interval for all continuous public headline rotations. */
export const HERO_ROTATION_INTERVAL_MS = 2400;

/** Own exactly one clock. Suspended timers never replay missed ticks. */
export function createHeroRotationClock (
  start: ( tick: () => void, intervalMs: number ) => number,
  clear: ( timer: number ) => void,
  tick: () => void,
) {
  let timer: number | undefined;
  const stop = () => {
    if ( timer === undefined ) return;
    clear( timer );
    timer = undefined;
  };
  return {
    sync ( enabled: boolean ) {
      if ( !enabled ) { stop(); return; }
      if ( timer === undefined ) timer = start( tick, HERO_ROTATION_INTERVAL_MS );
    },
    stop,
  };
}
