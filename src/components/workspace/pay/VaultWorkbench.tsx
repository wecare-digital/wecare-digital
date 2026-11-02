/**
 * Fresh Vault workbench for Pay & Flow.
 *
 * One customer-bound private file, one server-owned native payment request and
 * one post-payment Access Vault template. There is NO interactive menu, offer
 * chooser, browser price calculation, raw PDF send or direct Meta payload.
 *
 * Display is read-only. Create uses explicit staff actions and never retries
 * a WhatsApp send after an ambiguous response.
 */
import React from 'react';
import Link from 'next/link';
import * as api from '../../../api/client';
import { useConfirm } from '../../../contexts/ConfirmContext';

interface Props {
  signOut?: () => void;
  user?: unknown;
  embedded?: boolean;
  workspaceView?: 'display' | 'create';
}
type DeliveryRecord = api.VaultMessageDeliveryEvidence;
type DeliveryKey = keyof api.VaultMessageDeliveryLog['evidence'];
const EVIDENCE_STAGES: { key: DeliveryKey; label: string }[] = [
  { key: 'nativePay', label: 'Approved Review & Pay' },
  { key: 'processing', label: 'Payment Processing' },
  { key: 'completed', label: 'Payment Completed' },
  { key: 'invoice', label: 'Paid GST invoice' },
  { key: 'autoAccess', label: 'Automatic Access Vault' },
  { key: 'access', label: 'Manual access resend' },
];
const digits = (v: string) => v.replace(/[^0-9]/g, '');
const when = (v?: string | number | null): string => {
  if (!v) return '—';
  const num = typeof v === 'number' ? v : Number(v);
  const date = Number.isFinite(num) && num > 0
    ? new Date(num > 1e12 ? num : num * 1000)
    : new Date(String(v));
  return Number.isNaN(date.getTime()) ? '—'
    : date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
};
const outcomeText = (file: api.SecureFile): string =>
  file.accessState || file.vaultPaymentStatus || file.deliveryStatus || 'Not verified';

const VaultWorkbench: React.FC<Props> = ({ workspaceView = 'display' }) => {
  const confirm = useConfirm();
  const [files, setFiles] = React.useState<api.SecureFile[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [listError, setListError] = React.useState('');
  const [truncated, setTruncated] = React.useState(false);
  const [mobileFilter, setMobileFilter] = React.useState('');
  const [appliedMobile, setAppliedMobile] = React.useState('');
  const [historical, setHistorical] = React.useState(false);
  const [fileName, setFileName] = React.useState('');
  const [ownerMobile, setOwnerMobile] = React.useState('');
  const [selectedFile, setSelectedFile] = React.useState<File | null>(null);
  const [uploading, setUploading] = React.useState(false);
  const [uploadOutcome, setUploadOutcome] = React.useState('');
  const [actionOutcome, setActionOutcome] = React.useState('');
  const [actionFile, setActionFile] = React.useState('');
  const [attempted, setAttempted] = React.useState<Set<string>>(() => new Set());
  const [deliveryFile, setDeliveryFile] = React.useState('');
  const [delivery, setDelivery] = React.useState<api.VaultMessageDeliveryLog | null>(null);
  const [deliveryMessage, setDeliveryMessage] = React.useState('');
  const inFlight = React.useRef(false);

  const load = React.useCallback(async (phone = appliedMobile, history = historical) => {
    setLoading(true);
    setListError('');
    setFiles([]);
    try {
      if (history) {
        const answer = await api.listSecureFileLogs(phone || undefined);
        if (!answer.ok) throw new Error(answer.failure.message);
        // Historical listing is read-only, and deliberately cannot drive staff sends.
        setFiles(answer.data.logs);
        setTruncated(!!answer.data.truncated);
      } else {
        const answer = await api.listSecureFiles(phone || undefined);
        if (!answer.ok) throw new Error(answer.failure.message);
        setFiles(answer.data.files || []);
        setTruncated(!!answer.data.truncated);
      }
    } catch {
      setListError('Vault file register is unavailable. No file may be assumed payable or accessible.');
    } finally {
      setLoading(false);
    }
  }, [appliedMobile, historical]);

  React.useEffect(() => { void load(); }, [load]);

  const applySearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = digits(mobileFilter);
    setAppliedMobile(value);
  };

  const upload = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (uploading || inFlight.current || !selectedFile) return;
    if (!fileName.trim() || digits(ownerMobile).length < 10) {
      setUploadOutcome('Enter the customer name and a valid WhatsApp mobile number.');
      return;
    }
    if (!['application/pdf', 'image/jpeg', 'image/png'].includes(selectedFile.type)) {
      setUploadOutcome('Choose a PDF, JPEG or PNG. Other file types need server-side review.');
      return;
    }
    const approved = await confirm({
      title: 'Upload this private Vault file?',
      message: 'The backend will bind the private file to the entered customer and verify it. Uploading does not send WhatsApp, create a payment or grant access.',
      confirmText: 'Upload private file',
    });
    if (!approved || inFlight.current) return;
    inFlight.current = true;
    setUploading(true);
    setUploadOutcome('');
    let createdId = '';
    try {
      const init = await api.initVaultFileUpload({
        name: fileName.trim(),
        mobile: digits(ownerMobile),
        originalFilename: selectedFile.name,
        contentType: selectedFile.type,
        sizeBytes: selectedFile.size,
      });
      if (!init.ok) {
        setUploadOutcome('Upload not authorized: ' + init.failure.message);
        return;
      }
      createdId = init.data.fileId;
      const received = await api.uploadVaultFileBytes(
        init.data.uploadUrl, selectedFile, init.data.contentType);
      if (!received) {
        setUploadOutcome('Upload could not be confirmed for file ' + createdId
          + '. Check the register before starting a second upload.');
        return;
      }
      const verified = await api.confirmVaultFileUpload(createdId);
      if (!verified.ok || verified.data.status !== 'active') {
        setUploadOutcome('File verification is not confirmed for ' + createdId
          + '. Check the register; do not send a payment request yet.');
        return;
      }
      setUploadOutcome('File verified: ' + createdId
        + '. Refresh the register and review its exact owner before requesting payment.');
      setFileName('');
      setOwnerMobile('');
      setSelectedFile(null);
      await load();
    } catch {
      setUploadOutcome('File upload result is uncertain'
        + (createdId ? ' for ' + createdId : '')
        + '. Check the register before trying again.');
    } finally {
      setUploading(false);
      inFlight.current = false;
    }
  };

  const send = async (file: api.SecureFile, action: 'payment' | 'access') => {
    if (inFlight.current || historical || file.status !== 'active') return;
    const canPay = file.accessState === 'UNPAID'
      && !file.lastPaymentRequestedAt && !attempted.has(file.fileId);
    const canAccess = file.accessState === 'READY' || file.accessState === 'OPEN';
    if ((action === 'payment' && !canPay) || (action === 'access' && !canAccess)) return;
    const approved = await confirm({
      title: action === 'payment' ? 'Request native Review & Pay?' : 'Resend Access Vault link?',
      message: action === 'payment'
        ? 'The backend will verify this exact file and owner, live price, payment configuration and approved Meta template. This requests payment; it does not mark anything paid. An ambiguous send must never be retried blindly.'
        : 'The backend must re-check a verified paid entitlement. This sends only the approved Access Vault URL template; it cannot charge the customer.',
      confirmText: action === 'payment' ? 'Send payment request once' : 'Send approved access link',
    });
    if (!approved || inFlight.current) return;
    inFlight.current = true;
    setActionFile(file.fileId);
    setActionOutcome('');
    if (action === 'payment') {
      setAttempted(current => new Set([...current, file.fileId]));
    }
    try {
      const response = action === 'payment'
        ? await api.requestSecureFilePayment(file.fileId)
        : await api.sendSecureFileAccess(file.fileId);
      setActionOutcome((response.ok ? 'Server accepted: ' : 'Not confirmed: ')
        + response.outcome + ' · ' + response.message
        + ' Check the provider message log and payment ledger before further action.');
      await load();
    } catch {
      setActionOutcome('The send status is unknown. Check the WhatsApp message log'
        + ' and payment ledger. Do not retry blindly.');
    } finally {
      inFlight.current = false;
      setActionFile('');
    }
  };

  const showDelivery = async (fileId: string) => {
    if (deliveryFile === fileId) {
      setDeliveryFile('');
      setDelivery(null);
      return;
    }
    setDeliveryFile(fileId);
    setDelivery(null);
    setDeliveryMessage('Reading provider evidence…');
    try {
      const result = await api.readVaultMessageDeliveryLog(fileId);
      if (result.ok) {
        setDelivery(result.data);
        setDeliveryMessage('');
      } else {
        setDeliveryMessage('Provider evidence unavailable: ' + result.failure.message);
      }
    } catch {
      setDeliveryMessage('Provider evidence could not be loaded.');
    }
  };

  const downloadForStaff = async (fileId: string) => {
    try {
      const url = await api.getVaultStaffDownloadUrl(fileId);
      if (!url) { setActionOutcome('Staff preview unavailable; no download was opened.'); return; }
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch {
      setActionOutcome('Staff preview could not be retrieved.');
    }
  };

  return (
    <section className="vault-workbench" aria-label="Exact-file Vault workbench">
      <header className="vault-intro">
        <div>
          <p className="eyebrow">PAY &amp; FLOW / VAULT</p>
          <h2>{workspaceView === 'display' ? 'Vault · File and delivery register' : 'Vault · Verify and request payment'}</h2>
          <p>Private, owner-bound files. Approved native Review &amp; Pay is sent only from the verified backend. There is no WhatsApp interactive menu or raw-document attachment.</p>
        </div>
        <div className="vault-links">
          <Link href="/workspace/payments?view=vault&tab=ledger">Vault ledger</Link>
          <Link href="/workspace/payments?view=timing">Access delay</Link>
        </div>
      </header>

      {workspaceView === 'create' && (
        <form className="vault-upload" onSubmit={upload}>
          <h3>1. Register a private file</h3>
          <p>Upload alone does not request payment or give the customer access. The server must confirm the file is active.</p>
          <div className="vault-fields">
            <label>Customer name<input value={fileName} onChange={e => setFileName(e.target.value)}
              maxLength={160} required placeholder="Verified customer name" /></label>
            <label>Customer WhatsApp mobile<input value={ownerMobile}
              onChange={e => setOwnerMobile(e.target.value)}
              required inputMode="tel" autoComplete="off" placeholder="91XXXXXXXXXX" /></label>
            <label>Private file (PDF / JPEG / PNG)<input type="file"
              accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
              onChange={e => setSelectedFile(e.target.files?.[0] || null)} required /></label>
          </div>
          <button type="submit" disabled={uploading || !selectedFile}>
            {uploading ? 'Verifying private upload…' : 'Upload & verify file'}</button>
          {uploadOutcome && <p role="status" className="vault-outcome">{uploadOutcome}</p>}
        </form>
      )}

      <div className="vault-register">
        <div className="vault-register-heading">
          <div><h3>{historical ? 'Retained file history · read only' : 'Current Vault files'}</h3>
            <p>{loading ? 'Checking live records…' : files.length + ' records'}
              {truncated ? ' · The backend truncated the listing; filter by owner.' : ''}</p></div>
          <label className="history-switch"><input type="checkbox" checked={historical}
            onChange={e => { setHistorical(e.target.checked); setDelivery(null); setDeliveryFile(''); }} />
            Show historical audit rows</label>
        </div>
        <form className="vault-filter" onSubmit={applySearch}>
          <label htmlFor="vault-search-mobile">Filter by customer mobile</label>
          <input id="vault-search-mobile" value={mobileFilter}
            onChange={e => setMobileFilter(e.target.value)} inputMode="tel"
            placeholder="WhatsApp number, or leave blank for all" />
          <button type="submit">Search</button>
          <button type="button" onClick={() => void load()}>Refresh</button>
        </form>
        {listError && <p role="alert" className="vault-error">{listError}</p>}
        {!listError && !loading && files.length === 0 && (
          <p role="status">No files found. Nothing is assumed uploaded, paid or delivered.</p>
        )}
        <div className="vault-list">
          {files.map(file => {
            const canPay = workspaceView === 'create' && !historical
              && file.status === 'active' && file.accessState === 'UNPAID'
              && !file.lastPaymentRequestedAt && !attempted.has(file.fileId);
            const canAccess = workspaceView === 'create' && !historical
              && file.status === 'active'
              && (file.accessState === 'READY' || file.accessState === 'OPEN');
            const rowBusy = actionFile === file.fileId;
            return (
              <article className="vault-file" key={file.fileId}>
                <div className="vault-file-heading">
                  <div>
                    <h4>{file.displayName || file.originalFilename || 'Private Vault file'}</h4>
                    <code>{file.fileId}</code>
                    <p>{file.ownerName || 'Owner not displayed'}{file.ownerPhoneMasked ? ' · ' + file.ownerPhoneMasked : ''}
                      {' · '}{file.status} · {outcomeText(file)}</p>
                  </div>
                  <small>{when(file.createdAt)}</small>
                </div>
                <div className="vault-file-actions">
                  <button type="button" onClick={() => void showDelivery(file.fileId)}>
                    {deliveryFile === file.fileId ? 'Hide delivery evidence' : 'Provider delivery evidence'}</button>
                  <button type="button" onClick={() => void downloadForStaff(file.fileId)}>
                    Staff file preview</button>
                  {canPay && <button type="button" disabled={rowBusy || uploading}
                    onClick={() => void send(file, 'payment')}>Send approved Review &amp; Pay once</button>}
                  {canAccess && <button type="button" disabled={rowBusy || uploading}
                    onClick={() => void send(file, 'access')}>Resend approved Access Vault</button>}
                </div>
                {workspaceView === 'create' && !historical && !canPay && !canAccess && (
                  <p className="vault-hint">Payment or access is not eligible for a new manual send.
                    Reconcile the file, entitlement and existing WhatsApp request in the ledger.</p>
                )}
                {deliveryFile === file.fileId && (
                  <div className="vault-evidence">
                    {deliveryMessage && <p role="status">{deliveryMessage}</p>}
                    {delivery && (
                      <dl>
                        {EVIDENCE_STAGES.map(stage => {
                          const evidence = delivery.evidence[stage.key] as DeliveryRecord | undefined;
                          return <div key={stage.key}><dt>{stage.label}</dt><dd>
                            {evidence?.status || 'NOT_TRACKED'} · {when(evidence?.observedAt)}
                          </dd></div>;
                        })}
                      </dl>
                    )}
                    <p>Provider accepted/read does not establish payment capture or access entitlement.</p>
                  </div>
                )}
              </article>
            );
          })}
        </div>
        {actionOutcome && <p role="status" className="vault-outcome">{actionOutcome}</p>}
      </div>
      <footer className="vault-footnote">
        Pay &amp; Flow owns money requests. S3 keys never appear here. Revoke/delete requires a separate
        entitlement and statutory-history review; this workbench does not silently erase paid records.
      </footer>
      <style jsx>{`
        .vault-workbench{display:grid;gap:20px;max-width:1230px;padding:8px 0 36px}
        .vault-intro{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}
        .eyebrow{font-size:11px;letter-spacing:.1em;font-weight:800;color:var(--text-muted);margin:0 0 7px}
        h2{font-size:clamp(23px,3vw,31px);margin:0 0 7px;color:var(--text-primary)}
        h3{font-size:18px;margin:0 0 6px;color:var(--text-primary)}
        h4{font-size:16px;margin:0 0 5px;color:var(--text-primary);overflow-wrap:anywhere}
        p{font-size:13px;line-height:1.55;color:var(--text-muted);margin:5px 0}
        button,.vault-links :global(a){min-height:42px;padding:9px 13px;border:1px solid var(--border);border-radius:9px;background:var(--surface);font:inherit;font-size:12px;font-weight:750;color:var(--text-primary);cursor:pointer;text-decoration:none}
        button:disabled{cursor:not-allowed;opacity:.55}
        button:focus-visible,input:focus-visible,.vault-links :global(a:focus-visible){outline:3px solid var(--accent);outline-offset:2px}
        .vault-links{display:flex;gap:8px;flex-wrap:wrap}
        .vault-upload,.vault-register,.vault-footnote{border:1px solid var(--border);border-radius:14px;background:var(--surface);padding:18px}
        .vault-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0}
        .vault-fields label,.vault-filter label{display:grid;gap:7px;font-size:12px;font-weight:750;color:var(--text-primary)}
        input:not([type=checkbox]){width:100%;box-sizing:border-box;min-height:43px;border:1px solid var(--border);border-radius:9px;padding:9px 11px;font:inherit;font-size:13px;background:#fff}
        .vault-register-heading{display:flex;justify-content:space-between;gap:12px;align-items:center}
        .history-switch{display:flex;align-items:center;gap:9px;font-size:12px;font-weight:700}
        .vault-filter{display:grid;grid-template-columns:1fr auto auto;gap:10px;align-items:end;margin:16px 0}
        .vault-filter label{grid-column:1/-1}
        .vault-list{display:grid;gap:11px}
        .vault-file{border:1px solid var(--border);border-radius:12px;padding:15px;background:var(--bg-secondary)}
        .vault-file-heading{display:flex;justify-content:space-between;gap:15px}
        .vault-file-heading code{font-size:11px;overflow-wrap:anywhere}
        .vault-file-heading small{font-size:11px;color:var(--text-muted);white-space:nowrap}
        .vault-file-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
        .vault-hint{font-size:12px}
        .vault-evidence{margin-top:14px;border-top:1px solid var(--border);padding-top:12px}
        .vault-evidence dl{margin:0;display:grid;gap:6px}
        .vault-evidence dl>div{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--border)}
        .vault-evidence dt{font-size:12px;color:var(--text-muted)}
        .vault-evidence dd{margin:0;font-size:12px;font-weight:750;text-align:right}
        .vault-outcome,.vault-error{padding:12px;border:1px solid var(--border);border-radius:9px;overflow-wrap:anywhere}
        .vault-error{color:#a32626}
        .vault-footnote{font-size:12px;line-height:1.5;color:var(--text-muted)}
        @media(max-width:760px){.vault-intro,.vault-register-heading,.vault-file-heading{flex-direction:column}.vault-fields,.vault-filter{grid-template-columns:1fr}.vault-filter label{grid-column:auto}.vault-links :global(a){flex:1;text-align:center}.vault-file-heading small{white-space:normal}}
      `}</style>
    </section>
  );
};

export default VaultWorkbench;
