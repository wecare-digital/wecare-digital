import Head from 'next/head';
import Link from 'next/link';
import React from 'react';

/** Separate, intentionally inactive checkout path until native WhatsApp QA ships. */
export default function WhatsAppCheckout (): React.ReactElement {
  return (
    <>
      <Head>
        <title>WhatsApp checkout | WECARE.DIGITAL</title>
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      <main className="wa-checkout">
        <h1>WhatsApp checkout</h1>
        <p>WhatsApp checkout is being built separately. No payment or message has been started.</p>
        <Link className="wa-return" href="/checkout/">Return to website checkout</Link>
        <style jsx>{`
          .wa-checkout{width:min(100% - 40px,680px);margin:0 auto;min-height:60vh;padding:148px 0 70px;font-family:var(--font-sans);color:var(--public-text)}
          .wa-checkout h1{font-size:var(--public-section-size);line-height:var(--public-section-leading);font-weight:var(--public-section-weight);letter-spacing:var(--public-section-tracking);margin:0 0 18px}
          .wa-checkout p{font-size:var(--public-body-size);line-height:var(--public-body-leading);margin:0 0 26px}
          .wa-checkout :global(.wa-return){display:inline-flex;align-items:center;min-height:var(--public-cta-height);padding:12px 18px;border-radius:10px;color:var(--public-brand-green);background:var(--public-lime-tint);font-weight:700}
          .wa-checkout :global(.wa-return:focus-visible){outline:3px solid var(--public-brand-green);outline-offset:3px}
        `}</style>
      </main>
    </>
  );
}
