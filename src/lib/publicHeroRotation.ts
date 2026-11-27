/** Shared timing for the decorative, finite public headline introduction.
 * The normal final update is due by 4000ms; the 4400ms deadline allows minor
 * scheduling delay while leaving room for the existing 520ms tint transition.
 * A stalled/hidden document never catches up with late animation.
 */
export const HERO_ROTATION_DEADLINE_MS = 4400;
export const heroRotationStepMs = ( wordCount: number ): number =>
  wordCount > 1 ? Math.max( 1, Math.min( 2400, Math.floor( 4000 / wordCount ) ) ) : 0;
