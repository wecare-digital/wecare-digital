import { SERVICES_PRODUCT_ID, SERVICE_CHOICES } from '../config/services';

export const META_PIXEL_ID = '3411484995761247';
export const MARKETING_CONSENT_EVENT = 'wecare:marketing-consent';
const CONSENT_KEY = 'wecare.marketing-consent.v1';
const PURCHASE_KEY = 'wecare.catalog-purchases.v1';
const listed = SERVICE_CHOICES.filter( row => row.kind === 'SUBMIT_REQUEST' || row.kind === 'VAULT' );
const contentIds = new Set( listed.map( row => `wix:${SERVICES_PRODUCT_ID}:${row.variantId}` ) );
type Pixel = ( ( ...args: unknown[] ) => void ) & {
  callMethod?: ( ...args: unknown[] ) => void; queue?: unknown[][];
  push?: Pixel; loaded?: boolean; version?: string;
};
type PixelWindow = Window & { fbq?: Pixel; _fbq?: Pixel };

export interface CatalogPurchaseFacts {
  contents: Array<{ id: string; quantity: number }>;
  amountPaise: number;
  currency: string;
}

export function marketingConsent (): 'granted' | 'denied' | null {
  if ( typeof window === 'undefined' ) return null;
  try {
    const value = window.localStorage.getItem( CONSENT_KEY );
    return value === 'granted' || value === 'denied' ? value : null;
  } catch { return null; }
}

export function setMarketingConsent ( granted: boolean ): void {
  try { window.localStorage.setItem( CONSENT_KEY, granted ? 'granted' : 'denied' ); }
  catch { return; }
  ( window as PixelWindow ).fbq?.( 'consent', granted ? 'grant' : 'revoke' );
  window.dispatchEvent( new Event( MARKETING_CONSENT_EVENT ) );
}

function pixel (): Pixel | null {
  if ( typeof window === 'undefined' || marketingConsent() !== 'granted' ) return null;
  // Preview builds and staff tooling must never populate production conversion reports.
  if ( ![ 'wecare.digital', 'www.wecare.digital' ].includes( window.location.hostname ) ) return null;
  const w = window as PixelWindow;
  if ( !w.fbq ) {
    const queue: Pixel = function ( ...args: unknown[] ) {
      if ( queue.callMethod ) queue.callMethod( ...args );
      else queue.queue!.push( args );
    };
    queue.queue = []; queue.push = queue; queue.loaded = true; queue.version = '2.0';
    w.fbq = queue; w._fbq = queue;
    const script = document.createElement( 'script' );
    script.id = 'meta-catalog-pixel'; script.async = true;
    script.src = 'https://connect.facebook.net/en_US/fbevents.js';
    document.head.appendChild( script );
    queue( 'set', 'autoConfig', false, META_PIXEL_ID );
    queue( 'init', META_PIXEL_ID );
    queue( 'consent', 'grant' );
  }
  return w.fbq;
}

export function catalogContentId ( variantId: string ): string | null {
  const id = `wix:${SERVICES_PRODUCT_ID}:${variantId}`;
  return contentIds.has( id ) ? id : null;
}

export function trackCatalogView ( path: string ): void {
  const choice = listed.find( row => row.path.replace( /\/$/, '' ) === path.split( '?' )[0].replace( /\/$/, '' ) );
  const fbq = choice && pixel();
  if ( !choice || !fbq ) return;
  fbq( 'trackSingle', META_PIXEL_ID, 'ViewContent', {
    content_type: 'product', content_ids: [ catalogContentId( choice.variantId ) ],
    contents: [ { id: catalogContentId( choice.variantId ), quantity: 1 } ], currency: 'INR',
  } );
}

export function trackCatalogAdd ( variantId: string, amountPaise: number ): void {
  const id = catalogContentId( variantId );
  if ( !id || !Number.isSafeInteger( amountPaise ) || amountPaise <= 0 ) return;
  pixel()?.( 'trackSingle', META_PIXEL_ID, 'AddToCart', {
    content_type: 'product', content_ids: [ id ], contents: [ { id, quantity: 1 } ],
    currency: 'INR', value: amountPaise / 100,
  } );
}

/** Called only after the authenticated status endpoint confirms PAID + an order. */
export function trackCatalogPurchase ( attemptId: string, facts?: CatalogPurchaseFacts ): boolean {
  if ( !attemptId || !facts || facts.currency !== 'INR'
    || !Number.isSafeInteger( facts.amountPaise ) || facts.amountPaise <= 0
    || !Array.isArray( facts.contents ) || facts.contents.length === 0
    || facts.contents.some( row => !row || typeof row !== 'object' || !contentIds.has( row.id )
      || !Number.isSafeInteger( row.quantity ) || row.quantity <= 0 ) ) return false;
  const fbq = pixel();
  if ( !fbq ) return false;
  try {
    const recorded: unknown = JSON.parse( window.localStorage.getItem( PURCHASE_KEY ) || '[]' );
    const sent = Array.isArray( recorded ) ? recorded.filter( x => typeof x === 'string' ) : [];
    if ( sent.includes( attemptId ) ) return false;
    fbq( 'trackSingle', META_PIXEL_ID, 'Purchase', {
      content_type: 'product', content_ids: facts.contents.map( row => row.id ),
      contents: facts.contents, currency: facts.currency, value: facts.amountPaise / 100,
    }, { eventID: `wecare-purchase-${attemptId}` } );
    window.localStorage.setItem( PURCHASE_KEY, JSON.stringify( [ ...sent, attemptId ].slice( -100 ) ) );
    return true;
  } catch { return false; }
}
