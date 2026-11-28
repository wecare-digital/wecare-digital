import React, { useEffect, useId, useRef, useState } from 'react';
import { formatPaiseINR } from '../../lib/money';

/**
 * F004 website form. Presentation only: the authenticated Orders controller owns
 * the selected order, authoritative quote, idempotent checkout and payment status.
 * Mount with key={orderNumber}. Never mark "received" from a click, a sent payment
 * request or a captured payment alone: require the durable F004 submission receipt.
 */
export interface SubmitRequestQuote {
  orderNumber: string;
  currency: string;
  totalPayablePaise: number;
  itemSubtotalPaise: number;
  supplyGstPaise: number;
  delightPaise: number;
  expressPaise: number;
  convenienceFeePaise: number;
  convenienceGstPaise: number;
}

export type SubmitRequestPaymentState = 'idle' | 'starting' | 'pending' | 'saving' | 'received' | 'failed';

export interface SubmitRequestFormProps {
  orderNumber: string;
  quote: SubmitRequestQuote | null;
  quoteUnavailable?: boolean;
  paymentState: SubmitRequestPaymentState;
  onReview: () => void;
  onPay: ( input: { orderNumber: string; note: string; expectedTotalPaise: number } ) => void;
  onCheckStatus: () => void;
  onDone: () => void;
  onNewRequest: () => void;
}

const MAX_NOTE_LENGTH = 300;

export default function SubmitRequestForm ( {
  orderNumber, quote, quoteUnavailable = false, paymentState,
  onReview, onPay, onCheckStatus, onDone, onNewRequest,
}: SubmitRequestFormProps ): React.ReactElement {
  const [ note, setNote ] = useState( '' );
  const [ reviewing, setReviewing ] = useState( false );
  const [ invalid, setInvalid ] = useState( false );
  const id = useId();
  const field = useRef<HTMLTextAreaElement>( null );
  const heading = useRef<HTMLHeadingElement>( null );
  const payRequested = useRef( false );
  const starting = paymentState === 'starting';
  const pending = paymentState === 'pending';
  const saving = paymentState === 'saving';
  const waiting = pending || saving;
  const received = paymentState === 'received';
  const failed = paymentState === 'failed';
  const review = reviewing || starting || waiting;
  const cleanNote = note.trim();
  const noteValid = cleanNote.length > 0 && note.length <= MAX_NOTE_LENGTH;
  const amounts = quote ? [ quote.itemSubtotalPaise, quote.supplyGstPaise, quote.delightPaise,
    quote.expressPaise, quote.convenienceFeePaise, quote.convenienceGstPaise ] : [];
  const price = quote && quote.orderNumber === orderNumber && quote.currency === 'INR'
    && Number.isSafeInteger( quote.totalPayablePaise ) && quote.totalPayablePaise > 0
    && amounts.every( amount => Number.isSafeInteger( amount ) && amount >= 0 )
    && quote.itemSubtotalPaise + quote.supplyGstPaise - quote.delightPaise
      + quote.expressPaise + quote.convenienceFeePaise + quote.convenienceGstPaise === quote.totalPayablePaise
    ? formatPaiseINR( quote.totalPayablePaise, quote.currency ) : '';
  const canPay = Boolean( price && noteValid && !starting && !waiting && !received && !quoteUnavailable );
  const title = received ? 'Request received'
    : saving ? 'Saving request' : starting || pending ? 'Complete payment' : review ? 'Review request' : 'Add a note';

  useEffect( () => { heading.current?.focus( { preventScroll: true } ); }, [ title ] );
  useEffect( () => {
    // Only a definitive failure may unlock a second explicit payment action.
    // A network timeout or unconfirmed send belongs in "pending", not "failed".
    if ( failed ) payRequested.current = false;
  }, [ failed ] );

  const continueToReview = () => {
    if ( !noteValid ) {
      setInvalid( true );
      field.current?.focus();
      return;
    }
    setInvalid( false );
    setReviewing( true );
    onReview();
  };

  const pay = () => {
    if ( !canPay || !quote || payRequested.current ) return;
    payRequested.current = true;
    onPay( { orderNumber, note: cleanNote, expectedTotalPaise: quote.totalPayablePaise } );
  };

  const priceRows: Array<{ label: string; paise: number; discount?: boolean }> = quote ? [
    { label: 'Submit Request', paise: quote.itemSubtotalPaise },
    { label: 'GST on service', paise: quote.supplyGstPaise },
    { label: 'Delight discount', paise: quote.delightPaise, discount: true },
    { label: 'Express', paise: quote.expressPaise },
    { label: 'Convenience fee', paise: quote.convenienceFeePaise },
    { label: 'GST on convenience fee', paise: quote.convenienceGstPaise },
  ] : [];

  return (
    <section className="sr-form" aria-labelledby={ id + '-heading' }>
      <div className="sr-brand" aria-label="WECARE.DIGITAL" data-wc-no-translate="true">
        <span className="sr-mark" aria-hidden="true" />
        <span className="sr-wordmark"><span>WECARE<span className="sr-dot">.</span></span><span>DIGITAL</span></span>
      </div>
      <div className="sr-accent" aria-hidden="true" />
      <p className="sr-title">Submit Request</p>
      { received && <div className="sr-check" aria-hidden="true">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12 4 4L19 6" /></svg>
      </div> }
      <h2 ref={ heading } id={ id + '-heading' } tabIndex={ -1 }>{ title }</h2>
      { received ? <p className="sr-copy">Your request has been received and linked for review.</p>
        : !review ? <p className="sr-copy">Tell our team what you need help with.</p> : null }
      <div className="sr-linked">
        <span className="sr-caption">Linked to</span>
        <strong data-wc-no-translate="true">{ orderNumber }</strong>
      </div>
      { !received && !review && <>
        <label htmlFor={ id + '-note' }>Note</label>
        <textarea
          id={ id + '-note' } ref={ field } rows={ 4 } maxLength={ MAX_NOTE_LENGTH }
          value={ note } required aria-invalid={ invalid || undefined }
          aria-describedby={ id + '-count' + ( invalid ? ' ' + id + '-error' : '' ) }
          onChange={ event => { setNote( event.target.value ); setInvalid( false ); } }
        />
        <div className="sr-count" id={ id + '-count' }>{ note.length } / { MAX_NOTE_LENGTH }</div>
        { invalid && <p className="sr-error" id={ id + '-error' } role="alert">Enter a note.</p> }
      </> }
      { !received && review && !starting && !waiting && <>
        <div className="sr-review-note"><span className="sr-caption">Note</span><p>{ cleanNote }</p></div>
        { price && quote && !quoteUnavailable ? <>
          <div className="sr-total"><span>Total payable</span><strong data-wc-no-translate="true">{ price }</strong></div>
          <details>
            <summary className="sr-details">
              <span>Price details</span>
              <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
                <path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </summary>
            <dl>{ priceRows.map( row => <div key={ row.label }>
              <dt>{ row.label }</dt>
              <dd data-wc-no-translate="true">{ row.discount ? '−' : '' }{ formatPaiseINR( row.paise, quote.currency ) }</dd>
            </div> ) }</dl>
          </details>
        </> : <p className="sr-copy" role="status">{ quoteUnavailable ? 'Price unavailable.' : 'Checking price…' }</p> }
        { failed && <p className="sr-error" role="alert">Payment was not completed.</p> }
      </> }
      { starting && <p className="sr-copy" role="status">Preparing payment…</p> }
      { pending && <p className="sr-copy" role="status">Check WhatsApp to complete your payment.</p> }
      { saving && <p className="sr-copy" role="status">Payment received. Saving your request.</p> }
      <div className="sr-actions">
        { received ? <>
          <button type="button" className="sr-action" onClick={ onDone }>Done</button>
          <button type="button" className="sr-action" onClick={ onNewRequest }>New request</button>
        </>
          : starting ? <button type="button" className="sr-action" disabled>Preparing payment…</button>
            : waiting ? <>
              <button type="button" className="sr-action" onClick={ onCheckStatus }>Check status</button>
              <button type="button" className="sr-action" onClick={ onDone }>Back to orders</button>
            </>
              : review ? <>
                { quoteUnavailable ? <button type="button" className="sr-action" onClick={ onReview }>Try again</button>
                  : <button type="button" className="sr-action" onClick={ pay } disabled={ !canPay }>Pay{ price ? ' ' + price : '' }</button> }
                <button type="button" className="sr-action" onClick={ () => setReviewing( false ) }>Back</button>
              </> : <>
                <button type="button" className="sr-action" onClick={ continueToReview }>Continue</button>
                <button type="button" className="sr-action" onClick={ onDone }>Back to orders</button>
              </> }
      </div>
      <style jsx>{`
        .sr-form{width:min(100%,440px);max-width:100%;margin:0 auto;padding:24px 22px max(24px,env(safe-area-inset-bottom));box-sizing:border-box;background:#fff;color:var(--public-text);font:400 16px/1.5 var(--font-sans)}
        .sr-brand{display:flex;align-items:center;justify-content:center;gap:8px;min-height:66px;color:var(--public-text);font-size:20px;font-weight:800;line-height:1.04;letter-spacing:-.5px}
        .sr-mark{width:54px;height:54px;border-radius:10px;background:url('https://wecare.digital/get/o/stream/media/m/wecaredigital.png') center/contain no-repeat;filter:grayscale(1)}
        .sr-wordmark{display:flex;flex-direction:column}.sr-dot{color:var(--public-brand-green)}
        .sr-accent{height:8px;margin:14px 0 24px;background:url('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAUgAAAAICAIAAAAUWfG8AAAAtUlEQVR42u2TMRKDQAwDlbw4X81f0osCcMyhY9KkSXZpwCd0smd8e74elmxZsm1J27uG+vreTu2glHLd+2mvB6WmztHhkK2d5mz7853uwuh8+n0M3E2UAp+GM3VQrrvfvn1LrR+9Z1rtVdBRuXrNlGXSlTWdqKwwXbnmVnnl2AdlhYnKMunK1OD5ulmDnypTsKHBi8kPDV5M/tjgXQDwc7DYACw2ALDYAMBiAwCLDQAsNsD/sADMw7edeU5bDwAAAABJRU5ErkJggg==') center/100% 100% no-repeat}
        .sr-title{margin:0 0 8px;color:var(--public-brand-green);font-size:15px;font-weight:600}
        h2{margin:0 0 8px;font-size:30px;line-height:1.15;letter-spacing:-.8px;font-weight:700;outline:none;overflow-wrap:anywhere}
        .sr-copy{color:#444;margin:0 0 20px}.sr-caption{font-size:13px;color:#626262}
        .sr-linked{display:flex;flex-direction:column;gap:2px;padding:14px 0;margin:0 0 24px;border-block:1px solid var(--public-hairline)}
        .sr-linked strong{font-size:16px;color:var(--public-brand-green);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
        label{display:block;margin:0 0 10px;font-weight:600}
        textarea{width:100%;min-height:116px;display:block;resize:vertical;border:0;border-bottom:1px solid #bfc5c1;border-radius:0;padding:8px 0;box-sizing:border-box;background:transparent;color:var(--public-text);font:inherit;outline:none}
        textarea:focus,textarea[aria-invalid=true]{border-bottom-color:var(--public-brand-green);box-shadow:0 2px 0 var(--public-brand-green)}
        .sr-count{text-align:right;color:#626262;font-size:12px;margin:8px 0 0;font-variant-numeric:tabular-nums}
        .sr-error{color:var(--public-brand-green);font-weight:600;font-size:14px;margin:8px 0 0}
        .sr-review-note{margin-bottom:20px}.sr-review-note p{white-space:pre-wrap;overflow-wrap:anywhere;margin:5px 0 0}
        .sr-total{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:16px 0;border-top:1px solid var(--public-hairline);font-weight:600}
        .sr-total strong{font-size:24px;color:var(--public-brand-green);font-variant-numeric:tabular-nums}
        .sr-actions{display:grid;gap:10px;margin-top:26px}
        .sr-action{display:inline-flex;align-items:center;justify-content:center;min-height:52px;width:100%;max-width:100%;box-sizing:border-box;padding:10px 18px;border:0;border-radius:var(--public-hover-radius);background:var(--public-lime-tint);color:var(--public-brand-green);font:700 var(--public-responsive-cta-size)/1.35 var(--font-sans);text-align:center;text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;white-space:normal;overflow-wrap:anywhere;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;transition:background-color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s}
        @media(hover:hover) and (pointer:fine){.sr-action:hover:not(:disabled){background:var(--public-button-hover);text-decoration-color:transparent}}
        .sr-action:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
        .sr-action:disabled{opacity:.6;cursor:not-allowed;transform:none;box-shadow:none}
        .sr-details{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:44px;box-sizing:border-box;padding:8px 10px;border:0;border-radius:var(--public-hover-radius);background:transparent;color:var(--public-brand-green);font:600 var(--public-supporting-size)/1.4 var(--font-sans);cursor:pointer;list-style:none;overflow-wrap:anywhere}
        .sr-details::-webkit-details-marker{display:none}
        .sr-details::marker{content:''}
        .sr-details svg{flex:none}
        details[open] .sr-details{background:var(--public-lime-tint)}
        details[open] .sr-details svg{transform:rotate(180deg)}
        @media(hover:hover) and (pointer:fine){.sr-details:hover{background:var(--public-hover-surface)}}
        .sr-details:focus-visible{outline:2px solid var(--public-brand-green);outline-offset:2px}
        dl{margin:12px 0 0;font-size:14px}dl div{display:flex;justify-content:space-between;gap:10px;padding:5px 0}dd{margin:0;white-space:nowrap;font-variant-numeric:tabular-nums}
        .sr-check{display:flex;align-items:center;justify-content:center;width:48px;height:48px;margin-bottom:18px;background:var(--public-lime-tint);border-radius:var(--public-hover-radius);color:var(--public-brand-green)}
        @media(min-width:768px){.sr-form{margin:32px auto;padding:24px 32px 32px;border:1px solid var(--public-hairline);border-radius:var(--public-card-radius)}.sr-actions{margin-top:32px}}
        @media(max-width:359px){.sr-form{padding-inline:16px}.sr-brand{font-size:18px}h2{font-size:27px}}
        @media(prefers-reduced-motion:reduce){.sr-action{transition:none}.sr-action:hover:not(:disabled){transform:none;box-shadow:none}}
      `}</style>
    </section>
  );
}
