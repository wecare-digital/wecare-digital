/**
 * Contact Message Composer
 * Send WhatsApp contact card messages (vCard format).
 * Per WhatsApp Cloud API: POST /messages with type=contacts
 */
import React, { useState } from 'react';
import * as api from '../api/client';
import Select, { type SelectOption } from './ui/Select';

/* The three phone types, hoisted. Same order, same values, same visible text. */
const PHONE_TYPE_OPTIONS: SelectOption[] = [
  { value: 'CELL', label: 'Cell' },
  { value: 'WORK', label: 'Work' },
  { value: 'HOME', label: 'Home' },
];

/* LAYOUT ONLY - it sits in a flex row beside a flex-1 phone input. */
const PHONE_TYPE_SELECT_STYLE: React.CSSProperties = { flex: '0 0 110px' };

interface ContactMessageComposerProps {
  contactId: string;
  phoneNumberId: string;
  recipientBsuid?: string;
  onClose: () => void;
  onSent: () => void;
  onError: (msg: string) => void;
}

interface ContactCard {
  name: { formatted_name: string; first_name: string; last_name: string };
  phones: { phone: string; type: string }[];
  emails: { email: string; type: string }[];
  org?: { company: string; title: string };
}

const ContactMessageComposer: React.FC<ContactMessageComposerProps> = ({
  contactId, phoneNumberId, recipientBsuid, onClose, onSent, onError,
}) => {
  const [sending, setSending] = useState(false);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [phone, setPhone] = useState('');
  const [phoneType, setPhoneType] = useState('CELL');
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [title, setTitle] = useState('');

  const handleSend = async () => {
    if (!firstName.trim()) { onError('First name is required'); return; }
    if (!phone.trim()) { onError('Phone number is required'); return; }
    setSending(true);
    try {
      const contact: ContactCard = {
        name: {
          formatted_name: `${firstName} ${lastName}`.trim(),
          first_name: firstName.trim(),
          last_name: lastName.trim(),
        },
        phones: [{ phone: phone.trim(), type: phoneType }],
        emails: email ? [{ email: email.trim(), type: 'WORK' }] : [],
      };
      if (company) contact.org = { company, title };
      const content = JSON.stringify({ _type: 'contacts', contacts: [contact] });
      await api.sendWhatsAppMessage({
        contactId, phoneNumberId, content,
        recipientBsuid: recipientBsuid || undefined,
      });
      onSent();
    } catch (e: any) {
      onError(e?.message || 'Failed to send contact');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="p-4 border rounded-lg bg-white shadow-sm space-y-3">
      <div className="flex justify-between items-center">
        <h3 className="font-medium text-sm">Send Contact Card</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg" aria-label="Close">&times;</button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <input placeholder="First name *" value={firstName} onChange={e => setFirstName(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm" />
        <input placeholder="Last name" value={lastName} onChange={e => setLastName(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm" />
      </div>
      <div className="flex gap-2">
        <input placeholder="Phone number *" value={phone} onChange={e => setPhone(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm flex-1" />
        {/* The ariaLabel-ALONE case: this control already had `aria-label="Phone type"` and no
            visible label, so it keeps exactly that and renders no label of its own. The
            utility classes that skinned the native box are dropped, since className on a
            Select lands on the wrapper. */}
        <Select ariaLabel="Phone type" value={phoneType} onChange={v => setPhoneType(v)}
          options={PHONE_TYPE_OPTIONS} style={PHONE_TYPE_SELECT_STYLE} />
      </div>
      <input placeholder="Email (optional)" value={email} onChange={e => setEmail(e.target.value)}
        className="border rounded px-2 py-1.5 text-sm w-full" />
      <div className="grid grid-cols-2 gap-2">
        <input placeholder="Company" value={company} onChange={e => setCompany(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm" />
        <input placeholder="Job title" value={title} onChange={e => setTitle(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm" />
      </div>
      <button onClick={handleSend} disabled={sending}
        className="w-full bg-green-600 text-white rounded py-2 text-sm hover:bg-green-700 disabled:opacity-50">
        {sending ? 'Sending...' : 'Send Contact'}
      </button>
    </div>
  );
};

export default ContactMessageComposer;
