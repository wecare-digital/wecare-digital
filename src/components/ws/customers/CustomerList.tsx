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

type ViewFilter = 'all' | 'address' | 'incomplete' | 'unnamed' | 'unverified';
const MAX_BULK = 100; // Bound each deliberately confirmed operation; never fire unbounded writes.
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

const WHATSAPP_BUSINESS_PORTFOLIOS = [
  { id: '382642103987922', name: 'WECARE.DIGITAL' },
  { id: '125951953587391', name: 'Manish Agarwal' },
] as const;

function displayName(contact: Contact): string {
  return contact.name?.trim() || 'Unnamed customer';
}
function initials(contact: Contact): string {
  const value = displayName(contact);
  if (value === 'Unnamed customer') return 'WC';
  const words = value.split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : value.slice(0, 2)).toUpperCase();
}
function identityId(contact: Contact): string {
  return contact.contactId || contact.id || '';
}
function customerId(contact: Contact): string {
  return contact.customerDisplayId || contact.subscriberId || identityId(contact) || 'Unknown ID';
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
function needsName(contact: Contact): boolean {
  return !contact.name?.trim();
}
function missingDetails(contact: Contact): boolean {
  return needsName(contact) || !contactDeliveryAddress(contact);
}
function isBulkEligible(contact: Contact): boolean {
  // Identity or retention-lock uncertainty means review, not deletion/archiving.
  // Phone-hidden WhatsApp users must be reviewed individually, not bulk-archived
  // because a missing phone/verification is not evidence of inactivity.
  return Boolean(identityId(contact)) && !contact.locked && !contact.archivedAt
    && !(contact.bsuid && !contact.phone);
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
            {contact.phone && <span className={contact.phoneVerifiedAt ? styles.successTag : styles.neutralTag}>
              {contact.phoneVerifiedAt ? 'Phone verified' : 'Phone not verified'}
            </span>}
            {contact.bsuid && <span className={styles.neutralTag}>WhatsApp BSUID linked</span>}
            {contact.bsuid && !contact.phone && <span className={styles.neutralTag}>Phone not shared</span>}
            {!contact.phone && <span className={styles.warningTag}>Website OTP and checkout require a phone</span>}
            {contact.locked && <span className={styles.warningTag}>Retention lock</span>}
            {contact.archivedAt && <span className={styles.neutralTag}>Archived</span>}
          </div>

          <section className={styles.detailSection} aria-labelledby="wsc-profile-title">
            <h3 id="wsc-profile-title">Profile</h3>
            <dl className={styles.detailFields}>
              <dt>WhatsApp number</dt><dd>{contact.phone || (contact.bsuid ? 'Not shared by WhatsApp' : '—')}</dd>
              <dt>Meta WhatsApp username</dt><dd>{contact.username ? (contact.username.startsWith('@') ? contact.username : '@' + contact.username) : '—'}</dd>
              <dt>Business-scoped user ID (BSUID)</dt><dd>{contact.bsuid || '—'}</dd>
              <dt>Parent BSUID</dt><dd>{contact.parentBsuid || '—'}</dd>
              <dt>Meta contact-book name</dt><dd>{contact.contactBookName || '—'}</dd>
              {WHATSAPP_BUSINESS_PORTFOLIOS.map(business => {
                const identity = contact.whatsappIdentities?.[business.id];
                return <React.Fragment key={business.id}>
                  <dt>{business.name} BSUID</dt><dd>{identity?.bsuid || '—'}</dd>
                  <dt>{business.name} Meta username</dt><dd>{identity?.username ? '@' + identity.username.replace(/^@/, '') : '—'}</dd>
                  <dt>{business.name} parent BSUID</dt><dd>{identity?.parentBsuid || '—'}</dd>
                </React.Fragment>;
              })}
              <dt>WECARE profile username</dt><dd>{contact.profileUsername || '—'}</dd>
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
          <button type="button" className={styles.secondaryButton} onClick={onActions}
            disabled={!identityId(contact)}>More actions</button>
          <button type="button" className={styles.primaryButton} onClick={onEdit}
            disabled={!identityId(contact)}>Edit contact <ArrowGlyph /></button>
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
  const [bulkProgress, setBulkProgress] = React.useState<{ done: number; total: number } | null>(null);
  const [bulkOutcome, setBulkOutcome] = React.useState('');
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
      if (response.ok) {
        setContacts(response.data);
        // A successful save returns a server snapshot; refresh the open detail panel with
        // the canonical re-read instead of leaving a stale saved response on screen.
        setDetailsFor(current => current
          ? response.data.find(item => Boolean(identityId(current)) && identityId(item) === identityId(current)) || current
          : null);
      } else setLoadError(response.failure.message || 'The customer directory could not be loaded.');
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
  const unnamed = React.useMemo(() => contacts.filter(needsName).length, [contacts]);
  const unverified = React.useMemo(() => contacts.filter(item => Boolean(item.phone) && !item.phoneVerifiedAt).length, [contacts]);

  const visible = React.useMemo(() => {
    const term = search.trim().toLowerCase();
    return contacts.filter(contact => {
      if (filter === 'address' && !contactDeliveryAddress(contact)) return false;
      if (filter === 'incomplete' && !missingDetails(contact)) return false;
      if (filter === 'unnamed' && !needsName(contact)) return false;
      if (filter === 'unverified' && (!contact.phone || contact.phoneVerifiedAt)) return false;
      if (!term) return true;
      const text = [
        contact.name, contact.phone, contact.email, contact.companyName, contact.designation,
        contact.profileUsername, contact.username, contact.bsuid, contact.parentBsuid,
        contact.contactBookName,
        ...Object.values(contact.whatsappIdentities || {}).flatMap(identity =>
          [identity.bsuid, identity.username, identity.parentBsuid, identity.contactBookName]),
        customerId(contact), contactDeliveryAddress(contact),
        ...(contact.tags || []),
      ].join(' ').toLowerCase();
      return text.includes(term);
    }).sort((a, b) => sort === 'name'
      ? displayName(a).localeCompare(displayName(b), undefined, { sensitivity: 'base' })
      : timestamp(b.updatedAt) - timestamp(a.updatedAt));
  }, [contacts, search, filter, sort]);

  const dropRow = React.useCallback((id: string) => {
    setContacts(previous => previous.filter(item => identityId(item) !== id));
    setSelected(previous => { const next = new Set(previous); next.delete(id); return next; });
    setDetailsFor(previous => previous && identityId(previous) === id ? null : previous);
  }, []);

  const toggleSelected = (id: string) => {
    const record = contacts.find(item => identityId(item) === id);
    if (!record || !isBulkEligible(record)) {
      toast.warning('Protected or unidentified contacts cannot be selected for bulk cleanup.');
      return;
    }
    if (!selected.has(id) && selected.size >= MAX_BULK) {
      toast.warning('Review up to ' + MAX_BULK + ' contacts at once.');
      return;
    }
    setSelected(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else if (next.size < MAX_BULK) next.add(id);
      return next;
    });
  };
  // Never retain a hidden bulk selection when staff switch search/filter criteria.
  React.useEffect(() => { setSelected(new Set()); setBulkOutcome(''); }, [search, filter]);

  const selectableVisible = visible.filter(isBulkEligible);
  const protectedVisible = visible.length - selectableVisible.length;
  const batchVisible = selectableVisible.slice(0, MAX_BULK);
  const allVisibleSelected = batchVisible.length > 0
    && batchVisible.every(contact => selected.has(identityId(contact)));
  const selectAllVisible = () => {
    // Replace the selection instead of unioning. This cannot exceed MAX_BULK even when
    // one manually selected row sits outside the first 100 visible candidates.
    setSelected(allVisibleSelected ? new Set() : new Set(batchVisible.map(identityId)));
  };
  const endSelection = () => { setSelecting(false); setSelected(new Set()); };
  const reviewUnnamed = () => {
    setSearch('');
    setFilter('unnamed');
    setSelected(new Set());
    setSelecting(true);
  };
  const selectEligible = () => {
    setSelecting(true);
    setSelected(new Set(selectableVisible.slice(0, MAX_BULK).map(identityId)));
  };

  // Reuse the proven CSV export used by /workspace/customers, limited to the visible rows.
  const exportVisible = () => {
    const csv = api.exportContactsToCSV(visible);
    api.downloadFile(csv, 'customers_' + new Date().toISOString().slice(0, 10) + '.csv', 'text/csv');
    toast.success('Exported ' + visible.length + ' contact(s).');
  };

  /**
   * Archive-only bulk review. This is reversible and preserves contacts, consent, messages
   * and financial history. Individual soft-delete remains in CustomerActionsSheet.
   * Two server-side reads before writes reduce stale selection risks; the separately
   * deployed Contacts Lambda enforces an atomic retention lock when released.
   */
  const bulkArchive = async () => {
    if (bulkBusy || selected.size === 0) return;
    setBulkBusy(true);
    setBulkOutcome('');
    setBulkProgress(null);
    try {
      const snapshot = await api.listContactsResult();
      if (!snapshot.ok) {
        toast.error('Cannot confirm current retention status. Refresh the directory before archiving.');
        return;
      }
      const authoritative = new Map(snapshot.data.map(contact => [identityId(contact), contact]));
      const targets: Contact[] = [];
      let excluded = 0;
      for (const id of selected) {
        const contact = authoritative.get(id);
        if (!contact || !isBulkEligible(contact)
          || (filter === 'unnamed' && !needsName(contact))
          || (filter === 'unverified' && (!contact.phone || Boolean(contact.phoneVerifiedAt)))) {
          excluded++;
        } else if (targets.length < MAX_BULK) {
          targets.push(contact);
        }
      }
      if (excluded) toast.warning(excluded + ' protected, changed or missing record(s) excluded from cleanup.');
      if (targets.length === 0) {
        toast.warning('No eligible records. Locked contacts must be kept and reviewed individually.');
        return;
      }

      const approved = await confirm({
        title: 'Archive ' + targets.length + ' customer' + (targets.length === 1 ? '' : 's') + '?',
        message: 'These selected contacts will leave the active directory, but their phone identities, WhatsApp messages, orders, payments, consent records and audit history remain intact. Missing names and unverified phones do not prove inactivity. Confirm this reviewed bulk archive?',
        confirmText: 'Archive selected',
        danger: false,
      });
      if (!approved) return;

      // Review may remain open while another operator names, verifies or locks a contact.
      // Fail closed on an unreadable final directory; never run an unverified write batch.
      const finalSnapshot = await api.listContactsResult();
      if (!finalSnapshot.ok) {
        toast.error('Cannot recheck locks after confirmation. No archive started.');
        return;
      }
      const finalById = new Map(finalSnapshot.data.map(contact => [identityId(contact), contact]));
      const finalTargets = targets.filter(contact => {
        const latest = finalById.get(identityId(contact));
        return Boolean(latest && isBulkEligible(latest)
          && (filter !== 'unnamed' || needsName(latest))
          && (filter !== 'unverified' || (Boolean(latest.phone) && !latest.phoneVerifiedAt)));
      });
      if (finalTargets.length !== targets.length) {
        toast.warning((targets.length - finalTargets.length) + ' record(s) changed or became protected during review and were skipped.');
      }
      if (finalTargets.length === 0) return;

      let archived = 0;
      let refused = 0;
      let unconfirmed = 0;
      setBulkProgress({ done: 0, total: finalTargets.length });
      for (const contact of finalTargets) {
        try {
          const result = await api.archiveContact(
            identityId(contact), 'Staff-reviewed bulk cleanup via /ws/customers (' + filter + ')',
          );
          if (result.ok && result.data?.archivedAt) archived++;
          else if (!result.ok) refused++;
          else unconfirmed++;
        } catch {
          // Network failure may arrive after the server committed the archive.
          // Never retry automatically; the next directory refresh reconciles reality.
          unconfirmed++;
        }
        setBulkProgress(previous => previous ? { ...previous, done: previous.done + 1 } : null);
      }
      const outcome = archived + ' archived, ' + refused + ' refused, ' + unconfirmed + ' unconfirmed.';
      setBulkOutcome(outcome);
      if (archived) toast.success(outcome);
      else toast.warning(outcome);
      if (refused || unconfirmed) {
        toast.warning('Some records were kept or unconfirmed. Review the directory before retrying.');
      }
      endSelection();
      await load();
    } catch {
      toast.error('Archive status could not be confirmed. Refresh the directory before trying again.');
    } finally {
      setBulkProgress(null);
      setBulkBusy(false);
    }
  };

  const openDetails = (contact: Contact) => {
    if (selecting && isBulkEligible(contact)) toggleSelected(identityId(contact));
    else setDetailsFor(contact);
  };
  const saveContact = (saved: Contact, warning?: string) => {
    toast.success(editorFor === 'new' ? 'Contact created.' : 'Customer profile updated.');
    if (warning) toast.warning(warning);
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
          <button type="button" className={styles.iconButton} onClick={() => void load()} disabled={loading || bulkBusy}
            aria-label="Refresh customers" title="Refresh customers"><RefreshGlyph /></button>
          <button type="button" className={styles.primaryButton} onClick={() => { endSelection(); setEditorFor('new'); }} disabled={bulkBusy}>
            <PlusGlyph /> Create contact
          </button>
        </div>
      </header>

      {!loadError && (
        <div className={styles.stats} aria-label="Customer directory summary">
          <div className={styles.statCard}><span>All contacts</span><strong>{loading ? '—' : total}</strong><small>Active customer records</small></div>
          <div className={styles.statCard}><span>With address</span><strong>{loading ? '—' : withAddress}</strong><small>Delivery details saved</small></div>
          <button type="button" className={styles.statAction} onClick={reviewUnnamed}
            disabled={loading || bulkBusy} aria-label={'Review ' + unnamed + ' unnamed customer records'}>
            <span>Unnamed customers</span><strong>{loading ? '—' : unnamed}</strong><small>Review and clean up</small>
          </button>
        </div>
      )}

      <div className={styles.directory}>
        <div className={styles.toolbar}>
          <label className={styles.searchBox}>
            <SearchGlyph />
            <input ref={searchRef} type="search" value={search} disabled={bulkBusy} onChange={e => setSearch(e.target.value)}
              placeholder="Search customers, numbers, addresses…" aria-label="Search customers" autoComplete="off" />
            {search && <button type="button" disabled={bulkBusy}
              onClick={() => { if (!bulkBusy) { setSearch(''); searchRef.current?.focus(); } }}
              aria-label="Clear customer search">
              <CloseGlyph />
            </button>}
            <kbd>/</kbd>
          </label>
          <div className={styles.utilityButtons}>
            <button type="button" className={styles.secondaryButton} onClick={exportVisible}
              disabled={loading || bulkBusy || loadError !== '' || visible.length === 0}>Export CSV</button>
            <button type="button" className={styles.secondaryButton} disabled={bulkBusy}
              onClick={() => setManageOpen(true)}>Manage data</button>
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
              disabled={bulkBusy} aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All <span>{total}</span></button>
            <button type="button" className={filter === 'unnamed' ? styles.activeTab : styles.tab}
              disabled={bulkBusy} aria-pressed={filter === 'unnamed'} onClick={() => setFilter('unnamed')}>Unnamed <span>{unnamed}</span></button>
            <button type="button" className={filter === 'unverified' ? styles.activeTab : styles.tab}
              disabled={bulkBusy} aria-pressed={filter === 'unverified'} onClick={() => setFilter('unverified')}>Unverified <span>{unverified}</span></button>
            <button type="button" className={filter === 'address' ? styles.activeTab : styles.tab}
              disabled={bulkBusy} aria-pressed={filter === 'address'} onClick={() => setFilter('address')}>With address <span>{withAddress}</span></button>
            <button type="button" className={filter === 'incomplete' ? styles.activeTab : styles.tab}
              disabled={bulkBusy} aria-pressed={filter === 'incomplete'} onClick={() => setFilter('incomplete')}>Needs details <span>{incomplete}</span></button>
          </div>
          <label className={styles.sortControl}>
            <span>Sort</span>
            <select value={sort} disabled={bulkBusy} onChange={event => setSort(event.target.value as SortOrder)} aria-label="Sort customers">
              <option value="recent">Recently updated</option>
              <option value="name">Name A–Z</option>
            </select>
          </label>
        </div>

        {(filter === 'unnamed' || filter === 'unverified') && !loading && !loadError && (
          <div className={styles.cleanupInfo}>
            <div>
              <strong>{filter === 'unnamed' ? 'Review customers without a name' : 'Review phone verification'}</strong>
              <p>
                {filter === 'unnamed'
                  ? 'A missing name does not mean a customer is inactive. Check activity before removing a record.'
                  : 'An unverified phone does not mean an unused customer. Check messages and identity history first.'}
                {' '}Archive preserves customer identity, orders, payments and audit history.
              </p>
              {protectedVisible > 0 && (
                <small>{protectedVisible} protected or unidentified record(s) cannot be bulk-selected.</small>
              )}
            </div>
            <button type="button" className={styles.secondaryButton}
              disabled={bulkBusy || selectableVisible.length === 0} onClick={selectEligible}>
              Select {Math.min(selectableVisible.length, MAX_BULK)} eligible
            </button>
          </div>
        )}

        {selecting && visible.length > 0 && (
          <div className={styles.selectionBar}>
            <label><input type="checkbox" checked={allVisibleSelected} disabled={bulkBusy || batchVisible.length === 0}
              onChange={selectAllVisible} />
              Select all {batchVisible.length} eligible shown{selectableVisible.length > MAX_BULK ? ' (first 100)' : ''}</label>
            <span>{selected.size} selected · {protectedVisible} protected</span>
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
            {visible.map((contact, index) => (
              <li key={identityId(contact) || 'missing-id-' + index}
                className={selected.has(identityId(contact)) ? styles.selectedEntry : styles.entry}>
                {selecting && (
                  <label className={styles.rowCheckbox}>
                    <input type="checkbox" checked={selected.has(identityId(contact))}
                      disabled={bulkBusy || !isBulkEligible(contact)}
                      onChange={() => toggleSelected(identityId(contact))}
                      aria-label={'Select ' + displayName(contact)}
                      title={isBulkEligible(contact) ? 'Select for reviewed cleanup' : 'Protected: review individually'} />
                  </label>
                )}
                <button type="button" className={styles.rowMain} onClick={() => openDetails(contact)}
                  aria-label={(selecting ? 'Select ' : 'View ') + displayName(contact)}>
                  <span className={styles.personCell}>
                    <span className={styles.avatar} aria-hidden="true">{initials(contact)}</span>
                    <span className={styles.personIdentity}>
                      <strong>{displayName(contact)}</strong>
                      <small>{customerId(contact)}</small>
                      {contact.username && <small>Meta @{contact.username.replace(/^@/, '')}</small>}
                      {WHATSAPP_BUSINESS_PORTFOLIOS.map(business => contact.whatsappIdentities?.[business.id]?.bsuid
                        ? <small key={business.id}>{business.name} WhatsApp linked</small> : null)}
                      {contact.bsuid && !contact.phone && <small>WhatsApp ID only · number not shared</small>}
                      {contact.locked && <small className={styles.protectedMarker}>Retention lock · Keep</small>}
                    </span>
                  </span>
                  <span className={styles.contactCell}>
                    <strong>{contact.phone || (contact.bsuid || Object.keys(contact.whatsappIdentities || {}).length ? 'BSUID-only customer' : '—')}</strong>
                    <small>{contact.email || (!contact.phone ? 'Phone not shared' : (contact.phoneVerifiedAt ? 'Phone verified' : 'Phone not verified'))}</small>
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

      {bulkOutcome && (
        <p className={styles.bulkOutcome} role="status">{bulkOutcome} Review remaining contacts before retrying any unconfirmed action.</p>
      )}
      {selecting && selected.size > 0 && (
        <div className={styles.bulkTray} role="region" aria-label="Selected customer cleanup actions">
          <div className={styles.bulkSummary}>
            <strong>{selected.size} selected</strong>
            <small>{bulkProgress
              ? 'Archiving ' + bulkProgress.done + ' / ' + bulkProgress.total
              : 'Archive keeps customer history. Permanent erasure is unavailable.'}</small>
          </div>
          <div className={styles.bulkActions}>
            <button type="button" className={styles.primaryButton} onClick={() => void bulkArchive()}
              disabled={bulkBusy}>{bulkBusy ? 'Archiving…' : 'Archive selected'}</button>
          </div>
        </div>
      )}

      {detailsFor && !editorFor && !actionsFor && (
        <CustomerDetails key={identityId(detailsFor) || 'missing-id'} contact={detailsFor}
          onClose={() => setDetailsFor(null)}
          onEdit={() => { setEditorFor(detailsFor); setDetailsFor(null); }}
          onActions={() => { setActionsFor(detailsFor); setDetailsFor(null); }} />
      )}
      {editorFor && (
        <CustomerEditor key={editorFor === 'new' ? 'new' : identityId(editorFor)}
          contact={editorFor === 'new' ? null : editorFor} contacts={contacts}
          onClose={() => setEditorFor(null)} onSaved={saveContact}
          onExisting={existing => { setEditorFor(null); setDetailsFor(existing); }} />
      )}
      {actionsFor && (
        <CustomerActionsSheet contact={actionsFor} onClose={() => setActionsFor(null)}
          onArchived={dropRow}
          onChanged={async () => { await load(); }} />
      )}
      {manageOpen && (
        <CustomerManageData contacts={contacts} onClose={() => setManageOpen(false)}
          onOpenCustomer={id => {
            const contact = contacts.find(item => identityId(item) === id);
            setManageOpen(false);
            if (contact) setDetailsFor(contact);
          }}
          onChanged={load} />
      )}
    </section>
  );
};

export default CustomerList;
