import React, { useMemo, useState } from 'react';
import type { Contact } from '../../../api/client';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';

type ReviewContact = Pick<Contact,
  'contactId' | 'customerUuid' | 'name' | 'phone' | 'email' |
  'checkoutDeliveryAddress' | 'shippingAddress' | 'addressLine1' | 'locked' | 'lockedReason'>;

export interface DuplicateGroup {
  key: string;
  kind: 'phone' | 'email';
  value: string;
  contacts: ReviewContact[];
}

export interface CustomerDataReview {
  duplicates: DuplicateGroup[];
  missingCustomerId: ReviewContact[];
  missingPhone: ReviewContact[];
  invalidPhone: ReviewContact[];
  missingAddress: ReviewContact[];
}

/**
 * The three ways a reviewed merge can be classified, PREVIEW-FIRST.
 *
 *   safe                        exact shared identity, neither record is financially locked —
 *                               the merge can proceed on confirmation.
 *   needs-review                the records disagree on a routing identity (a different phone or
 *                               email), so a human must choose which survives; the backend will
 *                               refuse an ambiguous merge and this mirrors that up front.
 *   blocked-by-financial-history a record is locked for legal/financial retention; it must not be
 *                               folded away. The merge is not offered.
 */
export type MergeClassification = 'safe' | 'needs-review' | 'blocked-by-financial-history';

export interface MergePreview {
  classification: MergeClassification;
  /** The record that becomes the single canonical customer. */
  canonical: ReviewContact;
  /** The record that is retained as an alias and whose history keeps pointing at the canonical. */
  alias: ReviewContact;
  reason: string;
  /** Everything a merge preserves — shown so staff can see nothing is deleted. */
  preserved: string[];
}

const PRESERVED: string[] = [
  'Messages', 'Orders', 'Payments', 'Invoices', 'Consent history', 'Addresses',
  'Service requests', 'Flow submissions', 'Notes', 'Provenance', 'Activity',
];

function normalizedPhone ( value?: string ): string {
  const raw = String( value || '' ).trim();
  if ( !raw ) return '';
  const digits = raw.replace( /\D/g, '' );
  return digits ? `+${digits}` : '';
}

function normalizedEmail ( value?: string ): string {
  return String( value || '' ).trim().toLowerCase();
}

/**
 * Classify a two-record merge BEFORE anything is written. Pure and unit-tested.
 *
 * The canonical record is the one that already carries the most identity: a record with a
 * Customer ID is preferred as canonical over one without, matching the backend's
 * "merge into the identity-rich row" rule. A financial lock on either record blocks the merge
 * entirely; a routing-identity disagreement routes it to human review.
 */
export function classifyMerge ( a: ReviewContact, b: ReviewContact ): MergePreview {
  // Prefer the record with a Customer ID (then with a phone) as canonical.
  const score = ( c: ReviewContact ) =>
    ( String( c.customerUuid || '' ).trim() ? 2 : 0 ) + ( String( c.phone || '' ).trim() ? 1 : 0 );
  const [ canonical, alias ] = score( a ) >= score( b ) ? [ a, b ] : [ b, a ];

  if ( canonical.locked || alias.locked ) {
    return {
      classification: 'blocked-by-financial-history', canonical, alias,
      reason: 'One record is locked for legal or financial retention and must not be merged away. '
        + 'Keep both records; resolve the lock first.',
      preserved: PRESERVED,
    };
  }

  const phoneA = normalizedPhone( canonical.phone );
  const phoneB = normalizedPhone( alias.phone );
  const emailA = normalizedEmail( canonical.email );
  const emailB = normalizedEmail( alias.email );
  const phoneConflict = !!phoneA && !!phoneB && phoneA !== phoneB;
  const emailConflict = !!emailA && !!emailB && emailA !== emailB;
  if ( phoneConflict || emailConflict ) {
    return {
      classification: 'needs-review', canonical, alias,
      reason: 'The records disagree on a routing identity (phone or email). A person must choose '
        + 'which identity survives before these can be merged.',
      preserved: PRESERVED,
    };
  }

  return {
    classification: 'safe', canonical, alias,
    reason: 'Exact shared identity and no financial lock. The alias is retained and every '
      + 'historic reference keeps pointing at the canonical customer.',
    preserved: PRESERVED,
  };
}

function normalizedPhoneExport ( value?: string ): string { return normalizedPhone( value ); }
function normalizedEmailExport ( value?: string ): string { return normalizedEmail( value ); }
export { normalizedPhoneExport, normalizedEmailExport };

export function buildCustomerDataReview ( contacts: ReviewContact[] ): CustomerDataReview {
  const phones = new Map<string, ReviewContact[]>();
  const emails = new Map<string, ReviewContact[]>();

  for ( const contact of contacts ) {
    const phone = normalizedPhone( contact.phone );
    const email = normalizedEmail( contact.email );
    if ( phone ) phones.set( phone, [ ...( phones.get( phone ) || [] ), contact ] );
    if ( email ) emails.set( email, [ ...( emails.get( email ) || [] ), contact ] );
  }

  const duplicates: DuplicateGroup[] = [];
  for ( const [ value, group ] of phones ) {
    if ( group.length > 1 ) duplicates.push( { key: `phone:${value}`, kind: 'phone', value, contacts: group } );
  }
  for ( const [ value, group ] of emails ) {
    if ( group.length > 1 ) duplicates.push( { key: `email:${value}`, kind: 'email', value, contacts: group } );
  }

  return {
    duplicates,
    missingCustomerId: contacts.filter( contact => !String( contact.customerUuid || '' ).trim() ),
    missingPhone: contacts.filter( contact => !String( contact.phone || '' ).trim() ),
    invalidPhone: contacts.filter( contact => {
      const raw = String( contact.phone || '' ).trim();
      return !!raw && !/^\+[1-9]\d{7,14}$/.test( raw );
    } ),
    missingAddress: contacts.filter( contact =>
      !contact.checkoutDeliveryAddress
      && !String( contact.shippingAddress || '' ).trim()
      && !String( contact.addressLine1 || '' ).trim()
    ),
  };
}

interface Props {
  contacts: Contact[];
  onClose: () => void;
  onOpenCustomer: ( contactId: string ) => void;
  // Fired after a reviewed merge or an archive so the parent can reload the active customer set.
  onChanged?: () => void | Promise<void>;
}

const CLASS_LABEL: Record<MergeClassification, string> = {
  'safe': 'Safe to merge',
  'needs-review': 'Needs review',
  'blocked-by-financial-history': 'Blocked — financial history',
};
// The classification label text carries the state; colour is reinforcement only. Mapped to the
// semantic design tokens with the prior hex kept as a fallback so rendering is unchanged.
const CLASS_COLOR: Record<MergeClassification, string> = {
  'safe': 'var(--success, #15803d)',
  'needs-review': 'var(--warning, #b45309)',
  'blocked-by-financial-history': 'var(--danger, #b91c1c)',
};

const CustomerManageData: React.FC<Props> = ( { contacts, onClose, onOpenCustomer, onChanged } ) => {
  const review = useMemo( () => buildCustomerDataReview( contacts ), [ contacts ] );
  const toast = useToastContext();
  const confirm = useConfirm();
  const [ preview, setPreview ] = useState<MergePreview | null>( null );
  const [ merging, setMerging ] = useState( false );
  const [ busy, setBusy ] = useState<string | null>( null );

  const issueCount = review.duplicates.length + review.missingCustomerId.length
    + review.missingPhone.length + review.invalidPhone.length + review.missingAddress.length;

  const rows = [
    { label: 'Potential duplicate groups', count: review.duplicates.length, detail: 'Exact normalized phone or email only' },
    { label: 'Missing Customer ID', count: review.missingCustomerId.length, detail: 'Canonical public customer identifier is absent' },
    { label: 'Missing phone', count: review.missingPhone.length, detail: 'No primary phone/WhatsApp routing identity' },
    { label: 'Invalid phone shape', count: review.invalidPhone.length, detail: 'Not stored as canonical +E.164' },
    { label: 'Missing delivery address', count: review.missingAddress.length, detail: 'No checkout or curated delivery address' },
  ];

  const open = ( contact: ReviewContact ) => onOpenCustomer( contact.contactId );

  const startPreview = ( group: DuplicateGroup ) => {
    // Review the first two records of a group. A larger group is resolved pairwise, never a
    // blind bulk delete-N.
    if ( group.contacts.length < 2 ) return;
    setPreview( classifyMerge( group.contacts[ 0 ], group.contacts[ 1 ] ) );
  };

  const runMerge = async () => {
    if ( !preview || preview.classification !== 'safe' ) return;
    const ok = await confirm( {
      title: 'Merge these customers?',
      message: `“${preview.alias.name || preview.alias.contactId}” will be retained as an alias of `
        + `“${preview.canonical.name || preview.canonical.contactId}”. All messages, orders, payments, `
        + `invoices, consent history, addresses, service requests, Flow submissions, notes, provenance `
        + `and activity are preserved. This cannot be undone from here.`,
      confirmText: 'Merge customers',
      danger: true,
    } );
    if ( !ok ) return;
    setMerging( true );
    try {
      const result = await api.mergeContacts(
        preview.alias.contactId, preview.canonical.contactId,
        'Operator-reviewed merge from Manage data' );
      if ( result.ok && result.data?.merged ) {
        toast.success( 'Customers merged; all history preserved on the canonical record.' );
        setPreview( null );
        await onChanged?.();
      } else {
        toast.error( result.ok ? 'Merge was not applied' : ( result.failure.message || 'Merge failed' ) );
      }
    } catch ( err: unknown ) {
      toast.error( err instanceof Error ? err.message : 'Merge failed' );
    } finally {
      setMerging( false );
    }
  };

  // Archive hides a customer from daily queues without deleting identity, orders, invoices,
  // payments, consent or history. It is additive to the preview-first merge path and never a
  // destructive delete.
  const archive = async ( contact: ReviewContact ) => {
    const ok = await confirm( {
      title: 'Archive customer',
      message: `Archive "${contact.name || contact.contactId}" from daily customer queues? Identity, orders, invoices, payments, consent and history remain intact.`,
      confirmText: 'Archive',
    } );
    if ( !ok ) return;
    setBusy( `archive:${contact.contactId}` );
    const result = await api.archiveContact(
      contact.contactId,
      'Archived from Customers → Manage data after operator review',
    );
    setBusy( null );
    if ( result.ok ) {
      toast.success( 'Customer archived without deleting history' );
      await onChanged?.();
    } else {
      toast.error( result.failure.message || 'Archive refused' );
    }
  };

  return (
    <div className="md-backdrop" role="dialog" aria-modal="true" aria-labelledby="manage-data-title" onClick={ onClose }>
      <section className="md-panel" onClick={ event => event.stopPropagation() }>
        <header className="md-head">
          <div>
            <p className="eyebrow">Customers</p>
            <h2 id="manage-data-title">Manage data</h2>
            <p>Review identity and data-quality exceptions, then merge a duplicate group through a preview-first, reviewed merge. Duplicate groups use exact normalized phone/email only; display names never trigger a merge, and nothing is ever bulk-deleted.</p>
          </div>
          <button type="button" className="close" onClick={ onClose } aria-label="Close Manage data">×</button>
        </header>

        <div className="summary" aria-label="Data quality summary">
          <strong>{ issueCount }</strong>
          <span>review items across { contacts.length } active customers</span>
        </div>

        <div className="issue-grid">
          { rows.map( row => (
            <article key={ row.label } className="issue-card">
              <strong>{ row.count }</strong>
              <h3>{ row.label }</h3>
              <p>{ row.detail }</p>
            </article>
          ) ) }
        </div>

        <section className="review-section" aria-labelledby="duplicate-title">
          <div className="section-head">
            <div>
              <h3 id="duplicate-title">Potential duplicates</h3>
              <p>Select a group to preview a reviewed merge. The merge preserves every record (messages, orders, payments, invoices, consent, addresses, service requests, Flow submissions, notes, provenance, activity) and retains the alias; it never deletes. Archive hides a customer from daily queues without deleting identity or financial history.</p>
            </div>
          </div>
          { review.duplicates.length === 0 ? (
            <p className="empty">No exact phone/email duplicate groups in the loaded active customer set.</p>
          ) : review.duplicates.map( group => (
            <article key={ group.key } className="duplicate">
              <div className="duplicate-head">
                <span>{ group.kind === 'phone' ? 'Phone' : 'Email' }</span>
                <strong>{ group.value }</strong>
                <small>{ group.contacts.length } records</small>
                { group.contacts.length >= 2 && (
                  <button type="button" className="preview-btn" onClick={ () => startPreview( group ) }>Preview merge</button>
                ) }
              </div>
              <div className="customer-list">
                { group.contacts.map( ( contact ) => (
                  // Merging a duplicate group is preview-first (classified safe / needs-review /
                  // blocked) via "Preview merge" above; it is never a per-row one-click merge.
                  // Archive is the only per-row action and hides without deleting history.
                  <div className="customer-action-row" key={ contact.contactId }>
                    <button type="button" className="customer-open" onClick={ () => open( contact ) }>
                      <span><strong>{ contact.name || 'Unnamed customer' }</strong><small>{ contact.contactId }</small></span>
                      <span aria-hidden="true">›</span>
                    </button>
                    <div className="row-actions">
                      <button type="button" className="action"
                        disabled={ busy === `archive:${contact.contactId}` }
                        onClick={ () => void archive( contact ) }>
                        { busy === `archive:${contact.contactId}` ? 'Archiving…' : 'Archive' }
                      </button>
                    </div>
                  </div>
                ) ) }
              </div>
            </article>
          ) ) }
        </section>

        { preview && (
          <section className="review-section" aria-labelledby="merge-preview-title">
            <h3 id="merge-preview-title">Merge preview</h3>
            <div className="merge-preview">
              <span className="class-pill" style={ { color: CLASS_COLOR[ preview.classification ], borderColor: CLASS_COLOR[ preview.classification ] } }>
                { CLASS_LABEL[ preview.classification ] }
              </span>
              <p className="merge-reason">{ preview.reason }</p>
              <dl className="merge-records">
                <div><dt>Canonical (kept)</dt><dd>{ preview.canonical.name || 'Unnamed' } · <small>{ preview.canonical.contactId }</small></dd></div>
                <div><dt>Alias (retained)</dt><dd>{ preview.alias.name || 'Unnamed' } · <small>{ preview.alias.contactId }</small></dd></div>
              </dl>
              <div className="preserved">
                <strong>Preserved on merge</strong>
                <ul>{ preview.preserved.map( item => <li key={ item }>{ item }</li> ) }</ul>
              </div>
              <div className="merge-actions">
                <button type="button" className="ghost" onClick={ () => setPreview( null ) } disabled={ merging }>Cancel</button>
                <button type="button" className="primary" onClick={ runMerge }
                  disabled={ merging || preview.classification !== 'safe' }>
                  { merging ? 'Merging…' : preview.classification === 'safe' ? 'Review & merge' : 'Cannot merge' }
                </button>
              </div>
            </div>
          </section>
        ) }

        <section className="review-section" aria-labelledby="exceptions-title">
          <h3 id="exceptions-title">Exceptions</h3>
          { [
            [ 'Missing Customer ID', review.missingCustomerId ],
            [ 'Missing phone', review.missingPhone ],
            [ 'Invalid phone', review.invalidPhone ],
            [ 'Missing delivery address', review.missingAddress ],
          ].map( ( [ label, items ] ) => {
            const typed = items as ReviewContact[];
            if ( typed.length === 0 ) return null;
            return (
              <div className="exception" key={ label as string }>
                <strong>{ label as string } · { typed.length }</strong>
                <div className="customer-list">
                  { typed.slice( 0, 50 ).map( contact => (
                    <button type="button" key={ `${label}-${contact.contactId}` } onClick={ () => open( contact ) }>
                      <span><strong>{ contact.name || 'Unnamed customer' }</strong><small>{ contact.phone || contact.email || contact.contactId }</small></span>
                      <span aria-hidden="true">›</span>
                    </button>
                  ) ) }
                </div>
                { typed.length > 50 && <small className="more">Showing first 50 of { typed.length }.</small> }
              </div>
            );
          } ) }
          { review.missingCustomerId.length + review.missingPhone.length + review.invalidPhone.length + review.missingAddress.length === 0
            && <p className="empty">No customer data exceptions in the loaded active set.</p> }
        </section>
      </section>

      <style jsx>{`
        .md-backdrop{position:fixed;inset:0;z-index:1300;background:rgba(0,0,0,.42);display:flex;justify-content:flex-end}
        .md-panel{width:min(760px,100%);height:100dvh;overflow:auto;background:#fff;padding:clamp(18px,3vw,28px);box-sizing:border-box;box-shadow:-14px 0 44px rgba(0,0,0,.14)}
        .md-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
        .eyebrow{margin:0 0 4px;color:var(--text-muted);font-size:var(--text-xs);font-weight:750;text-transform:uppercase;letter-spacing:.08em}
        h2{margin:0;color:var(--text);font-size:clamp(28px,5vw,40px);letter-spacing:-.035em}
        .md-head p:last-child{max-width:650px;margin:8px 0 0;color:var(--text-muted);font-size:var(--text-sm);line-height:1.5}
        .close{min-width:44px;min-height:44px;border:1px solid var(--border);border-radius:12px;background:#fff;color:var(--text);font-size:26px;cursor:pointer}
        .summary{margin:22px 0 14px;padding:16px;border:1px solid var(--border);border-radius:14px;display:flex;align-items:baseline;gap:9px}
        .summary strong{font-size:28px}.summary span{color:var(--text-muted);font-size:var(--text-sm)}
        .issue-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
        .issue-card{border:1px solid var(--border);border-radius:14px;padding:14px;min-width:0}
        .issue-card>strong{font-size:24px}.issue-card h3{margin:3px 0;font-size:var(--text-sm)}.issue-card p{margin:0;color:var(--text-muted);font-size:var(--text-xs);line-height:1.4}
        .review-section{margin-top:26px}.section-head{display:flex;justify-content:space-between;gap:12px}.review-section h3{margin:0 0 4px;font-size:var(--text-lg)}.review-section p{color:var(--text-muted);font-size:var(--text-sm)}
        .duplicate,.exception{margin-top:10px;border:1px solid var(--border);border-radius:14px;overflow:hidden}
        .duplicate-head{padding:12px 14px;background:var(--bg-secondary);display:flex;gap:8px;align-items:center;flex-wrap:wrap}.duplicate-head span,.duplicate-head small{font-size:var(--text-xs);color:var(--text-muted)}.duplicate-head small{margin-inline-start:auto}
        .preview-btn{min-height:44px;border:1px solid var(--accent);border-radius:10px;background:#fff;color:var(--accent);font-size:var(--text-xs);font-weight:700;padding:8px 12px;cursor:pointer}
        .preview-btn:hover,.preview-btn:focus-visible{background:var(--bg-secondary)}
        .customer-list{display:flex;flex-direction:column}.customer-list>button,.customer-open{border:0;border-top:1px solid var(--border-light);background:#fff;min-height:58px;padding:9px 14px;display:flex;align-items:center;justify-content:space-between;gap:12px;text-align:start;cursor:pointer;color:var(--text)}.customer-list>button:first-child{border-top:0}.customer-list>button:hover,.customer-list>button:focus-visible,.customer-open:hover,.customer-open:focus-visible{background:var(--bg-secondary)}.customer-list>button:focus-visible,.customer-open:focus-visible,.action:focus-visible,.close:focus-visible,.preview-btn:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}.customer-list button span:first-child{display:flex;flex-direction:column;min-width:0}.customer-list small{color:var(--text-muted);font-size:var(--text-xs);overflow-wrap:anywhere}.customer-action-row{display:grid;grid-template-columns:minmax(0,1fr) auto;border-top:1px solid var(--border-light);align-items:stretch}.customer-action-row:first-child{border-top:0}.customer-action-row .customer-open{border-top:0;width:100%}.row-actions{display:flex;align-items:center;gap:6px;padding:8px}.action{min-height:44px;padding:7px 10px;border:1px solid var(--border);border-radius:10px;background:#fff;color:var(--text);font:inherit;font-size:var(--text-xs);font-weight:700;cursor:pointer}.action:disabled{opacity:.55;cursor:default}
        .merge-preview{margin-top:10px;border:1px solid var(--border);border-radius:14px;padding:16px}
        .class-pill{display:inline-block;border:1.5px solid;border-radius:9999px;padding:4px 12px;font-size:var(--text-xs);font-weight:800;text-transform:uppercase;letter-spacing:.05em}
        .merge-reason{margin:10px 0;color:var(--text);font-size:var(--text-sm);line-height:1.5}
        .merge-records{display:grid;gap:8px;margin:0 0 12px}.merge-records div{display:flex;flex-direction:column}.merge-records dt{font-size:var(--text-xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em}.merge-records dd{margin:2px 0 0;font-size:var(--text-sm)}
        .preserved strong{font-size:var(--text-xs);text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)}.preserved ul{margin:6px 0 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:6px}.preserved li{font-size:var(--text-xs);background:var(--bg-secondary);border:1px solid var(--border);border-radius:9999px;padding:3px 10px}
        .merge-actions{display:flex;gap:10px;margin-top:16px}.merge-actions button{min-height:44px;border-radius:10px;font-size:var(--text-sm);font-weight:700;padding:0 18px;cursor:pointer}.merge-actions .ghost{border:1px solid var(--border);background:#fff;color:var(--text)}.merge-actions .primary{border:1px solid var(--accent);background:var(--accent);color:#06240f}.merge-actions .primary:disabled{opacity:.5;cursor:not-allowed}
        .exception>strong{display:block;padding:11px 14px;background:var(--bg-secondary);font-size:var(--text-sm)}.more{display:block;padding:8px 14px;color:var(--text-muted)}.empty{padding:16px;border:1px dashed var(--border);border-radius:12px}
        @media(max-width:640px){.issue-grid{grid-template-columns:1fr 1fr}.md-panel{padding:16px}.summary{align-items:flex-start;flex-direction:column;gap:2px}}
        @media(max-width:390px){.issue-grid{grid-template-columns:1fr}}
        @media(forced-colors:active){.md-panel,.issue-card,.duplicate,.exception,.summary,.close,.merge-preview{border-color:CanvasText}}
      `}</style>
    </div>
  );
};

export default CustomerManageData;
