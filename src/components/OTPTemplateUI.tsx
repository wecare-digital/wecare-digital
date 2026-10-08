/**
 * OTP / Authentication Template UI
 * Dedicated UI for creating and sending WhatsApp authentication templates.
 * Supports copy_code, url, one_tap and zero_tap OTP delivery methods.
 * Per WhatsApp Cloud API: Authentication template category with OTP button.
 *
 * Two things worth knowing before editing this file.
 *
 * 1. All four delivery methods send the SAME payload. copy_code emits a
 *    `copy_code` button component; url, one_tap and zero_tap all emit the `url`
 *    sub_type. The difference between them lives in the TEMPLATE DEFINITION
 *    (otp_type, package_name, signature_hash, autofill_text,
 *    zero_tap_terms_accepted), which is why the fields below describe the approved
 *    template and are NOT transmitted with the send.
 * 2. one_tap and zero_tap are not functional yet, and that is an owner gate rather
 *    than a missing feature: Meta can only verify the autofill against a real signed
 *    Android app, and native packaging is post-project. Zero-tap additionally needs
 *    the zero-tap terms accepted in the Meta console, which is not an API action.
 *    No placeholder package name or signature hash is shipped here.
 */
import React, { useState } from 'react';
import * as api from '../api/client';

interface OTPTemplateUIProps {
  contactId: string;
  phoneNumberId: string;
  recipientBsuid?: string;
  onClose: () => void;
  onSent: () => void;
  onError: (msg: string) => void;
}

type OtpButtonType = 'copy_code' | 'url' | 'one_tap' | 'zero_tap';

const OTP_BUTTON_OPTIONS: { value: OtpButtonType; label: string }[] = [
  { value: 'copy_code', label: 'Copy Code' },
  { value: 'url', label: 'URL Button' },
  { value: 'one_tap', label: 'One-tap autofill' },
  { value: 'zero_tap', label: 'Zero-tap' },
];

// Mirrors whatsapp_types.OTP_AUTOFILL_TEXT_MAX and SIGNATURE_HASH_LEN. Validation is
// server-authoritative; these only drive the counters and the inline hints.
const AUTOFILL_TEXT_MAX = 25;
const SIGNATURE_HASH_LEN = 11;

const OTPTemplateUI: React.FC<OTPTemplateUIProps> = ({
  contactId, phoneNumberId, recipientBsuid, onClose, onSent, onError,
}) => {
  const [sending, setSending] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [buttonType, setButtonType] = useState<OtpButtonType>('copy_code');
  const [language, setLanguage] = useState('en');
  // Template-definition fields for the autofill types. No default value: an invented
  // package name or hash would make a demo look like a capability.
  const [packageName, setPackageName] = useState('');
  const [signatureHash, setSignatureHash] = useState('');
  const [autofillText, setAutofillText] = useState('');
  const [zeroTapTermsAccepted, setZeroTapTermsAccepted] = useState(false);

  const isAutofill = buttonType === 'one_tap' || buttonType === 'zero_tap';

  const handleSend = async () => {
    if (!templateName.trim()) { onError('Template name is required'); return; }
    if (!otpCode.trim()) { onError('OTP code is required'); return; }
    if (isAutofill && (!packageName.trim() || !signatureHash.trim())) {
      onError('One-tap and zero-tap need the template\'s package name and signature hash');
      return;
    }
    if (buttonType === 'zero_tap' && !zeroTapTermsAccepted) {
      onError('Zero-tap requires the zero-tap terms to be accepted for this template');
      return;
    }
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
      <div className="flex gap-4 flex-wrap">
        {OTP_BUTTON_OPTIONS.map(opt => (
          <label key={opt.value} className="flex items-center gap-1 text-sm">
            <input type="radio" name="otpType" checked={buttonType === opt.value}
              onChange={() => setButtonType(opt.value)} /> {opt.label}
          </label>
        ))}
      </div>
      {isAutofill && (
        <div className="space-y-2 border-t pt-2">
          <p className="text-xs text-gray-500">
            These describe the approved template&apos;s OTP button and are not sent with the
            message. Autofill only works once the Android app is signed and registered with Meta.
          </p>
          <input placeholder="Template package_name *" value={packageName} onChange={e => setPackageName(e.target.value)}
            className="border rounded px-2 py-1.5 text-sm w-full" />
          <input placeholder={`Template signature_hash * (${SIGNATURE_HASH_LEN} characters)`}
            value={signatureHash} onChange={e => setSignatureHash(e.target.value)}
            className="border rounded px-2 py-1.5 text-sm w-full" />
          <input placeholder={`Autofill button text (<= ${AUTOFILL_TEXT_MAX})`} value={autofillText}
            onChange={e => setAutofillText(e.target.value)} maxLength={AUTOFILL_TEXT_MAX}
            className="border rounded px-2 py-1.5 text-sm w-full" />
          {buttonType === 'zero_tap' && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={zeroTapTermsAccepted}
                onChange={e => setZeroTapTermsAccepted(e.target.checked)} />
              Zero-tap terms accepted for this template (set in the Meta console)
            </label>
          )}
        </div>
      )}
      <div>
        <label className="text-xs text-gray-500 block mb-1" htmlFor="otp-lang">Language</label>
        <select id="otp-lang" value={language} onChange={e => setLanguage(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm">
          <option value="en">English</option>
          <option value="hi">Hindi</option>
          <option value="en_US">English (US)</option>
        </select>
      </div>
      <button onClick={handleSend} disabled={sending}
        className="w-full bg-blue-600 text-white rounded py-2 text-sm hover:bg-blue-700 disabled:opacity-50">
        {sending ? 'Sending...' : 'Send OTP'}
      </button>
    </div>
  );
};

export default OTPTemplateUI;
