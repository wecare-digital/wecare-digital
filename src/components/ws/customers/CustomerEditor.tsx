/**
 * A staff-side editor for the canonical F001 Subscribe profile.
 * Profile -> Address -> Review mirrors the customer Flow while reusing the existing Contacts API.
 * Creating a record does not verify WhatsApp ownership or grant marketing consent.
 */
import React from 'react';
import type { Contact, ContactMutation } from '../../../api/client';
import * as api from '../../../api/client';
import { DIAL_CODES } from '../../../lib/dialCodes';
import { contactPhoneE164, contactPhoneMatchKey } from '../../../lib/contactPhone';
import {
  ADDRESS_FIELDS, EMPTY_ADDRESS_FIELDS, addressComplete, addressFieldsFromContact,
  addressPayload, formatAddress, type AddressFormFields,
} from '../../../lib/address-format';
import { COUNTRY_OPTIONS, countryCodeForName } from '../../../config/countryOptions';
import styles from './CustomerEditor.module.css';

interface Props {
  contact?: Contact | null;
  contacts: Contact[];
  onClose: () => void;
  onSaved: (contact: Contact, warning?: string) => void | Promise<void>;
  onExisting: (contact: Contact) => void;
}

const STAGES = ['Profile', 'Address', 'Review'] as const;

function splitPhone(value: string): { dial: string; national: string } {
  const clean = String(value || '').trim();
  const match = [...DIAL_CODES].sort((a, b) => b.code.length - a.code.length)
    .find(option => clean.startsWith(option.code));
  // India is the explicitly visible initial choice for a new contact, not an inferred dial
  // prefix for arbitrary numbers. Unknown +E.164 values remain intact in the input.
  return match
    ? { dial: match.code, national: clean.slice(match.code.length) }
    : { dial: '+91', national: clean };
}

function hasAddressContent(address: AddressFormFields): boolean {
  return ADDRESS_FIELDS.some(field => field.key !== 'country' && Boolean(address[field.key].trim()));
}

const CustomerEditor: React.FC<Props> = ({ contact, contacts, onClose, onSaved, onExisting }) => {
  const editing = Boolean(contact);
  const existingPhone = splitPhone(contact?.phone || '');
  const originalAddress = React.useMemo(
    () => contact ? addressFieldsFromContact(contact) : { ...EMPTY_ADDRESS_FIELDS },
    [contact],
  );
  const [stage, setStage] = React.useState(0);
  const [name, setName] = React.useState(contact?.name || '');
  const [dial, setDial] = React.useState(existingPhone.dial);
  const [phone, setPhone] = React.useState(existingPhone.national);
  const [username, setUsername] = React.useState(contact?.profileUsername || '');
  const [organization, setOrganization] = React.useState(contact?.companyName || '');
  const [jobTitle, setJobTitle] = React.useState(contact?.designation || '');
  const [address, setAddress] = React.useState<AddressFormFields>(originalAddress);
  const [error, setError] = React.useState('');
  const [duplicate, setDuplicate] = React.useState<Contact | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [pendingIdentityContactId, setPendingIdentityContactId] = React.useState('');
  const requestInFlight = React.useRef(false);
  const firstField = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => { firstField.current?.focus(); }, []);
  React.useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !requestInFlight.current) onClose();
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  const fullPhone = editing
    ? (contact?.phone || '')
    : contactPhoneE164(phone, dial);
  const addressChanged = JSON.stringify(address) !== JSON.stringify(originalAddress);

  const showError = (message: string) => {
    setError(message);
    setDuplicate(null);
  };
  const changeAddress = (key: keyof AddressFormFields, value: string) => {
    setAddress(previous => ({ ...previous, [key]: value }));
    setError('');
  };

  const validateProfile = () => {
    if (!name.trim()) { showError('Enter the customer’s full name.'); return false; }
    if (name.trim().length > 200) { showError('Full name must be 200 characters or less.'); return false; }
    if (username.trim().length > 50) { showError('WhatsApp username must be 50 characters or less.'); return false; }
    if (!/^\+[1-9]\d{6,14}$/.test(fullPhone)) {
      showError('Enter a valid phone number with its country calling code.');
      return false;
    }
    const matching = contacts.find(other =>
      other.contactId !== contact?.contactId &&
      contactPhoneMatchKey(other.phone) === contactPhoneMatchKey(fullPhone));
    if (matching) {
      setDuplicate(matching);
      setError('This number already has a customer record. Open it instead of creating a duplicate.');
      return false;
    }
    return true;
  };

  const validateAddress = () => {
    // Historical contacts may not have an address: editing only their name must remain possible.
    if (editing && !addressChanged) return true;
    if (editing && !hasAddressContent(address)) {
      showError('Keep the existing address or enter a replacement. Address removal needs separate review.');
      return false;
    }
    const missing = ADDRESS_FIELDS.find(field => field.required && !address[field.key].trim());
    if (missing || !addressComplete(address)) {
      showError('Enter ' + (missing ? missing.label.toLowerCase() : 'a valid country') + '.');
      return false;
    }
    return true;
  };

  const save = async () => {
    if (requestInFlight.current) return;
    if (!validateProfile()) { setStage(0); return; }
    if (!validateAddress()) { setStage(1); return; }
    requestInFlight.current = true;
    setSaving(true);
    setError('');
    setDuplicate(null);

    const payload: ContactMutation = {
      name: name.trim(),
      // An unchanged phone is still a trust-changing write on the Contacts backend.
      // Never overwrite provider-verified provenance from a staff profile edit.
      ...(!editing ? { phone: fullPhone } : {}),
      profileUsername: username.trim(),
      companyName: organization.trim(),
      designation: jobTitle.trim(),
    };
    if (!editing || addressChanged) {
      const normalized = addressPayload(address);
      if (normalized) {
        payload.address = normalized as NonNullable<Contact['address']>;
        const formatted = formatAddress(address);
        payload.shippingAddress = formatted;
        payload.billingAddress = formatted;
        payload.addressLine1 = address.addressLine1.trim();
        payload.addressLine2 = address.addressLine2.trim();
        payload.landmark = address.locality.trim();
        payload.city = address.city.trim();
        payload.state = address.state.trim();
        payload.postalCode = address.postalCode.trim();
        payload.country = address.country.trim();
      }
    }

    try {
      if (pendingIdentityContactId === 'unknown') {
        const directory = await api.listContactsResult();
        const matches = directory.ok ? directory.data.filter(item =>
          contactPhoneMatchKey(item.phone) === contactPhoneMatchKey(fullPhone)) : [];
        if (matches.length === 1) {
          setPendingIdentityContactId(matches[0].contactId || matches[0].id);
          setError('The saved customer was found. Complete account setup for this record.');
        } else {
          setError('The earlier create outcome is still unconfirmed. Check the directory before creating another customer.');
        }
        return;
      }
      const result = pendingIdentityContactId
        ? await api.provisionContactIdentityResult(pendingIdentityContactId)
        : contact
        ? await api.updateContactResult(contact.contactId, payload)
        : await api.createContactResult(payload);
      if (result.ok) {
        // A 2xx without a returned canonical customer must NOT trigger a success toast;
        // the write may have happened and retrying would risk a duplicate.
        if (result.data) {
          let saved = result.data;
          if (saved.phone && !saved.checkoutCustomerId) {
            const identity = await api.provisionContactIdentityResult(saved.contactId || saved.id);
            if (!identity.ok || !identity.data?.checkoutCustomerId) {
              setPendingIdentityContactId(saved.contactId || saved.id);
              setStage(2);
              setError('Customer saved, but account setup is incomplete. Complete setup for this record.');
              return;
            }
            saved = identity.data;
          }
          let warning = '';
          const desiredUsername = username.trim();
          // The live Contacts create runtime may predate the F001 profileUsername mapping.
          // On a successful create only, use the existing field-only update path as a safe
          // compatibility bridge. Never resend the phone or any consent/verification field.
          if (!editing && desiredUsername && saved.profileUsername !== desiredUsername) {
            const createdId = saved.contactId || saved.id;
            if (createdId) {
              try {
                const usernamePatch = await api.updateContactResult(createdId, { profileUsername: desiredUsername });
                if (usernamePatch.ok && usernamePatch.data) saved = usernamePatch.data;
                else warning = 'Contact was created, but its profile username could not be confirmed. Edit the contact to retry.';
              } catch {
                warning = 'Contact was created, but its profile username update failed. Edit the contact to retry.';
              }
            } else {
              warning = 'Contact was created without a returned customer ID. Refresh the directory before editing the profile username.';
            }
          }
          await onSaved(saved, warning);
        } else {
          setError('The server accepted the request but returned no customer record. Refresh the directory before retrying.');
        }
        return;
      }
      if (!editing && ['timeout', 'network', 'unavailable'].includes(result.failure.kind)
          && result.failure.details?.contactCreated !== true) {
        setPendingIdentityContactId(pendingIdentityContactId || 'unknown');
        setStage(2);
        setError('The create outcome is unconfirmed. Check the saved customer before another create; completing setup will not create a duplicate.');
        return;
      }
      if (result.failure.details?.contactCreated === true
          && typeof result.failure.details.contactId === 'string') {
        setPendingIdentityContactId(result.failure.details.contactId);
        setError(typeof result.failure.details.error === 'string' ? result.failure.details.error : 'Customer saved. Complete account setup for this record before using payments.');
        setStage(2);
        return;
      }
      // Success was already handled above; retain the server's structured refusal.
      if (result.failure.status === 409) {
          const reconciliation = result.failure.code === 'CONTACT_IDENTITY_RECONCILIATION_REQUIRED'
            || result.failure.details?.reconciliationRequired === true;
          if (reconciliation) {
            setError('This WhatsApp identity is reserved without an accessible customer record. Ask an administrator to reconcile it.');
          } else {
            const id = result.failure.details?.existingContactId;
            const existing = typeof id === 'string' ? await api.getContact(id) : null;
            const local = contacts.find(item => contactPhoneMatchKey(item.phone) === contactPhoneMatchKey(fullPhone));
            setDuplicate(existing || local || null);
            setError('This WhatsApp number already belongs to a customer. Open that record instead.');
          }
          setStage(0);
      } else {
        setError(result.failure.message || 'The customer record could not be saved.');
      }
    } catch {
      setError('The request failed. Check the connection and try again; do not create a second record until you have checked the directory.');
    } finally {
      requestInFlight.current = false;
      setSaving(false);
    }
  };

  const next = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setDuplicate(null);
    if (stage === 0) {
      if (validateProfile()) setStage(1);
    } else if (stage === 1) {
      if (validateAddress()) setStage(2);
    } else {
      void save();
    }
  };

  return (
    <div className={styles.overlay} role="presentation" onClick={event => {
      if (event.target === event.currentTarget && !saving) onClose();
    }}>
      <section className={styles.panel} role="dialog" aria-modal="true" aria-labelledby="cde-title">
        <header className={styles.header}>
          <div>
            <p className={styles.eyebrow}>WECARE.DIGITAL / Customers</p>
            <h2 id="cde-title">{editing ? 'Edit customer' : 'Create contact'}</h2>
            <p className={styles.subline}>
              {editing ? 'Update the existing customer profile.' : 'Save a new contact to the canonical customer directory.'}
            </p>
          </div>
          <button type="button" className={styles.close} onClick={onClose} disabled={saving} aria-label="Close customer editor">
            <span aria-hidden="true">×</span>
          </button>
        </header>

        <nav className={styles.progress} aria-label="Form progress">
          {STAGES.map((label, index) => (
            <span key={label} className={index === stage ? styles.current : index < stage ? styles.complete : styles.future}
              aria-current={index === stage ? 'step' : undefined}>
              <span className={styles.stepNumber}>{index + 1}</span>{label}
            </span>
          ))}
        </nav>

        <form onSubmit={next} noValidate className={styles.form}>
          <div className={styles.body} data-wc-no-translate="true">
            {stage === 0 && (
              <>
                <h3 className={styles.sectionTitle}>Customer profile</h3>
                <p className={styles.hint}>The phone identifies a contact; adding it here does not verify WhatsApp ownership or grant message consent.</p>
                <label className={styles.field}>
                  <span>Full name <b aria-hidden="true">*</b></span>
                  <input ref={firstField} value={name} onChange={e => { setName(e.target.value); setError(''); }}
                    maxLength={200} autoComplete="name" placeholder="Full name" required />
                </label>
                <div className={styles.field}>
                  <label htmlFor="cde-phone">WhatsApp phone number <b aria-hidden="true">*</b></label>
                  <div className={styles.phoneRow}>
                    <select aria-label="Country dial code" value={dial} disabled={editing} onChange={e => { setDial(e.target.value); setError(''); }}>
                      {DIAL_CODES.map(entry => <option key={entry.code} value={entry.code}>{entry.country} ({entry.code})</option>)}
                    </select>
                    <input id="cde-phone" value={phone} type="tel" inputMode="tel" autoComplete="tel-national"
                      readOnly={editing} aria-readonly={editing} onChange={e => { setPhone(e.target.value); setError(''); }}
                      placeholder="Mobile number" required />
                  </div>
                  {editing
                    ? <small>Linked phone numbers are protected; use identity reconciliation to change them.</small>
                    : <small>India (+91) is selected initially. Choose the correct country code, or enter a full +international number.</small>}
                </div>
                <label className={styles.field}>
                  <span>WhatsApp username <em>Optional</em></span>
                  <input value={username} onChange={e => { setUsername(e.target.value); setError(''); }}
                    maxLength={50} placeholder="Profile username" />
                  <small>Customer profile name, not Meta’s provider-owned username.</small>
                </label>
                <div className={styles.twoColumns}>
                  <label className={styles.field}>
                    <span>Organization <em>Optional</em></span>
                    <input value={organization} onChange={e => { setOrganization(e.target.value); setError(''); }}
                      maxLength={200} placeholder="Company or organization" />
                  </label>
                  <label className={styles.field}>
                    <span>Job title <em>Optional</em></span>
                    <input value={jobTitle} onChange={e => { setJobTitle(e.target.value); setError(''); }}
                      maxLength={200} placeholder="Designation" />
                  </label>
                </div>
              </>
            )}

            {stage === 1 && (
              <>
                <h3 className={styles.sectionTitle}>Customer address</h3>
                <p className={styles.hint}>
                  Same structured address fields as F001 Subscribe and checkout.
                  {editing ? ' Historical customers without an address may keep it empty when unchanged.' : ' Required fields are marked with *.'}
                </p>
                <div className={styles.twoColumns}>
                  {ADDRESS_FIELDS.map(field => (
                    <label key={field.key} className={styles.field}>
                      <span>{field.label} {field.required && <b aria-hidden="true">*</b>}</span>
                      {field.key === 'country' ? (
                        <select value={address.country} onChange={e => {
                          setAddress(previous => ({ ...previous, country: e.target.value, countryCode: countryCodeForName(e.target.value) }));
                          setError('');
                        }}>
                          {COUNTRY_OPTIONS.map(option => <option key={option.code} value={option.name}>{option.name}</option>)}
                        </select>
                      ) : (
                        <input value={address[field.key]} maxLength={field.maxLength}
                          onChange={e => changeAddress(field.key, e.target.value)}
                          placeholder={field.placeholder} required={field.required && !editing} />
                      )}
                    </label>
                  ))}
                </div>
                {hasAddressContent(address) && <div className={styles.preview}>
                  <strong>Address preview</strong><p>{formatAddress(address)}</p>
                </div>}
              </>
            )}

            {stage === 2 && (
              <>
                <h3 className={styles.sectionTitle}>Review before saving</h3>
                <p className={styles.hint}>Check the customer identity and address. A customer ID is assigned by the server when a new contact is saved.</p>
                <div className={styles.reviewBlock}>
                  <h4>PROFILE</h4>
                  <dl>
                    <dt>Full name</dt><dd>{name.trim()}</dd>
                    <dt>WhatsApp phone</dt><dd>{fullPhone}</dd>
                    {username.trim() && <><dt>Profile username</dt><dd>{username.trim()}</dd></>}
                    {organization.trim() && <><dt>Organization</dt><dd>{organization.trim()}</dd></>}
                    {jobTitle.trim() && <><dt>Job title</dt><dd>{jobTitle.trim()}</dd></>}
                  </dl>
                </div>
                <div className={styles.reviewBlock}>
                  <h4>ADDRESS</h4>
                  <p>{formatAddress(address) || 'No address on file'}</p>
                </div>
                <p className={styles.notice}>This staff action does not send a WhatsApp message, mark the number as verified, or opt the customer into marketing.</p>
              </>
            )}

            {error && <div className={styles.error} role="alert">{error}</div>}
            {duplicate && (
              <button type="button" className={styles.existing} onClick={() => onExisting(duplicate)}>
                View existing customer: {duplicate.name || duplicate.phone}
              </button>
            )}
          </div>

          <footer className={styles.footer}>
            {stage > 0 ? (
              <button type="button" className={styles.secondary} onClick={() => { setStage(stage - 1); setError(''); }} disabled={saving || !!pendingIdentityContactId}>Back</button>
            ) : (
              <button type="button" className={styles.secondary} onClick={onClose} disabled={saving}>Cancel</button>
            )}
            <button type="submit" className={styles.primary} disabled={saving}>
              {saving ? 'Saving…' : pendingIdentityContactId ? 'Complete customer setup' : stage === 2 ? (editing ? 'Save changes' : 'Create contact') : 'Continue'}
              {!saving && <span aria-hidden="true">→</span>}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
};

export default CustomerEditor;
