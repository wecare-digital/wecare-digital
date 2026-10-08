/**
 * Contacts Management Page
 * Full CRUD with sorting, pagination, tooltips, keyboard shortcuts,
 * bulk actions, inline edit, column visibility, detail panel, duplicate detection, tags
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import Layout from '../../../components/Layout';
import SEO, { PAGE_SEO } from '../../../components/SEO';
import { SkeletonTable } from '../../../components/Skeleton';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';
import * as api from '../../../api/client';
import { DIAL_CODES } from '../../../lib/dialCodes';

// SVG Icons — lime + dark green theme (#1a3a2a) — Fix #17: added aria-hidden for decorative icons
const AddUserIcon = () => (<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none"><path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M12 5v14m-7-7h14"/></svg>);
const UploadIcon = () => (<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none"><path fill="none" stroke="#1a3a2a" strokeMiterlimit="10" strokeWidth="1.5" d="M12 2.5v17.14m7.62-9.52L12 2.5l-7.62 7.62m15.24 8.57v3.81H4.38v-3.81"/></svg>);
const RefreshIcon = () => (<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none"><path fill="#1a3a2a" d="m13.146 11.05-.174-1.992 2.374-.208a5 5 0 1 0 .82 6.173l2.002.5a7 7 0 1 1-1.315-7.996l-.245-2.803L18.6 4.55l.523 5.977z"/></svg>);
const ExportIcon = () => (<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>);
const EditIcon = ({ size = 18 }: { size?: number }) => (<svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H6.8c-1.68 0-2.52 0-3.162.327a3 3 0 0 0-1.311 1.311C2 6.28 2 7.12 2 8.8v8.4c0 1.68 0 2.52.327 3.162a3 3 0 0 0 1.311 1.311C4.28 22 5.12 22 6.8 22h8.4c1.68 0 2.52 0 3.162-.327a3 3 0 0 0 1.311-1.311C20 19.72 20 18.88 20 17.2V13M8 16h1.675c.489 0 .733 0 .963-.055.204-.05.4-.13.579-.24.201-.123.374-.296.72-.642L21.5 5.5a2.121 2.121 0 0 0-3-3l-9.563 9.563c-.346.346-.519.519-.642.72a2 2 0 0 0-.24.579c-.055.23-.055.474-.055.963z"/></svg>);
const DeleteIcon = ({ size = 18 }: { size?: number }) => (<svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3h6M3 6h18m-2 0-.701 10.52c-.106 1.583-.158 2.374-.499 2.98a3 3 0 0 1-1.298 1.215C16.56 21 15.767 21 14.182 21H9.818c-1.585 0-2.378 0-2.82-.285a3 3 0 0 1-1.298-1.215c-.341-.606-.393-1.397-.499-2.98L5 6m5 4.5v5m4-5v5"/></svg>);
const SortIcon = ({ dir }: { dir: 'asc' | 'desc' | null }) => (<svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ marginLeft: 4, opacity: dir ? 1 : 0.3 }}><path d="M6 1l3 4H3z" fill={dir === 'asc' ? '#1a3a2a' : '#d1d5db'} /><path d="M6 11l3-4H3z" fill={dir === 'desc' ? '#1a3a2a' : '#d1d5db'} /></svg>);
const CloseIcon = () => (<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>);

type SortKey = 'name' | 'phone' | 'email' | 'updatedAt';
type SortDir = 'asc' | 'desc';

// Fix #20: SortHeader extracted outside component to avoid re-creation on every render
const SortHeader = ({ label, sKey, sortKey, sortDir, onSort, style }: { label: string; sKey: SortKey; sortKey: SortKey; sortDir: SortDir; onSort: (key: SortKey) => void; style?: React.CSSProperties }) => (
  <th onClick={() => onSort(sKey)} style={{ cursor: 'pointer', userSelect: 'none', padding: '12px 14px', textAlign: 'left', fontSize: 14, fontWeight: 600, color: '#374151', background: '#f9fafb', borderBottom: '2px solid #f3f4f6', position: 'sticky', top: 0, zIndex: 2, ...style }}>
    <span style={{ display: 'inline-flex', alignItems: 'center' }}>{label}<SortIcon dir={sortKey === sKey ? sortDir : null} /></span>
  </th>
);

const PAGE_SIZE = 25;
const TAG_OPTIONS = ['VIP', 'Lead', 'Customer', 'Prospect', 'Partner', 'Vendor'] as const;
const TAG_COLORS: Record<string, string> = { VIP: '#0f2a1d', Lead: '#0f2a1d', Customer: '#1a3a2a', Prospect: '#1a3a2a', Partner: '#34d399', Vendor: '#d1d5db', 'blog-subscriber': '#1a3a2a' };
const tagLabel = ( tag: string ) => tag.toLowerCase() === 'blog-subscriber' ? 'Blog Subscriber' : tag;

/*
 * Country codes for phone number parsing - NOW SHARED, not a literal.
 *
 * The public sign-in field needs the same twenty entries, and the second copy would have been two
 * lists to keep in step: the workspace offering a dial code the storefront refuses, or the reverse.
 * The list moved to src/lib/dialCodes.ts unchanged, including its India-first order, which the
 * longest-prefix sort at the parsing site below does not depend on.
 */
const COUNTRY_CODES = DIAL_CODES;

type ColumnKey = 'shipping' | 'checkoutAddress' | 'updated' | 'tags';
const ALL_COLUMNS: { key: ColumnKey; label: string }[] = [
  { key: 'shipping', label: 'Delivery Address' },
  // A SECOND address column, not a replacement. See `formatCheckoutAddress`: checkout writes
  // `checkoutDeliveryAddress` and the CRM only ever read `shippingAddress`, so an address a
  // customer typed at checkout showed as a dash here. Visible by default, because "it is not in
  // the CRM" is the reported symptom; it is in the column menu for anyone who wants it hidden.
  { key: 'checkoutAddress', label: 'Checkout Address' },
  { key: 'updated', label: 'Updated' },
  { key: 'tags', label: 'Tags' },
];

/**
 * One line out of the structured checkout address, or '' when there is nothing stored.
 *
 * Returns '' rather than a partial placeholder so the caller's existing `value || '—'` renders
 * the same dash every other empty field renders. Each part is coerced and trimmed because this
 * is server data: a legacy row may hold a number or a null where a string is expected, and
 * `[a, b].join()` on those would print 'null' into the panel.
 */
function formatCheckoutAddress(address?: api.CheckoutDeliveryAddress): string {
  if (!address || typeof address !== 'object') return '';
  const parts = [
    address.addressLine1, address.addressLine2, address.locality,
    address.city, address.state, address.postalCode, address.countryCode,
  ].map(part => String(part ?? '').trim()).filter(Boolean);
  return parts.join(', ');
}

/**
 * The checkout address for the detail panel, with the age of the write appended.
 *
 * `checkoutAddressUpdatedAt` answers a question the address alone cannot: whether this is what
 * the customer typed for the order being looked at, or an address from a purchase months ago.
 * Folded into this row rather than given a row of its own, so a contact that never checked out
 * still shows one dash here instead of two. Returns '' on an empty address for the same reason
 * `formatCheckoutAddress` does - the caller's `value || '—'` owns the placeholder.
 */
function formatCheckoutAddressDetail(contact: api.Contact): string {
  const line = formatCheckoutAddress(contact.checkoutDeliveryAddress);
  if (!line) return '';
  const age = contact.checkoutAddressUpdatedAt ? timeAgo(contact.checkoutAddressUpdatedAt) : '';
  return age && age !== '—' ? `${line} (saved ${age})` : line;
}
function timeAgo(dateStr?: string | number): string {
  if (!dateStr && dateStr !== 0) return '—';
  // Backend stores timestamps as Unix epoch seconds (int(time.time()))
  // Detect epoch seconds vs milliseconds vs ISO string
  let d: Date;
  if (typeof dateStr === 'number') {
    d = new Date(dateStr < 1e12 ? dateStr * 1000 : dateStr);
  } else {
    const num = Number(dateStr);
    if (!isNaN(num)) {
      d = new Date(num < 1e12 ? num * 1000 : num);
    } else {
      d = new Date(dateStr);
    }
  }
  if (isNaN(d.getTime())) return '—';
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 0) return 'just now';
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

interface PageProps { signOut?: () => void; user?: any; }

// ── Contact Activity Timeline ──
interface ActivityItem {
  id: string;
  type: 'flow' | 'change' | 'message' | 'created';
  icon: string;
  title: string;
  details?: { field: string; old: string; new: string }[];
  meta?: string;
  timestamp: number;
}

const ContactActivityTimeline: React.FC<{ phone: string; contactId: string; createdAt: string }> = ({ phone, contactId, createdAt }) => {
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    if (!phone && !contactId) return;
    setLoading(true);
    (async () => {
      const items: ActivityItem[] = [];

      // Customer ideas are read from their authoritative ReviewTable records.
      try {
        const { reviews } = await api.listReviews({ customerPhone: phone, contactId });
        for (const review of reviews.filter(r => r.reviewType === 'customer_idea' && r.contactId === contactId)) {
          items.push({ id: review.reviewId, type: 'flow', icon: '↗',
            title: 'Customer idea shared', meta: review.comment || '', timestamp: review.createdAt });
        }
      } catch { /* existing activity remains available if reviews cannot load */ }

      // Load flow logs/submissions for this phone
      try {
        const logs = await api.listFlowLogs(phone);
        for (const log of logs) {
          // Check if it's a change log
          let flowData: any = {};
          try { flowData = log.flowData ? JSON.parse(log.flowData) : {}; } catch {}
          const changes = flowData?.changes;

          if (changes && typeof changes === 'object' && Object.keys(changes).length > 0) {
            // Change log entry
            const details = Object.entries(changes).map(([field, vals]: [string, any]) => ({
              field,
              old: vals?.old || '(empty)',
              new: vals?.new || '(empty)',
            }));
            items.push({
              id: log.id,
              type: 'change',
              icon: '🔄',
              title: `${flowData.updated_by?.replace(/_/g, ' ') || 'Flow'} updated contact`,
              details,
              meta: flowData.subscriber_id || '',
              timestamp: log.createdAt,
            });
          } else {
            // Flow submission
            items.push({
              id: log.id,
              type: 'flow',
              icon: '📋',
              title: `${log.type || log.action || 'Flow'} submission`,
              meta: log.subject || log.order_id || '',
              timestamp: log.createdAt,
            });
          }
        }
      } catch { /* ignore */ }

      // Add contact created event
      if (createdAt) {
        const ts = Number(createdAt);
        const epoch = !isNaN(ts) ? (ts < 1e12 ? ts : Math.floor(ts / 1000)) : 0;
        if (epoch > 0) {
          items.push({
            id: 'created',
            type: 'created',
            icon: '✨',
            title: 'Contact created',
            meta: 'Auto-created from inbound message',
            timestamp: epoch,
          });
        }
      }

      // Sort by timestamp descending (newest first)
      items.sort((a, b) => b.timestamp - a.timestamp);
      setActivities(items);
      setLoading(false);
    })();
  }, [phone, contactId, createdAt]);

  const fmtTs = (ts: number) => {
    if (!ts) return '—';
    const ms = ts > 1e12 ? ts : ts * 1000;
    return new Date(ms).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' });
  };

  return (
    <div style={{ marginTop: 20, borderTop: '2px solid #f3f4f6', paddingTop: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <button onClick={() => setExpanded(!expanded)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, color: '#1a3a2a' }}>
          <span style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s', display: 'inline-block' }}>▶</span>
          Activity ({activities.length})
        </button>
      </div>
      {expanded && (
        <div>
          {loading && <p style={{ fontSize: 12, color: '#9ca3af' }}>Loading...</p>}
          {!loading && activities.length === 0 && <p style={{ fontSize: 12, color: '#9ca3af' }}>No activity yet</p>}
          {activities.map(a => (
            <div key={a.id} style={{ display: 'flex', gap: 8, marginBottom: 12, position: 'relative' }}>
              {/* Timeline line */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 20, flexShrink: 0 }}>
                <span style={{ fontSize: 14 }}>{a.icon}</span>
                <div style={{ flex: 1, width: 1, background: '#e5e7eb', marginTop: 4 }} />
              </div>
              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ margin: 0, fontSize: 12, fontWeight: 600, color: '#374151' }}>{a.title}</p>
                <p style={{ margin: '2px 0 0', fontSize: 10, color: '#9ca3af' }}>{fmtTs(a.timestamp)}{a.meta ? ` · ${a.meta}` : ''}</p>
                {a.details && a.details.length > 0 && (
                  <div style={{ marginTop: 4, padding: '6px 8px', background: '#f9fafb', borderRadius: 6, fontSize: 11 }}>
                    {a.details.map(d => (
                      <div key={d.field} style={{ marginBottom: 2 }}>
                        <span style={{ color: '#6b7280' }}>{d.field}:</span>{' '}
                        <span style={{ color: '#dc2626', textDecoration: 'line-through' }}>{d.old}</span>{' → '}
                        <span style={{ color: '#059669', fontWeight: 500 }}>{d.new}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const Contacts: React.FC<PageProps> = ({ signOut, user }) => {
  const [showModal, setShowModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [editingContact, setEditingContact] = useState<api.Contact | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const toast = useToastContext();
  const confirm = useConfirm();
  
  // Mobile detection
  const [isMobile, setIsMobile] = useState(false);
  
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth <= 768);
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // Debounce search input (300ms)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Sorting & Pagination
  const [sortKey, setSortKey] = useState<SortKey>('updatedAt');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [currentPage, setCurrentPage] = useState(1);

  // Form state
  const [formName, setFormName] = useState('');
  const [formPhone, setFormPhone] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formBsuid, setFormBsuid] = useState('');
  const [formUsername, setFormUsername] = useState('');
  const [formContactBookName, setFormContactBookName] = useState('');
  const [formShippingAddress, setFormShippingAddress] = useState('');
  const [formBillingAddress, setFormBillingAddress] = useState('');
  const [formAddressLine1, setFormAddressLine1] = useState('');
  const [formAddressLine2, setFormAddressLine2] = useState('');
  const [formCity, setFormCity] = useState('');
  const [formState, setFormState] = useState('');
  const [formPostalCode, setFormPostalCode] = useState('');
  const [formLandmark, setFormLandmark] = useState('');
  const [formHouseNumber, setFormHouseNumber] = useState('');
  const [formBuildingName, setFormBuildingName] = useState('');
  const [formTowerNumber, setFormTowerNumber] = useState('');
  const [formFloorNumber, setFormFloorNumber] = useState('');
  const [formCountry, setFormCountry] = useState('India');
  const [formGstin, setFormGstin] = useState('');
  const [formCompanyName, setFormCompanyName] = useState('');
  const [formDesignation, setFormDesignation] = useState('');
  const [formCountryCode, setFormCountryCode] = useState('+91');
  const [showCountryDropdown, setShowCountryDropdown] = useState(false);
  const [countrySearch, setCountrySearch] = useState('');
  const [formOptInWA, setFormOptInWA] = useState(true);
  const [formOptInSms, setFormOptInSms] = useState(true);
  const [formOptInEmail, setFormOptInEmail] = useState(true);
  const [formAllowlistWA, setFormAllowlistWA] = useState(true);
  const [formAllowlistSms, setFormAllowlistSms] = useState(true);
  const [formAllowlistEmail, setFormAllowlistEmail] = useState(true);

  // Delete confirmation (uses global useConfirm)

  // CSV import
  const [previewData, setPreviewData] = useState<Partial<api.Contact>[]>([]);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<api.ImportResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [contacts, setContacts] = useState<api.Contact[]>([]);
  // Fix #13: Error state for retry UI
  const [loadError, setLoadError] = useState(false);

  // === NEW FEATURES STATE ===
  // Bulk selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Column visibility
  const [hiddenCols, setHiddenCols] = useState<Set<ColumnKey>>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('ct-hidden-cols');
      if (saved) return new Set(JSON.parse(saved) as ColumnKey[]);
    }
    return new Set();
  });
  const [showColMenu, setShowColMenu] = useState(false);

  // Inline edit — Fix #8: added 'phone' as inline-editable field
  const [inlineEdit, setInlineEdit] = useState<{ id: string; field: 'name' | 'email' | 'phone'; value: string } | null>(null);

  // Fix #7: Deleting state to prevent double-click on delete modal
  const [deleting, setDeleting] = useState(false);

  // Fix #12 (R2): Track Escape to prevent onBlur from committing after cancel
  const inlineEditCancelled = useRef(false);

  // Detail panel
  const [detailContact, setDetailContact] = useState<api.Contact | null>(null);

  // Keep detail panel in sync when contacts list refreshes
  useEffect(() => {
    if (detailContact) {
      const updated = contacts.find(c => c.contactId === detailContact.contactId);
      if (updated) setDetailContact(updated);
      else setDetailContact(null); // contact was deleted
    }
  }, [contacts]); // eslint-disable-line react-hooks/exhaustive-deps

  // Tags (persisted to DynamoDB via contact.tags field)
  const contactTags = useMemo<Record<string, string[]>>(() => {
    const map: Record<string, string[]> = {};
    for (const c of contacts) {
      if (c.tags && c.tags.length > 0) map[c.contactId] = c.tags;
    }
    return map;
  }, [contacts]);
  const [showTagMenu, setShowTagMenu] = useState<string | null>(null);
  const [tagMenuPos, setTagMenuPos] = useState<{ top: number; left: number; flipUp: boolean }>({ top: 0, left: 0, flipUp: false });
  const [showOptIn, setShowOptIn] = useState(false);

  // Fix #10: Close tag menu on scroll to prevent stale positioning
  useEffect(() => {
    if (!showTagMenu) return;
    const handleScroll = () => setShowTagMenu(null);
    window.addEventListener('scroll', handleScroll, true);
    return () => window.removeEventListener('scroll', handleScroll, true);
  }, [showTagMenu]);

  // Persist column visibility
  useEffect(() => { localStorage.setItem('ct-hidden-cols', JSON.stringify([...hiddenCols])); }, [hiddenCols]);

  const colVisible = (key: ColumnKey) => !hiddenCols.has(key);
  const toggleCol = (key: ColumnKey) => {
    setHiddenCols(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  };

  const loadContacts = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const data = await api.listContacts();
      if (data.length > 0) {
        setContacts(data);
      } else {
        // Empty result — check if API actually failed
        const status = api.getConnectionStatus();
        if (status.status === 'disconnected') {
          // API failed — try messages fallback
          const messages = await api.listMessages(undefined, undefined, 2000);
          if (messages.length > 0) {
            const phoneMap = new Map<string, Partial<api.Contact>>();
            messages.forEach(m => {
              const phone = m.senderPhone || m.receivingPhone || '';
              if (phone && m.contactId && !phoneMap.has(m.contactId)) {
                phoneMap.set(m.contactId, {
                  contactId: m.contactId, name: m.senderName || phone, phone, email: '',
                  optInWhatsApp: true, optInSms: false, optInEmail: false,
                  allowlistWhatsApp: true, allowlistSms: false, allowlistEmail: false,
                  createdAt: m.timestamp, updatedAt: m.timestamp,
                });
              }
            });
            setContacts(Array.from(phoneMap.values()) as api.Contact[]);
            toast.warning(`Contacts API error — showing ${phoneMap.size} contacts from messages`);
          } else {
            setLoadError(true);
            toast.error(status.lastError || 'Failed to load contacts');
          }
        } else {
          setContacts(data); // genuinely empty
        }
      }
    } catch (err: any) {
      setLoadError(true);
      toast.error(err?.message || 'Failed to load contacts');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadContacts(); }, [loadContacts]);

  const resetForm = () => {
    setFormName(''); setFormPhone(''); setFormEmail('');
    setFormBsuid(''); setFormUsername(''); setFormContactBookName('');
    setFormShippingAddress(''); setFormBillingAddress(''); setFormCountryCode('+91');
    setFormAddressLine1(''); setFormAddressLine2(''); setFormCity(''); setFormState('');
    setFormPostalCode(''); setFormLandmark(''); setFormHouseNumber(''); setFormBuildingName('');
    setFormTowerNumber(''); setFormFloorNumber('');
    setFormCountry('India');
    setFormGstin('');
    setFormCompanyName(''); setFormDesignation('');
    setFormOptInWA(true); setFormOptInSms(true); setFormOptInEmail(true);
    setFormAllowlistWA(true); setFormAllowlistSms(true); setFormAllowlistEmail(true);
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
      if (e.key === 'Escape') {
        if (detailContact) { setDetailContact(null); return; }
        if (showModal) { setShowModal(false); return; }
        if (showEditModal) { setShowEditModal(false); setEditingContact(null); return; }
      }
      if (inInput) return;
      if (e.key === 'n' || e.key === 'N') { e.preventDefault(); resetForm(); setShowModal(true); }
      if (e.key === '/') { e.preventDefault(); searchInputRef.current?.focus(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [showModal, showEditModal, detailContact]);

  // Filter + sort (includes tag search)
  const filteredSorted = useMemo(() => {
    const q = debouncedSearch.toLowerCase();
    let list = contacts.filter(c =>
      (c.name || '').toLowerCase().includes(q) ||
      (c.phone || '').includes(debouncedSearch) ||
      (c.email || '').toLowerCase().includes(q) ||
      (c.tags || []).some(tag => tag.toLowerCase().includes(q))
    );
    list.sort((a, b) => {
      const av = (a[sortKey] || '') as string;
      const bv = (b[sortKey] || '') as string;
      if (sortKey === 'updatedAt') {
        const parseTs = (v: string) => { const n = Number(v); if (!isNaN(n)) return n < 1e12 ? n * 1000 : n; return new Date(v).getTime() || 0; };
        const da = parseTs(av);
        const db = parseTs(bv);
        return sortDir === 'asc' ? da - db : db - da;
      }
      return sortDir === 'asc' ? av.localeCompare(bv, undefined, { sensitivity: 'base' }) : bv.localeCompare(av, undefined, { sensitivity: 'base' });
    });
    return list;
  }, [contacts, debouncedSearch, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filteredSorted.length / PAGE_SIZE));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const paginatedContacts = filteredSorted.slice((safeCurrentPage - 1) * PAGE_SIZE, safeCurrentPage * PAGE_SIZE);
  useEffect(() => { setCurrentPage(1); }, [debouncedSearch]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('asc'); }
  };

  // Duplicate detection
  const checkDuplicate = (phone: string, email: string, excludeId?: string): string | null => {
    const fullPhone = phone ? (phone.startsWith('+') ? phone : `${formCountryCode}${phone.replace(/^0+/, '')}`) : '';
    for (const c of contacts) {
      if (excludeId && c.contactId === excludeId) continue;
      if (fullPhone && c.phone === fullPhone) return `Phone ${fullPhone} already exists (${c.name || 'unnamed'})`;
      if (email && c.email && c.email.toLowerCase() === email.toLowerCase()) return `Email ${email} already exists (${c.name || 'unnamed'})`;
    }
    return null;
  };

  // Fix #9: Frontend validation helpers
  const isValidPhone = (phone: string): boolean => {
    const cleaned = phone.replace(/[\s\-().]/g, '');
    return /^\+?\d{7,15}$/.test(cleaned);
  };
  const isValidEmail = (email: string): boolean => {
    return /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(email);
  };

  const handleCreate = async () => {
    if (formName.trim().length > 500) { toast.warning('Name is too long (max 500 characters)'); return; }
    if (!formPhone && !formEmail) { toast.warning('Phone or email is required'); return; }
    if (formPhone && !isValidPhone(formPhone.startsWith('+') ? formPhone : `${formCountryCode}${formPhone.replace(/^0+/, '')}`)) {
      toast.warning('Invalid phone number format'); return;
    }
    if (formEmail && !isValidEmail(formEmail)) {
      toast.warning('Invalid email format'); return;
    }
    const dup = checkDuplicate(formPhone, formEmail);
    if (dup) { toast.warning(dup); return; }
    const fullPhone = formPhone ? (formPhone.startsWith('+') ? formPhone : `${formCountryCode}${formPhone.replace(/^0+/, '')}`) : '';
    setSaving(true);
    try {
      const result = await api.createContact({
        name: formName, phone: fullPhone || undefined, email: formEmail || undefined,
        bsuid: formBsuid || undefined, username: formUsername || undefined, contactBookName: formContactBookName || undefined,
        shippingAddress: formShippingAddress || undefined, billingAddress: formBillingAddress || undefined,
        addressLine1: formAddressLine1 || undefined, addressLine2: formAddressLine2 || undefined,
        city: formCity || undefined, state: formState || undefined, postalCode: formPostalCode || undefined,
        landmark: formLandmark || undefined, houseNumber: formHouseNumber || undefined, buildingName: formBuildingName || undefined,
        towerNumber: formTowerNumber || undefined, floorNumber: formFloorNumber || undefined,
        country: formCountry || undefined,
        // FEAT-003: validated structured address -> checkoutDeliveryAddress via the shared
        // server-side validator. Flat fields kept for other readers; collapsing is a follow-up.
        address: (formAddressLine1 && formCity && formState && formPostalCode) ? {
          addressLine1: formAddressLine1, addressLine2: formAddressLine2 || undefined,
          city: formCity, state: formState, postalCode: formPostalCode,
          country: formCountry || undefined, countryCode: formCountry || undefined,
        } : undefined,
        gstin: formGstin || undefined,
        companyName: formCompanyName || undefined,
        designation: formDesignation || undefined,
        optInWhatsApp: formOptInWA, optInSms: formOptInSms, optInEmail: formOptInEmail,
        allowlistWhatsApp: formAllowlistWA, allowlistSms: formAllowlistSms, allowlistEmail: formAllowlistEmail,
      } as any);
      if (result) { toast.success('Contact created'); setShowModal(false); resetForm(); await loadContacts(); }
      else toast.error('Failed to create contact');
    } catch { toast.error('Failed to create contact'); }
    finally { setSaving(false); }
  };

  const handleEdit = (contact: api.Contact) => {
    setEditingContact(contact);
    setFormName(contact.name || '');
    const ph = contact.phone || '';
    
    // Find matching country code from our list
    let matchedCode = '+91'; // default
    let phoneNumber = ph;
    
    if (ph.startsWith('+')) {
      // Try to match against known country codes (longest first)
      const sortedCodes = COUNTRY_CODES.map(cc => cc.code).sort((a, b) => b.length - a.length);
      for (const code of sortedCodes) {
        if (ph.startsWith(code)) {
          matchedCode = code;
          phoneNumber = ph.slice(code.length);
          break;
        }
      }
    }
    
    setFormCountryCode(matchedCode);
    setFormPhone(phoneNumber);
    setFormEmail(contact.email || '');
    setFormBsuid(contact.bsuid || ''); setFormUsername(contact.username || ''); setFormContactBookName(contact.contactBookName || '');
    setFormShippingAddress(contact.shippingAddress || ''); setFormBillingAddress(contact.billingAddress || '');
    setFormAddressLine1(contact.addressLine1 || ''); setFormAddressLine2(contact.addressLine2 || '');
    setFormCity(contact.city || ''); setFormState(contact.state || '');
    setFormPostalCode(contact.postalCode || ''); setFormLandmark(contact.landmark || '');
    setFormHouseNumber(contact.houseNumber || ''); setFormBuildingName(contact.buildingName || '');
    setFormTowerNumber(contact.towerNumber || ''); setFormFloorNumber(contact.floorNumber || '');
    setFormCountry(contact.country || 'India');
    setFormGstin((contact as any).gstin || '');
    setFormCompanyName(contact.companyName || '');
    setFormDesignation(contact.designation || '');
    setFormOptInWA(contact.optInWhatsApp || false); setFormOptInSms(contact.optInSms || false); setFormOptInEmail(contact.optInEmail || false);
    setFormAllowlistWA(contact.allowlistWhatsApp || false); setFormAllowlistSms(contact.allowlistSms || false); setFormAllowlistEmail(contact.allowlistEmail || false);
    setShowEditModal(true);
  };

  const handleUpdate = async () => {
    if (formName.trim().length > 500) { toast.warning('Name is too long (max 500 characters)'); return; }
    if (!editingContact || (!formPhone && !formEmail)) { toast.warning('Phone or email is required'); return; }
    if (formPhone && !isValidPhone(formPhone.startsWith('+') ? formPhone : `${formCountryCode}${formPhone.replace(/^0+/, '')}`)) {
      toast.warning('Invalid phone number format'); return;
    }
    if (formEmail && !isValidEmail(formEmail)) {
      toast.warning('Invalid email format'); return;
    }
    const dup = checkDuplicate(formPhone, formEmail, editingContact.contactId);
    if (dup) { toast.warning(dup); return; }
    const fullPhone = formPhone ? (formPhone.startsWith('+') ? formPhone : `${formCountryCode}${formPhone.replace(/^0+/, '')}`) : '';
    setSaving(true);
    try {
      const result = await api.updateContact(editingContact.contactId, {
        name: formName, phone: fullPhone || undefined, email: formEmail || undefined,
        bsuid: formBsuid || undefined, username: formUsername || undefined, contactBookName: formContactBookName || undefined,
        shippingAddress: formShippingAddress || undefined, billingAddress: formBillingAddress || undefined,
        addressLine1: formAddressLine1 || undefined, addressLine2: formAddressLine2 || undefined,
        city: formCity || undefined, state: formState || undefined, postalCode: formPostalCode || undefined,
        landmark: formLandmark || undefined, houseNumber: formHouseNumber || undefined, buildingName: formBuildingName || undefined,
        towerNumber: formTowerNumber || undefined, floorNumber: formFloorNumber || undefined,
        country: formCountry || undefined,
        // FEAT-003: validated structured address -> checkoutDeliveryAddress via the shared
        // server-side validator. Flat fields kept for other readers; collapsing is a follow-up.
        address: (formAddressLine1 && formCity && formState && formPostalCode) ? {
          addressLine1: formAddressLine1, addressLine2: formAddressLine2 || undefined,
          city: formCity, state: formState, postalCode: formPostalCode,
          country: formCountry || undefined, countryCode: formCountry || undefined,
        } : undefined,
        gstin: formGstin || undefined,
        companyName: formCompanyName || undefined,
        designation: formDesignation || undefined,
        optInWhatsApp: formOptInWA, optInSms: formOptInSms, optInEmail: formOptInEmail,
        allowlistWhatsApp: formAllowlistWA, allowlistSms: formAllowlistSms, allowlistEmail: formAllowlistEmail,
      } as any);
      if (result) { toast.success('Contact updated'); setShowEditModal(false); setEditingContact(null); resetForm(); await loadContacts(); }
      else toast.error('Failed to update contact');
    } catch { toast.error('Failed to update contact'); }
    finally { setSaving(false); }
  };

  // ARCHIVE, not delete. `api.deleteContact` has always been the SOFT delete: it sets
  // `deletedAt`, and `_list_all` / `_search` / `_read_one` hide those rows. So the record, the
  // messages and every payment link stay intact. The old copy said "delete" in the title and
  // the button and "will be archived" in the body — one of those was wrong, and it was the
  // scary one. Nothing about the call changed; only the words an operator reads.
  const handleArchive = async (contactId: string, contactName?: string) => {
    const ok = await confirm({
      title: 'Archive Contact',
      message: `Archive ${contactName ? `"${contactName}"` : 'this contact'}? It will be hidden from the contacts list. The record, its messages and any payment links are kept, and an admin can restore it.`,
      confirmText: 'Archive',
    });
    if (!ok) return;
    setDeleting(true);
    try {
      const result = await api.deleteContact(contactId);
      if (result) {
        toast.success('Contact archived');
        setSelectedIds(prev => { const next = new Set(prev); next.delete(contactId); return next; });
        await loadContacts();
      }
      else toast.error('Failed to archive contact');
    } catch { toast.error('Failed to archive contact'); }
    finally { setDeleting(false); }
  };

  // Bulk archive — Fix #6: Use batched Promise.all instead of sequential.
  // Same soft call as `handleArchive`, so the same word.
  const handleBulkArchive = async () => {
    if (selectedIds.size === 0) return;
    const count = selectedIds.size;
    if (!(await confirm(`Archive ${count} contact${count > 1 ? 's' : ''}? They will be hidden from the list and can be restored by an admin.`))) return;
    let archived = 0;
    const ids = Array.from(selectedIds);
    const BATCH = 5;
    for (let i = 0; i < ids.length; i += BATCH) {
      const batch = ids.slice(i, i + BATCH);
      const results = await Promise.all(batch.map(id => api.deleteContact(id).catch(() => false)));
      archived += results.filter(Boolean).length;
    }
    setSelectedIds(new Set());
    toast.success(`Archived ${archived} contact${archived > 1 ? 's' : ''}`);
    await loadContacts();
  };

  // Bulk export selected — Fix #11: added feedback toast
  const handleBulkExport = () => {
    const selected = contacts.filter(c => selectedIds.has(c.contactId));
    if (selected.length === 0) return;
    const csv = api.exportContactsToCSV(selected);
    api.downloadFile(csv, `contacts_selected_${new Date().toISOString().split('T')[0]}.csv`, 'text/csv');
    toast.success(`Exported ${selected.length} contact${selected.length > 1 ? 's' : ''}`);
  };

  // Fix #9: Select all on current page (with clear indication)
  const allPageSelected = paginatedContacts.length > 0 && paginatedContacts.every(c => selectedIds.has(c.contactId));
  const allFilteredSelected = filteredSorted.length > 0 && filteredSorted.every(c => selectedIds.has(c.contactId));
  const toggleSelectAll = () => {
    const next = new Set(selectedIds);
    if (allPageSelected) { paginatedContacts.forEach(c => next.delete(c.contactId)); }
    else { paginatedContacts.forEach(c => next.add(c.contactId)); }
    setSelectedIds(next);
  };
  const selectAllFiltered = () => {
    const next = new Set(selectedIds);
    filteredSorted.forEach(c => next.add(c.contactId));
    setSelectedIds(next);
  };
  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedIds(next);
  };

  // Inline edit — Fix #8: supports name, email, and phone
  const commitInlineEdit = async () => {
    if (!inlineEdit || inlineEditCancelled.current) { inlineEditCancelled.current = false; return; }
    const { id, field, value } = inlineEdit;
    // Validate inline email edits
    if (field === 'email' && value && !isValidEmail(value)) {
      toast.warning('Invalid email format');
      return;
    }
    // Validate inline phone edits
    if (field === 'phone' && value && !isValidPhone(value)) {
      toast.warning('Invalid phone number format');
      return;
    }
    // THE DIAL CODE IS COMPOSED HERE, with the same expression `handleCreate` and `handleUpdate`
    // already use. `contacts/handler.py::_e164_or_error` REFUSES a number carrying no dial code
    // with 400 PHONE_COUNTRY_CODE_REQUIRED rather than guessing +91 — correct, because guessing
    // would send an OTP to an unrelated Indian subscriber for a ten-digit foreign number and
    // reserve the wrong identity permanently. But `isValidPhone` above accepts a bare
    // `9876543210`, so the commonest inline edit an operator makes — retyping a national number
    // — would be refused by the server. The dialog form never hit this because it composes the
    // code first; the inline cell PUT the raw cell value. Normalisation stays the server's job;
    // this only supplies the dial code the form supplies.
    const outgoing = field === 'phone' && value
      ? (value.startsWith('+') ? value : `${formCountryCode}${value.replace(/^0+/, '')}`)
      : value;
    setInlineEdit(null);
    try {
      // `updateContactResult`, not `updateContact`: the latter collapses a 400 to null, and by
      // this line the editor has already closed, so the old code re-rendered the stale value
      // with no toast, no reload and no explanation — the refusal was invisible and the save
      // looked like it had worked. The failure message is the server's own and is safe to show.
      const result = await api.updateContactResult(id, { [field]: outgoing });
      if (result.ok) { toast.success(`${field} updated`); await loadContacts(); }
      else toast.error(`Could not update ${field} — ${result.failure.message}`);
    } catch { toast.error('Failed to update'); }
  };

  // Tags
  const toggleTag = async (contactId: string, tag: string) => {
    const current = contactTags[contactId] || [];
    const next = current.includes(tag) ? current.filter(t => t !== tag) : [...current, tag];
    // Optimistic update: refresh contacts list after API call
    try {
      await api.updateContact(contactId, { tags: next } as any);
      await loadContacts();
    } catch {
      toast.error('Failed to update tags');
    }
  };

  // CSV import handlers
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      if (file.name.endsWith('.vcf')) {
        setPreviewData(parseVCard(text));
      } else {
        // Fix #5: Use the robust CSV parser that handles quoted fields
        const parsed = api.parseContactsCSV(text);
        if (parsed.length === 0) { toast.warning('CSV file is empty or has no valid rows'); return; }
        setPreviewData(parsed);
      }
    };
    reader.readAsText(file);
  };

  // Fix #12: Improved vCard parser — handles vCard 3.0/4.0 TYPE params, folded lines, QP encoding
  const parseVCard = (text: string): Partial<api.Contact>[] => {
    // Unfold continuation lines (RFC 6350: line starting with space/tab is continuation)
    const unfolded = text.replace(/\r\n[ \t]/g, '').replace(/\n[ \t]/g, '');
    const cards = unfolded.split('BEGIN:VCARD').filter(c => c.trim());
    return cards.map(card => {
      const lines = card.split(/\r?\n/);
      let name = '', phone = '', email = '';
      for (const line of lines) {
        const trimmed = line.trim();
        // FN (formatted name) — may have params like FN;CHARSET=UTF-8:Name
        if (/^FN[;:]/i.test(trimmed) && !name) {
          const colonIdx = trimmed.indexOf(':');
          if (colonIdx !== -1) name = trimmed.slice(colonIdx + 1).trim();
        }
        // TEL — handles TEL;TYPE=cell:, TEL;TYPE=WORK,VOICE:, TEL;VALUE=uri:tel:
        if (/^TEL[;:]/i.test(trimmed) && !phone) {
          const colonIdx = trimmed.indexOf(':');
          if (colonIdx !== -1) {
            let val = trimmed.slice(colonIdx + 1).trim();
            // Strip tel: URI prefix
            val = val.replace(/^tel:/i, '');
            const m = val.match(/([\d+\s\-().]+)/);
            if (m) phone = m[1].replace(/[\s\-().]/g, '');
          }
        }
        // EMAIL — handles EMAIL;TYPE=INTERNET:, EMAIL;TYPE=HOME:
        if (/^EMAIL[;:]/i.test(trimmed) && !email) {
          const colonIdx = trimmed.indexOf(':');
          if (colonIdx !== -1) email = trimmed.slice(colonIdx + 1).trim();
        }
      }
      return { name, phone, email };
    }).filter(c => c.phone || c.email);
  };

  const handleImport = async () => {
    if (previewData.length === 0) return;
    setImporting(true);
    try {
      const result = await api.importContacts(previewData);
      setImportResult(result);
      toast.success(`Imported ${result.created} of ${result.total} contacts`);
      setPreviewData([]);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await loadContacts();
    } catch { toast.error('Import failed'); }
    finally { setImporting(false); }
  };

  const handleExport = () => {
    const data = debouncedSearch ? filteredSorted : contacts;
    const csv = api.exportContactsToCSV(data);
    api.downloadFile(csv, `contacts_${new Date().toISOString().split('T')[0]}.csv`, 'text/csv');
    toast.success(`Exported ${data.length} contact${data.length !== 1 ? 's' : ''}`);
  };

  const downloadTemplate = () => {
    api.downloadFile('Name,Phone,Email\nJohn Doe,+919000090000,[email]', 'contacts_template.csv', 'text/csv');
  };

  // Inline styles for form (bypasses Next.js style jsx scoping)
  const S: Record<string, React.CSSProperties> = {
    label: { display: 'block', fontSize: 14, fontWeight: 600, color: '#374151', marginBottom: 5 },
    input: { width: '100%', padding: '10px 14px', border: '2px solid #f3f4f6', borderRadius: 13, fontSize: 15, outline: 'none', transition: 'border-color 0.15s, box-shadow 0.15s', background: '#fff' },
    row: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 },
    hint: { fontSize: 12, color: '#9ca3af', marginTop: 3 },
  };
  const focusStyle = (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => { e.target.style.borderColor = '#1a3a2a'; e.target.style.boxShadow = '0 0 0 3px rgba(26,58,42,0.1)'; };
  const blurStyle = (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => { e.target.style.borderColor = '#f3f4f6'; e.target.style.boxShadow = 'none'; };

  const renderContactForm = (isEdit: boolean) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '20px 24px' }}>
      {/* Name */}
      <div>
        <label htmlFor="contact-name" style={S.label}>Name</label>
        <input id="contact-name" style={S.input} value={formName} onChange={e => setFormName(e.target.value)} placeholder="Full name" maxLength={500} onFocus={focusStyle} onBlur={blurStyle} />
      </div>
      {/* Phone */}
      <div>
        <label htmlFor="contact-phone" style={S.label}>Phone</label>
        <div style={{ display: 'flex', gap: 6 }}>
          {/* Searchable Country Code Dropdown */}
          <div style={{ position: 'relative', width: 120, flexShrink: 0 }}>
            <input
              type="text"
              value={showCountryDropdown ? countrySearch : formCountryCode}
              onChange={e => { setCountrySearch(e.target.value); setShowCountryDropdown(true); }}
              onFocus={() => { setShowCountryDropdown(true); setCountrySearch(''); }}
              onBlur={(e) => {
                // Fix #13: Use relatedTarget check instead of fragile setTimeout
                const dropdown = e.currentTarget.parentElement?.querySelector('[data-country-dropdown]');
                if (dropdown && dropdown.contains(e.relatedTarget as Node)) return;
                setShowCountryDropdown(false);
              }}
              placeholder="Code"
              style={{ width: '100%', padding: '8px 8px', border: '2px solid #f3f4f6', borderRadius: 13, fontSize: 14, outline: 'none', transition: 'border-color 0.15s, box-shadow 0.15s', background: '#fff', color: '#374151', cursor: 'pointer' }}
              onFocusCapture={focusStyle}
              onBlurCapture={blurStyle}
            />
            {showCountryDropdown && (
              <div data-country-dropdown tabIndex={-1} style={{ position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4, maxHeight: 200, overflowY: 'auto', background: '#fff', border: '2px solid #f3f4f6', borderRadius: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.1)', zIndex: 1000 }}>
                {COUNTRY_CODES
                  .filter(cc => 
                    cc.code.includes(countrySearch) || 
                    cc.country.toLowerCase().includes(countrySearch.toLowerCase())
                  )
                  .map(cc => (
                    <div
                      key={cc.code}
                      tabIndex={-1}
                      onMouseDown={() => { setFormCountryCode(cc.code); setShowCountryDropdown(false); setCountrySearch(''); }}
                      style={{ padding: '8px 12px', cursor: 'pointer', fontSize: 13, color: '#374151', transition: 'background 0.15s' }}
                      onMouseEnter={e => e.currentTarget.style.background = '#f9fafb'}
                      onMouseLeave={e => e.currentTarget.style.background = '#fff'}
                    >
                      {cc.code} {cc.country}
                    </div>
                  ))}
              </div>
            )}
          </div>
          <input id="contact-phone" style={S.input} value={formPhone} onChange={e => setFormPhone(e.target.value)} placeholder="[Phone]" maxLength={20} onFocus={focusStyle} onBlur={blurStyle} />
        </div>
        <p style={S.hint}>Include country code</p>
      </div>
      {/* Email */}
      <div>
        <label htmlFor="contact-email" style={S.label}>Email</label>
        <input id="contact-email" style={S.input} type="email" value={formEmail} onChange={e => setFormEmail(e.target.value)} placeholder="[email]" onFocus={focusStyle} onBlur={blurStyle} />
      </div>
      {/* WhatsApp Identity row — BSUID, Username, Contact Book Name */}
      <div style={S.row}>
        <div>
          <label htmlFor="contact-bsuid" style={S.label}>BSUID <span style={{ color: '#9ca3af', fontWeight: 400, fontSize: 11 }}>(auto-filled)</span></label>
          <input id="contact-bsuid" style={{ ...S.input, background: '#f9fafb', color: '#6b7280' }} value={formBsuid} onChange={e => setFormBsuid(e.target.value)} placeholder="e.g. IN.13491208655302741918" onFocus={focusStyle} onBlur={blurStyle} />
        </div>
        <div>
          <label htmlFor="contact-username" style={S.label}>Username <span style={{ color: '#9ca3af', fontWeight: 400, fontSize: 11 }}>(auto-filled)</span></label>
          <input id="contact-username" style={{ ...S.input, background: '#f9fafb', color: '#6b7280' }} value={formUsername} onChange={e => setFormUsername(e.target.value)} placeholder="e.g. @pablomorales" onFocus={focusStyle} onBlur={blurStyle} />
        </div>
      </div>
      <div>
        <label htmlFor="contact-book-name" style={S.label}>Contact Book Name <span style={{ color: '#9ca3af', fontWeight: 400, fontSize: 11 }}>(auto from Meta)</span></label>
        <input id="contact-book-name" style={{ ...S.input, background: '#f9fafb', color: '#6b7280' }} value={formContactBookName} onChange={e => setFormContactBookName(e.target.value)} placeholder="Enter company name" onFocus={focusStyle} onBlur={blurStyle} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div>
          <label style={S.label}>Organization</label>
          <input style={S.input} value={formCompanyName} onChange={e => setFormCompanyName(e.target.value)} placeholder="Enter organization name" onFocus={focusStyle} onBlur={blurStyle} />
        </div>
        <div>
          <label style={S.label}>Job Title</label>
          <input style={S.input} value={formDesignation} onChange={e => setFormDesignation(e.target.value)} placeholder="Enter role or job title" onFocus={focusStyle} onBlur={blurStyle} />
        </div>
      </div>
      {/* Shipping + Billing row */}
      <div>
        <label htmlFor="contact-address" style={S.label}>Delivery Address <span style={{ color: '#9ca3af', fontWeight: 400, fontSize: 11 }}>(used for billing too)</span></label>
        <textarea id="contact-address" style={{ ...S.input, minHeight: 60, resize: 'vertical' } as any} value={formShippingAddress} onChange={e => { setFormShippingAddress(e.target.value); setFormBillingAddress(e.target.value); }} placeholder="Enter full delivery address" onFocus={focusStyle as any} onBlur={blurStyle as any} />
      </div>
      {/* Structured Address Fields (for WhatsApp Payments) */}
      <div>
        <button type="button" onClick={() => {}} style={{ fontSize: 13, color: '#1a3a2a', background: 'none', border: 'none', padding: 0, fontWeight: 600, marginBottom: 8, display: 'block' }}>
          Structured Address (WhatsApp Payments)
        </button>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div><label style={S.label}>House / Unit Number</label><input style={S.input} value={formHouseNumber} onChange={e => setFormHouseNumber(e.target.value)} placeholder="e.g. 12" onFocus={focusStyle} onBlur={blurStyle} /></div>
          <div><label style={S.label}>Address</label><input style={S.input} value={formBuildingName} onChange={e => setFormBuildingName(e.target.value)} placeholder="Enter your complete address" onFocus={focusStyle} onBlur={blurStyle} /></div>
          <div><label style={S.label}>Landmark</label><input style={S.input} value={formLandmark} onChange={e => setFormLandmark(e.target.value)} placeholder="Enter a nearby landmark" onFocus={focusStyle} onBlur={blurStyle} /></div>
          <div><label style={S.label}>City</label><input style={S.input} value={formCity} onChange={e => setFormCity(e.target.value)} placeholder="e.g. Mumbai" onFocus={focusStyle} onBlur={blurStyle} /></div>
          <div><label style={S.label}>State</label><input style={S.input} value={formState} onChange={e => setFormState(e.target.value)} placeholder="e.g. Maharashtra" onFocus={focusStyle} onBlur={blurStyle} /></div>
          <div><label style={S.label}>Postal Code</label><input style={S.input} value={formPostalCode} onChange={e => setFormPostalCode(e.target.value)} placeholder="Enter postal code" onFocus={focusStyle} onBlur={blurStyle} /></div>
          <div><label style={S.label}>Country</label><input style={S.input} value={formCountry} onChange={e => setFormCountry(e.target.value)} placeholder="India" onFocus={focusStyle} onBlur={blurStyle} /></div>
        </div>
      </div>
      {/* Opt-in toggle */}
      <div>
        <button type="button" onClick={() => setShowOptIn(!showOptIn)} style={{ fontSize: 14, color: '#1a3a2a', background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
          <span style={{ transform: showOptIn ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s', display: 'inline-block', color: '#1a3a2a', fontSize: 16 }}>▶</span>
          Opt-in &amp; Allowlist
        </button>
        {showOptIn && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10, padding: 14, background: '#f9fafb', borderRadius: 13, border: '2px solid #f3f4f6' }}>
            {[
              { label: 'WhatsApp Opt-in', val: formOptInWA, set: setFormOptInWA },
              { label: 'WhatsApp Allowlist', val: formAllowlistWA, set: setFormAllowlistWA },
              { label: 'SMS Opt-in', val: formOptInSms, set: setFormOptInSms },
              { label: 'SMS Allowlist', val: formAllowlistSms, set: setFormAllowlistSms },
              { label: 'Email Opt-in', val: formOptInEmail, set: setFormOptInEmail },
              { label: 'Email Allowlist', val: formAllowlistEmail, set: setFormAllowlistEmail },
            ].map(item => (
              <label key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
                <input type="checkbox" checked={item.val} onChange={e => item.set(e.target.checked)} style={{ accentColor: '#1a3a2a', width: 16, height: 16 }} />
                {item.label}
              </label>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <Layout onSignOut={signOut} user={user}>
      <SEO {...PAGE_SEO.contacts} />
      <div className="inner-page-container">
        {/* Toolbar */}
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          {/* Contact count badge */}
          <span style={{ background: '#f9fafb', color: '#1a3a2a', fontWeight: 600, fontSize: 13, padding: '4px 12px', borderRadius: 13 }}>
            {filteredSorted.length} contact{filteredSorted.length !== 1 ? 's' : ''}
          </span>

          {/* Search */}
          <div style={{ position: 'relative', flex: '1 1 200px', maxWidth: 320 }}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>
              <path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="m21 21-4.35-4.35M11 6a5 5 0 0 1 5 5m3 0a8 8 0 1 1-16 0 8 8 0 0 1 16 0"/>
            </svg>
            <input ref={searchInputRef} aria-label="Search contacts" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search contacts..." style={{ width: '100%', padding: '8px 12px 8px 34px', border: '2px solid #f3f4f6', borderRadius: 13, fontSize: 14, outline: 'none', background: '#fff' }} onFocus={focusStyle} onBlur={blurStyle} />
          </div>

          {/* Action buttons */}
          <button onClick={() => { resetForm(); setShowModal(true); }} title="Add contact (N)" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '8px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, cursor: 'pointer' }}>
            <AddUserIcon />
          </button>
          <button onClick={() => setShowImport(!showImport)} title="Import contacts" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '8px', background: '#fff', color: '#374151', border: '2px solid #f3f4f6', borderRadius: 13, cursor: 'pointer' }}>
            <UploadIcon />
          </button>
          <button onClick={handleExport} title="Export all contacts" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '8px', background: '#fff', color: '#374151', border: '2px solid #f3f4f6', borderRadius: 13, cursor: 'pointer' }}>
            <ExportIcon />
          </button>
          <button onClick={() => loadContacts()} title="Refresh" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '8px', background: '#fff', border: '2px solid #f3f4f6', borderRadius: 13, cursor: 'pointer' }}>
            <RefreshIcon />
          </button>

          {/* Column visibility */}
          <div style={{ position: 'relative' }}>
            <button onClick={() => setShowColMenu(!showColMenu)} title="Toggle columns" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '8px', background: '#fff', border: '2px solid #f3f4f6', borderRadius: 13, cursor: 'pointer' }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="2"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0H5a2 2 0 0 1-2-2v-4m6 6h10a2 2 0 0 0 2-2v-4M3 9h18M3 15h18"/></svg>
            </button>
            {showColMenu && (
              <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 4, background: '#fff', border: '2px solid #f3f4f6', borderRadius: 13, padding: 8, zIndex: 50, minWidth: 160, boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}>
                {ALL_COLUMNS.map(col => (
                  <label key={col.key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', fontSize: 13, cursor: 'pointer', borderRadius: 8 }}>
                    <input type="checkbox" checked={colVisible(col.key)} onChange={() => toggleCol(col.key)} style={{ accentColor: '#1a3a2a' }} />
                    {col.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Bulk action bar — Fix #9: shows select-all-pages option */}
        {selectedIds.size > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px', marginBottom: 12, background: '#f9fafb', borderRadius: 13, border: '2px solid #f3f4f6', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#1a3a2a' }}>{selectedIds.size} selected</span>
            {allPageSelected && !allFilteredSelected && filteredSorted.length > PAGE_SIZE && (
              <button onClick={selectAllFiltered} style={{ fontSize: 12, color: '#1a3a2a', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>
                Select all {filteredSorted.length} contacts
              </button>
            )}
            <button onClick={handleBulkExport} title="Export selected" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '6px', background: '#fff', border: '2px solid #f3f4f6', borderRadius: 13, cursor: 'pointer' }}>
              <ExportIcon />
            </button>
            <button onClick={handleBulkArchive} title="Archive selected" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '6px', background: '#fff', border: '2px solid #1a3a2a', borderRadius: 13, cursor: 'pointer' }}>
              <DeleteIcon size={14} />
            </button>
            <button onClick={() => setSelectedIds(new Set())} style={{ marginLeft: 'auto', fontSize: 12, color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer' }}>Clear selection</button>
          </div>
        )}

        {/* Import section */}
        {showImport && (
          <div style={{ marginBottom: 16, padding: 16, border: '2px solid #f3f4f6', borderRadius: 13, background: '#f9fafb' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <label title="Choose CSV/VCF file" style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 14px', background: '#fff', color: '#1a3a2a', border: '2px solid #f3f4f6', borderRadius: 13, cursor: 'pointer', fontSize: 13, fontWeight: 500 }}>
                <UploadIcon /> Choose File
                <input ref={fileInputRef} type="file" accept=".csv,.vcf" onChange={handleFileSelect} style={{ display: 'none' }} />
              </label>
              <label onClick={downloadTemplate} title="Download template" style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 14px', background: '#fff', color: '#1a3a2a', border: '2px solid #f3f4f6', borderRadius: 13, cursor: 'pointer', fontSize: 13, fontWeight: 500 }}>
                <ExportIcon /> Template
              </label>
            </div>
            {previewData.length > 0 && (
              <div>
                <p style={{ fontSize: 13, color: '#374151', marginBottom: 8 }}>{previewData.length} contacts ready to import</p>
                <div style={{ maxHeight: 150, overflow: 'auto', border: '2px solid #f3f4f6', borderRadius: 13, marginBottom: 8 }}>
                  <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                    <thead><tr>{['Name','Phone','Email'].map(h => <th key={h} style={{ padding: '6px 8px', background: '#f9fafb', textAlign: 'left', borderBottom: '2px solid #f3f4f6', position: 'sticky', top: 0 }}>{h}</th>)}</tr></thead>
                    <tbody>{previewData.slice(0, 10).map((r, i) => <tr key={i}><td style={{ padding: '4px 8px', borderBottom: '1px solid #f3f4f6' }}>{r.name}</td><td style={{ padding: '4px 8px', borderBottom: '1px solid #f3f4f6' }}>{r.phone}</td><td style={{ padding: '4px 8px', borderBottom: '1px solid #f3f4f6' }}>{r.email}</td></tr>)}</tbody>
                  </table>
                </div>
                {previewData.length > 10 && (
                  <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>…and {previewData.length - 10} more</p>
                )}
                <button onClick={handleImport} disabled={importing} style={{ padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 13, fontWeight: 600, cursor: 'pointer', opacity: importing ? 0.6 : 1 }}>
                  {importing ? 'Importing...' : `Import ${previewData.length} contacts`}
                </button>
              </div>
            )}
            {importResult && (
              <p style={{ fontSize: 13, color: '#1a3a2a', marginTop: 8 }}>
                Done: {importResult.created} created, {importResult.updated} updated, {importResult.failed} failed{importResult.errors.length > 0 ? `, ${importResult.errors.length} errors` : ''}
              </p>
            )}
          </div>
        )}

        {/* Main content area with table + detail panel */}
        <div style={{ display: 'flex', gap: 0 }}>
          {/* Desktop Table View */}
          {!isMobile && (
          <div className="contacts-table-wrapper" style={{ flex: 1, minWidth: 0, border: '2px solid #f3f4f6', borderRadius: 13, overflow: 'hidden', background: '#fff' }}>
            {loading ? <div style={{ padding: 24 }}><SkeletonTable rows={8} /></div> : loadError ? (
              <div style={{ padding: 48, textAlign: 'center' }}>
                {/*
                  Was "Contacts Lambda returned 500" / "needs to be redeployed to AWS.
                  Check CloudWatch logs." Neither action is available to the person
                  reading it, and an error that prescribes something you cannot do
                  reads as a dead end. Say what happened, say nothing was lost, and
                  give the one action that is actually in reach.
                */}
                <p style={{ fontSize: 15, color: '#dc2626', marginBottom: 4 }}>Couldn’t load contacts</p>
                <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>The server returned an error, so nothing is shown here. No contact was changed or deleted. Try again — if it keeps happening, note the time and report it.</p>
                <button onClick={() => loadContacts()} style={{ padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Retry</button>
              </div>
            ) : filteredSorted.length === 0 ? (
              <div style={{ padding: 48, textAlign: 'center' }}>
                {searchQuery ? (
                  <div>
                    <p style={{ fontSize: 15, color: '#6b7280' }}>No results for &quot;{searchQuery}&quot;</p>
                    <button onClick={() => setSearchQuery('')} style={{ marginTop: 8, fontSize: 13, color: '#1a3a2a', background: 'none', border: 'none', cursor: 'pointer' }}>Clear search</button>
                  </div>
                ) : (
                  <div>
                    <p style={{ marginBottom: 8 }}><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></p>
                    <p style={{ fontSize: 15, color: '#6b7280' }}>No contacts yet</p>
                    <p style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>Press <kbd style={{ padding: '2px 6px', background: '#f3f4f6', borderRadius: 4, fontSize: 11 }}>N</kbd> to add one</p>
                    {/* Was rendered TWICE, identically, and named the DynamoDB table
                        to whoever opened an empty contact list. The connection status
                        is the useful half - it tells the user whether "no contacts"
                        means "none yet" or "could not reach the backend". The table
                        name told them nothing they could act on. */}
                    <p style={{ fontSize: 11, color: '#d97706', marginTop: 8 }}>API: {api.getConnectionStatus().status}</p>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ maxHeight: 'calc(100vh - 240px)', overflow: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                  <thead>
                    <tr>
                      <th style={{ width: 40, padding: '12px 10px', background: '#f9fafb', borderBottom: '2px solid #f3f4f6', position: 'sticky', top: 0, zIndex: 2 }}>
                        <input type="checkbox" checked={allPageSelected} onChange={toggleSelectAll} style={{ accentColor: '#1a3a2a', width: 16, height: 16 }} />
                      </th>
                      <SortHeader label="Name" sKey="name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                      <SortHeader label="Phone" sKey="phone" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                      <SortHeader label="Email" sKey="email" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                      {colVisible('shipping') && <th style={{ padding: '12px 14px', textAlign: 'left', fontSize: 14, fontWeight: 600, color: '#374151', background: '#f9fafb', borderBottom: '2px solid #f3f4f6', position: 'sticky', top: 0, zIndex: 2 }}>Delivery Address</th>}
                      {colVisible('checkoutAddress') && <th style={{ padding: '12px 14px', textAlign: 'left', fontSize: 14, fontWeight: 600, color: '#374151', background: '#f9fafb', borderBottom: '2px solid #f3f4f6', position: 'sticky', top: 0, zIndex: 2 }}>Checkout Address</th>}
                      {colVisible('updated') && <SortHeader label="Updated" sKey="updatedAt" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />}
                      {colVisible('tags') && <th style={{ padding: '12px 14px', textAlign: 'left', fontSize: 14, fontWeight: 600, color: '#374151', background: '#f9fafb', borderBottom: '2px solid #f3f4f6', position: 'sticky', top: 0, zIndex: 2 }}>Tags</th>}
                      <th style={{ width: 100, padding: '12px 10px', background: '#f9fafb', borderBottom: '2px solid #f3f4f6', position: 'sticky', top: 0, zIndex: 2 }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedContacts.map((c, rowIndex) => (
                      <tr key={c.contactId} onClick={() => setDetailContact(c)} style={{ cursor: 'pointer', transition: 'background 0.15s' }} onMouseEnter={e => (e.currentTarget.style.background = '#f9fafb')} onMouseLeave={e => (e.currentTarget.style.background = '')}>
                        <td style={{ padding: '10px', borderBottom: '1px solid #f3f4f6', textAlign: 'center' }} onClick={e => e.stopPropagation()}>
                          <input type="checkbox" checked={selectedIds.has(c.contactId)} onChange={() => toggleSelect(c.contactId)} style={{ accentColor: '#1a3a2a', width: 16, height: 16 }} />
                        </td>
                        {/* Name — inline editable (double-click) — Fix #18: cursor hint */}
                        <td style={{ padding: '10px 14px', borderBottom: '1px solid #f3f4f6', fontWeight: 500, fontSize: 14, cursor: 'text' }} title="Double-click to edit" onDoubleClick={e => { e.stopPropagation(); setInlineEdit({ id: c.contactId, field: 'name', value: c.name }); }}>
                          {inlineEdit?.id === c.contactId && inlineEdit.field === 'name' ? (
                            <input autoFocus value={inlineEdit.value} onChange={e => setInlineEdit({ ...inlineEdit, value: e.target.value })} onBlur={commitInlineEdit} onKeyDown={e => { if (e.key === 'Enter') commitInlineEdit(); if (e.key === 'Escape') { inlineEditCancelled.current = true; setInlineEdit(null); } }} onClick={e => e.stopPropagation()} style={{ width: '100%', padding: '6px 10px', border: '2px solid #1a3a2a', borderRadius: 8, fontSize: 14, outline: 'none' }} />
                          ) : (c.name || <span style={{ color: '#9ca3af', fontStyle: 'italic' }}>unnamed</span>)}
                        </td>
                        {/* Phone — inline editable (double-click) — Fix #8 */}
                        <td style={{ padding: '10px 14px', borderBottom: '1px solid #f3f4f6', fontSize: 14, cursor: 'text' }} title="Double-click to edit" onDoubleClick={e => { e.stopPropagation(); setInlineEdit({ id: c.contactId, field: 'phone', value: c.phone || '' }); }}>
                          {inlineEdit?.id === c.contactId && inlineEdit.field === 'phone' ? (
                            <input autoFocus value={inlineEdit.value} onChange={e => setInlineEdit({ ...inlineEdit, value: e.target.value })} onBlur={commitInlineEdit} onKeyDown={e => { if (e.key === 'Enter') commitInlineEdit(); if (e.key === 'Escape') { inlineEditCancelled.current = true; setInlineEdit(null); } }} onClick={e => e.stopPropagation()} style={{ width: '100%', padding: '6px 10px', border: '2px solid #1a3a2a', borderRadius: 8, fontSize: 14, outline: 'none' }} />
                          ) : (c.phone || '—')}
                        </td>
                        {/* Email — inline editable (double-click) — Fix #18: cursor hint */}
                        <td style={{ padding: '10px 14px', borderBottom: '1px solid #f3f4f6', fontSize: 14, cursor: 'text' }} title="Double-click to edit" onDoubleClick={e => { e.stopPropagation(); setInlineEdit({ id: c.contactId, field: 'email', value: c.email || '' }); }}>
                          {inlineEdit?.id === c.contactId && inlineEdit.field === 'email' ? (
                            <input autoFocus value={inlineEdit.value} onChange={e => setInlineEdit({ ...inlineEdit, value: e.target.value })} onBlur={commitInlineEdit} onKeyDown={e => { if (e.key === 'Enter') commitInlineEdit(); if (e.key === 'Escape') { inlineEditCancelled.current = true; setInlineEdit(null); } }} onClick={e => e.stopPropagation()} style={{ width: '100%', padding: '6px 10px', border: '2px solid #1a3a2a', borderRadius: 8, fontSize: 14, outline: 'none' }} />
                          ) : (c.email || '—')}
                        </td>
                        {colVisible('shipping') && <td style={{ padding: '10px 14px', borderBottom: '1px solid #f3f4f6', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 14 }}>{c.shippingAddress || '—'}</td>}
                        {colVisible('checkoutAddress') && <td title={formatCheckoutAddress(c.checkoutDeliveryAddress)} style={{ padding: '10px 14px', borderBottom: '1px solid #f3f4f6', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 14 }}>{formatCheckoutAddress(c.checkoutDeliveryAddress) || '—'}</td>}
                        {colVisible('updated') && <td style={{ padding: '10px 14px', borderBottom: '1px solid #f3f4f6', color: '#6b7280', fontSize: 13 }} title={c.updatedAt ? (() => { const n = Number(c.updatedAt); const d = new Date(!isNaN(n) && n < 1e12 ? n * 1000 : (!isNaN(n) ? n : c.updatedAt)); return isNaN(d.getTime()) ? '' : d.toLocaleString(); })() : ''}>{timeAgo(c.updatedAt)}</td>}
                        {colVisible('tags') && (
                          <td style={{ padding: '10px 14px', borderBottom: '1px solid #f3f4f6' }} onClick={e => e.stopPropagation()}>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
                              {(contactTags[c.contactId] || []).map(tag => (
                                <span key={tag} style={{ display: 'inline-block', padding: '3px 10px', borderRadius: 10, fontSize: 12, fontWeight: 600, color: '#fff', background: TAG_COLORS[tag] || '#6b7280' }}>{tagLabel(tag)}</span>
                              ))}
                              {c.phoneVerifiedAt && <span style={{ display: 'inline-block', padding: '3px 10px', borderRadius: 10, fontSize: 12, fontWeight: 600, color: '#1a3a2a', background: '#d1f470', whiteSpace: 'nowrap' }}>✓ WhatsApp verified</span>}
                              {c.emailVerifiedAt && <span style={{ display: 'inline-block', padding: '3px 10px', borderRadius: 10, fontSize: 12, fontWeight: 600, color: '#1a3a2a', background: '#d1f470', whiteSpace: 'nowrap' }}>✓ Email verified</span>}
                              <div style={{ position: 'relative' }}>
                                <button 
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    if (showTagMenu === c.contactId) {
                                      setShowTagMenu(null);
                                    } else {
                                      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                                      const dropdownHeight = 200;
                                      const flipUp = rect.bottom + dropdownHeight > window.innerHeight;
                                      setTagMenuPos({
                                        top: flipUp ? rect.top : rect.bottom + 4,
                                        left: rect.left,
                                        flipUp
                                      });
                                      setShowTagMenu(c.contactId);
                                    }
                                  }} 
                                  title="Add tag"
                                  style={{ 
                                    width: 24, 
                                    height: 24, 
                                    borderRadius: '50%', 
                                    border: '2px solid #1a3a2a', 
                                    background: '#fff', 
                                    cursor: 'pointer', 
                                    display: 'flex', 
                                    alignItems: 'center', 
                                    justifyContent: 'center', 
                                    padding: 0, 
                                    flexShrink: 0,
                                    position: 'relative'
                                  } as React.CSSProperties}
                                >
                                  <span style={{ 
                                    position: 'absolute',
                                    fontSize: 18, 
                                    fontWeight: 300, 
                                    color: '#1a3a2a',
                                    lineHeight: 1,
                                    fontFamily: 'Arial, sans-serif',
                                    userSelect: 'none'
                                  }}>+</span>
                                </button>
                              </div>
                            </div>
                          </td>
                        )}
                        <td style={{ padding: '10px', borderBottom: '1px solid #f3f4f6', textAlign: 'center' }} onClick={e => e.stopPropagation()}>
                          <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
                            <button onClick={() => handleEdit(c)} title="Edit" style={{ padding: 6, background: 'none', border: 'none', cursor: 'pointer', borderRadius: 6 }}><EditIcon size={18} /></button>
                            <button onClick={() => handleArchive(c.contactId, c.name)} title="Archive" style={{ padding: 6, background: 'none', border: 'none', cursor: 'pointer', borderRadius: 6 }}><DeleteIcon size={18} /></button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          )}

          {/* Mobile Card View */}
          {isMobile && (
          <div className="contacts-mobile-cards" style={{ padding: '0 16px' }}>
            {loading ? <div style={{ padding: 24 }}><SkeletonTable rows={5} /></div> : loadError ? (
              <div style={{ padding: 48, textAlign: 'center' }}>
                <p style={{ fontSize: 15, color: '#6b7280', marginBottom: 8 }}>Failed to load contacts</p>
                <button onClick={() => loadContacts()} style={{ padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Retry</button>
              </div>
            ) : filteredSorted.length === 0 ? (
              <div style={{ padding: 48, textAlign: 'center' }}>
                {searchQuery ? (
                  <div>
                    <p style={{ fontSize: 15, color: '#6b7280' }}>No results for &quot;{searchQuery}&quot;</p>
                    <button onClick={() => setSearchQuery('')} style={{ marginTop: 8, fontSize: 13, color: '#1a3a2a', background: 'none', border: 'none', cursor: 'pointer' }}>Clear search</button>
                  </div>
                ) : (
                  <div>
                    <p style={{ marginBottom: 8 }}><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></p>
                    <p style={{ fontSize: 15, color: '#6b7280' }}>No contacts yet</p>
                    <p style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>Tap + to add one</p>
                  </div>
                )}
              </div>
            ) : (
              <div>
                {paginatedContacts.map(c => (
                  <div key={c.contactId} className="contact-card" onClick={() => setDetailContact(c)}>
                    <div className="contact-card-header">
                      <div onClick={e => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', marginRight: 8 }}>
                        <input type="checkbox" checked={selectedIds.has(c.contactId)} onChange={() => toggleSelect(c.contactId)} style={{ accentColor: '#1a3a2a', width: 18, height: 18 }} />
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="contact-card-name">{c.name || 'Unnamed'}</div>
                        <div className="contact-card-phone">{c.phone}</div>
                        {c.email && <div className="contact-card-email">{c.email}</div>}
                      </div>
                      <div className="contact-card-actions" onClick={e => e.stopPropagation()}>
                        <button onClick={() => handleEdit(c)} title="Edit" style={{ padding: 8, background: 'none', border: 'none', cursor: 'pointer' }}><EditIcon size={20} /></button>
                        <button onClick={() => handleArchive(c.contactId, c.name)} title="Archive" style={{ padding: 8, background: 'none', border: 'none', cursor: 'pointer' }}><DeleteIcon size={20} /></button>
                      </div>
                    </div>
                    {((contactTags[c.contactId] || []).length > 0 || c.phoneVerifiedAt || c.emailVerifiedAt) && (
                      <div className="contact-card-tags" aria-label="Contact badges">
                        {(contactTags[c.contactId] || []).map(tag => (
                          <span key={tag} style={{ flex: '0 0 auto', padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, color: '#fff', background: TAG_COLORS[tag] || '#6b7280', whiteSpace: 'nowrap' }}>{tagLabel(tag)}</span>
                        ))}
                        {c.phoneVerifiedAt && <span style={{ flex: '0 0 auto', padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, color: '#1a3a2a', background: '#d1f470', whiteSpace: 'nowrap' }}>✓ WhatsApp verified</span>}
                        {c.emailVerifiedAt && <span style={{ flex: '0 0 auto', padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, color: '#1a3a2a', background: '#d1f470', whiteSpace: 'nowrap' }}>✓ Email verified</span>}
                      </div>
                    )}
                    <div className="contact-card-meta">
                      Updated {timeAgo(c.updatedAt)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          )}

          {/* Detail side panel */}
          {detailContact && (
            <div style={{ width: 340, flexShrink: 0, borderLeft: '2px solid #f3f4f6', background: '#fff', overflow: 'auto', marginLeft: -2, borderRadius: '0 13px 13px 0', maxHeight: 'calc(100vh - 200px)' }}>
              <div style={{ padding: '16px 20px', background: '#f9fafb', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '2px solid #f3f4f6' }}>
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: '#374151' }}>Contact Details</h3>
                <button onClick={() => setDetailContact(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}><CloseIcon /></button>
              </div>
              <div style={{ padding: 20 }}>
                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <div style={{ width: 56, height: 56, borderRadius: '50%', background: '#f9fafb', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 8px', fontSize: 24, color: '#1a3a2a', fontWeight: 700 }}>
                    {(detailContact.name || '?')[0]?.toUpperCase()}
                  </div>
                  <p style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>{detailContact.name || 'Unnamed'}</p>
                  <p style={{ fontSize: 13, color: '#6b7280', margin: '4px 0 0' }}>{detailContact.phone}</p>
                </div>
                {[
                  { label: 'Subscriber ID', value: (detailContact.tags || []).find((t: string) => t.startsWith('sub:'))?.replace('sub:', '') || '—' },
                  { label: 'Email', value: detailContact.email },
                  { label: 'Organization', value: detailContact.companyName },
                  { label: 'Job Title', value: detailContact.designation },
                  { label: 'Username', value: detailContact.username },
                  { label: 'Delivery Address', value: detailContact.shippingAddress },
                  // Shown as its OWN row, next to the curated one rather than instead of it.
                  // Checkout writes `checkoutDeliveryAddress`; this panel used to read only
                  // `shippingAddress`, so an address a customer typed at checkout appeared
                  // nowhere in the CRM. Two separate rows keep "what the customer gave for this
                  // order" distinguishable from "what we curated".
                  { label: 'Checkout Delivery Address', value: formatCheckoutAddressDetail(detailContact) },
                  { label: 'Created', value: detailContact.createdAt ? (() => { const ts = Number(detailContact.createdAt); const d = new Date(!isNaN(ts) && ts < 1e12 ? ts * 1000 : (!isNaN(ts) ? ts : detailContact.createdAt)); return isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }); })() : '—' },
                  { label: 'Updated', value: timeAgo(detailContact.updatedAt) },
                  { label: 'Last Message', value: timeAgo(detailContact.lastInboundMessageAt) },
                ].map(item => (
                  <div key={item.label} style={{ marginBottom: 12 }}>
                    <p style={{ fontSize: 11, color: '#9ca3af', margin: '0 0 2px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{item.label}</p>
                    <p style={{ fontSize: 13, color: '#374151', margin: 0, wordBreak: 'break-word' }}>{item.value || '—'}</p>
                  </div>
                ))}
                {/* Tags in detail */}
                <div style={{ marginBottom: 12 }}>
                  <p style={{ fontSize: 11, color: '#9ca3af', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Tags</p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {(contactTags[detailContact.contactId] || []).map(tag => (
                      <span key={tag} style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, color: '#fff', background: TAG_COLORS[tag] || '#6b7280' }}>{tagLabel(tag)}</span>
                    ))}
                    {(contactTags[detailContact.contactId] || []).length === 0 && <span style={{ fontSize: 12, color: '#9ca3af' }}>No tags</span>}
                  </div>
                </div>
                {/* Verification status — server timestamps, not browser claims. */}
                {(detailContact.phoneVerifiedAt || detailContact.emailVerifiedAt || detailContact.blogSubscribedAt) && (
                  <div style={{ marginBottom: 12 }}>
                    <p style={{ fontSize: 11, color: '#9ca3af', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Verification</p>
                    <div style={{ display: 'flex', gap: 6, overflowX: 'auto', flexWrap: 'nowrap', paddingBottom: 4 }}>
                      {detailContact.phoneVerifiedAt && <span style={{ flex: '0 0 auto', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, color: '#1a3a2a', background: '#d1f470', whiteSpace: 'nowrap' }}>✓ WhatsApp verified</span>}
                      {detailContact.emailVerifiedAt && <span style={{ flex: '0 0 auto', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, color: '#1a3a2a', background: '#d1f470', whiteSpace: 'nowrap' }}>✓ Email verified</span>}
                      {detailContact.blogSubscribedAt && <span style={{ flex: '0 0 auto', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, color: '#fff', background: '#1a3a2a', whiteSpace: 'nowrap' }}>Blog Subscriber</span>}
                    </div>
                  </div>
                )}
                {/* Opt-in status */}
                <div style={{ marginBottom: 12 }}>
                  <p style={{ fontSize: 11, color: '#9ca3af', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Opt-in Status</p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {[
                      { label: 'WA', on: detailContact.optInWhatsApp },
                      { label: 'SMS', on: detailContact.optInSms },
                      { label: 'Email', on: detailContact.optInEmail },
                    ].map(ch => (
                      <span key={ch.label} style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 500, background: ch.on ? '#f9fafb' : '#f3f4f6', color: ch.on ? '#1a3a2a' : '#9ca3af' }}>
                        {ch.on ? '✓' : '✗'} {ch.label}
                      </span>
                    ))}
                  </div>
                </div>
                {/* Fix #15: Allowlist status */}
                <div style={{ marginBottom: 12 }}>
                  <p style={{ fontSize: 11, color: '#9ca3af', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Allowlist Status</p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {[
                      { label: 'WA', on: detailContact.allowlistWhatsApp },
                      { label: 'SMS', on: detailContact.allowlistSms },
                      { label: 'Email', on: detailContact.allowlistEmail },
                    ].map(ch => (
                      <span key={`al-${ch.label}`} style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 500, background: ch.on ? '#f9fafb' : '#f3f4f6', color: ch.on ? '#1a3a2a' : '#9ca3af' }}>
                        {ch.on ? '✓' : '✗'} {ch.label}
                      </span>
                    ))}
                  </div>
                </div>
                {/* Actions */}
                <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                  <button onClick={() => { handleEdit(detailContact); setDetailContact(null); }} style={{ flex: 1, padding: '8px 12px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Edit</button>
                  <button onClick={() => { const c = detailContact; setDetailContact(null); handleArchive(c.contactId, c.name); }} style={{ flex: 1, padding: '8px 12px', background: '#fff', color: '#1a3a2a', border: '2px solid #1a3a2a', borderRadius: 13, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Archive</button>
                </div>

                {/* Activity Timeline */}
                <ContactActivityTimeline phone={detailContact.phone} contactId={detailContact.contactId} createdAt={detailContact.createdAt} />
              </div>
            </div>
          )}
        </div>

        {/* Pagination */}
        {totalPages >= 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8, marginTop: 16 }}>
            <button onClick={() => setCurrentPage(1)} disabled={safeCurrentPage <= 1} title="First page" style={{ padding: '6px 10px', border: '2px solid #f3f4f6', borderRadius: 13, background: '#fff', cursor: safeCurrentPage <= 1 ? 'default' : 'pointer', opacity: safeCurrentPage <= 1 ? 0.4 : 1, fontSize: 13 }}>«</button>
            <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={safeCurrentPage <= 1} style={{ padding: '6px 12px', border: '2px solid #f3f4f6', borderRadius: 13, background: '#fff', cursor: safeCurrentPage <= 1 ? 'default' : 'pointer', opacity: safeCurrentPage <= 1 ? 0.4 : 1, fontSize: 13 }}>‹</button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).filter(p => p === 1 || p === totalPages || Math.abs(p - safeCurrentPage) <= 1).map((p, idx, arr) => (
              <React.Fragment key={p}>
                {idx > 0 && arr[idx - 1] !== p - 1 && <span style={{ color: '#9ca3af' }}>…</span>}
                <button onClick={() => setCurrentPage(p)} style={{ padding: '6px 10px', border: '2px solid #f3f4f6', borderRadius: 13, background: p === safeCurrentPage ? '#1a3a2a' : '#fff', color: p === safeCurrentPage ? '#fff' : '#374151', fontWeight: p === safeCurrentPage ? 600 : 400, cursor: 'pointer', fontSize: 13 }}>{p}</button>
              </React.Fragment>
            ))}
            <button onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))} disabled={safeCurrentPage >= totalPages} style={{ padding: '6px 12px', border: '2px solid #f3f4f6', borderRadius: 13, background: '#fff', cursor: safeCurrentPage >= totalPages ? 'default' : 'pointer', opacity: safeCurrentPage >= totalPages ? 0.4 : 1, fontSize: 13 }}>›</button>
            <button onClick={() => setCurrentPage(totalPages)} disabled={safeCurrentPage >= totalPages} title="Last page" style={{ padding: '6px 10px', border: '2px solid #f3f4f6', borderRadius: 13, background: '#fff', cursor: safeCurrentPage >= totalPages ? 'default' : 'pointer', opacity: safeCurrentPage >= totalPages ? 0.4 : 1, fontSize: 13 }}>»</button>
          </div>
        )}
      </div>

      {/* Add Contact Modal — Fix #10: accessibility */}
      {showModal && (
        <div role="dialog" aria-modal="true" aria-label="Add Contact" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setShowModal(false)}>
          <div style={{ background: '#fff', borderRadius: 14, width: 560, maxHeight: '85vh', overflow: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.15)' }} onClick={e => e.stopPropagation()}>
            <div style={{ padding: '20px 24px', background: '#f9fafb', borderRadius: '14px 14px 0 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '2px solid #f3f4f6' }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#374151' }}>Add Contact</h2>
              <button onClick={() => setShowModal(false)} aria-label="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}><CloseIcon /></button>
            </div>
            {renderContactForm(false)}
            <div style={{ padding: '16px 24px', borderTop: '2px solid #f3f4f6', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => setShowModal(false)} style={{ padding: '8px 16px', background: '#fff', border: '2px solid #f3f4f6', borderRadius: 13, fontSize: 13, cursor: 'pointer', color: '#374151' }}>Cancel</button>
              <button onClick={handleCreate} disabled={saving} style={{ padding: '8px 20px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 13, fontWeight: 600, cursor: 'pointer', opacity: saving ? 0.6 : 1 }}>{saving ? 'Saving...' : 'Create'}</button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Contact Modal — Fix #10: accessibility */}
      {showEditModal && editingContact && (
        <div role="dialog" aria-modal="true" aria-label="Edit Contact" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => { setShowEditModal(false); setEditingContact(null); }}>
          <div style={{ background: '#fff', borderRadius: 14, width: 560, maxHeight: '85vh', overflow: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.15)' }} onClick={e => e.stopPropagation()}>
            <div style={{ padding: '20px 24px', background: '#f9fafb', borderRadius: '14px 14px 0 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '2px solid #f3f4f6' }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#374151' }}>Edit Contact</h2>
              <button onClick={() => { setShowEditModal(false); setEditingContact(null); }} aria-label="Close" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}><CloseIcon /></button>
            </div>
            {renderContactForm(true)}
            <div style={{ padding: '16px 24px', borderTop: '2px solid #f3f4f6', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => { setShowEditModal(false); setEditingContact(null); }} style={{ padding: '8px 16px', background: '#fff', border: '2px solid #f3f4f6', borderRadius: 13, fontSize: 13, cursor: 'pointer', color: '#374151' }}>Cancel</button>
              <button onClick={handleUpdate} disabled={saving} style={{ padding: '8px 20px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 13, fontSize: 13, fontWeight: 600, cursor: 'pointer', opacity: saving ? 0.6 : 1 }}>{saving ? 'Saving...' : 'Update'}</button>
            </div>
          </div>
        </div>
      )}


      {/* Click outside to close menus */}
      {(showColMenu || showTagMenu) && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 49 }} onClick={() => { setShowColMenu(false); setShowTagMenu(null); }} />
      )}

      {/* Fixed-position tag dropdown (rendered outside overflow container) */}
      {showTagMenu && (
        <div 
          style={{ 
            position: 'fixed',
            top: tagMenuPos.flipUp ? 'auto' : tagMenuPos.top,
            bottom: tagMenuPos.flipUp ? (window.innerHeight - tagMenuPos.top + 4) : 'auto',
            left: tagMenuPos.left,
            background: '#fff', 
            border: '2px solid #f3f4f6', 
            borderRadius: 13, 
            padding: 6, 
            zIndex: 1001, 
            minWidth: 130, 
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)' 
          }}
          onClick={e => e.stopPropagation()}
        >
          {TAG_OPTIONS.map(tag => {
            const active = (contactTags[showTagMenu] || []).includes(tag);
            return (
              <button key={tag} onClick={() => toggleTag(showTagMenu, tag)} style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', padding: '6px 10px', border: 'none', background: active ? '#f9fafb' : 'transparent', borderRadius: 8, fontSize: 13, cursor: 'pointer', textAlign: 'left' }}>
                <span style={{ width: 12, height: 12, borderRadius: '50%', background: TAG_COLORS[tag] }}></span>
                {tag}
                {active && <span style={{ marginLeft: 'auto', color: '#1a3a2a', fontWeight: 600 }}>✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </Layout>
  );
};

export default Contacts;
