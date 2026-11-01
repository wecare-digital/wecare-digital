import React from 'react';

/**
 * One public/customer-facing notice surface, separate from Workspace ToastProvider.
 *
 * - toast: compact feedback (the caller owns dismissal; failures never auto-dismiss).
 * - inline: persistent validation, payment, access and retryable errors.
 * - screen-reader: nonvisual progress/results without duplicate visible banners.
 *
 * Tone governs ARIA severity; the lime/forest palette does not signal severity alone.
 * Do not show "Sent to WhatsApp." unless the sender API accepted that particular request.
 */
export type PublicNoticeMode = 'toast' | 'inline' | 'screen-reader';
export type PublicNoticeTone = 'info' | 'success' | 'error';

export interface PublicNoticeProps {
  message: string;
  mode: PublicNoticeMode;
  tone?: PublicNoticeTone;
  id?: string;
  /** Remove the margin when an existing container already supplies spacing. */
  flush?: boolean;
}

export default function PublicNotice ( {
  message, mode, tone = 'info', id, flush = false,
}: PublicNoticeProps ): React.ReactElement {
  const role = tone === 'error' ? 'alert' : 'status';

  return (
    <>
      <p
        id={ id }
        className={ `wc-public-notice is-${ mode } tone-${ tone }${ flush ? ' is-flush' : '' }` }
        role={ role }
        aria-live={ role === 'alert' ? 'assertive' : 'polite' }
        aria-atomic="true"
      >
        { message }
      </p>
      <style jsx>{`
        .wc-public-notice{
          box-sizing:border-box;max-inline-size:100%;margin:14px 0 0;padding:11px 13px;
          border-inline-start:4px solid var(--public-brand-lime);border-radius:10px;
          background:var(--public-lime-tint);color:var(--public-text);
          font-family:var(--font-sans);font-size:var(--public-supporting-size);
          font-weight:600;line-height:1.4;overflow-wrap:anywhere;
        }
        .wc-public-notice.is-inline{inline-size:min(100%,560px)}
        /* Match the supplied original screenshot: generous light-lime card,
           semibold dark type, 8px lime stripe, rounded 20px corners. Only action
           toasts use this; inline errors retain their existing readable style. */
        .wc-public-notice.is-toast{
          inline-size:fit-content;max-inline-size:100%;margin:0;
          padding:var(--wc-toast-padding);
          border-inline-start:var(--wc-toast-stripe-width) solid var(--wc-toast-stripe);
          border-radius:var(--wc-toast-radius);
          background:var(--wc-toast-surface);color:var(--wc-toast-ink);
          font-size:var(--wc-toast-type-size);font-weight:600;line-height:1.4;
        }
        .wc-public-notice.tone-error{font-weight:700}
        .wc-public-notice.is-flush{margin:0}
        .wc-public-notice.is-screen-reader{
          position:absolute;inline-size:1px;block-size:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        @media(max-width:767px){
          .wc-public-notice{font-size:var(--public-mobile-supporting-size)}
          .wc-public-notice.is-toast{
            font-size:var(--wc-toast-mobile-type-size);
            padding:var(--wc-toast-mobile-padding);
            border-inline-start-width:var(--wc-toast-mobile-stripe-width);
            border-radius:var(--wc-toast-mobile-radius);
          }
        }
        @media(forced-colors:active){
          .wc-public-notice:not(.is-screen-reader){
            background:Canvas;color:CanvasText;border:1px solid CanvasText;
            border-inline-start-width:4px;
          }
        }
      `}</style>
    </>
  );
}
