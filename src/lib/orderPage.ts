/**
 * One customer Orders destination for all checkout and service entry points.
 * No public per-order URL, query parameter, session-stored row selector or
 * individual order detail page is generated.
 */
export function orderPagePath ( _orderNumber: string ): string {
  return '/orders/';
}
