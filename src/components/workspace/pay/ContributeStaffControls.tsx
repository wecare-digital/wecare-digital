/**
 * Staff controls for Contribute payment PREPARATION.
 *
 * Customer identity, Meta ORDER_DETAILS and money are server-owned. This form
 * only builds an internal, in-memory draft. In particular, never call the
 * generic template sender or invoice engine to fabricate a contribution charge.
 */
import React from 'react';
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
const EXPRESS_ALLOCATION_PAISE = 1500;
const META_PAYMENT_BODY = '💳 Your order is ready for payment. Tap Review and Pay to complete it securely.';
const CONTACT_LIMIT = 40;
const money = (v: number) => '₹' + rupeesFromPaise(v);
const keyOf = (c: api.Contact): string => c.contactId || c.id;
const usableContact = (c: api.Contact): boolean =>
  !!keyOf(c) && !!c.phone && !c.deletedAt && !c.archivedAt && !c.locked;

/**
 * This is a readiness CHECK for the existing exempt Contribute price contract,
 * not permission to initiate a payment. The actual sender must still reserve a
 * purpose-bound, immutable ₹300 order and verify the recipient and Meta status.
 */
const matchesContributionQuote = (p: ServicePrice): boolean => {
  if (!p.available || p.paise !== TARGET_PAISE || !p.breakdown) return false;
  const b = p.breakdown;
  return b.itemSubtotalPaise === TARGET_PAISE
    && b.collectionBeforeConveniencePaise === TARGET_PAISE
    && b.totalPayablePaise === TARGET_PAISE
    && b.supplyGstPaise === 0
    && b.delightPaise === 0
    && b.expressPaise === 0
    && b.convenienceFeePaise === 0
    && b.convenienceGstPaise === 0;
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

  const templateName = templates?.nativePay || '';
  const templateId = templates?.templateIds?.nativePay || '';

  const loadContacts = React.useCallback(async () => {
    setLoadingContacts(true);
    setContactsMessage('');
    try {
      const records = await api.listContacts();
      const usable = records.filter(usableContact);
      setContacts(usable);
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
  const canReview = !!selected && referenceValid;

  const copiedSummary = [
    'INTERNAL REVIEW DRAFT ONLY — NOT A WHATSAPP PAYMENT REQUEST',
    'Recipient: ' + (selected?.name || 'None'),
    'Saved phone: ' + (selected?.phone || 'None'),
    'Staff reference: ' + reference.trim(),
    'Proposed customer total: ₹300.00',
    'Express: ₹15.00 allocated internally (not an additional customer fee)',
    'Current contribution policy: Delight ₹0; supply GST ₹0; convenience ₹0; fee GST ₹0',
    'Server quote: ' + (price.available
      ? money(price.breakdown?.totalPayablePaise ?? price.paise) : 'Unavailable'),
    'Server quote matches ₹300 exempt policy: ' + (priceMatches ? 'YES' : 'NO'),
    'Native Meta template: ' + (templateName || 'Unavailable'),
    'Meta status readback: ' + (approval === 'approved' ? 'Approved' : 'Not confirmed'),
    'Internal note (not sent): ' + (internalNote.trim() || 'None'),
    'No send/payment authorization has been generated.',
  ].join('\n');

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
        <div><strong>Exact ₹300 exempt policy</strong><span>{loadingPrice ? 'Checking…' : priceMatches ? 'Matches' : 'Blocked: mismatch'}</span></div>
        <div><strong>Native Meta template</strong><span>{approval === 'checking' ? 'Checking…'
          : approval === 'approved' ? 'Approved in staff lookup' : 'Not confirmed here'}</span></div>
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
          <button className="disabled-send" type="button" disabled>
            Send Review &amp; Pay — not enabled
          </button>
        </div>
        <p className="send-explanation" role="note">
          Sending requires a server-issued, purpose-bound ₹300 native order and verified customer,
          current Meta approval, matching payment/receipt records, and authorized final confirmation.
          The current staff Contribute API has no such send action. Never use the generic template
          picker or a generic invoice to bypass this gate.
        </p>
      </form>

      {reviewOpen && selected && (
        <div className="staff-review" aria-live="polite">
          <header>
            <h4>Internal draft review — nothing sent</h4>
            <button type="button" className="secondary" onClick={() => setReviewOpen(false)}>Edit draft</button>
          </header>
          <dl>
            <div><dt>Customer</dt><dd>{selected.name} · {selected.phone}</dd></div>
            <div><dt>Staff reference</dt><dd>{reference.trim()}</dd></div>
            <div><dt>Payment template</dt><dd>{templateName || 'Unavailable'} · Review and Pay</dd></div>
            <div><dt>Item image</dt><dd>Default WECARE order-details thumbnail</dd></div>
            <div><dt>Header image</dt><dd>Shared WECARE branded header</dd></div>
            <div><dt>Proposed total</dt><dd>{money(TARGET_PAISE)}</dd></div>
            <div><dt>Express (internal allocation)</dt><dd>{money(EXPRESS_ALLOCATION_PAISE)}</dd></div>
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
        button.disabled-send{margin-left:auto;border-style:dashed}
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
        @media(max-width:700px){.contribute-staff{padding:13px}.staff-head{display:grid}.staff-form-grid,.staff-readiness{grid-template-columns:1fr}.staff-actions{display:grid}.staff-actions button,.staff-head button{width:100%}button.disabled-send{margin-left:0}.staff-review header{flex-wrap:wrap}}
      `}</style>
    </section>
  );
};

export default ContributeStaffControls;
