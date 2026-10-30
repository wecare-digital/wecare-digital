import { buildPageTitle } from '../../lib/page-title';
/**
 * Customer-owned order confirmation. A URL is never payment evidence: this page
 * requires an authenticated status read, PAYMENT_PAID and a server order number.
 * Missing, pending or unavailable evidence must not display payment success.
 */

import Head from 'next/head';
import Link from 'next/link';
import React, { useEffect, useState } from 'react';

import RotatingHero from '../../components/RotatingHero';
import { getSession, restoreSession } from '../../lib/customerAuth';
import { isOrderNumber, isPaid } from '../../lib/paymentVocabulary';
import { orderPagePath } from '../../lib/orderPage';

const STATUS_URL = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/ecommerce/checkout/status`;

export default function CheckoutSuccess (): React.ReactElement {
  const [ orderNumber, setOrderNumber ] = useState<string>( '' );
  const [ verified, setVerified ] = useState<boolean>( false );
  const [ checking, setChecking ] = useState<boolean>( true );
  const [ vaultReturnFile, setVaultReturnFile ] = useState( '' );

  useEffect( () => {
    try {
      const file = window.sessionStorage.getItem( 'wecare.vault.websiteCheckoutReturnFile' ) || '';
      if ( /^[A-Za-z0-9_-]{1,120}$/.test( file ) ) setVaultReturnFile( file );
    } catch { /* Return link is optional, never authorization. */ }
  }, [] );

  useEffect( () => {
    let stopped = false;
    const attemptId = new URLSearchParams( window.location.search ).get( 'a' );
    if ( !attemptId ) { setChecking( false ); return undefined; }
    void ( async () => {
      try {
        const session = getSession() || await restoreSession();
        if ( !session ) {
          window.location.replace( '/auth?return=/orders/' );
          return;
        }
        const response = await fetch( STATUS_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.accessToken}` },
          body: JSON.stringify( { action: 'status', paymentAttemptId: attemptId } ),
        } );
        if ( response.status === 401 ) {
          window.location.replace( '/auth?return=/orders/' );
          return;
        }
        if ( !response.ok ) return;
        const data = await response.json() as { attempt?: { status?: string; orderNumber?: string } };
        const number = data.attempt?.orderNumber || '';
        // Same vocabulary and same shape check /checkout/status uses, so the two screens cannot
        // disagree about what counts as paid. Behaviour is unchanged; the literal is gone.
        if ( !stopped && isPaid( data.attempt?.status ) && isOrderNumber( number ) ) {
          setOrderNumber( number ); setVerified( true );
        }
      } catch { /* An unavailable verification is never a successful payment. */ }
      finally { if ( !stopped ) setChecking( false ); }
    } )();
    return () => { stopped = true; };
  }, [] );

  const heading = verified ? 'Payment successful' : checking ? 'Checking your order' : 'Order confirmation unavailable';
  const destination = verified && orderNumber ? orderPagePath( orderNumber ) : '/orders/';

  return (
    <>
      <Head>
        <title>{ buildPageTitle( heading ) }</title>
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      <RotatingHero
        ariaLabel="WECARE.DIGITAL customer"
        frame="One account."
        words={ [
          { word: 'securely', tint: '#e0f7c8', dot: '#3da35a' },
          { word: 'simply', tint: '#dbeafe', dot: '#2563eb' },
          { word: 'anywhere', tint: '#ede9fe', dot: '#9849e8' },
        ] }
        sub="Pick up where you left off."
        mobileFoundation
        compact
      >
        <section className="cs-card" aria-live="polite">
          <h2 className="cs-title">{ heading }</h2>
          {/* THE TICK IS DRAWN FROM BORDERS, NOT TYPED. The old mark was the literal character ✓
              inside a filled disc, so its shape and weight varied by platform font - the same
              reason the header's chevron is two borders. A tick is an ORIENTATION rather than a
              side, so it is NOT mirrored under rtl: a flipped tick reads as a cross. */}
          { verified && <div className="cs-mark" aria-hidden="true"><i className="cs-tick" /></div> }

          {orderNumber && (
            <p className="cs-order">
              <span className="cs-order-label">Order number</span>
              {/* data-wc-no-translate: this is an identifier, and a translated or regrouped
                  WD-ORD-… is a different string. The same reason the prices carry it. */}
              <span className="cs-order-number" data-wc-no-translate="true">{orderNumber}</span>
            </p>
          )}

          { !checking && !verified && (
            <p className="cs-safety" role="status">Do not pay again.</p>
          ) }

          <div className="cs-actions">
            { verified && vaultReturnFile && (
              <Link className="cs-auth-action cs-auth-primary"
                href={ { pathname: '/vault/', query: { file: vaultReturnFile } } }>
                Return to Vault · Download
              </Link>
            ) }
            <Link className="cs-auth-action" href={ destination }>
              { verified ? 'Order' : 'Orders' }
            </Link>
          </div>
        </section>

        {/* The global Contribute + Subscribe + Share dock is mounted once by _app after policy. */}

        <style jsx>{`
          /* No top padding, no measure, no font stack: PageTopBand owns all three. */
          .cs-card{width:min(100%,560px);max-width:100%;margin:0;padding:clamp(28px,4vw,36px) clamp(24px,4.5vw,40px) clamp(30px,4.5vw,40px);border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);border-radius:24px;background:var(--public-bg);box-shadow:0 14px 38px rgba(26,58,42,.08);box-sizing:border-box;color:var(--public-text);font-family:var(--font-sans)}
          .cs-title{margin:0 0 24px;color:var(--public-text);font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking)}

          /* The disc is the palette's grassy green #3da35a, not a non-palette green - that value appears
             nowhere in the home design. 56px matches the status screen's mark, so the two
             checkout screens agree on the size of their one piece of iconography. */
          .cs-mark{
            inline-size:56px;block-size:56px;border-radius:50%;background:#3da35a;
            display:flex;align-items:center;justify-content:center;margin-block-end:24px;
          }
          /* Two borders on a rotated box: 10px x 20px, bottom and inline-end stroked at 3px,
             rotated 45deg. Deliberately NOT mirrored for rtl - see the note on the markup. */
          .cs-tick{
            inline-size:10px;block-size:20px;box-sizing:border-box;
            border-right:3px solid #fff;border-bottom:3px solid #fff;
            transform:rotate(45deg) translateY(-2px);
          }

          .cs-order{margin:0;display:flex;flex-direction:column;gap:6px}
          /* The dim rung at rgba(0,0,0,.54), not #777. Tracking in em on a fixed size is fine -
             the em rule is about clamp() sizes, where a px value makes optical tightness swing
             with the viewport. */
          .cs-order-label{
            font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
            color:var(--public-muted);
          }
          /* The card-heading rung in dark green - the same 22px/700/1.27/-.25px the catalogue
             gives a price, because this is the other identifier a customer reads back to us.
             Tabular figures so the digits are evenly spaced. */
          .cs-order-number{
            font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);
            color:#1a3a2a;font-variant-numeric:tabular-nums;
          }

          .cs-safety{margin:0;color:var(--public-brand-green);font-size:16px;font-weight:700;line-height:1.5}

          .cs-actions{margin-block-start:32px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
          .cs-card :global(.cs-auth-action){display:inline-flex;align-items:center;justify-content:center;min-height:48px;min-width:48px;padding:8px 14px;border:0;border-radius:10px;background:var(--public-lime-tint);color:var(--public-brand-green);font:600 var(--public-cta-font-size)/1.35 var(--font-sans);text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;touch-action:manipulation;cursor:pointer;transition:background-color .18s,transform .18s,box-shadow .18s}
          .cs-card :global(.cs-auth-primary){font-weight:700}
          .cs-card :global(.cs-auth-action:hover){background:var(--public-brand-lime);transform:translateY(-1px);box-shadow:var(--public-lift-shadow);text-decoration-color:transparent}
          .cs-card :global(.cs-auth-action:focus-visible){outline:3px solid var(--public-brand-green);outline-offset:3px}
          @media(max-width:767px){.cs-card{width:100%;padding:24px 18px max(24px,env(safe-area-inset-bottom));border-radius:20px}.cs-title{margin-bottom:18px;font-size:var(--public-mobile-card-size)}.cs-mark{inline-size:48px;block-size:48px;margin-block-end:18px}.cs-actions{display:grid;grid-template-columns:1fr;width:100%;margin-block-start:22px}.cs-card :global(.cs-auth-action){width:100%}}
          @media(prefers-reduced-motion:reduce){.cs-card :global(.cs-auth-action){transition:none}.cs-card :global(.cs-auth-action:hover){transform:none;box-shadow:none}}
        `}</style>
      </RotatingHero>
    </>
  );
}
