/**
 * OTP / Authentication Template UI
 * Dedicated UI for creating and sending WhatsApp authentication templates.
 * Supports copy_code and one_tap OTP delivery methods.
 * Per WhatsApp Cloud API: Authentication template category with OTP button.
 */
import React, { useState } from 'react';
import * as api from '../api/client';
import Select, { type SelectOption } from './ui/Select';

/* The three languages, hoisted. Same order, same values, same visible text. */
const OTP_LANGUAGE_OPTIONS: SelectOption[] = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'Hindi' },
  { value: 'en_US', label: 'English (US)' },
];

/* LAYOUT ONLY. The native control sized itself to "English (US)". */
const OTP_LANGUAGE_SELECT_STYLE: React.CSSProperties = { width: 200 };

interface OTPTemplateUIProps {
  contactId: string;
  phoneNumberId: string;
  recipientBsuid?: string;
  onClose: () => void;
  onSent: () => void;
  onError: (msg: string) => void;
}

const OTPTemplateUI: React.FC<OTPTemplateUIProps> = ({
  contactId, phoneNumberId, recipientBsuid, onClose, onSent, onError,
}) => {
  const [sending, setSending] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [buttonType, setButtonType] = useState<'copy_code' | 'url'>('copy_code');
  const [language, setLanguage] = useState('en');

  const handleSend = async () => {
    if (!templateName.trim()) { onError('Template name is required'); return; }
    if (!otpCode.trim()) { onError('OTP code is required'); return; }
    setSending(true);
    try {
      await api.sendWhatsAppMessage({
        contactId, phoneNumberId,
        isTemplate: true,
        templateName: templateName.trim(),
        templateParams: [language],
        isOtpTemplate: true,
        otpCode: otpCode.trim(),
        otpButtonType: buttonType,
        recipientBsuid: recipientBsuid || undefined,
      });
      onSent();
    } catch (e: any) {
      onError(e?.message || 'Failed to send OTP');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="p-4 border rounded-lg bg-white shadow-sm space-y-3">
      <div className="flex justify-between items-center">
        <h3 className="font-medium text-sm">Send OTP / Authentication</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg" aria-label="Close">&times;</button>
      </div>
      <input placeholder="Auth template name *" value={templateName} onChange={e => setTemplateName(e.target.value)}
        className="border rounded px-2 py-1.5 text-sm w-full" />
      <input placeholder="OTP code *" value={otpCode} onChange={e => setOtpCode(e.target.value)}
        className="border rounded px-2 py-1.5 text-sm w-full" maxLength={10} />
      <div className="flex gap-4">
        <label className="flex items-center gap-1 text-sm">
          <input type="radio" name="otpType" checked={buttonType === 'copy_code'}
            onChange={() => setButtonType('copy_code')} /> Copy Code
        </label>
        <label className="flex items-center gap-1 text-sm">
          <input type="radio" name="otpType" checked={buttonType === 'url'}
            onChange={() => setButtonType('url')} /> URL Button
        </label>
      </div>
      <div>
        {/* SHAPE (b), design 5.2 and 1.7(b) - this is the eleventh id-carrying select, the one
            the earlier audit missed. The external label keeps its own utility classes, gains
            an id, loses its `for` attribute, and is named by labelledBy; without that this
            control would announce only "English". */}
        <label className="text-xs text-gray-500 block mb-1" id="otp-lang-label">Language</label>
        <Select labelledBy="otp-lang-label" value={language} onChange={v => setLanguage(v)}
          options={OTP_LANGUAGE_OPTIONS} style={OTP_LANGUAGE_SELECT_STYLE} />
      </div>
      <button onClick={handleSend} disabled={sending}
        className="w-full bg-blue-600 text-white rounded py-2 text-sm hover:bg-blue-700 disabled:opacity-50">
        {sending ? 'Sending...' : 'Send OTP'}
      </button>
    </div>
  );
};

export default OTPTemplateUI;
