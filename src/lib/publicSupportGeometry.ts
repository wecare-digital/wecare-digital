export interface PublicSupportGeometryInput {
  layoutHeight: number;
  viewportTop: number;
  viewportHeight: number;
  viewportWidth: number;
  headerBottom: number;
  footerTop: number | null;
  pillHeight: number;
  safeBottom: number;
  open: boolean;
}

/** Coordinates use the layout viewport; the usable rectangle is the visual viewport. */
export function publicSupportGeometry(input: PublicSupportGeometryInput) {
  const {layoutHeight, viewportTop, viewportHeight, viewportWidth, headerBottom, footerTop, pillHeight, safeBottom, open} = input;
  const viewportBottom = viewportTop + viewportHeight;
  const topEdge = viewportTop + Math.min(8, viewportHeight / 4);
  const restingBottom = Math.max(0, layoutHeight - viewportBottom) + 20 + Math.max(0, safeBottom);
  const baseBottom = Math.min(restingBottom, Math.max(0, layoutHeight - topEdge - pillHeight));
  const available = Math.max(0, layoutHeight - baseBottom - pillHeight - 10 - topEdge);
  const reserve = open ? Math.min(132, available) : 0;
  const panelTop = Math.max(topEdge, Math.min(headerBottom + 12, layoutHeight - baseBottom - pillHeight - (open ? 10 + reserve : 0)));
  const maximumBottom = Math.max(baseBottom, layoutHeight - panelTop - pillHeight - (open ? 10 + reserve : 0));
  const footerBottom = viewportWidth <= 767 && footerTop !== null ? layoutHeight - footerTop + 16 : baseBottom;
  const bottom = Math.min(Math.max(baseBottom, footerBottom), maximumBottom);
  const panelMax = Math.max(0, Math.floor(layoutHeight - bottom - pillHeight - 10 - panelTop));
  return {bottom, panelMax};
}
