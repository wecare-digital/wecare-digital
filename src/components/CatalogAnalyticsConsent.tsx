import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import {
  MARKETING_CONSENT_EVENT, marketingConsent, setMarketingConsent, trackCatalogView,
} from '../lib/metaCatalogAnalytics';

/** Public pages only. Optional product tracking starts after an explicit choice. */
export default function CatalogAnalyticsConsent (): React.ReactElement {
  const router = useRouter();
  const [ choice, setChoice ] = useState<'granted' | 'denied' | null>( null );
  const [ editing, setEditing ] = useState( false );
  useEffect( () => {
    const changed = () => { setChoice( marketingConsent() ); };
    changed();
    window.addEventListener( MARKETING_CONSENT_EVENT, changed );
    return () => window.removeEventListener( MARKETING_CONSENT_EVENT, changed );
  }, [] );
  useEffect( () => {
    if ( choice === 'granted' ) trackCatalogView( router.asPath );
  }, [ choice, router.asPath ] );
  const choose = ( allow: boolean ) => { setMarketingConsent( allow ); setEditing( false ); };
  return (
    <section className="catalog-consent" aria-label="Cookie choices">
      { choice === null || editing ? <>
        <p>Allow optional cookies to help us measure product visits and purchases?
          {' '}<Link href="/privacy/#s12">Privacy policy</Link></p>
        <div className="choices">
          <button type="button" onClick={ () => choose( false ) }>Essential only</button>
          <button type="button" onClick={ () => choose( true ) }>Allow optional cookies</button>
        </div>
      </> : <button type="button" onClick={ () => setEditing( true ) }>Cookie choices</button> }
      <style jsx>{`
        .catalog-consent{padding:16px 24px;background:#fff;color:#1a3a2a;border-top:1px solid rgba(0,0,0,.12);font-size:14px}
        p{margin:0 0 12px;line-height:1.5}.catalog-consent :global(a){color:inherit;text-decoration:underline}
        .choices{display:flex;flex-wrap:wrap;gap:12px}
        button{font:inherit;color:inherit;background:#fff;border:1px solid #1a3a2a;border-radius:50px;padding:10px 18px;cursor:pointer;min-height:44px}
        button:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
      `}</style>
    </section>
  );
}
