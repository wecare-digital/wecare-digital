/**
 * Shared preview descriptor for the fresh /ws/collect surface.
 *
 * Every panel (Create, Log, Vault) hands the page a single preview to render in one
 * in-viewport surface. The image/PDF is ALWAYS a server-rendered or server-signed source;
 * the frontend never invents an invoice image or a price. `type` lets the page pick the PDF
 * canvas renderer (application/pdf) vs a plain <img> for a PNG/JPEG or server invoice image.
 */
export interface WsCollectPreview {
  src: string;
  label: string;
  /** MIME-ish hint: 'application/pdf' uses the private PDF canvas; anything else renders as an image. */
  type?: string;
  /** Fired when the preview has actually painted — Vault send waits for this. */
  onReady?: () => void;
}
