/**
 * Staff controls for Contribute payment PREPARATION.
 *
 * Customer identity, Meta ORDER_DETAILS and money are server-owned. This form
 * only builds an internal, in-memory draft. In particular, never call the
 * generic template sender or invoice engine to fabricate a contribution charge.
 */
import React from 'react';
import { useConfirm } from '../../../contexts/ConfirmContext';
import * as api from '../../../api/client';
import { rupeesFromPaise, type ServicePaymentTemplates, type ServicePrice } from '../../../lib/servicePricing';

interface Props {
  readonly price: ServicePrice;
  readonly templates: ServicePaymentTemplates | null;
  readonly loadingPrice: boolean;
  readonly refreshPrice: () => void;
}

type Approval = 'checking' | 'approved' | 'unverified';
const TARGET_PAISE = 30000;
const EXPRESS_CHARGE_PAISE = 1500;
const META_PAYMENT_BODY = '💳 Your order is ready for payment. Tap Review and Pay to complete it securely.';
const CONTACT_LIMIT = 40;
const money = (v: number) => '₹' + rupeesFromPaise(v);
const keyOf = (c: api.Contact): string => c.id; // DynamoDB ContactsTable primary key, not a display ID
const usableContact = (c: api.Contact): boolean =>
  !!keyOf(c) && !!c.phone && !c.deletedAt && !c.archivedAt && !c.locked;

/** Read-only quote check: every Contribute tax/fee line must reconcile exactly. */
const matchesContributionQuote = (p: ServicePrice): boolean => {
  if (!p.available || p.paise !== TARGET_PAISE || !p.breakdown) return false;
  const b = p.breakdown;
  return b.itemSubtotalPaise === 23541
    && b.collectionBeforeConveniencePaise === 29140
    && b.totalPayablePaise === TARGET_PAISE
    && b.supplyGstPaise === 4237
    && b.delightPaise === 138
    && b.expressPaise === 1500
    && b.convenienceFeePaise === 729
    && b.convenienceGstPaise === 131;
};

const ContributeStaffControls: React.FC<Props> = ({
  price, templates, loadingPrice, refreshPrice,
}) => {
  const [contacts, setContacts] = React.useState<api.Contact[]>([]);
  const [loadingContacts, setLoadingContacts] = React.useState(false);
  const [contactsMessage, setContactsMessage] = React.useState('');
  const [query, setQuery] = React.useState('');
  const [selectedId, setSelectedId] = React.useState('');
  const [reference, setReference] = React.useState('Contribute · ₹300');
  const [internalNote, setInternalNote] = React.useState('');
  const [reviewOpen, setReviewOpen] = React.useState(false);
  const [feedback, setFeedback] = React.useState('');
  const [templateRefresh, setTemplateRefresh] = React.useState(0);
  const [approval, setApproval] = React.useState<Approval>('unverified');
  // The live backend's current catalog and exact-quote readiness, not the
  // browser build or template preview, controls whether Send can be attempted.
  const [backendReady, setBackendReady] = React.useState<'checking' | 'enabled' | 'blocked'>('checking');
  const [backendReason, setBackendReason] = React.useState('Checking production payment availability…');
  const [sending, setSending] = React.useState(false);
  const [sendLocked, setSendLocked] = React.useState(false);
  const [sendOutcome, setSendOutcome] = React.useState('');
  const inFlight = React.useRef(false);
  const confirm = useConfirm();

  const templateName = templates?.nativePay || '';
  const templateId = templates?.templateIds?.nativePay || '';

  const loadContacts = React.useCallback(async () => {
    setLoadingContacts(true);
    setContactsMessage('');
    setContacts([]); // No stale recipient may be reviewed during a refresh.
    try {
      const records = await api.listContacts();
      const usable = records.filter(usableContact);
      setContacts(usable);
      setSelectedId(current => usable.some(c => keyOf(c) === current) ? current : '');
      if (!usable.length) setContactsMessage('No usable saved contacts were returned. Check Contacts and retry; no recipient has been selected.');
    } catch {
      setContacts([]);
      setContactsMessage('The Contacts lookup was not completed. Refresh before preparing a new draft.');
    } finally {
      setLoadingContacts(false);
    }
  }, []);

  React.useEffect(() => { void loadContacts(); }, [loadContacts]);

  React.useEffect(() => {
    let active = true;
    setBackendReady('checking');
    setBackendReason('Checking server payment readiness…');
    void api.getStaffContributionSendReadiness().then(result => {
      if (!active) return;
      setBackendReady(result.sendEnabled && result.amountPaise === TARGET_PAISE
        ? 'enabled' : 'blocked');
      setBackendReason(result.reason);
    }).catch(() => {
      if (active) { setBackendReady('blocked'); setBackendReason('BACKEND_UNAVAILABLE'); }
    });
    return () => { active = false; };
  }, [templateRefresh]);

  React.useEffect(() => {
    let active = true;
    if (!templateName || !/^[0-9]{10,25}$/.test(templateId)) {
      setApproval('unverified');
      return () => { active = false; };
    }
    setApproval('checking');
    void api.getTemplateDetails(templateId)
      .then(raw => {
        if (!active) return;
        const row = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
        const status = String(row.status || '').toUpperCase();
        const name = String(row.name || '');
        const id = String(row.id || row.templateId || '');
        const components = Array.isArray(row.components) ? row.components : [];
        const header = components.some((entry: any) =>
          String(entry?.type || '').toUpperCase() === 'HEADER'
          && String(entry?.format || '').toUpperCase() === 'IMAGE');
        const orderButton = components.some((entry: any) =>
          String(entry?.type || '').toUpperCase() === 'BUTTONS'
          && Array.isArray(entry.buttons) && entry.buttons.some((button: any) =>
            String(button?.type || '').toUpperCase() === 'ORDER_DETAILS'));
        setApproval(status === 'APPROVED' && name === templateName
          && (!id || id === templateId) && header && orderButton
          ? 'approved' : 'unverified');
      })
      .catch(() => { if (active) setApproval('unverified'); });
    return () => { active = false; };
  }, [templateName, templateId, templateRefresh]);

  const selected = contacts.find(c => keyOf(c) === selectedId) || null;
  const filter = query.trim().toLowerCase();
  const filtered = contacts
    .filter(c => !filter || (c.name || '').toLowerCase().includes(filter)
      || c.phone.includes(filter) || (c.email || '').toLowerCase().includes(filter))
    .slice(0, CONTACT_LIMIT);
  const options = selected && !filtered.some(c => keyOf(c) === selectedId)
    ? [selected, ...filtered] : filtered;
  const priceMatches = matchesContributionQuote(price);
  const referenceValid = reference.trim().length >= 3 && reference.trim().length <= 60;
  const canReview = !!selected && referenceValid && !loadingContacts && !loadingPrice;
  const canSend = !!selected?.id && canReview && reviewOpen && priceMatches
    && approval === 'approved' && backendReady === 'enabled' && !sending && !sendLocked;

  const copiedSummary = [
    'INTERNAL REVIEW DRAFT ONLY — NOT A WHATSAPP PAYMENT REQUEST',
    'Recipient: ' + (selected?.name || 'None'),
    'Saved phone: ' + (selected?.phone || 'None'),
    'Staff reference: ' + reference.trim(),
    'Proposed customer total: ₹300.00',
    'Express: +₹15.00 charged within the exact ₹300 total',
    'Contribute ₹235.41 + GST ₹42.37 − Delight ₹1.38 + Express ₹15.00 + Convenience ₹7.29 + fee GST ₹1.31',
    'Server quote: ' + (price.available
      ? money(price.breakdown?.totalPayablePaise ?? price.paise) : 'Unavailable'),
    'Server quote matches ₹300 taxable quote: ' + (priceMatches ? 'YES' : 'NO'),
    'Native Meta template: ' + (templateName || 'Unavailable'),
    'Meta status readback: ' + (approval === 'approved' ? 'Approved' : 'Not confirmed'),
    'Commerce payment readiness: ' + (backendReady === 'enabled' ? 'Enabled' : 'Blocked: ' + backendReason),
    'Internal note (not sent): ' + (internalNote.trim() || 'None'),
    sendLocked
      ? 'A send was attempted; check staff outcome and customer payment records.'
      : 'No send/payment authorization has been generated.',
  ].join('\n');

  const sendOnce = async () => {
    if (!canSend || !selected || inFlight.current) return;
    inFlight.current = true;
    try {
      const accepted = await confirm({
        title: 'Send ₹300 Review & Pay?',
        message: `Customer: ${selected.name} (${selected.phone}).\nContribute ₹235.41 + GST ₹42.37 − Delight ₹1.38 + Express ₹15.00 + Convenience ₹7.29 + fee GST ₹1.31 = ₹300.00.\nThe server will re-check identity, exact price and Meta readiness. This does not charge the customer; only their payment approval does.\nAn uncertain send must be reconciled before retrying.`,
        confirmText: 'Send ₹300 payment request',
      });
      if (!accepted) return;
      // Once a request has left the browser, NEVER retry automatically or
      // unlock this draft on a network failure (Meta may have accepted it).
      setSendLocked(true);
      setSending(true);
      setSendOutcome('');
      const outcome = await api.sendStaffContributionPaymentOnce(selected.id);
      if (outcome.state === 'ACCEPTED') {
        setSendOutcome(`Request accepted for ₹300. Attempt ${outcome.paymentAttemptId}. Check WhatsApp/ledger for actual delivery and verified payment. Do not send again.`);
      } else if (outcome.state === 'UNCONFIRMED') {
        setSendOutcome(`Sending could not be confirmed (${outcome.code}). The customer may already have a payment request. Check the chat and ledger; do not retry blindly.`);
      } else {
        setSendOutcome(`Server refused the request (${outcome.code}): ${outcome.message} Check the live customer and payment status before trying again.`);
      }
    } catch {
      setSendLocked(true);
      setSendOutcome('Send confirmation failed or its outcome is unknown. Check the chat and payment ledger before any retry.');
    } finally {
      setSending(false);
      inFlight.current = false;
    }
  };

  const reset = () => {
    setSelectedId('');
    setQuery('');
    setReference('Contribute · ₹300');
    setInternalNote('');
    setReviewOpen(false);
    setFeedback('Draft cleared. No payment or message was created.');
  };
  const copyInternalReview = async () => {
    setFeedback('');
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(copiedSummary);
      setFeedback('Internal draft copied for staff review. Do not paste it to a customer as a payment request.');
    } catch {
      setFeedback('Clipboard unavailable. Review the draft on this screen instead.');
    }
  };
  const refresh = () => {
    setReviewOpen(false);
    setFeedback('');
    refreshPrice();
    void loadContacts();
    setTemplateRefresh(current => current + 1);
  };

  return (
    <section className="contribute-staff" aria-labelledby="contribute-staff-title">
      <header className="staff-head">
        <div>
          <h3 id="contribute-staff-title">Staff payment controls</h3>
          <p>Choose a saved customer and prepare a local, reviewable draft. The payment amount, approved message body and media cannot be overridden here.</p>
        </div>
        <button type="button" className="secondary" onClick={refresh}
          disabled={loadingPrice || loadingContacts}>
          {loadingPrice || loadingContacts ? 'Refreshing…' : 'Refresh price, contacts & Meta'}
        </button>
      </header>

      <div className="staff-readiness" role="status" aria-live="polite">
        <div><strong>Server contribution quote</strong><span>{loadingPrice ? 'Checking…' : price.available
          ? money(price.breakdown?.totalPayablePaise ?? price.paise) : 'Unavailable'}</span></div>
        <div><strong>Exact ₹300 taxable quote</strong><span>{loadingPrice ? 'Checking…' : priceMatches ? 'Matches' : 'Blocked: mismatch'}</span></div>
        <div><strong>Native Meta template</strong><span>{approval === 'checking' ? 'Checking…'
          : approval === 'approved' ? 'Approved in staff lookup' : 'Not confirmed here'}</span></div>
        <div><strong>Commerce payment readiness</strong><span>{backendReady === 'checking'
          ? 'Checking…' : backendReady === 'enabled' ? 'Enabled' : `Blocked: ${backendReason}`}</span></div>
        <div><strong>Customer recipient</strong><span>{selected ? 'Selected, backend verification required' : 'Not selected'}</span></div>
      </div>

      <form onSubmit={event => { event.preventDefault(); setFeedback(''); if (canReview) setReviewOpen(true); }}
        aria-label="Prepare Contribute review draft">
        <div className="staff-form-grid">
          <div className="staff-field">
            <label htmlFor="contribute-customer-search">Find customer in Contacts</label>
            <input id="contribute-customer-search" value={query}
              onChange={event => { setQuery(event.target.value); setReviewOpen(false); }}
              placeholder="Search name, phone or email" autoComplete="off" />
            <label htmlFor="contribute-customer-choice">Customer for proposed payment</label>
            <select id="contribute-customer-choice" value={selectedId}
              disabled={loadingContacts || contacts.length === 0}
              onChange={event => { setSelectedId(event.target.value); setReviewOpen(false); setFeedback(''); }}>
              <option value="">Choose saved customer…</option>
              {options.map(contact => (
                <option value={keyOf(contact)} key={keyOf(contact)}>
                  {contact.name || 'Unnamed contact'} · {contact.phone}
                </option>
              ))}
            </select>
            {contactsMessage && <small role="status">{contactsMessage}</small>}
            {selected && (
              <p className="recipient-proof">
                Recipient: <strong>{selected.name} · {selected.phone}</strong>.
                {selected.phoneVerifiedAt
                  ? ' A phone-verification timestamp exists, but the payment sender must reverify identity.'
                  : ' No reliable phone-verification proof is shown here; backend identity verification is still required.'}
              </p>
            )}
            <a href="/workspace/payments?view=collect">Open general Collect / customer management</a>
          </div>
          <div className="staff-field">
            <label htmlFor="contribute-reference">Internal draft reference (3–60 characters)</label>
            <input id="contribute-reference" maxLength={60} value={reference}
              onChange={event => { setReference(event.target.value); setReviewOpen(false); }}
              aria-invalid={!referenceValid} />
            <small>Staff-only. This does not change the immutable catalog item or Meta template body.</small>
            <label htmlFor="contribute-note">Internal notes (optional, up to 240 characters)</label>
            <textarea id="contribute-note" maxLength={240} rows={3} value={internalNote}
              onChange={event => { setInternalNote(event.target.value); setReviewOpen(false); }}
              placeholder="For internal review; never forwarded to WhatsApp" />
            <small>Unsaved in-memory draft. Leaving or reloading this page clears it.</small>
          </div>
        </div>

        <div className="staff-actions">
          <button className="primary" type="submit" disabled={!canReview}>Review draft</button>
          <button className="secondary" type="button" onClick={reset}>Clear draft</button>
          <button className="primary send-payment" type="button"
            onClick={() => { void sendOnce(); }} disabled={!canSend}
            title={backendReady !== 'enabled' ? 'Commerce payment readiness must be verified before sending' : undefined}>
            {sending ? 'Sending once…' : sendLocked ? 'Send locked · check ledger' : 'Send ₹300 Review & Pay'}
          </button>
        </div>
        <p className="send-explanation" role="note">
          Admin-only sending requires a reviewed draft, live backend payment readiness,
          a fresh exact ₹300 server quote, an approved native Meta template, and explicit final confirmation. The backend
          re-verifies the customer, current price and provider readiness before reserving
          a payment. A request is not proof of delivery or payment. Express is a ₹15
          billed line already included in the exact ₹300 total; never use the generic
          template picker or a separate invoice to alter this contribution.
        </p>
      </form>

      {reviewOpen && selected && (
        <div className="staff-review" aria-live="polite">
          <header>
            <h4>{sendLocked ? 'Request attempted — verify its outcome' : 'Internal draft review — nothing sent'}</h4>
            <button type="button" className="secondary" onClick={() => setReviewOpen(false)}>Edit draft</button>
          </header>
          <dl>
            <div><dt>Customer</dt><dd>{selected.name} · {selected.phone}</dd></div>
            <div><dt>Staff reference</dt><dd>{reference.trim()}</dd></div>
            <div><dt>Payment template</dt><dd>{templateName || 'Unavailable'} · Review and Pay</dd></div>
            <div><dt>Item image</dt><dd>Default WECARE order-details thumbnail</dd></div>
            <div><dt>Header image</dt><dd>Shared WECARE branded header</dd></div>
            <div><dt>Proposed total</dt><dd>{money(TARGET_PAISE)}</dd></div>
            <div><dt>Express</dt><dd>{money(EXPRESS_CHARGE_PAISE)}</dd></div>
            <div><dt>Server pricing match</dt><dd>{priceMatches ? 'Yes' : 'NO — send blocked'}</dd></div>
            <div><dt>Internal note</dt><dd>{internalNote || 'None'}</dd></div>
          </dl>
          <div className="message-preview" aria-label="Approved native template body preview">
            <strong>Fixed WhatsApp message text</strong>
            <p>{META_PAYMENT_BODY}</p>
            <span>Review and Pay button · preview only; no live checkout link</span>
          </div>
          <button type="button" className="secondary" onClick={() => { void copyInternalReview(); }}>
            Copy internal review draft
          </button>
        </div>
      )}
      {sendOutcome && <p className="staff-feedback" role="status" aria-live="polite">{sendOutcome}</p>}
      {feedback && <p className="staff-feedback" role="status">{feedback}</p>}

      <style jsx>{`
        .contribute-staff{min-width:0;background:var(--surface);border:1px solid var(--border);border-radius:13px;padding:17px;display:grid;gap:15px}
        .staff-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}
        .staff-head h3{margin:0 0 6px;font-size:17px;color:var(--text-primary)}
        .staff-head p,.recipient-proof,.send-explanation,.staff-field small,.staff-feedback{font-size:12px;line-height:1.6;color:var(--text-muted);margin:5px 0 0}
        .staff-readiness{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
        .staff-readiness>div{border:1px solid var(--border);border-radius:10px;padding:12px;display:grid;gap:5px;min-width:0}
        .staff-readiness strong{font-size:11px;color:var(--text-muted)}
        .staff-readiness span{font-size:13px;font-weight:800;color:var(--text-primary)}
        .staff-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
        .staff-field{min-width:0;display:flex;flex-direction:column;gap:8px}
        .staff-field label{font-size:12px;font-weight:800;color:var(--text-primary)}
        .staff-field input,.staff-field select,.staff-field textarea{width:100%;max-width:100%;box-sizing:border-box;min-height:44px;border:1px solid var(--border);border-radius:9px;padding:9px 11px;font:inherit;background:var(--surface-raised,#fff);color:var(--text-primary)}
        .staff-field textarea{min-height:86px;resize:vertical}
        .staff-field input[aria-invalid="true"]{border-color:#b74545}
        .staff-field a{font-size:12px;color:var(--text-primary);text-decoration:underline;align-self:flex-start}
        .staff-actions{margin-top:15px;display:flex;gap:8px;flex-wrap:wrap}
        button{min-height:42px;padding:8px 13px;border-radius:9px;border:1px solid var(--border);font-weight:800;font-size:12px;cursor:pointer;background:var(--surface);color:var(--text-primary)}
        button.primary{background:var(--lime);border-color:var(--accent);color:var(--accent)}
        button:disabled{cursor:not-allowed;opacity:.55}
        button.send-payment{margin-left:auto}
        .send-explanation{max-width:800px;margin-top:10px}
        .staff-review{border-top:1px solid var(--border);padding-top:15px;display:grid;justify-items:start;gap:12px}
        .staff-review header{display:flex;width:100%;align-items:center;justify-content:space-between;gap:8px}
        .staff-review h4{margin:0;font-size:15px}
        .staff-review dl{width:100%;display:grid;margin:0}
        .staff-review dl>div{display:flex;justify-content:space-between;align-items:baseline;gap:15px;padding:8px 0;border-bottom:1px solid var(--border)}
        .staff-review dt{color:var(--text-muted);font-size:12px}
        .staff-review dd{margin:0;text-align:right;font-weight:750;color:var(--text-primary);font-size:12px;overflow-wrap:anywhere}
        .message-preview{width:100%;box-sizing:border-box;border:1px solid var(--border);border-radius:10px;padding:14px}
        .message-preview strong,.message-preview span{font-size:12px}
        .message-preview span{color:var(--text-muted)}
        .message-preview p{font-size:14px;margin:9px 0;line-height:1.6}
        button:focus-visible,.staff-field a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
        @media(max-width:700px){.contribute-staff{padding:13px}.staff-head{display:grid}.staff-form-grid,.staff-readiness{grid-template-columns:1fr}.staff-actions{display:grid}.staff-actions button,.staff-head button{width:100%}button.send-payment{margin-left:0}.staff-review header{flex-wrap:wrap}}
      `}</style>
    </section>
  );
};

export default ContributeStaffControls;
