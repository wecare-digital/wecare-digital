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
        className={ `wc-public-notice is-${ mode } tone-${ tone }${ mode === 'toast' ? ' wc-action-toast' : '' }${ flush ? ' is-flush' : '' }` }
        role={ role }
        aria-live={ role === 'alert' ? 'assertive' : 'polite' }
        aria-atomic="true"
      >
        { message }
      </p>
      <style jsx>{`
        .wc-public-notice:not(.is-toast){
          box-sizing:border-box;max-inline-size:100%;margin:14px 0 0;padding:11px 13px;
          border-inline-start:4px solid var(--public-brand-lime);border-radius:10px;
          background:var(--public-lime-tint);color:var(--public-text);
          font-family:var(--font-sans);font-size:var(--public-supporting-size);
          font-weight:600;line-height:1.4;overflow-wrap:anywhere;
        }
        .wc-public-notice.is-inline{inline-size:min(100%,560px)}
        /* All toast visuals come from the global .wc-action-toast rule.
           Inline and screen-reader variants keep their existing semantics. */
        .wc-public-notice.tone-error:not(.is-toast){font-weight:700}
        .wc-public-notice.is-flush{margin:0}
        .wc-public-notice.is-screen-reader{
          position:absolute;inline-size:1px;block-size:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        @media(max-width:767px){
          .wc-public-notice:not(.is-toast){font-size:var(--public-mobile-supporting-size)}
        }
        @media(forced-colors:active){
          .wc-public-notice:not(.is-toast):not(.is-screen-reader){
            background:Canvas;color:CanvasText;border:1px solid CanvasText;
            border-inline-start-width:4px;
          }
        }
      `}</style>
    </>
  );
}
