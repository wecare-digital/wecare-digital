/**
 * Staff-only read-only preview of the two owner-approved WhatsApp payment images.
 *
 * This is one reusable visual contract for Vault, Drop Docs, Pay and future
 * services. Prices and outbound ORDER_DETAILS are composed by the canonical
 * commerce + outbound Lambdas, never by this component.
 */
import React from 'react';
import type { ServicePaymentTemplates } from '../../../lib/servicePricing';

interface Props {
  templates?: ServicePaymentTemplates | null;
  serviceLabel: string;
}

const PaymentTemplateMedia: React.FC<Props> = ( { templates, serviceLabel } ) => {
  const header = templates?.headerImage;
  const item = templates?.itemThumbnail;
  return (
    <section className="payment-template-media" aria-label={ `${serviceLabel} shared payment media` }>
      <div className="payment-template-heading">
        <strong>Shared Review &amp; Pay images</strong>
        <span>{ templates?.nativePay || 'Awaiting server contract' }</span>
      </div>
      { header && item ? (
        <div className="payment-template-images">
          <figure>
            {/* Static, server-validated public Meta template asset; no upload or send. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={ header } alt="Approved WhatsApp payment template header" loading="lazy" />
            <figcaption>Approved header · reused across services</figcaption>
          </figure>
          <figure>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={ item } alt="Approved ORDER_DETAILS item icon" loading="lazy" />
            <figcaption>Same item icon · quantity and price remain server-owned</figcaption>
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
