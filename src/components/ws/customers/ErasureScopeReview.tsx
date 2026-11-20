/**
 * Read-only scope review for an eventual, audited customer-erasure request.
 *
 * An inbox display name is not a stable person identifier. Staff explicitly
 * choose the exact canonical contacts to preserve, including same-name records.
 * This view never calls a deletion or archive API and never marks a customer
 * eligible just because it is outside the keep set.
 */
import React from 'react';
import type { Contact } from '../../../api/client';
import styles from './ErasureScopeReview.module.css';

interface Props {
  contacts: Contact[];
  onClose: () => void;
}

function contactKey(contact: Contact): string {
  return contact.contactId || contact.id || '';
}

export interface ErasureScopePreview {
  protectedContacts: number;
  candidateContacts: number;
  candidateLocked: number;
  candidateMissingId: number;
  candidateAlreadyArchived: number;
  incomplete: boolean;
  eligibleToDelete: 0;
}

export function buildErasureScopePreview(
  contacts: Contact[],
  protectedIds: ReadonlySet<string>,
): ErasureScopePreview {
  const idCounts = new Map<string, number>();
  for (const contact of contacts) {
    const id = contactKey(contact);
    if (id) idCounts.set(id, (idCounts.get(id) || 0) + 1);
  }
  const missing = contacts.filter(contact => !contactKey(contact));
  const duplicates = [...idCounts.values()].some(count => count > 1);
  const preserved = contacts.filter(contact => protectedIds.has(contactKey(contact)) && Boolean(contactKey(contact)));
  const candidates = contacts.filter(contact => !protectedIds.has(contactKey(contact)));
  const keepSetComplete = protectedIds.size > 0 && preserved.length === protectedIds.size;
  return {
    protectedContacts: preserved.length,
    candidateContacts: candidates.length,
    candidateLocked: candidates.filter(contact => contact.locked === true).length,
    candidateMissingId: candidates.filter(contact => !contactKey(contact)).length,
    candidateAlreadyArchived: candidates.filter(contact => Boolean(contact.archivedAt)).length,
    incomplete: !keepSetComplete || missing.length > 0 || duplicates,
    // Local contact fields cannot prove that linked message and Razorpay records
    // are safe to erase. Every candidate still needs server-side review.
    eligibleToDelete: 0,
  };
}

const ErasureScopeReview: React.FC<Props> = ({ contacts, onClose }) => {
  const [protectedIds, setProtectedIds] = React.useState<Set<string>>(() => new Set());
  const [search, setSearch] = React.useState('');
  const headingId = React.useId();

  // A concurrent directory refresh may remove or replace a row. Never keep
  // an invisible, stale protection selection after the identity disappears.
  React.useEffect(() => {
    const known = new Set(contacts.map(contactKey).filter(Boolean));
    setProtectedIds(previous => new Set([...previous].filter(id => known.has(id))));
  }, [contacts]);

  const review = React.useMemo(
    () => buildErasureScopePreview(contacts, protectedIds),
    [contacts, protectedIds],
  );
  const visible = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return contacts.filter(contact =>
      !q || [contact.name, contact.phone, contact.contactId, contact.customerDisplayId]
        .some(value => String(value || '').toLowerCase().includes(q)),
    );
  }, [contacts, search]);

  const toggle = (id: string) => {
    if (!id) return;
    setProtectedIds(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className={styles.backdrop} role="presentation"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section className={styles.panel} role="dialog" aria-modal="true" aria-labelledby={headingId}>
        <header className={styles.header}>
          <div>
            <h2 id={headingId}>Review permanent deletion scope</h2>
            <p>Select the exact customer records to keep. Two customers with the same name
              are not automatically the same identity.</p>
          </div>
          <button type="button" onClick={onClose} className={styles.close}
            aria-label="Close deletion scope review">Close</button>
        </header>
        <div className={styles.body}>
          <label className={styles.search}>
            <span>Find contacts to preserve</span>
            <input type="search" value={search} onChange={event => setSearch(event.target.value)}
              placeholder="Search name, phone, or customer ID" />
          </label>
          <ul className={styles.contacts} aria-label="Choose exact contacts to keep">
            {visible.map((contact, index) => {
              const id = contactKey(contact);
              return (
                <li key={id || 'missing-id-' + index}>
                  <label className={styles.contact}>
                    <input type="checkbox" checked={Boolean(id) && protectedIds.has(id)}
                      disabled={!id} onChange={() => toggle(id)}
                      aria-label={'Keep ' + (contact.name || 'Unnamed contact') + ' ' + (contact.phone || id)} />
                    <span>
                      <strong>{contact.name || 'Unnamed contact'}</strong>
                      <small>{contact.phone || 'Phone not shared'}</small>
                      <small>{contact.customerDisplayId || id || 'Missing canonical ID'}</small>
                      {contact.locked && <small>Retention lock</small>}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>

          <div className={styles.counts} role="status" aria-live="polite">
            <div><span>Protected contacts</span><strong>{review.protectedContacts}</strong></div>
            <div><span>Others to assess</span><strong>{review.candidateContacts}</strong></div>
            <div><span>Locked among others</span><strong>{review.candidateLocked}</strong></div>
            <div><span>Certified for erasure</span><strong>{review.eligibleToDelete}</strong></div>
          </div>

          {review.incomplete && <p className={styles.warning}>
            Protection selection is incomplete or an identity is missing/duplicated.
            No deletion can be requested from an incomplete scope.
          </p>}
          <p className={styles.warning}>
            This preview only counts currently loaded contacts. It does not inspect every
            WhatsApp message, versioned media object, identity claim, Razorpay transaction,
            payment webhook, invoice, order, or legal hold. Those records and all
            payment-related communications must remain untouched until an authenticated,
            independently reviewed cross-service inventory certifies eligibility.
          </p>
          <p>
            Permanent deletion still requires Admin MFA, approved case evidence and
            an independently deployed erasure coordinator. Without that coordinator,
            the API reports ERASURE_COORDINATOR_UNAVAILABLE. This review changes no records.
          </p>
        </div>
        <footer className={styles.footer}>
          <button type="button" className={styles.cancel} onClick={onClose}>Close review</button>
          <button type="button" className={styles.disabledDelete} disabled
            title="Requires Operator approval, MFA, legal retention review, and audited cross-service erasure">
            Delete candidates — approval required
          </button>
        </footer>
      </section>
    </div>
  );
};

export default ErasureScopeReview;
