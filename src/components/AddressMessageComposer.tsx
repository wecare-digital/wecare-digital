/**
 * Address Message Composer
 * Request delivery address via WhatsApp interactive address_message.
 * Per WhatsApp Cloud API: POST /messages with type=interactive, interactive.type=address_message
 */
import React, { useState } from 'react';
import * as api from '../api/client';
import Select, { type SelectOption } from './ui/Select';

/* The five countries, hoisted. Same order, same values, same visible text. */
const COUNTRY_OPTIONS: SelectOption[] = [
  { value: 'IN', label: 'India' },
  { value: 'US', label: 'United States' },
  { value: 'AE', label: 'UAE' },
  { value: 'GB', label: 'United Kingdom' },
  { value: 'SG', label: 'Singapore' },
];

/* LAYOUT ONLY. The native control sized itself to "United Kingdom"; the trigger shows the
   selected label, so without a width the field would be the full column. */
const COUNTRY_SELECT_STYLE: React.CSSProperties = { width: 200 };

interface AddressMessageComposerProps {
  contactId: string;
  phoneNumberId: string;
  recipientBsuid?: string;
  onClose: () => void;
  onSent: () => void;
  onError: (msg: string) => void;
}

const AddressMessageComposer: React.FC<AddressMessageComposerProps> = ({
  contactId, phoneNumberId, recipientBsuid, onClose, onSent, onError,
}) => {
  const [sending, setSending] = useState(false);
  const [bodyText, setBodyText] = useState('Please provide your delivery address.');
  const [country, setCountry] = useState('IN');

  const handleSend = async () => {
    if (!bodyText.trim()) { onError('Body text is required'); return; }
    setSending(true);
    try {
      const content = JSON.stringify({
        _type: 'address_message',
        body: bodyText.trim(),
        parameters: { country: country || 'IN' },
      });
      await api.sendWhatsAppMessage({
        contactId, phoneNumberId, content,
        recipientBsuid: recipientBsuid || undefined,
      });
      onSent();
    } catch (e: any) {
      onError(e?.message || 'Failed to send address request');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="p-4 border rounded-lg bg-white shadow-sm space-y-3">
      <div className="flex justify-between items-center">
        <h3 className="font-medium text-sm">Request Delivery Address</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg" aria-label="Close">&times;</button>
      </div>
      <textarea placeholder="Message body *" value={bodyText} onChange={e => setBodyText(e.target.value)}
        className="border rounded px-2 py-1.5 text-sm w-full" rows={2} />
      <div>
        {/* SHAPE (b), design 5.2 and 1.7(b). The external label bound by id KEEPS its own
            utility classes - `text-xs text-gray-500 block mb-1` is a size and colour
            .ui-field-label does not render - so it stays, gains an id, loses its `for`
            attribute, and is named by labelledBy. Keeping the old wiring would have left this
            control announcing only "India": the trigger is a <button>, and per HTML-AAM a
            button takes its accessible name from its CONTENTS. */}
        <label className="text-xs text-gray-500 block mb-1" id="country-select-label">Country</label>
        <Select labelledBy="country-select-label" value={country} onChange={v => setCountry(v)}
          options={COUNTRY_OPTIONS} style={COUNTRY_SELECT_STYLE} />
      </div>
      <button onClick={handleSend} disabled={sending}
        className="w-full bg-green-600 text-white rounded py-2 text-sm hover:bg-green-700 disabled:opacity-50">
        {sending ? 'Sending...' : 'Request Address'}
      </button>
    </div>
  );
};

export default AddressMessageComposer;
