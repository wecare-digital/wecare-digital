/**
 * CustomerActionsSheet — the per-customer action surface for /ws/customers (FEAT-003).
 *
 * A mobile-first bottom sheet (full-width card on desktop) that carries the confirm-gated,
 * server-reason-honouring actions for a single customer:
 *   - Delete a specific stored field (clears one field via api.updateContactResult)
 *   - Deleting messages and versioned media is disabled here until one complete,
 *     audited erasure workflow can report every dependency correctly.
 *   - Block / archive (api.archiveContact — hides from daily queues, keeps identity + history)
 *   - Permanent deletion is disabled until the audited cross-service erasure workflow exists.
 *     A legacy soft-delete would leave identity claims, media and dependent history behind.
 *
 * Every destructive action is useConfirm()-gated and styled with --danger. On an ApiResult !ok
 * the server's own failure.message / failure.code is shown via useToastContext and the parent is
 * NOT told the row was removed. On success the parent is notified so it can drop/refresh the row.
 *
 * React 19 removed the global JSX namespace, so icon helpers are typed React.JSX.Element.
 */
import React from 'react';
import { useRouter } from 'next/router';
import type { Contact } from '../../../api/client';
import * as api from '../../../api/client';
import { useToastContext } from '../../../contexts/ToastContext';
import { useConfirm } from '../../../contexts/ConfirmContext';

interface CustomerActionsSheetProps {
  contact: Contact;
  onClose: () => void;
  /** Called after an archive so the parent can drop the row from the active (daily-queue) list. */
  onArchived: ( contactId: string ) => void;
  /** Called after a field clear so the parent can re-read fresh server data. */
  onChanged: () => void | Promise<void>;
}

// A stored field a staffer may clear from the sheet. `key` is a Contact field cleared by writing
// an empty string through the one validated write path (api.updateContactResult).
const CLEARABLE_FIELDS: { key: keyof Contact; label: string }[] = [
  { key: 'email', label: 'Email' },
  { key: 'shippingAddress', label: 'Shipping address' },
  { key: 'billingAddress', label: 'Billing address' },
  { key: 'companyName', label: 'Company name' },
  { key: 'gstin', label: 'GSTIN' },
  { key: 'designation', label: 'Designation' },
];

const CloseGlyph = (): React.JSX.Element => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);

const CustomerActionsSheet: React.FC<CustomerActionsSheetProps> = ( {
  contact, onClose, onArchived, onChanged,
} ) => {
  const toast = useToastContext();
  const confirm = useConfirm();
  const router = useRouter();
  const [ busy, setBusy ] = React.useState( false );
  const [ showDeleteForm, setShowDeleteForm ] = React.useState( false );
  const [ caseId, setCaseId ] = React.useState( '' );
  const [ manifestSha256, setManifestSha256 ] = React.useState( '' );
  const [ approvalToken, setApprovalToken ] = React.useState( '' );
  const [ reviewStatus, setReviewStatus ] = React.useState( '' );

  const name = contact.name || contact.phone || 'this customer';
  const locked = contact.locked === true;

  // ---- Delete a specific stored field -------------------------------------------------------
  const clearField = async ( field: keyof Contact, label: string ) => {
    if ( busy ) return;
    const ok = await confirm( {
      title: 'Delete this field?',
      message: `Clear the ${label} on ${name}? The customer and all other fields are kept. This only removes the stored ${label.toLowerCase()}.`,
      confirmText: 'Delete field',
      danger: true,
    } );
    if ( !ok ) return;
    setBusy( true );
    try {
      // updateContactResult (not updateContact): the Result form preserves the server's refusal
      // reason so a refused clear is never rendered as a silent success.
      const result = await api.updateContactResult( contact.contactId, { [ field ]: '' } as Partial<Contact> );
      if ( result.ok ) {
        toast.success( `${label} cleared.` );
        await onChanged();
      } else {
        toast.error( `Could not clear ${label}: ${result.failure.message}` );
      }
    } catch {
      toast.error( `Could not clear ${label}. It was not changed.` );
    } finally {
      setBusy( false );
    }
  };

  // ---- Block / archive ----------------------------------------------------------------------
  const archive = async () => {
    if ( busy ) return;
    if ( locked ) {
      toast.warning( 'This customer is protected by a retention lock. An administrator must review it before blocking.' );
      return;
    }
    const ok = await confirm( {
      title: 'Block / archive customer?',
      message: `Block ${name}? They are hidden from your daily queues and lists. Their identity, messages and any payment/order history are kept, and an admin can restore them.`,
      confirmText: 'Block / archive',
    } );
    if ( !ok ) return;
    setBusy( true );
    try {
      const result = await api.archiveContact( contact.contactId, 'Blocked/archived from /ws customers after operator review' );
      if ( result.ok ) {
        toast.success( 'Customer blocked and hidden from daily queues; identity and history kept.' );
        onArchived( contact.contactId );
        onClose();
      } else {
        // Honour the server reason; the row is NOT reported hidden.
        toast.error( `Block refused: ${result.failure.message}` );
      }
    } catch {
      toast.error( 'Block request failed. The customer was not changed.' );
    } finally {
      setBusy( false );
    }
  };


  const openMessages = () => {
    onClose();
    void router.push( `/workspace/communications/?view=inbox&contactId=${encodeURIComponent( contact.contactId )}` );
  };

  const prepareDeletion = async () => {
    if ( busy ) return;
    setBusy( true );
    try {
      const result = await api.prepareContactErasure( contact.contactId );
      if ( result.ok && result.data.status === 'PENDING_SECOND_REVIEW' ) {
        setCaseId( result.data.caseId );
        setManifestSha256( result.data.manifestSha256 );
        setApprovalToken( '' );
        setReviewStatus( 'Another administrator must approve this case before deletion.' );
        toast.success( 'Eligible contact verified. Case prepared for a second reviewer.' );
      } else {
        setReviewStatus( 'Contact review did not pass. Nothing was deleted.' );
        toast.error( result.ok ? 'Case preparation was not confirmed.' : result.failure.message );
      }
    } catch {
      toast.error( 'Could not verify the contact and linked records.' );
    } finally {
      setBusy( false );
    }
  };

  const approveDeletion = async () => {
    if ( busy || !caseId.trim() ) return;
    setBusy( true );
    try {
      const result = await api.approveContactErasure( caseId.trim(), contact.contactId );
      if ( result.ok && result.data.status === 'APPROVED' && result.data.approvalToken ) {
        setManifestSha256( result.data.manifestSha256 );
        setApprovalToken( result.data.approvalToken );
        setReviewStatus( 'Second-reviewer approval confirmed. Deletion is now available for this exact contact.' );
        toast.success( 'Approved. The one-use token is held only in this open form.' );
      } else {
        toast.error( result.ok ? 'Approval was not verified.' : result.failure.message );
      }
    } catch {
      toast.error( 'Approval could not be verified.' );
    } finally {
      setBusy( false );
    }
  };

  const requestDeletion = async () => {
    if ( busy || !caseId || !approvalToken || !/^[a-f0-9]{64}$/.test( manifestSha256 ) ) return;
    const ok = await confirm( {
      title: 'Delete contact and release identity?',
      message: `Request deletion of ${name} and their phone/email identity claims so the contact can be added again? Only an approved, audited deletion may complete. Protected messages, payment records and unrelated customers remain untouched.`,
      confirmText: 'Request deletion',
      danger: true,
    } );
    if ( !ok ) return;
    setBusy( true );
    try {
      const result = await api.requestApprovedContactErasure( contact.contactId, {
        caseId, manifestSha256, approvalToken,
      } );
      if ( result.ok && result.data.erasureComplete
        && result.data.identityClaimsReleased === true && result.data.contactRecreatable === true ) {
        toast.success( 'Contact deleted and identity released for re-creation.' );
        onArchived( contact.contactId );
        onClose();
      } else if ( result.ok && result.data.status === 'PENDING' ) {
        toast.warning( 'Deletion accepted for review; the contact has not been deleted.' );
      } else {
        toast.error( result.ok ? 'Deletion was not verified; nothing is marked removed.'
          : result.failure.message );
      }
    } catch {
      toast.error( 'Deletion could not be verified. The customer remains in the list.' );
    } finally {
      setBusy( false );
    }
  };

  return (
    <div className="cas-backdrop" role="dialog" aria-modal="true" aria-labelledby="cas-title" onClick={ onClose }>
      <div className="cas-sheet" onClick={ e => e.stopPropagation() }>
        <header className="cas-head">
          <div className="cas-id" data-wc-no-translate="true">
            <h2 id="cas-title" className="cas-name">{ contact.name || 'Unnamed customer' }</h2>
            <p className="cas-phone">{ contact.phone || 'No phone' }{ contact.email ? ` · ${ contact.email }` : '' }</p>
          </div>
          <button type="button" className="cas-close" onClick={ onClose } aria-label="Close actions">
            <CloseGlyph />
          </button>
        </header>

        { locked && (
          <p className="cas-lock" role="note">
            { contact.lockedReason === 'created'
              ? 'Creation lock: blocking is unavailable. Contact deletion requires two independent Admin reviews and a complete dependency check.'
              : 'Protected by a retention lock. Blocking and deletion will be refused until a verified legal review.' }
          </p>
        ) }

        <div className="cas-group">
          <h3 className="cas-group-title">Delete a stored field</h3>
          <div className="cas-fields">
            { CLEARABLE_FIELDS.map( f => {
              const value = ( contact[ f.key ] as unknown as string ) || '';
              return (
                <button
                  key={ String( f.key ) }
                  type="button"
                  className="cas-field"
                  disabled={ busy || !value }
                  onClick={ () => clearField( f.key, f.label ) }
                >
                  <span className="cas-field-label">{ f.label }</span>
                  <span className="cas-field-value">{ value || '—' }</span>
                </button>
              );
            } ) }
          </div>
        </div>

        <div className="cas-group">
          <h3 className="cas-group-title">Danger</h3>
          <div className="cas-actions">
            <button type="button" className="cas-btn" disabled={ busy } onClick={ openMessages }>
              View and delete messages
            </button>
            <button type="button" className="cas-btn" disabled={ busy || locked } onClick={ archive }>
              Block / archive
            </button>
            <button type="button" className="cas-btn cas-danger" disabled={ busy }
              onClick={ () => setShowDeleteForm( value => !value ) }
              aria-expanded={ showDeleteForm }>
              Delete contact and release identity…
            </button>
            { showDeleteForm && (
              <div className="cas-deletion-form">
                <p className="cas-hint">Only an eligible contact with no linked conversations, payments or provider identity can be removed. Two different Admin accounts with MFA must review. Audit records remain retained.</p>
                <button type="button" className="cas-btn" disabled={ busy }
                  onClick={ () => void prepareDeletion() }>
                  1. Check eligibility and prepare case
                </button>
                <button type="button" className="cas-btn" disabled={ busy || !caseId.trim() }
                  onClick={ () => void approveDeletion() }>
                  2. Approve as a different administrator
                </button>
                { reviewStatus && <p role="status" className="cas-hint">{ reviewStatus }</p> }
                <label className="cas-deletion-field">Approved case ID
                  <input value={ caseId } onChange={ e => setCaseId( e.target.value ) }
                    placeholder="Case reference" autoComplete="off" />
                </label>
                <label className="cas-deletion-field">Reviewed manifest SHA-256
                  <input value={ manifestSha256 } readOnly
                    placeholder="Provided after approval" autoComplete="off" />
                </label>
                <label className="cas-deletion-field">Single-use approval token
                  <input value={ approvalToken } readOnly
                    type="password" placeholder="Provided after second review" autoComplete="off" />
                </label>
                <button type="button" className="cas-btn cas-danger"
                  disabled={ busy || !caseId.trim() || !/^[a-f0-9]{64}$/.test( manifestSha256 ) || approvalToken.length < 24 }
                  onClick={ () => void requestDeletion() }>
                  { busy ? 'Checking deletion…' : '3. Delete approved contact and release identity' }
                </button>
              </div>
            ) }
            <p className="cas-lock" role="note">
              Contact and identity deletion requires the backend to confirm protected-history and payment retention. A request is not a completed deletion.
            </p>
          </div>
        </div>
      </div>

      <style jsx>{ `
        .cas-backdrop{
          position:fixed; inset:0; z-index:1200;
          background:rgba(0,0,0,0.4);
          display:flex; align-items:flex-end; justify-content:center;
          padding:0;
        }
        .cas-sheet{
          width:100%; max-width:560px; box-sizing:border-box;
          background:var(--surface,#fff);
          border-radius:var(--radius-2xl,16px) var(--radius-2xl,16px) 0 0;
          padding:16px 16px calc(20px + env(safe-area-inset-bottom,0px));
          display:grid; gap:16px;
          max-height:88dvh; overflow-y:auto;
          -webkit-overflow-scrolling:touch;
        }
        .cas-head{ display:flex; align-items:flex-start; gap:12px; }
        .cas-id{ min-width:0; }
        .cas-name{ margin:0; font-size:18px; font-weight:700; color:var(--text,#1a1a1a); overflow-wrap:anywhere; }
        .cas-phone{ margin:2px 0 0; font-size:13px; color:var(--text-muted,#6b7280); overflow-wrap:anywhere; }
        .cas-close{
          flex:0 0 auto; margin-left:auto;
          width:var(--tap-min,44px); height:var(--tap-min,44px);
          display:inline-flex; align-items:center; justify-content:center;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-full,9999px);
          background:var(--surface,#fff); color:var(--text-muted,#6b7280); cursor:pointer;
        }
        .cas-close:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }

        .cas-lock{
          margin:0; padding:10px 12px; border-radius:var(--radius-md,8px);
          background:var(--danger-bg,#f5f5f5); color:var(--danger,#374151);
          font-size:12px; line-height:1.5;
        }

        .cas-group{ display:grid; gap:8px; }
        .cas-group-title{
          margin:0; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;
          color:var(--text-muted,#6b7280);
        }

        .cas-fields{ display:grid; gap:8px; }
        .cas-field{
          display:flex; align-items:center; justify-content:space-between; gap:12px;
          width:100%; min-height:var(--tap-min,44px); box-sizing:border-box;
          padding:10px 14px; text-align:left;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-lg,12px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a); font:inherit; cursor:pointer;
        }
        .cas-field:hover:not(:disabled){ border-color:var(--danger,#374151); color:var(--danger,#374151); }
        .cas-field:disabled{ opacity:0.5; cursor:not-allowed; }
        .cas-field:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }
        .cas-field-label{ flex:0 0 auto; font-weight:600; font-size:14px; }
        .cas-field-value{
          flex:1 1 auto; min-width:0; text-align:right;
          font-size:13px; color:var(--text-muted,#6b7280);
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }

        .cas-actions{ display:grid; gap:8px; }
        .cas-deletion-form{ display:grid; gap:10px; padding:12px; border:1px solid var(--border,#e5e7eb); border-radius:12px; }
        .cas-hint{ margin:0; color:var(--text-muted,#6b7280); font-size:12px; line-height:1.5; }
        .cas-deletion-field{ display:grid; gap:5px; font-size:12px; font-weight:600; }
        .cas-deletion-field input{ width:100%; box-sizing:border-box; min-height:40px; padding:8px 10px; border:1px solid var(--border,#e5e7eb); border-radius:8px; background:var(--surface,#fff); color:var(--text,#1a1a1a); }

        .cas-btn{
          width:100%; min-height:var(--tap-min,44px); box-sizing:border-box;
          padding:12px 16px;
          border:1px solid var(--border,#e5e7eb); border-radius:var(--radius-lg,12px);
          background:var(--surface,#fff); color:var(--text,#1a1a1a);
          font:inherit; font-weight:700; font-size:14px; cursor:pointer;
        }
        .cas-btn:hover:not(:disabled){ background:var(--bg-hover,#f5f5f5); }
        .cas-btn:disabled{ opacity:0.5; cursor:not-allowed; }
        .cas-btn:focus-visible{ outline:2px solid var(--accent,#1a3a2a); outline-offset:2px; }
        .cas-danger{
          border-color:var(--danger,#374151); color:var(--danger,#374151);
        }
        .cas-danger:hover:not(:disabled){ background:var(--danger-bg,#f5f5f5); }

        @media (min-width:768px){
          .cas-backdrop{ align-items:center; padding:20px; }
          .cas-sheet{ border-radius:var(--radius-2xl,16px); padding:20px; max-height:86vh; }
        }
      ` }</style>
    </div>
  );
};

export default CustomerActionsSheet;
