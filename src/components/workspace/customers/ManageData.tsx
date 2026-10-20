import React, { useMemo, useState } from 'react';
import * as api from '../../../api/client';
import type { Contact } from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';

type ReviewContact = Pick<Contact,
  'contactId' | 'customerUuid' | 'name' | 'phone' | 'email' |
  'checkoutDeliveryAddress' | 'shippingAddress' | 'addressLine1'>;

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

function normalizedPhone ( value?: string ): string {
  const raw = String( value || '' ).trim();
  if ( !raw ) return '';
  const digits = raw.replace( /\D/g, '' );
  return digits ? `+${digits}` : '';
}

function normalizedEmail ( value?: string ): string {
  return String( value || '' ).trim().toLowerCase();
}

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
  onChanged?: () => void | Promise<void>;
}

const CustomerManageData: React.FC<Props> = ( { contacts, onClose, onOpenCustomer, onChanged } ) => {
  const toast = useToastContext();
  const confirm = useConfirm();
  const [ busy, setBusy ] = useState<string | null>( null );
  const review = useMemo( () => buildCustomerDataReview( contacts ), [ contacts ] );
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

  const merge = async ( source: ReviewContact, target: ReviewContact ) => {
    const key = `merge:${source.contactId}:${target.contactId}`;
    const ok = await confirm( {
      title: 'Merge duplicate customers',
      message: `Merge "${source.name || source.contactId}" into "${target.name || target.contactId}"? The source becomes a retained alias and financial/history records are preserved. The server will refuse weak or conflicting identity evidence.`,
      confirmText: 'Merge',
    } );
    if ( !ok ) return;
    setBusy( key );
    const result = await api.mergeContacts(
      source.contactId,
      target.contactId,
      'Reviewed exact duplicate from Customers → Manage data',
    );
    setBusy( null );
    if ( result.ok ) {
      toast.success( 'Customers merged; source retained as an alias' );
      await onChanged?.();
    } else {
      toast.error( result.failure.message || 'Merge refused' );
    }
  };

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
            <p>Review identity and data-quality exceptions before taking action. Duplicate groups use exact normalized phone/email only; display names never trigger a merge.</p>
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
              <p>Reviewed actions only. Merge preserves the source as an alias; archive hides a customer from daily queues without deleting identity or financial history.</p>
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
              </div>
              <div className="customer-list">
                { group.contacts.map( ( contact, index ) => {
                  const target = group.contacts.find( ( candidate, candidateIndex ) =>
                    candidateIndex !== index
                    && ( !!candidate.phone || !!candidate.email )
                    && ( !!candidate.customerUuid || !contact.customerUuid )
                  ) || group.contacts.find( ( _, candidateIndex ) => candidateIndex !== index );
                  const mergeKey = target ? `merge:${contact.contactId}:${target.contactId}` : '';
                  return (
                    <div className="customer-action-row" key={ contact.contactId }>
                      <button type="button" className="customer-open" onClick={ () => open( contact ) }>
                        <span><strong>{ contact.name || 'Unnamed customer' }</strong><small>{ contact.contactId }</small></span>
                        <span aria-hidden="true">›</span>
                      </button>
                      <div className="row-actions">
                        { target && (
                          <button type="button" className="action merge"
                            disabled={ busy === mergeKey }
                            onClick={ () => void merge( contact, target ) }>
                            { busy === mergeKey ? 'Merging…' : 'Merge' }
                          </button>
                        ) }
                        <button type="button" className="action"
                          disabled={ busy === `archive:${contact.contactId}` }
                          onClick={ () => void archive( contact ) }>
                          { busy === `archive:${contact.contactId}` ? 'Archiving…' : 'Archive' }
                        </button>
                      </div>
                    </div>
                  );
                } ) }
              </div>
            </article>
          ) ) }
        </section>

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
        .customer-list{display:flex;flex-direction:column}.customer-list>button,.customer-open{border:0;border-top:1px solid var(--border-light);background:#fff;min-height:58px;padding:9px 14px;display:flex;align-items:center;justify-content:space-between;gap:12px;text-align:start;cursor:pointer;color:var(--text)}.customer-list>button:first-child{border-top:0}.customer-list>button:hover,.customer-list>button:focus-visible,.customer-open:hover,.customer-open:focus-visible{background:var(--bg-secondary)}.customer-list>button:focus-visible,.customer-open:focus-visible,.action:focus-visible,.close:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}.customer-list button span:first-child{display:flex;flex-direction:column;min-width:0}.customer-list small{color:var(--text-muted);font-size:var(--text-xs);overflow-wrap:anywhere}.customer-action-row{display:grid;grid-template-columns:minmax(0,1fr) auto;border-top:1px solid var(--border-light);align-items:stretch}.customer-action-row:first-child{border-top:0}.customer-action-row .customer-open{border-top:0;width:100%}.row-actions{display:flex;align-items:center;gap:6px;padding:8px}.action{min-height:40px;padding:7px 10px;border:1px solid var(--border);border-radius:10px;background:#fff;color:var(--text);font:inherit;font-size:var(--text-xs);font-weight:700;cursor:pointer}.action.merge{border-color:var(--accent);color:var(--accent)}.action:disabled{opacity:.55;cursor:default}
        .exception>strong{display:block;padding:11px 14px;background:var(--bg-secondary);font-size:var(--text-sm)}.more{display:block;padding:8px 14px;color:var(--text-muted)}.empty{padding:16px;border:1px dashed var(--border);border-radius:12px}
        @media(max-width:640px){.issue-grid{grid-template-columns:1fr 1fr}.md-panel{padding:16px}.summary{align-items:flex-start;flex-direction:column;gap:2px}}
        @media(max-width:390px){.issue-grid{grid-template-columns:1fr}}
        @media(forced-colors:active){.md-panel,.issue-card,.duplicate,.exception,.summary,.close{border-color:CanvasText}}
      `}</style>
    </div>
  );
};

export default CustomerManageData;
