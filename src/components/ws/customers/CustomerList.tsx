/**
 * /ws/customers — a responsive customer directory using the shared /ws design system.
 *
 * Uses the existing Contacts API only. Create/update goes through the canonical F001-aligned
 * CustomerEditor; the existing confirm-gated retention/identity safeguards stay in place.
 */
import React from 'react';
import { useRouter } from 'next/router';
import type { Contact } from '../../../api/client';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import { contactDeliveryAddress } from '../../../lib/address-format';
import CustomerManageData from '../../workspace/customers/ManageData';
import CustomerActionsSheet from './CustomerActionsSheet';
import CustomerEditor from './CustomerEditor';
import styles from './CustomerList.module.css';

type ViewFilter = 'all' | 'address' | 'incomplete';
type SortOrder = 'recent' | 'name';

const SearchGlyph = () => (
  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="7" /><path d="m20 20-3.8-3.8" />
  </svg>
);
const PlusGlyph = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
);
const ArrowGlyph = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg>
);
const RefreshGlyph = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M20 6v6h-6M4 18v-6h6M5.8 9A7 7 0 0 1 18 7l2 5M4 12l2 5A7 7 0 0 0 18.2 15" />
  </svg>
);
const CloseGlyph = () => (
  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
    strokeLinecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
);

function displayName(contact: Contact): string {
  return contact.name?.trim() || 'Unnamed customer';
}
function initials(contact: Contact): string {
  const value = displayName(contact);
  if (value === 'Unnamed customer') return 'WC';
  const words = value.split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : value.slice(0, 2)).toUpperCase();
}
function customerId(contact: Contact): string {
  return contact.customerDisplayId || contact.subscriberId || contact.contactId || contact.id;
}
function timestamp(value?: string | number): number {
  if (value === undefined || value === null || value === '') return 0;
  const n = Number(value);
  return Number.isFinite(n) ? (n < 1e12 ? n * 1000 : n) : Date.parse(String(value)) || 0;
}
function formatUpdated(value?: string | number): string {
  const date = timestamp(value);
  if (!date) return '—';
  const days = Math.max(0, Math.floor((Date.now() - date) / 86400000));
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return days + ' days ago';
  return new Date(date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}
function formatFullDate(value?: string | number): string {
  const date = timestamp(value);
  return date ? new Date(date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—';
}
function missingDetails(contact: Contact): boolean {
  return !contact.name?.trim() || !contactDeliveryAddress(contact);
}
function consentLabel(contact: Contact): string {
  const status = contact.whatsappMarketingConsent;
  if (status === 'OPTED_IN') return 'Opted in';
  if (status === 'OPTED_OUT') return 'Opted out';
  return 'Not confirmed';
}

interface DetailsProps {
  contact: Contact;
  onClose: () => void;
  onEdit: () => void;
  onActions: () => void;
}
const CustomerDetails: React.FC<DetailsProps> = ({ contact, onClose, onEdit, onActions }) => {
  const closeRef = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    closeRef.current?.focus();
    const handle = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, [onClose]);

  return (
    <div className={styles.detailsBackdrop} role="presentation"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className={styles.detailsPanel} role="dialog" aria-modal="true" aria-labelledby="wsc-detail-name">
        <header className={styles.detailsTop}>
          <div><p className={styles.overline}>Customer record</p><p className={styles.detailHint}>Canonical contact details</p></div>
          <button ref={closeRef} type="button" className={styles.iconButton} onClick={onClose} aria-label="Close customer details">
            <CloseGlyph />
          </button>
        </header>
        <div className={styles.detailsScroll} data-wc-no-translate="true">
          <div className={styles.personHero}>
            <span className={styles.largeAvatar} aria-hidden="true">{initials(contact)}</span>
            <div className={styles.personText}>
              <h2 id="wsc-detail-name">{displayName(contact)}</h2>
              <p>{customerId(contact)}</p>
            </div>
          </div>
          <div className={styles.detailBadges}>
            <span className={contact.phoneVerifiedAt ? styles.successTag : styles.neutralTag}>
              {contact.phoneVerifiedAt ? 'Phone verified' : 'Phone not verified'}
            </span>
            {contact.locked && <span className={styles.warningTag}>Retention lock</span>}
            {contact.archivedAt && <span className={styles.neutralTag}>Archived</span>}
          </div>

          <section className={styles.detailSection} aria-labelledby="wsc-profile-title">
            <h3 id="wsc-profile-title">Profile</h3>
            <dl className={styles.detailFields}>
              <dt>WhatsApp number</dt><dd>{contact.phone || '—'}</dd>
              <dt>Profile username</dt><dd>{contact.profileUsername || '—'}</dd>
              <dt>Email</dt><dd>{contact.email || '—'}</dd>
              <dt>Organization</dt><dd>{contact.companyName || '—'}</dd>
              <dt>Job title</dt><dd>{contact.designation || '—'}</dd>
            </dl>
          </section>

          <section className={styles.detailSection} aria-labelledby="wsc-address-title">
            <h3 id="wsc-address-title">Delivery address</h3>
            <p className={styles.addressText}>{contactDeliveryAddress(contact) || 'No delivery address saved.'}</p>
          </section>

          <section className={styles.detailSection} aria-labelledby="wsc-identity-title">
            <h3 id="wsc-identity-title">Identity and history</h3>
            <dl className={styles.detailFields}>
              <dt>Customer ID</dt><dd>{customerId(contact)}</dd>
              <dt>WhatsApp marketing</dt><dd>{consentLabel(contact)}</dd>
              <dt>Created</dt><dd>{formatFullDate(contact.createdAt)}</dd>
              <dt>Last updated</dt><dd>{formatFullDate(contact.updatedAt)}</dd>
              <dt>Tags</dt><dd>{contact.tags?.length ? contact.tags.join(', ') : '—'}</dd>
            </dl>
            <p className={styles.safetyNote}>Phone verification and marketing consent are tracked by the server; editing a contact does not change either.</p>
          </section>
        </div>
        <footer className={styles.detailsFooter}>
          <button type="button" className={styles.secondaryButton} onClick={onActions}>More actions</button>
          <button type="button" className={styles.primaryButton} onClick={onEdit}>Edit contact <ArrowGlyph /></button>
        </footer>
      </aside>
    </div>
  );
};

const CustomerList: React.FC = () => {
  const router = useRouter();
  const toast = useToastContext();
  const confirm = useConfirm();

  const [contacts, setContacts] = React.useState<Contact[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState('');
  const [search, setSearch] = React.useState('');
  const [filter, setFilter] = React.useState<ViewFilter>('all');
  const [sort, setSort] = React.useState<SortOrder>('recent');
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [selecting, setSelecting] = React.useState(false);
  const [bulkBusy, setBulkBusy] = React.useState(false);
  const [detailsFor, setDetailsFor] = React.useState<Contact | null>(null);
  const [actionsFor, setActionsFor] = React.useState<Contact | null>(null);
  const [editorFor, setEditorFor] = React.useState<Contact | 'new' | null>(null);
  const [manageOpen, setManageOpen] = React.useState(false);
  const searchRef = React.useRef<HTMLInputElement>(null);
  const openedDeepLink = React.useRef<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const response = await api.listContactsResult();
      if (response.ok) setContacts(response.data);
      else setLoadError(response.failure.message || 'The customer directory could not be loaded.');
    } catch {
      setLoadError('The customer directory could not be loaded. Check your connection.');
    } finally {
      setLoading(false);
    }
  }, []);
  React.useEffect(() => { void load(); }, [load]);

  // Existing search links from inbox/command palette open the requested identity.
  React.useEffect(() => {
    if (!router.isReady || loading || loadError) return;
    const id = typeof router.query.contact === 'string' ? router.query.contact : '';
    if (!id || openedDeepLink.current === id) return;
    openedDeepLink.current = id;
    const known = contacts.find(item => item.contactId === id || item.id === id);
    if (known) {
      setDetailsFor(known);
    } else {
      void api.getContact(id).then(result => {
        if (result) setDetailsFor(result);
      }).catch(() => {});
    }
  }, [router.isReady, router.query.contact, contacts, loading, loadError]);

  React.useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (detailsFor || editorFor || actionsFor || manageOpen) return;
      if (event.key === '/') { event.preventDefault(); searchRef.current?.focus(); }
      if (event.key.toLowerCase() === 'n' && !selecting) { event.preventDefault(); setEditorFor('new'); }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [detailsFor, editorFor, actionsFor, manageOpen, selecting]);

  const total = contacts.length;
  const withAddress = React.useMemo(
    () => contacts.filter(item => Boolean(contactDeliveryAddress(item))).length, [contacts]);
  const incomplete = React.useMemo(() => contacts.filter(missingDetails).length, [contacts]);

  const visible = React.useMemo(() => {
    const term = search.trim().toLowerCase();
    return contacts.filter(contact => {
      if (filter === 'address' && !contactDeliveryAddress(contact)) return false;
      if (filter === 'incomplete' && !missingDetails(contact)) return false;
      if (!term) return true;
      const text = [
        contact.name, contact.phone, contact.email, contact.companyName, contact.designation,
        contact.profileUsername, customerId(contact), contactDeliveryAddress(contact),
        ...(contact.tags || []),
      ].join(' ').toLowerCase();
      return text.includes(term);
    }).sort((a, b) => sort === 'name'
      ? displayName(a).localeCompare(displayName(b), undefined, { sensitivity: 'base' })
      : timestamp(b.updatedAt) - timestamp(a.updatedAt));
  }, [contacts, search, filter, sort]);

  const dropRow = React.useCallback((id: string) => {
    setContacts(previous => previous.filter(item => item.contactId !== id));
    setSelected(previous => { const next = new Set(previous); next.delete(id); return next; });
    setDetailsFor(previous => previous?.contactId === id ? null : previous);
  }, []);

  const toggleSelected = (id: string) => {
    setSelected(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  // Never retain a hidden bulk selection when staff switch search/filter criteria.
  React.useEffect(() => { setSelected(new Set()); }, [search, filter]);

  const allVisibleSelected = visible.length > 0 && visible.every(contact => selected.has(contact.contactId));
  const selectAllVisible = () => {
    setSelected(previous => {
      const next = new Set(previous);
      visible.forEach(contact => allVisibleSelected ? next.delete(contact.contactId) : next.add(contact.contactId));
      return next;
    });
  };
  const endSelection = () => { setSelecting(false); setSelected(new Set()); };

  // Reuse the proven CSV export used by /workspace/customers, limited to the visible rows.
  const exportVisible = () => {
    const csv = api.exportContactsToCSV(visible);
    api.downloadFile(csv, 'customers_' + new Date().toISOString().slice(0, 10) + '.csv', 'text/csv');
    toast.success('Exported ' + visible.length + ' contact(s).');
  };

  const bulkDelete = async () => {
    if (bulkBusy || selected.size === 0) return;
    const ids = [...selected];
    const locked = contacts.filter(contact => ids.includes(contact.contactId) && contact.locked).length;
    if (locked) {
      toast.warning(locked + ' selected customer(s) are protected by a retention lock. Review them before deleting.');
      return;
    }
    const approved = await confirm({
      title: 'Delete ' + ids.length + ' customer' + (ids.length === 1 ? '' : 's') + '?',
      message: 'This is a soft delete. Phone identities remain reserved, and payment, order and audit history are preserved. The server may refuse protected identities. Continue?',
      confirmText: 'Delete selected',
      danger: true,
    });
    if (!approved) return;
    setBulkBusy(true);
    try {
      const result = await api.bulkDeleteContacts(ids);
      if (result.deleted > 0) toast.success(result.deleted + ' customer(s) removed from the active directory.');
      if (result.failed > 0) toast.warning(result.failed + ' customer(s) were kept because the server refused or failed the deletion.');
      if (result.deleted === 0 && result.failed === 0) toast.warning('No deletion was confirmed.');
      endSelection();
      await load();
    } catch {
      toast.error('Delete request failed. No deletion was confirmed.');
      await load();
    } finally {
      setBulkBusy(false);
    }
  };

  const openDetails = (contact: Contact) => {
    if (selecting) toggleSelected(contact.contactId);
    else setDetailsFor(contact);
  };
  const saveContact = (saved: Contact) => {
    toast.success(editorFor === 'new' ? 'Contact created.' : 'Customer profile updated.');
    setEditorFor(null);
    setDetailsFor(saved);
    void load();
  };

  return (
    <section className={styles.root} aria-labelledby="wsc-heading">
      <header className={styles.header}>
        <div className={styles.headingBlock}>
          <p className={styles.overline}>WORKSPACE / DIRECTORY</p>
          <h1 id="wsc-heading">Customers</h1>
          <p className={styles.description}>One place for customer profiles, WhatsApp identities and delivery details.</p>
        </div>
        <div className={styles.headingButtons}>
          <button type="button" className={styles.iconButton} onClick={() => void load()} disabled={loading}
            aria-label="Refresh customers" title="Refresh customers"><RefreshGlyph /></button>
          <button type="button" className={styles.primaryButton} onClick={() => { endSelection(); setEditorFor('new'); }}>
            <PlusGlyph /> Create contact
          </button>
        </div>
      </header>

      {!loadError && (
        <div className={styles.stats} aria-label="Customer directory summary">
          <div className={styles.statCard}><span>All contacts</span><strong>{loading ? '—' : total}</strong><small>Active customer records</small></div>
          <div className={styles.statCard}><span>With address</span><strong>{loading ? '—' : withAddress}</strong><small>Delivery details saved</small></div>
          <div className={styles.statCard}><span>Needs details</span><strong>{loading ? '—' : incomplete}</strong><small>Missing name or address</small></div>
        </div>
      )}

      <div className={styles.directory}>
        <div className={styles.toolbar}>
          <label className={styles.searchBox}>
            <SearchGlyph />
            <input ref={searchRef} type="search" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search customers, numbers, addresses…" aria-label="Search customers" autoComplete="off" />
            {search && <button type="button" onClick={() => { setSearch(''); searchRef.current?.focus(); }} aria-label="Clear customer search">
              <CloseGlyph />
            </button>}
            <kbd>/</kbd>
          </label>
          <div className={styles.utilityButtons}>
            <button type="button" className={styles.secondaryButton} onClick={exportVisible}
              disabled={loading || loadError !== '' || visible.length === 0}>Export CSV</button>
            <button type="button" className={styles.secondaryButton} onClick={() => setManageOpen(true)}>Manage data</button>
            <button type="button" className={styles.secondaryButton}
              disabled={loading || total === 0 || bulkBusy}
              onClick={() => selecting ? endSelection() : setSelecting(true)}>
              {selecting ? 'Done' : 'Select'}
            </button>
          </div>
        </div>

        <div className={styles.filterBar}>
          <div className={styles.tabs} role="group" aria-label="Filter customers">
            <button type="button" className={filter === 'all' ? styles.activeTab : styles.tab}
              aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All <span>{total}</span></button>
            <button type="button" className={filter === 'address' ? styles.activeTab : styles.tab}
              aria-pressed={filter === 'address'} onClick={() => setFilter('address')}>With address <span>{withAddress}</span></button>
            <button type="button" className={filter === 'incomplete' ? styles.activeTab : styles.tab}
              aria-pressed={filter === 'incomplete'} onClick={() => setFilter('incomplete')}>Needs details <span>{incomplete}</span></button>
          </div>
          <label className={styles.sortControl}>
            <span>Sort</span>
            <select value={sort} onChange={event => setSort(event.target.value as SortOrder)} aria-label="Sort customers">
              <option value="recent">Recently updated</option>
              <option value="name">Name A–Z</option>
            </select>
          </label>
        </div>

        {selecting && visible.length > 0 && (
          <div className={styles.selectionBar}>
            <label><input type="checkbox" checked={allVisibleSelected} onChange={selectAllVisible} />
              Select all {visible.length} shown</label>
            <span>{selected.size} selected</span>
          </div>
        )}

        <div className={styles.listHeading} aria-hidden="true">
          <span>Customer</span><span>Contact</span><span>Profile</span><span>Delivery address</span><span>Updated</span>
        </div>

        {loading ? (
          <div className={styles.stateMessage} role="status">Loading customers…</div>
        ) : loadError ? (
          <div className={styles.stateMessage} role="alert">
            <h2>Could not load customers</h2>
            <p>{loadError}</p>
            <button type="button" className={styles.secondaryButton} onClick={() => void load()}>Retry</button>
          </div>
        ) : visible.length === 0 ? (
          <div className={styles.stateMessage}>
            <span className={styles.emptyIcon} aria-hidden="true"><SearchGlyph /></span>
            <h2>{search || filter !== 'all' ? 'No matching customers' : 'Your customer directory is empty'}</h2>
            <p>{search || filter !== 'all' ? 'Try another search or filter.' : 'Create your first contact to begin.'}</p>
            {search || filter !== 'all'
              ? <button type="button" className={styles.secondaryButton} onClick={() => { setSearch(''); setFilter('all'); }}>Clear filters</button>
              : <button type="button" className={styles.primaryButton} onClick={() => setEditorFor('new')}><PlusGlyph />Create contact</button>}
          </div>
        ) : (
          <ul className={styles.customerList} aria-label="Customers" data-wc-no-translate="true">
            {visible.map(contact => (
              <li key={contact.contactId} className={selected.has(contact.contactId) ? styles.selectedEntry : styles.entry}>
                {selecting && (
                  <label className={styles.rowCheckbox}>
                    <input type="checkbox" checked={selected.has(contact.contactId)}
                      onChange={() => toggleSelected(contact.contactId)}
                      aria-label={'Select ' + displayName(contact)} />
                  </label>
                )}
                <button type="button" className={styles.rowMain} onClick={() => openDetails(contact)}
                  aria-label={(selecting ? 'Select ' : 'View ') + displayName(contact)}>
                  <span className={styles.personCell}>
                    <span className={styles.avatar} aria-hidden="true">{initials(contact)}</span>
                    <span className={styles.personIdentity}>
                      <strong>{displayName(contact)}</strong>
                      <small>{customerId(contact)}</small>
                    </span>
                  </span>
                  <span className={styles.contactCell}>
                    <strong>{contact.phone || '—'}</strong>
                    <small>{contact.email || (contact.phoneVerifiedAt ? 'WhatsApp verified' : 'Phone not verified')}</small>
                  </span>
                  <span className={styles.profileCell}>
                    <strong>{contact.companyName || contact.profileUsername || '—'}</strong>
                    <small>{contact.designation || (contact.companyName ? 'Organization' : 'Customer profile')}</small>
                  </span>
                  <span className={styles.addressCell}>
                    <strong title={contactDeliveryAddress(contact)}>{contactDeliveryAddress(contact) || 'Not added'}</strong>
                    {!contactDeliveryAddress(contact) && <small>Needs details</small>}
                  </span>
                  <span className={styles.updatedCell}>
                    <span>{formatUpdated(contact.updatedAt)}</span>
                    <ArrowGlyph />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {!loading && !loadError && visible.length > 0 && (
          <p className={styles.resultCount} aria-live="polite">
            Showing {visible.length} of {total} active contacts
          </p>
        )}
      </div>

      {selecting && selected.size > 0 && (
        <div className={styles.bulkTray} role="region" aria-label="Selected customer actions">
          <strong>{selected.size} selected</strong>
          <button type="button" className={styles.dangerButton} onClick={() => void bulkDelete()} disabled={bulkBusy}>
            {bulkBusy ? 'Deleting…' : 'Delete selected'}
          </button>
        </div>
      )}

      {detailsFor && !editorFor && !actionsFor && (
        <CustomerDetails key={detailsFor.contactId} contact={detailsFor}
          onClose={() => setDetailsFor(null)}
          onEdit={() => { setEditorFor(detailsFor); setDetailsFor(null); }}
          onActions={() => { setActionsFor(detailsFor); setDetailsFor(null); }} />
      )}
      {editorFor && (
        <CustomerEditor key={editorFor === 'new' ? 'new' : editorFor.contactId}
          contact={editorFor === 'new' ? null : editorFor} contacts={contacts}
          onClose={() => setEditorFor(null)} onSaved={saveContact}
          onExisting={existing => { setEditorFor(null); setDetailsFor(existing); }} />
      )}
      {actionsFor && (
        <CustomerActionsSheet contact={actionsFor} onClose={() => setActionsFor(null)}
          onRemoved={dropRow} onArchived={dropRow}
          onChanged={async () => { await load(); }} />
      )}
      {manageOpen && (
        <CustomerManageData contacts={contacts} onClose={() => setManageOpen(false)}
          onOpenCustomer={id => {
            const contact = contacts.find(item => item.contactId === id);
            setManageOpen(false);
            if (contact) setDetailsFor(contact);
          }}
          onChanged={load} />
      )}
    </section>
  );
};

export default CustomerList;
