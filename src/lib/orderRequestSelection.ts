/** UI-only service selection. Never initiates payment, a Flow or a send. */
export const ORDER_REQUESTS = [
  { id: 'submit-request', label: 'Submit Request', description: 'Raise a request for an existing order.' },
  { id: 'request-amendment', label: 'Request Amendment', description: 'Ask to change a request linked to your order.' },
  { id: 'drop-docs', label: 'Drop Docs', description: 'Continue to the approved customer document-upload journey.' },
  { id: 'vault', label: 'Vault', description: 'Request access to an eligible private file. Exact-file access remains owner-checked.' },
  { id: 'shipments-track', label: 'Track', description: 'Ask for tracking for your own shipment.' },
  { id: 'request-pickup', label: 'Pickup Request', description: 'Ask about arranging a pickup for an eligible order.' },
] as const;
export type OrderRequestId = typeof ORDER_REQUESTS[number]['id'];
const KEY = 'wecare.orders.requestSelection.v1';

/** Bookmarkable UI state only; never an order selector, grant or send intent. */
export function orderRequestFromHash ( hash: string ): OrderRequestId | null {
  const fields = new URLSearchParams( hash.replace( /^#/, '' ) );
  if ( [ ...fields.keys() ].length !== 1 || !fields.has( 'request' ) ) return null;
  return orderRequestById( fields.get( 'request' ) )?.id ?? null;
}

export function orderRequestMenuHref ( label: string, href: string ): string {
  const request = href === '/orders/' ? orderRequestForLabel( label ) : null;
  return request ? `/orders/#request=${request.id}` : href;
}

export function preserveOrderRequest ( destination: string, hash: string ): string {
  const id = orderRequestFromHash( hash );
  if ( !id || !destination.startsWith( '/' ) || destination.startsWith( '//' ) ) return destination;
  const url = new URL( destination, 'https://wecare.digital' );
  if ( url.pathname !== '/orders/' && url.pathname !== '/orders'
    && !( /^\/auth\/?$/.test( url.pathname ) && url.searchParams.get( 'return' ) === '/orders/' ) ) return destination;
  url.hash = `request=${id}`;
  return url.pathname + url.search + url.hash;
}
export function orderRequestForLabel ( label: string ) {
  return ORDER_REQUESTS.find( item => item.label === label ) ?? null;
}
export function orderRequestById ( id: unknown ) {
  return ORDER_REQUESTS.find( item => item.id === id ) ?? null;
}
export function stashOrderRequest ( id: OrderRequestId ): void {
  if ( !orderRequestById( id ) || typeof window === 'undefined' ) return;
  try { window.sessionStorage.setItem( KEY, JSON.stringify( { id, at: Date.now() } ) ); } catch { /* No storage: history remains usable. */ }
}
export function takeOrderRequest (): OrderRequestId | null {
  if ( typeof window === 'undefined' ) return null;
  const linked = orderRequestFromHash( window.location?.hash || '' );
  try {
    const raw = window.sessionStorage.getItem( KEY );
    window.sessionStorage.removeItem( KEY );
    if ( linked ) return linked;
    if ( !raw ) return null;
    const value = JSON.parse( raw ) as { id?: unknown; at?: number };
    const now = Date.now();
    if ( typeof value.at !== 'number' || !Number.isFinite( value.at ) || value.at > now || now - value.at > 10 * 60 * 1000 ) return null;
    return orderRequestById( value.id )?.id ?? null;
  } catch { return linked; }
}
