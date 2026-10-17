import React from 'react';
import PublicShare from './PublicShare';
import { CONTRIBUTION_AMOUNT_LABEL } from '../config/contribution';

/**
 * One site-wide public action band, mounted by _app directly above Footer.
 *
 * The four hues are not a new palette: they are the established Home/Grahak OS subject tints.
 * Brand lime stays reserved for WECARE controls inside PublicShare. This component owns layout
 * only; payment availability remains server/catalog-authoritative.
 */
const PublicFooterBand: React.FC = () => (
  <aside className="pfb" aria-label="Contribute, subscribe and share">
    <div className="pfb-inner">
      <div className="pfb-copy">
        <span className="pfb-kicker">Stay connected</span>
        <h2>Contribute { CONTRIBUTION_AMOUNT_LABEL } to what comes next.</h2>
        <p>Support the work on WhatsApp, subscribe for updates, or share this page.</p>
      </div>

      <div className="pfb-hues" aria-hidden="true">
        <span className="pfb-hue pfb-amber" />
        <span className="pfb-hue pfb-purple" />
        <span className="pfb-hue pfb-green" />
        <span className="pfb-hue pfb-red" />
      </div>

      <div className="pfb-actions">
        <PublicShare />
      </div>
    </div>

    <style jsx>{`
      .pfb{
        width:100%;box-sizing:border-box;padding:56px 24px;
        border-block-start:1px solid #e5e7eb;background:#fcfdfb;
        font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
      }
      .pfb-inner{
        width:100%;max-width:1300px;margin:0 auto;display:grid;
        grid-template-columns:minmax(0,1.25fr) minmax(220px,.75fr) auto;
        gap:32px;align-items:center;
      }
      .pfb-copy{min-width:0}
      .pfb-kicker{
        display:inline-flex;align-items:center;min-height:28px;padding:0 10px;
        border-radius:999px;background:#d1f470;color:#1a3a2a;
        font-size:13px;font-weight:700;line-height:1;
      }
      .pfb h2{
        margin:14px 0 8px;max-width:720px;color:rgba(0,0,0,.95);
        font-size:clamp(28px,3.4vw,46px);font-weight:700;line-height:1.08;letter-spacing:-.035em;
      }
      .pfb p{margin:0;max-width:680px;color:rgba(0,0,0,.64);font-size:17px;line-height:1.55}
      .pfb-hues{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
      .pfb-hue{display:block;min-height:54px;border-radius:14px;border:1px solid rgba(26,58,42,.08)}
      .pfb-amber{background:#fef3c7}
      .pfb-purple{background:#ede9fe}
      .pfb-green{background:#e0f7c8}
      .pfb-red{background:#fee2e2}
      .pfb-actions{justify-self:end;min-width:180px}
      .pfb-actions :global(.public-share){margin:0;padding:0}
      @media(max-width:900px){
        .pfb-inner{grid-template-columns:minmax(0,1fr) auto}
        .pfb-hues{grid-column:1 / -1;grid-row:2;grid-template-columns:repeat(4,minmax(0,1fr))}
        .pfb-hue{min-height:18px}
      }
      @media(max-width:640px){
        .pfb{padding:40px 16px}
        .pfb-inner{grid-template-columns:1fr;gap:22px}
        .pfb-actions{justify-self:start;min-width:0}
        .pfb-hues{grid-column:auto;grid-row:auto}
        .pfb h2{font-size:30px}
      }
    `}</style>
  </aside>
);

export default PublicFooterBand;
