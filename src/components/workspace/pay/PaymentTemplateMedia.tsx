/**
 * Staff-only read-only preview of the two owner-approved WhatsApp payment images.
 *
 * This is one reusable visual contract for Vault, Drop Docs, Pay and future
 * services. Prices and outbound ORDER_DETAILS are composed by the canonical
 * commerce + outbound Lambdas, never by this component.
 */
import React from 'react';
import * as api from '../../../api/client';
import type { ServicePaymentTemplates } from '../../../lib/servicePricing';

interface Props {
  templates?: ServicePaymentTemplates | null;
  serviceLabel: string;
  /** Staff-only, short-lived S3 GET preview. Does not change the Meta sender. */
  signedPreview?: boolean;
}

const PaymentTemplateMedia: React.FC<Props> = ( { templates, serviceLabel, signedPreview = false } ) => {
  const [ signed, setSigned ] = React.useState<api.VaultPaymentMediaPreview | null>( null );
  const [ loading, setLoading ] = React.useState( false );
  const [ error, setError ] = React.useState( '' );
  const refreshSignedPreview = async () => {
    setLoading( true );
    setError( '' );
    setSigned( null );
    try {
    const result = await api.getVaultPaymentMediaPreview();
    if ( !result.ok ) setError( 'Unable to load a signed S3 preview. The approved public image is shown instead.' );
    else {
      const data = result.data;
      const signedGet = ( url: string ): boolean => {
        try {
          const parsed = new URL( url );
          return parsed.protocol === 'https:' && parsed.hostname.endsWith( '.amazonaws.com' )
            && parsed.searchParams.has( 'X-Amz-Signature' );
        } catch { return false; }
      };
      if ( signedGet( data.headerPreviewUrl ) && signedGet( data.itemPreviewUrl )
        && data.expiresInSeconds > 0 && data.expiresInSeconds <= 60 ) {
        setSigned( data );
      } else setError( 'Signed S3 preview was not validated; no private URL was displayed.' );
    }
    } catch {
      setError( 'S3 preview status could not be verified; approved source images remain available.' );
    } finally {
      setLoading( false );
    }
  };
  const header = signed?.headerPreviewUrl || templates?.headerImage;
  const item = signed?.itemPreviewUrl || templates?.itemThumbnail;
  return (
    <section className="payment-template-media" aria-label={ `${serviceLabel} shared payment media` }>
      <div className="payment-template-heading">
        <strong>Shared Review &amp; Pay images</strong>
        <span>{ templates?.nativePay || 'Awaiting server contract' }</span>
      </div>
      { signedPreview && (
        <div className="payment-media-signed">
          <button type="button" disabled={ loading } onClick={ () => { void refreshSignedPreview(); } }>
            { loading ? 'Loading signed S3 media…' : signed ? 'Refresh 60-second S3 preview' : 'Preview approved S3 header and item image' }
          </button>
          <small>{ signed ? 'Signed preview valid for up to 60 seconds; never forwarded to customers.' : 'The approved source images remain read-only.' }</small>
          { error && <small role="alert">{ error }</small> }
        </div>
      ) }
      { header && item ? (
        <div className="payment-template-images">
          <figure>
            {/* Static, server-validated public Meta template asset; no upload or send. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={ header } alt="Approved WhatsApp payment template header" loading="lazy" />
            <figcaption>{ signed ? 'Verified S3 GET · approved template header' : 'Approved header · reused across services' }</figcaption>
          </figure>
          <figure>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={ item } alt="Approved ORDER_DETAILS item icon" loading="lazy" />
            <figcaption>{ signed ? 'Verified S3 GET · approved ORDER_DETAILS item' : 'Same item icon · quantity and price remain server-owned' }</figcaption>
          </figure>
        </div>
      ) : (
        <p className="payment-template-unavailable" role="status">
          The server has not supplied verified payment media for this preview.
          This screen cannot replace or upload a payment image.
        </p>
      ) }
      <small>Visual reference only. The existing payment backend applies these images and the live service quote.</small>
      <style jsx>{`
        .payment-media-signed{margin-bottom:12px;display:flex;flex-wrap:wrap;align-items:center;gap:8px}
        .payment-media-signed button{border:1px solid var(--border);border-radius:8px;padding:8px 12px;background:var(--surface,#fff);font-weight:700;cursor:pointer}
        .payment-media-signed button:disabled{opacity:.6;cursor:wait}
        .payment-template-media{min-width:0;padding:12px;border:1px solid var(--border);border-radius:11px;background:#fff;color:var(--text)}
        .payment-template-heading{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:5px;margin-bottom:10px}
        .payment-template-heading strong{font-size:13px;color:var(--text)}
        .payment-template-heading span{font-size:11px;overflow-wrap:anywhere;color:var(--text-muted)}
        .payment-template-images{display:grid;grid-template-columns:1fr 1fr;gap:10px}
        figure{min-width:0;margin:0;padding:8px;border:1px solid var(--border-light,var(--border));border-radius:8px;background:var(--bg-secondary,#f8faf9)}
        img{width:100%;height:106px;object-fit:contain;display:block}
        figcaption{margin-top:6px;font-size:11px;color:var(--text-muted);line-height:1.4}
        small,.payment-template-unavailable{display:block;font-size:11px;color:var(--text-muted);line-height:1.5;margin:10px 0 0}
        @media(max-width:420px){.payment-template-images{grid-template-columns:1fr}img{height:90px}}
      `}</style>
    </section>
  );
};

export default PaymentTemplateMedia;
