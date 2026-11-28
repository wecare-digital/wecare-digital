/** One browser SDK loader for customer website payments. */
const RAZORPAY_SDK = 'https://checkout.razorpay.com/v1/checkout.js';

export type RazorpaySuccess = {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
};

type RazorpayOptions = {
  key: string;
  amount: number;
  currency: string;
  order_id: string;
  name: string;
  description: string;
  /** Absolute URL of the brand mark Razorpay paints at the head of its modal. */
  image?: string;
  /** Razorpay tints the modal header and its primary button with this hex. */
  theme?: { color: string };
  prefill?: Record<string, string>;
  handler: ( result: RazorpaySuccess ) => void | Promise<void>;
  modal?: { ondismiss?: () => void };
};

declare global {
  interface Window {
    Razorpay?: new ( options: RazorpayOptions ) => {
      open: () => void;
      on: ( event: string, callback: ( payload: unknown ) => void ) => void;
    };
  }
}

let razorpaySdkPromise: Promise<boolean> | null = null;
export function loadRazorpaySdk (): Promise<boolean> {
  if ( typeof window === 'undefined' ) return Promise.resolve( false );
  if ( window.Razorpay ) return Promise.resolve( true );
  if ( razorpaySdkPromise ) return razorpaySdkPromise;
  razorpaySdkPromise = new Promise<boolean>( resolve => {
    const existing = document.querySelector<HTMLScriptElement>( `script[src="${ RAZORPAY_SDK }"]` );
    const script = existing || document.createElement( 'script' );
    let done = false;
    const finish = ( ready: boolean ) => {
      if ( done ) return;
      done = true;
      window.clearTimeout( timer );
      script.removeEventListener( 'load', loaded );
      script.removeEventListener( 'error', failed );
      if ( !ready ) script.remove();
      resolve( ready );
    };
    const loaded = () => finish( Boolean( window.Razorpay ) );
    const failed = () => finish( false );
    const timer = window.setTimeout( failed, 12000 );
    script.addEventListener( 'load', loaded, { once: true } );
    script.addEventListener( 'error', failed, { once: true } );
    if ( !existing ) {
      script.src = RAZORPAY_SDK;
      script.async = true;
      try { document.head.appendChild( script ); } catch { failed(); }
    }
  } ).then( ready => {
    razorpaySdkPromise = null;
    return ready;
  } );
  return razorpaySdkPromise;
}
