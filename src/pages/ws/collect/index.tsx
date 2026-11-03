/**
 * /ws/collect — the fresh, mobile-first Collect money surface (FEAT-002).
 *
 * Auth is automatic via AuthShell (see src/pages/_app.tsx); this page receives { signOut, user }
 * and renders its own WsShell. It stays noindex via SEO.
 *
 * Three sub-surfaces share ONE in-viewport preview panel:
 *   - Create: fresh custom invoice with the mandatory Express input, a debounced server quote and
 *     a server-rendered invoice image, then an approved Review & Pay send (createCollectOnce +
 *     sendPaymentLinkResult, intent-deduped, no auto-retry).
 *   - Log: invoice / payment / receipt / delivery activity.
 *   - Vault: the private-file + paid-access half of the same proven money surface (upload-init no
 *     retry, full server quote breakdown, expectedTotalPaise, Express always ₹25).
 *
 * MONEY SAFETY: every read and mutation routes through src/api/collect.ts, src/api/vault.ts and
 * the src/api/client.ts helpers. No new endpoints and no bare fetch() to the payments/secure-files
 * API are introduced here. All amounts are server-owned; the frontend never computes a price.
 */
import React from 'react';
import SEO from '../../../components/SEO';
import WsShell from '../../../components/ws/WsShell';
import CollectCreatePanel from '../../../components/ws/collect/CollectCreatePanel';
import CollectLogPanel from '../../../components/ws/collect/CollectLogPanel';
import VaultPanel from '../../../components/ws/collect/VaultPanel';
import VaultPdfPreview from '../../../components/workspace/pay/VaultPdfPreview';
import type { WsCollectPreview } from '../../../components/ws/collect/preview';

interface PageProps { signOut?: () => void; user?: any; }

type Tab = 'create' | 'log' | 'vault';

const TABS: { id: Tab; label: string }[] = [
  { id: 'create', label: 'Create' },
  { id: 'log', label: 'Log' },
  { id: 'vault', label: 'Vault' },
];

const WsCollect: React.FC<PageProps> = ( { signOut, user } ) => {
  const [ tab, setTab ] = React.useState<Tab>( 'create' );
  const [ preview, setPreview ] = React.useState<WsCollectPreview | null>( null );
  const [ previewError, setPreviewError ] = React.useState( '' );
  // Bump on any create/send so the Log/Vault lists re-read fresh server evidence.
  const [ revision, setRevision ] = React.useState( 0 );

  const onPreview = React.useCallback( ( value: WsCollectPreview | null ) => { setPreviewError( '' ); setPreview( value ); }, [] );
  const changed = React.useCallback( () => setRevision( n => n + 1 ), [] );

  const switchTab = ( next: Tab ) => { setTab( next ); setPreview( null ); setPreviewError( '' ); };

  return (
    <>
      <SEO title="Collect" description="WECARE workspace collect." noindex />
      <WsShell active="collect" user={ user } signOut={ signOut }>
        <section className="wsc">
          <header className="wsc-head">
            <p className="wsc-eyebrow">Workspace / Collect</p>
            <h1 className="wsc-title">Collect</h1>
            <p className="wsc-sub">Custom invoices, payment and receipt evidence, and the private Vault — all amounts are server-owned.</p>
          </header>

          <div className="wsc-tabs" role="tablist" aria-label="Collect sections">
            { TABS.map( t => (
              <button
                key={ t.id }
                type="button"
                role="tab"
                aria-selected={ tab === t.id }
                className={ `wsc-tab ${ tab === t.id ? 'on' : '' }` }
                onClick={ () => switchTab( t.id ) }
              >
                { t.label }
              </button>
            ) ) }
          </div>

          <div className="wsc-grid">
            <div className="wsc-panel" role="tabpanel">
              { tab === 'create' && <CollectCreatePanel onPreview={ onPreview } onCreated={ changed } /> }
              { tab === 'log' && <CollectLogPanel revision={ revision } onPreview={ onPreview } /> }
              { tab === 'vault' && <VaultPanel revision={ revision } onPreview={ onPreview } onChanged={ changed } /> }
            </div>

            <aside className="wsc-preview" aria-label="Invoice and file preview">
              <p className="wsc-preview-eyebrow">Preview</p>
              <h2 className="wsc-preview-title">{ preview?.type === 'invoice' ? 'Saved invoice preview' : tab === 'vault' ? 'File & payment preview' : 'Invoice image preview' }</h2>
              { preview ? (
                <>
                  <p className="wsc-preview-label">{ preview.label }</p>
                  { preview.type === 'application/pdf'
                    ? <VaultPdfPreview key={ preview.src } src={ preview.src } onRendered={ preview.onReady } />
                    : <img className="wsc-preview-img" src={ preview.src } alt={ preview.label } onLoad={ preview.onReady } onError={ () => setPreviewError( 'Preview could not load. Refresh the selected file or saved invoice to obtain a fresh link; no amount or image is invented.' ) } /> }
                  { previewError && <p className="wsc-preview-err" role="alert">{ previewError }</p> }
                  <p className="wsc-preview-note">Private links expire. Use the preview control again to obtain a fresh link to the saved version.</p>
                </>
              ) : (
                <p className="wsc-preview-empty">The server-rendered invoice image or selected private file appears here. No invoice image is shown before the server produces it.</p>
              ) }
            </aside>
          </div>
        </section>

        <style jsx>{ `
          .wsc{ width:100%; min-width:0; display:grid; gap:16px; }
          .wsc-head{ display:grid; gap:4px; }
          .wsc-eyebrow{
            margin:0; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;
            color:var(--text-muted,#6b7280);
          }
          .wsc-title{ margin:0; font-size:24px; font-weight:700; letter-spacing:-0.5px; color:var(--text,#1a1a1a); }
          .wsc-sub{ margin:0; font-size:13px; line-height:1.6; color:var(--text-muted,#6b7280); }

          /* A calm Notion segmented control: a faint track, and the active tab lifts to a white
             pill with forest-green text and a soft shadow — the shell's quiet-active idiom, not a
             heavy solid-green fill. */
          .wsc-tabs{
            display:inline-flex; gap:4px; padding:4px;
            border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-full,9999px);
            background:var(--bg-secondary,#f9fafb); align-self:start; max-width:100%; overflow-x:auto;
          }
          .wsc-tab{
            flex:0 0 auto; min-height:var(--tap-min,44px); padding:8px 20px;
            border:0; border-radius:var(--radius-full,9999px); background:transparent;
            color:var(--text-muted,#6b7280); font:inherit; font-weight:600; font-size:14px; cursor:pointer;
            transition:background var(--transition-normal,0.15s ease),color var(--transition-normal,0.15s ease);
          }
          .wsc-tab:hover:not(.on){ color:var(--text,#1a1a1a); }
          .wsc-tab.on{
            background:var(--surface,#fff); color:var(--accent,#1a3a2a); font-weight:700;
            box-shadow:var(--shadow-sm,0 1px 2px rgba(0,0,0,.04));
          }
          .wsc-tab:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }

          .wsc-grid{ display:grid; gap:16px; grid-template-columns:minmax(0,1fr); min-width:0; }
          .wsc-panel{ min-width:0; }

          .wsc-preview{
            min-width:0; align-self:start;
            border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-xl,14px);
            background:var(--surface,#fff); padding:18px; display:grid; gap:8px;
          }
          .wsc-preview-eyebrow{
            margin:0; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
            color:var(--text-muted,#6b7280);
          }
          .wsc-preview-title{ margin:0 0 2px; font-size:15px; font-weight:700; letter-spacing:-0.2px; color:var(--text,#1a1a1a); }
          .wsc-preview-label{ margin:0; font-size:12px; line-height:1.6; color:var(--text-muted,#6b7280); overflow-wrap:anywhere; }
          .wsc-preview-img{ display:block; max-width:100%; height:auto; border:1px solid var(--border-light,#f0f0f0); border-radius:var(--radius-md,8px); }
          .wsc-preview-err{ margin:0; font-size:12px; line-height:1.6; color:var(--danger,#dc2626); }
          .wsc-preview-note{ margin:0; font-size:11px; line-height:1.6; color:var(--text-muted,#6b7280); }
          .wsc-preview-empty{ margin:0; font-size:12px; line-height:1.6; color:var(--text-muted,#6b7280); }

          /* Desktop: side-by-side with a sticky preview column. */
          @media (min-width:900px){
            .wsc-grid{ grid-template-columns:minmax(0,1fr) minmax(300px,380px); align-items:start; }
            .wsc-preview{ position:sticky; top:16px; }
          }

          @media (prefers-reduced-motion:reduce){
            .wsc-tab{ transition:none; }
          }
        ` }</style>
      </WsShell>
    </>
  );
};

export default WsCollect;
