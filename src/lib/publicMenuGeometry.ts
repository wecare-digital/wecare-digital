interface PublicMenuViewport { left: number; top: number; width: number; height: number }
interface PublicMenuAnchor { left: number; right: number; bottom: number }
interface PublicMenuGeometryInput {
  viewport: PublicMenuViewport;
  anchor: PublicMenuAnchor;
  headerBottom: number;
  direction: string;
  safeLeft: number;
  safeRight: number;
  safeBottom: number;
}

/** Layout-viewport coordinates, constrained to the current visible viewport. */
export function publicMenuGeometry( { viewport: v, anchor, headerBottom, direction, safeLeft, safeRight, safeBottom }: PublicMenuGeometryInput ) {
  const compact = v.width < 768;
  const gutter = compact ? 16 : 24;
  const leftEdge = v.left + Math.min( Math.max( gutter, safeLeft ), v.width / 3 );
  const rightEdge = v.left + v.width - Math.min( Math.max( gutter, safeRight ), v.width / 3 );
  const usableWidth = Math.max( 1, rightEdge - leftEdge );
  const rtl = direction === 'rtl';
  const anchoredRoom = rtl ? anchor.right - leftEdge : rightEdge - anchor.left;
  const width = Math.floor( compact ? usableWidth : Math.min( 760, usableWidth, Math.max( 500, anchoredRoom ) ) );
  const idealLeft = compact ? leftEdge : rtl ? anchor.right - width : anchor.left;
  const left = Math.min( Math.max( idealLeft, leftEdge ), rightEdge - width );
  const topEdge = v.top + Math.min( 8, v.height / 4 );
  const bottom = v.top + v.height - Math.min( Math.max( 16, safeBottom + 8 ), v.height / 4 );
  const minimumHeight = Math.min( 160, Math.max( 0, bottom - topEdge ) );
  const preferredTop = Math.max( topEdge, compact ? headerBottom + 4 : anchor.bottom + 8 );
  const top = Math.min( preferredTop, bottom - minimumHeight );
  const maxHeight = Math.max( 0, Math.floor( bottom - top ) );
  const columns = compact || width < 460 ? 1 : v.width <= 1024 || width < 680 ? 2 : 3;
  return { left, top, width, maxHeight, columns, tight: width < 240 };
}
