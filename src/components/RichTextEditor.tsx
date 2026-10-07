/**
 * Rich Text Editor Component
 * WhatsApp-style editor with templates, variables, and AI suggestions
 * Fetches real templates from WhatsApp API
 */

import React, { useState, useRef, useEffect } from 'react';
import styles from '../styles/RichTextEditor.module.css';
import * as api from '../api/client';
import { generateReferenceId } from '../lib/formatters';
import { PAYMENT_CONFIG, DEFAULT_GSTIN, PAYMENT_PHONES, DEFAULT_PAYMENT_CONFIG } from '../config/constants';
import Select, { type SelectOption } from './ui/Select';

/*
 * The two fixed option lists, hoisted. Each holds exactly the <option> rows it replaced, in
 * the same order, with the same values and the same visible text. The GST rates stay STRINGS
 * because that is what the request carries and what `item.gstRate` holds; no arithmetic is
 * introduced here, and none is wanted - a rate is compared and sent, never computed on.
 */
const PAYMENT_PHONE_OPTIONS: SelectOption[] = PAYMENT_PHONES.map( p => ( {
  value: p.id,
  label: `${p.display} (${p.name})${p.paymentProtected ? ' [Protected]' : ''}`,
} ) );
const GST_RATE_OPTIONS: SelectOption[] = [ '0', '3', '5', '12', '18', '28' ].map(
  rate => ( { value: rate, label: `${rate}%` } )
);

// Payment dialog state
interface PaymentItem {
  name: string;
  amount: string;
  quantity: string;
  gstRate: string;  // Per-item GST rate (0, 3, 5, 12, 18, 28)
}

interface PaymentDialogState {
  items: PaymentItem[];
  referenceId: string;
  promo: string;      // Discount/Promo
  express: string;    // Delivery/Express
  gstin: string;      // GSTIN number
  paymentMethod: string;  // Payment configuration name on WABA
  phoneNumberId: string;  // Which phone to send from
  orderId: string;    // Order ID (blank = Offline)
}

interface RichTextEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  maxLength?: number;
  showCharCount?: boolean;
  showAISuggestions?: boolean;
  channel?: 'whatsapp' | 'sms' | 'email' | 'rcs' | 'voice';
  onSend?: () => void;
  contactContext?: string;
  onTemplateSelect?: (template: api.WhatsAppTemplate) => void;
  selectedContactId?: string;
  phoneNumberId?: string;
  onAttachClick?: () => void;
  onSendTTS?: (data: { text: string; voiceId: string; languageCode: string; engine: string }) => Promise<boolean>;
  onEmojiClick?: () => void;
  emojiActive?: boolean;
  onInteractiveClick?: () => void;
  interactiveActive?: boolean;
  onLocationClick?: () => void;
}

// Variable placeholders for templates
const VARIABLES = [
  { key: '{{1}}', label: 'Variable 1', icon: '①' },
  { key: '{{2}}', label: 'Variable 2', icon: '②' },
  { key: '{{3}}', label: 'Variable 3', icon: '③' },
  { key: '{{4}}', label: 'Variable 4', icon: '④' },
];

const RichTextEditor: React.FC<RichTextEditorProps> = ({
  value,
  onChange,
  placeholder = 'Type a message...',
  disabled = false,
  maxLength,
  showCharCount = false,
  showAISuggestions = true,
  channel = 'whatsapp',
  onSend,
  contactContext,
  onTemplateSelect,
  selectedContactId,
  phoneNumberId,
  onAttachClick,
  onSendTTS,
  onEmojiClick,
  emojiActive = false,
  onInteractiveClick,
  interactiveActive = false,
  onLocationClick,
}) => {
  const [showTemplates, setShowTemplates] = useState(false);
  const [showVariables, setShowVariables] = useState(false);
  const [showFormatting, setShowFormatting] = useState(false);
  const [templates, setTemplates] = useState<api.WhatsAppTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [aiSuggestions, setAiSuggestions] = useState<string[]>([]);
  const [loadingAI, setLoadingAI] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [sendingTemplate, setSendingTemplate] = useState(false);
  const [templateMessage, setTemplateMessage] = useState<string | null>(null);
  const [templateVariableDialog, setTemplateVariableDialog] = useState<{
    template: api.WhatsAppTemplate;
    variables: string[];
    variableCount: number;
  } | null>(null);
  const [showPaymentDialog, setShowPaymentDialog] = useState(false);
  const [paymentForm, setPaymentForm] = useState<PaymentDialogState>({
    items: [{ name: '', amount: '', quantity: '1', gstRate: '0' }],
    referenceId: '',
    promo: '0',
    express: '0',
    gstin: DEFAULT_GSTIN,
    paymentMethod: DEFAULT_PAYMENT_CONFIG,
    phoneNumberId: PAYMENT_CONFIG.phoneNumberId,
    orderId: '',
  });
  const [sendingPayment, setSendingPayment] = useState(false);
  const [payPhone2Unlocked, setPayPhone2Unlocked] = useState(false);
  // TTS state
  const [showTTSPanel, setShowTTSPanel] = useState(false);
  const [ttsText, setTtsText] = useState('');
  const [ttsLanguage, setTtsLanguage] = useState('en-IN');
  const [ttsVoiceId, setTtsVoiceId] = useState('Kajal');
  const [ttsEngine, setTtsEngine] = useState('neural');
  const [ttsSending, setTtsSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const loadTemplates = async () => {
    setTemplatesLoading(true);
    try {
      const data = await api.listTemplates();
      setTemplates(data);
    } catch (error) {
      console.error('Failed to load templates:', error);
    } finally {
      setTemplatesLoading(false);
    }
  };

  // Load templates from API
  useEffect(() => {
    if (channel === 'whatsapp') {
      loadTemplates();
    }
  }, [channel]);

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowTemplates(false);
        setShowVariables(false);
        setShowFormatting(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + 'px';
    }
  }, [value]);

  const insertAtCursor = (text: string) => {
    const textarea = textareaRef.current;
    if (textarea) {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const newValue = value.substring(0, start) + text + value.substring(end);
      onChange(newValue);
      setTimeout(() => {
        textarea.selectionStart = textarea.selectionEnd = start + text.length;
        textarea.focus();
      }, 0);
    } else {
      onChange(value + text);
    }
  };

  const wrapSelection = (prefix: string, suffix: string) => {
    const textarea = textareaRef.current;
    if (textarea) {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const selected = value.substring(start, end);
      const newValue = value.substring(0, start) + prefix + selected + suffix + value.substring(end);
      onChange(newValue);
      setTimeout(() => {
        textarea.selectionStart = start + prefix.length;
        textarea.selectionEnd = end + prefix.length;
        textarea.focus();
      }, 0);
    }
    setShowFormatting(false);
  };

  // Count variables in template body ({{1}}, {{2}}, etc.)
  const countTemplateVariables = (template: api.WhatsAppTemplate): number => {
    const bodyComponent = template.components.find(c => c.type === 'BODY');
    if (!bodyComponent?.text) return 0;
    const matches = bodyComponent.text.match(/\{\{\d+\}\}/g);
    return matches ? matches.length : 0;
  };

  const applyTemplate = async (template: api.WhatsAppTemplate) => {
    // Check if template has variables
    const varCount = countTemplateVariables(template);
    
    if (varCount > 0 && selectedContactId && phoneNumberId) {
      // Show variable input dialog
      setTemplateVariableDialog({
        template,
        variables: Array(varCount).fill(''),
        variableCount: varCount,
      });
      setShowTemplates(false);
      return;
    }
    
    // If we have contact and phone number, send the template directly
    if (selectedContactId && phoneNumberId) {
      await sendTemplateMessage(template, []);
    } else {
      // Fallback: put template body text in editor for manual editing
      const bodyComponent = template.components.find(c => c.type === 'BODY');
      const bodyText = bodyComponent?.text || `[Template: ${template.name}]`;
      onChange(bodyText);
      setShowTemplates(false);
      if (onTemplateSelect) {
        onTemplateSelect(template);
      }
    }
    textareaRef.current?.focus();
  };

  // Send template with variables
  const sendTemplateMessage = async (template: api.WhatsAppTemplate, variables: string[]) => {
    if (!selectedContactId || !phoneNumberId) return;
    
    setSendingTemplate(true);
    setTemplateMessage(`Sending template: ${template.name}...`);
    setTemplateVariableDialog(null);
    
    try {
      const result = await api.sendWhatsAppTemplateMessage({
        contactId: selectedContactId,
        templateName: template.name,
        language: template.language,
        phoneNumberId: phoneNumberId,
        templateParams: variables.filter(v => v.trim() !== ''),
      });
      
      if (result) {
        setTemplateMessage(`✓ Template "${template.name}" sent!`);
        setTimeout(() => setTemplateMessage(null), 3000);
      } else {
        setTemplateMessage(`× Failed to send template`);
        setTimeout(() => setTemplateMessage(null), 3000);
      }
    } catch (error: any) {
      console.error('Template send error:', error);
      setTemplateMessage(`× Error: ${error.message || 'Failed to send'}`);
      setTimeout(() => setTemplateMessage(null), 3000);
    } finally {
      setSendingTemplate(false);
      setShowTemplates(false);
    }
  };

  // Update variable value in dialog
  const updateVariableValue = (index: number, value: string) => {
    if (!templateVariableDialog) return;
    const newVars = [...templateVariableDialog.variables];
    newVars[index] = value;
    setTemplateVariableDialog({ ...templateVariableDialog, variables: newVars });
  };

  const insertVariable = (variable: typeof VARIABLES[0]) => {
    insertAtCursor(variable.key);
    setShowVariables(false);
  };

  const fetchAISuggestions = async () => {
    if (!value.trim() || value.length < 3) {
      setAiError('Type at least 3 characters');
      setTimeout(() => setAiError(null), 2000);
      return;
    }
    
    setLoadingAI(true);
    setAiError(null);
    setShowSuggestions(false);
    
    // WhatsApp AI auto-reply is disabled — show static suggestions only
    setAiSuggestions([
      'Thank you for reaching out! How can I assist you today?',
      'I understand. Let me help you with that.',
    ]);
    setShowSuggestions(true);
    setLoadingAI(false);
  };

  // Send payment message - ALWAYS use interactive mode from inbox
  // Both WABAs expose the identical pair WECAREDIGITAL / WECAREUPI, so the phone
  // does not change the config name. The old per-phone names (a hyphenated
  // WECARE-DIGITAL and ManishAgarwal_Pay) were deleted on Meta 2026-08-23 and
  // would now be rejected with error 136026.
  
  const getPayConfigForPhone = (phoneId: string) => {
    const phone = PAYMENT_PHONES.find(p => p.id === phoneId);
    return phone?.paymentConfigName || DEFAULT_PAYMENT_CONFIG;
  };

  const isPayPhoneLocked = () => {
    const phone = PAYMENT_PHONES.find(p => p.id === paymentForm.phoneNumberId);
    return phone?.paymentProtected && !payPhone2Unlocked;
  };

  const handlePayPhoneUnlock = async () => {
    try {
      setPayPhone2Unlocked( await api.verifyAdminAccess() );
    } catch {
      setPayPhone2Unlocked( false );
    }
  };
  
  const sendPaymentMessage = async () => {
    if (!selectedContactId) return;
    const validItems = paymentForm.items.filter(i => i.name.trim() && parseFloat(i.amount) > 0);
    if (validItems.length === 0 || !paymentForm.referenceId) return;

    // Mandatory field enforcement: check contact has email + addresses
    try {
      const contact = await api.getContact(selectedContactId);
      if (contact) {
        const missing: string[] = [];
        if (!contact.email) missing.push('email');
        if (!contact.shippingAddress) missing.push('shipping address');
        if (!contact.billingAddress) missing.push('billing address');
        if (missing.length > 0) {
          setTemplateMessage(`Contact missing: ${missing.join(', ')}. Update at /contacts first.`);
          setTimeout(() => setTemplateMessage(null), 5000);
          return;
        }
      }
    } catch { /* proceed if lookup fails */ }

    setSendingPayment(true);
    setTemplateMessage('Sending interactive payment request...');

    try {
      // Build items array in paise with per-item GST
      const itemsInPaise = validItems.map(item => {
        const amt = Math.round(parseFloat(item.amount) * 100);
        const qty = parseInt(item.quantity) || 1;
        const rate = parseInt(item.gstRate) || 0;
        return { name: item.name.trim(), amount: amt, quantity: qty, gstRate: rate };
      });

      const promoInPaise = Math.round(parseFloat(paymentForm.promo || '0') * 100);
      const expressInPaise = Math.round(parseFloat(paymentForm.express || '0') * 100);
      // Calculate total tax = sum of per-item GST
      const totalTaxPaise = itemsInPaise.reduce((sum, i) => sum + Math.round(i.amount * i.quantity * i.gstRate / 100), 0);

      const result = await api.sendWhatsAppPaymentMessage({
        contactId: selectedContactId,
        phoneNumberId: paymentForm.phoneNumberId,
        referenceId: paymentForm.referenceId,
        items: itemsInPaise.map(i => ({ name: i.name, amount: i.amount, quantity: i.quantity, gstRate: i.gstRate })),
        discount: promoInPaise,
        delivery: expressInPaise,
        tax: totalTaxPaise,
        gstin: paymentForm.gstin || DEFAULT_GSTIN,
        orderId: paymentForm.orderId || 'Offline',
        useInteractive: true,
        paymentConfiguration: getPayConfigForPhone(paymentForm.phoneNumberId),
      });

      if (result) {
        setTemplateMessage(`✓ Payment request sent! Ref: ${paymentForm.referenceId}`);
        setShowPaymentDialog(false);
        setPaymentForm({ items: [{ name: '', amount: '', quantity: '1', gstRate: '0' }], referenceId: '', promo: '0', express: '0', gstin: DEFAULT_GSTIN, paymentMethod: DEFAULT_PAYMENT_CONFIG, phoneNumberId: PAYMENT_CONFIG.phoneNumberId, orderId: '' });
      } else {
        const connStatus = api.getConnectionStatus();
        setTemplateMessage(`× Failed: ${connStatus.lastError || 'Unknown error'}`);
      }
    } catch (error: any) {
      console.error('Payment send error:', error);
      setTemplateMessage(`× Error: ${error.message || 'Failed to send'}`);
    } finally {
      setSendingPayment(false);
      setTimeout(() => setTemplateMessage(null), 5000);
    }
  };

  // Polly voices for TTS panel
  const POLLY_VOICES: Record<string, { label: string; voices: { id: string; name: string; gender: string; engine: string }[] }> = {
    'en-IN': { label: 'English (Indian)', voices: [{ id: 'Kajal', name: 'Kajal', gender: 'Female', engine: 'neural' }, { id: 'Raveena', name: 'Raveena', gender: 'Female', engine: 'standard' }] },
    'en-US': { label: 'English (US)', voices: [{ id: 'Joanna', name: 'Joanna', gender: 'Female', engine: 'neural' }, { id: 'Matthew', name: 'Matthew', gender: 'Male', engine: 'neural' }, { id: 'Ruth', name: 'Ruth', gender: 'Female', engine: 'neural' }, { id: 'Stephen', name: 'Stephen', gender: 'Male', engine: 'neural' }] },
    'en-GB': { label: 'English (British)', voices: [{ id: 'Amy', name: 'Amy', gender: 'Female', engine: 'neural' }, { id: 'Brian', name: 'Brian', gender: 'Male', engine: 'neural' }] },
    'hi-IN': { label: 'Hindi', voices: [{ id: 'Kajal', name: 'Kajal', gender: 'Female', engine: 'neural' }, { id: 'Aditi', name: 'Aditi', gender: 'Female', engine: 'standard' }] },
    'arb': { label: 'Arabic', voices: [{ id: 'Hala', name: 'Hala', gender: 'Female', engine: 'neural' }, { id: 'Zeina', name: 'Zeina', gender: 'Female', engine: 'standard' }] },
    'es-US': { label: 'Spanish', voices: [{ id: 'Lupe', name: 'Lupe', gender: 'Female', engine: 'neural' }, { id: 'Pedro', name: 'Pedro', gender: 'Male', engine: 'neural' }] },
    'fr-FR': { label: 'French', voices: [{ id: 'Lea', name: 'Léa', gender: 'Female', engine: 'neural' }, { id: 'Remi', name: 'Rémi', gender: 'Male', engine: 'neural' }] },
    'de-DE': { label: 'German', voices: [{ id: 'Vicki', name: 'Vicki', gender: 'Female', engine: 'neural' }, { id: 'Daniel', name: 'Daniel', gender: 'Male', engine: 'neural' }] },
    'ja-JP': { label: 'Japanese', voices: [{ id: 'Kazuha', name: 'Kazuha', gender: 'Female', engine: 'neural' }, { id: 'Takumi', name: 'Takumi', gender: 'Male', engine: 'neural' }] },
    'ko-KR': { label: 'Korean', voices: [{ id: 'Seoyeon', name: 'Seoyeon', gender: 'Female', engine: 'neural' }] },
    'pt-BR': { label: 'Portuguese', voices: [{ id: 'Camila', name: 'Camila', gender: 'Female', engine: 'neural' }, { id: 'Thiago', name: 'Thiago', gender: 'Male', engine: 'neural' }] },
    'cmn-CN': { label: 'Chinese (Mandarin)', voices: [{ id: 'Zhiyu', name: 'Zhiyu', gender: 'Female', engine: 'neural' }] },
    'it-IT': { label: 'Italian', voices: [{ id: 'Bianca', name: 'Bianca', gender: 'Female', engine: 'neural' }, { id: 'Adriano', name: 'Adriano', gender: 'Male', engine: 'neural' }] },
    'tr-TR': { label: 'Turkish', voices: [{ id: 'Burcu', name: 'Burcu', gender: 'Female', engine: 'neural' }] },
    'ru-RU': { label: 'Russian', voices: [{ id: 'Tatyana', name: 'Tatyana', gender: 'Female', engine: 'standard' }, { id: 'Maxim', name: 'Maxim', gender: 'Male', engine: 'standard' }] },
    'nl-NL': { label: 'Dutch', voices: [{ id: 'Laura', name: 'Laura', gender: 'Female', engine: 'neural' }, { id: 'Lotte', name: 'Lotte', gender: 'Female', engine: 'standard' }] },
    'pl-PL': { label: 'Polish', voices: [{ id: 'Ola', name: 'Ola', gender: 'Female', engine: 'neural' }, { id: 'Jacek', name: 'Jacek', gender: 'Male', engine: 'standard' }] },
    'sv-SE': { label: 'Swedish', voices: [{ id: 'Elin', name: 'Elin', gender: 'Female', engine: 'neural' }] },
    'da-DK': { label: 'Danish', voices: [{ id: 'Sofie', name: 'Sofie', gender: 'Female', engine: 'neural' }] },
    'nb-NO': { label: 'Norwegian', voices: [{ id: 'Ida', name: 'Ida', gender: 'Female', engine: 'neural' }] },
    'fi-FI': { label: 'Finnish', voices: [{ id: 'Suvi', name: 'Suvi', gender: 'Female', engine: 'neural' }] },
    'es-ES': { label: 'Spanish (Spain)', voices: [{ id: 'Lucia', name: 'Lucía', gender: 'Female', engine: 'neural' }, { id: 'Sergio', name: 'Sergio', gender: 'Male', engine: 'neural' }] },
    'es-MX': { label: 'Spanish (Mexico)', voices: [{ id: 'Mia', name: 'Mia', gender: 'Female', engine: 'neural' }, { id: 'Andres', name: 'Andrés', gender: 'Male', engine: 'neural' }] },
    'pt-PT': { label: 'Portuguese (PT)', voices: [{ id: 'Ines', name: 'Inês', gender: 'Female', engine: 'neural' }] },
    'fr-CA': { label: 'French (Canada)', voices: [{ id: 'Gabrielle', name: 'Gabrielle', gender: 'Female', engine: 'neural' }, { id: 'Liam', name: 'Liam', gender: 'Male', engine: 'neural' }] },
    'ca-ES': { label: 'Catalan', voices: [{ id: 'Arlet', name: 'Arlet', gender: 'Female', engine: 'neural' }] },
    'ro-RO': { label: 'Romanian', voices: [{ id: 'Carmen', name: 'Carmen', gender: 'Female', engine: 'standard' }] },
    'en-AU': { label: 'English (Australian)', voices: [{ id: 'Olivia', name: 'Olivia', gender: 'Female', engine: 'neural' }] },
    'en-NZ': { label: 'English (New Zealand)', voices: [{ id: 'Aria', name: 'Aria', gender: 'Female', engine: 'neural' }] },
    'en-ZA': { label: 'English (South Africa)', voices: [{ id: 'Ayanda', name: 'Ayanda', gender: 'Female', engine: 'neural' }] },
    'cy-GB': { label: 'Welsh', voices: [{ id: 'Gwyneth', name: 'Gwyneth', gender: 'Female', engine: 'standard' }] },
  };

  /* The two TTS lists. Built here rather than memoised or hoisted, because POLLY_VOICES is
     itself declared inside this component and recreated every render, so a useMemo keyed on
     it would never hit - and this is exactly the per-render .map the <option> rows already
     did. Same order, same values, same visible text. */
  const ttsLanguageOptions: SelectOption[] = Object.entries(POLLY_VOICES).map(
    ([code, data]) => ({ value: code, label: data.label })
  );
  const ttsVoiceOptions: SelectOption[] = (POLLY_VOICES[ttsLanguage]?.voices || []).map(
    v => ({ value: v.id, label: `${v.name} (${v.gender}) — ${v.engine}` })
  );

  const handleTTSLanguageChange = (lang: string) => {
    setTtsLanguage(lang);
    const voices = POLLY_VOICES[lang]?.voices || [];
    if (voices.length > 0) { setTtsVoiceId(voices[0].id); setTtsEngine(voices[0].engine); }
  };

  const handleTTSVoiceChange = (vid: string) => {
    setTtsVoiceId(vid);
    const voice = (POLLY_VOICES[ttsLanguage]?.voices || []).find(v => v.id === vid);
    if (voice) setTtsEngine(voice.engine);
  };

  const handleSendTTS = async () => {
    if (!onSendTTS || !ttsText.trim()) return;
    setTtsSending(true);
    try {
      const ok = await onSendTTS({ text: ttsText, voiceId: ttsVoiceId, languageCode: ttsLanguage, engine: ttsEngine });
      if (ok) { setShowTTSPanel(false); setTtsText(''); }
    } finally {
      setTtsSending(false);
    }
  };

  const applySuggestion = (suggestion: string) => {
    onChange(suggestion);
    setShowSuggestions(false);
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && onSend) {
      e.preventDefault();
      onSend();
    }
  };

  const charCount = value.length;
  const isOverLimit = maxLength ? charCount > maxLength : false;
  const hasVariables = value.includes('{{');

  // Get template status badge
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'APPROVED': return { text: '✓', class: 'approved' };
      case 'PENDING': return { text: '○', class: 'pending' };
      case 'REJECTED': return { text: '×', class: 'rejected' };
      default: return { text: '?', class: '' };
    }
  };

  return (
    <div className={styles['rich-text-editor']} ref={dropdownRef}>
      {/* Template Send Status */}
      {templateMessage && (
        <div className={styles['template-message']}>
          {templateMessage}
        </div>
      )}

      {/* AI Suggestions Panel */}
      {showAISuggestions && showSuggestions && aiSuggestions.length > 0 && (
        <div className={styles['ai-suggestions-panel']}>
          <div className={styles['ai-suggestions-header']}>
            <span>◇ AI Suggestion</span>
            <button onClick={() => setShowSuggestions(false)}>×</button>
          </div>
          <div className={styles['ai-suggestions-list']}>
            {aiSuggestions.map((suggestion, i) => (
              <button key={i} className={styles['ai-suggestion-item']} onClick={() => applySuggestion(suggestion)}>
                {suggestion.length > 100 ? suggestion.substring(0, 100) + '...' : suggestion}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Templates Dropdown */}
      {showTemplates && (
        <div className={styles['dropdown-panel']}>
          <div className={styles['dropdown-header']}>
            <span>▤ WhatsApp Templates</span>
            <button onClick={() => setShowTemplates(false)}>×</button>
          </div>
          <div className={styles['dropdown-list']}>
            {templatesLoading ? (
              <div className={styles['dropdown-loading']}>Loading templates...</div>
            ) : templates.length > 0 ? (
              templates.map((template) => {
                const badge = getStatusBadge(template.status);
                const bodyComponent = template.components.find(c => c.type === 'BODY');
                const preview = bodyComponent?.text?.substring(0, 50) || '';
                const varCount = countTemplateVariables(template);
                return (
                  <button 
                    key={template.id} 
                    className={styles['dropdown-item']} 
                    onClick={() => applyTemplate(template)}
                    disabled={template.status !== 'APPROVED' || sendingTemplate}
                  >
                    <span className={`${styles['template-status']} ${styles[badge.class]}`}>{badge.text}</span>
                    <div className={styles['template-info']}>
                      <span className={styles['template-name']}>{template.name}</span>
                      {preview && <span className={styles['template-preview']}>{preview}...</span>}
                    </div>
                    <span className={styles['template-category']}>
                      {template.category}
                      {varCount > 0 && <span className={styles['var-count']}> ({varCount} var)</span>}
                    </span>
                  </button>
                );
              })
            ) : (
              <div className={styles['dropdown-empty']}>
                <p>No templates found</p>
                <p className={styles['dropdown-hint-text']}>Templates are managed in AWS Console or Meta Business Suite</p>
              </div>
            )}
          </div>
          <div className={styles['dropdown-hint']}>
            {selectedContactId ? 'Click to send template directly' : 'Select a contact first to send templates'}
          </div>
        </div>
      )}

      {/* Template Variable Input Dialog */}
      {templateVariableDialog && (
        <div className={styles['variable-dialog']}>
          <div className={styles['variable-dialog-header']}>
            <span>▤ {templateVariableDialog.template.name}</span>
            <button onClick={() => setTemplateVariableDialog(null)}>×</button>
          </div>
          <div className={styles['variable-dialog-preview']}>
            {templateVariableDialog.template.components.find(c => c.type === 'BODY')?.text || ''}
          </div>
          <div className={styles['variable-dialog-inputs']}>
            {templateVariableDialog.variables.map((val, i) => (
              <div key={i} className={styles['variable-input-row']}>
                <label>{`{{${i + 1}}}`}</label>
                <input
                  type="text"
                  value={val}
                  onChange={(e) => updateVariableValue(i, e.target.value)}
                  placeholder={`Enter value for variable ${i + 1}`}
                  autoFocus={i === 0}
                />
              </div>
            ))}
          </div>
          <div className={styles['variable-dialog-actions']}>
            <button 
              className={styles['cancel-btn']}
              onClick={() => setTemplateVariableDialog(null)}
            >
              Cancel
            </button>
            <button 
              className={styles['send-template-btn']}
              onClick={() => sendTemplateMessage(templateVariableDialog.template, templateVariableDialog.variables)}
              disabled={sendingTemplate || templateVariableDialog.variables.some(v => !v.trim())}
            >
              {sendingTemplate ? 'Sending...' : 'Send Template'}
            </button>
          </div>
        </div>
      )}

      {/* Payment Dialog */}
      {showPaymentDialog && (
        <div className={`${styles['variable-dialog']} ${styles['payment-dialog']}`}>
          <div className={styles['variable-dialog-header']}>
            <span>Payment Request</span>
            <button onClick={() => setShowPaymentDialog(false)}>×</button>
          </div>
          <div className={styles['variable-dialog-preview']}>
            Razorpay Gateway (UPI + Cards + Netbanking) | {PAYMENT_PHONES.find(p => p.id === paymentForm.phoneNumberId)?.display || '+91 93309 94400'}
          </div>
          <div className={styles['variable-dialog-inputs']}>
            <div className={styles['payment-grid']}>
              <div className={styles['variable-input-row']}>
                {/* BOTH statements and their order are preserved, and that is load-bearing
                    rather than tidy: the second resets the admin-verification gate, so a
                    handler that lost it would leave this panel unlocked after the sender
                    changed. The `.variable-input-row` caption is an unassociated <label> -
                    no `for`, no wrapped control - so it stays and the control takes
                    ariaLabel. */}
                <label>Send From</label>
                <Select
                  ariaLabel="Send from"
                  value={paymentForm.phoneNumberId}
                  onChange={v => { setPaymentForm({...paymentForm, phoneNumberId: v}); setPayPhone2Unlocked(false); }}
                  options={PAYMENT_PHONE_OPTIONS}
                />
              </div>
              {isPayPhoneLocked() && (
                <div className={`${styles['variable-input-row']} ${styles['full-width']}`}>
                  <label>Admin authorization required for this number</label>
                  <button onClick={handlePayPhoneUnlock} style={{ padding: '6px 12px', borderRadius: '6px', background: '#d1f470', color: '#1a3a2a', border: 'none', fontSize: '12px', cursor: 'pointer' }}>Verify Admin access</button>
                </div>
              )}
              {!isPayPhoneLocked() && PAYMENT_PHONES.find(p => p.id === paymentForm.phoneNumberId)?.paymentProtected && (
                <div className={`${styles['variable-input-row']} ${styles['full-width']}`}>
                  <span style={{ color: '#1a3a2a', fontSize: '11px' }}>Unlocked for this session</span>
                </div>
              )}
              <div className={styles['variable-input-row']}>
                <label>Pay Config</label>
                <input type="text" value={getPayConfigForPhone(paymentForm.phoneNumberId)} readOnly style={{ background: '#f5f5f5' }} />
              </div>
              <div className={`${styles['variable-input-row']} ${styles['full-width']}`}>
                <label>Ref ID</label>
                <input
                  type="text"
                  value={paymentForm.referenceId}
                  onChange={(e) => setPaymentForm({...paymentForm, referenceId: e.target.value})}
                  placeholder="WD-PAY-XXXXXXXX"
                  readOnly
                />
              </div>
              <div className={`${styles['variable-input-row']} ${styles['full-width']}`}>
                <label>Order ID</label>
                <input
                  type="text"
                  value={paymentForm.orderId}
                  onChange={(e) => setPaymentForm({...paymentForm, orderId: e.target.value})}
                  placeholder="Blank = Offline"
                />
              </div>
              {/* Multi-item rows with per-item GST */}
              {paymentForm.items.map((item, idx) => {
                const itemAmt = parseFloat(item.amount) || 0;
                const itemQty = parseInt(item.quantity) || 1;
                const itemGst = parseInt(item.gstRate) || 0;
                const itemTotal = itemAmt * itemQty;
                const itemTax = itemTotal * itemGst / 100;
                return (
                <React.Fragment key={idx}>
                  <div className={`${styles['variable-input-row']} ${styles['full-width']}`} style={{ display: 'flex', gap: '6px', alignItems: 'flex-end' }}>
                    <div style={{ flex: 2.5 }}>
                      <label>{idx === 0 ? 'Item *' : `Item ${idx + 1} *`}</label>
                      <input
                        type="text"
                        value={item.name}
                        onChange={(e) => { const items = [...paymentForm.items]; items[idx] = {...items[idx], name: e.target.value}; setPaymentForm({...paymentForm, items}); }}
                        placeholder="Service Fee"
                        autoFocus={idx === 0}
                      />
                    </div>
                    <div style={{ flex: 1.2 }}>
                      <label>₹ *</label>
                      <input
                        type="number"
                        value={item.amount}
                        onChange={(e) => { const items = [...paymentForm.items]; items[idx] = {...items[idx], amount: e.target.value}; setPaymentForm({...paymentForm, items}); }}
                        placeholder="100"
                        step="0.01"
                        min="1"
                      />
                    </div>
                    <div style={{ flex: 0.6 }}>
                      <label>Qty</label>
                      <input
                        type="number"
                        value={item.quantity}
                        onChange={(e) => { const items = [...paymentForm.items]; items[idx] = {...items[idx], quantity: e.target.value}; setPaymentForm({...paymentForm, items}); }}
                        placeholder="1"
                        min="1"
                      />
                    </div>
                    <div style={{ flex: 0.8 }}>
                      <label>GST</label>
                      {/* The six rates keep their exact string values, which is what the
                          request carries; every statement of the handler is preserved in
                          order, and no arithmetic is introduced here. */}
                      <Select
                        ariaLabel="GST rate"
                        value={item.gstRate}
                        onChange={v => { const items = [...paymentForm.items]; items[idx] = {...items[idx], gstRate: v}; setPaymentForm({...paymentForm, items}); }}
                        options={GST_RATE_OPTIONS}
                      />
                    </div>
                    {paymentForm.items.length > 1 && (
                      <button
                        onClick={() => { const items = paymentForm.items.filter((_, i) => i !== idx); setPaymentForm({...paymentForm, items}); }}
                        style={{ padding: '4px 8px', borderRadius: '4px', background: '#f3f4f6', border: '1px solid #d1d5db', cursor: 'pointer', fontSize: '12px', marginBottom: '1px', color: '#6b7280' }}
                        title="Remove item"
                      >×</button>
                    )}
                  </div>
                  {/* Per-item GST calculation */}
                  {itemAmt > 0 && itemGst > 0 && (
                    <div className={`${styles['variable-input-row']} ${styles['full-width']}`} style={{ marginTop: '-4px', paddingLeft: '4px' }}>
                      <span style={{ fontSize: '11px', color: '#6b7280' }}>
                        ₹{itemTotal.toFixed(2)} + GST {itemGst}% = ₹{itemTax.toFixed(2)} tax
                      </span>
                    </div>
                  )}
                </React.Fragment>
                );
              })}
              <div className={`${styles['variable-input-row']} ${styles['full-width']}`}>
                <button
                  onClick={() => setPaymentForm({...paymentForm, items: [...paymentForm.items, { name: '', amount: '', quantity: '1', gstRate: '0' }]})}
                  style={{ padding: '4px 12px', borderRadius: '6px', background: '#f9fafb', color: '#1a3a2a', border: '1px solid #e5e7eb', fontSize: '12px', cursor: 'pointer' }}
                >+ Add Item</button>
              </div>
              <div className={styles['variable-input-row']}>
                <label>Promo (₹)</label>
                <input
                  type="number"
                  value={paymentForm.promo}
                  onChange={(e) => setPaymentForm({...paymentForm, promo: e.target.value})}
                  placeholder="0"
                  step="0.01"
                  min="0"
                />
              </div>
              <div className={styles['variable-input-row']}>
                <label>Express (₹)</label>
                <input
                  type="number"
                  value={paymentForm.express}
                  onChange={(e) => setPaymentForm({...paymentForm, express: e.target.value})}
                  placeholder="0"
                  step="0.01"
                  min="0"
                />
              </div>
              <div className={styles['variable-input-row']}>
                <label>GSTIN</label>
                <input
                  type="text"
                  value={paymentForm.gstin}
                  onChange={(e) => setPaymentForm({...paymentForm, gstin: e.target.value})}
                  placeholder={DEFAULT_GSTIN}
                />
              </div>
              {/* Live calculation summary */}
              {(() => {
                const items = paymentForm.items.filter(i => parseFloat(i.amount) > 0);
                if (items.length === 0) return null;
                const subtotal = items.reduce((s, i) => s + (parseFloat(i.amount) || 0) * (parseInt(i.quantity) || 1), 0);
                const totalGst = items.reduce((s, i) => {
                  const t = (parseFloat(i.amount) || 0) * (parseInt(i.quantity) || 1);
                  return s + t * (parseInt(i.gstRate) || 0) / 100;
                }, 0);
                const convBase = subtotal * 0.02;
                const convGst = convBase * 0.18;
                const convTotal = convBase + convGst;
                const promo = parseFloat(paymentForm.promo) || 0;
                const express = parseFloat(paymentForm.express) || 0;
                const grand = subtotal + totalGst + convTotal - promo + express;
                return (
                  <div className={`${styles['variable-input-row']} ${styles['full-width']}`} style={{ background: '#f9fafb', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', color: '#374151', lineHeight: '1.6' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Subtotal ({items.length} item{items.length > 1 ? 's' : ''})</span><span>₹{subtotal.toFixed(2)}</span></div>
                    {totalGst > 0 && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>GST (itemwise)</span><span>₹{totalGst.toFixed(2)}</span></div>}
                    {totalGst > 0 && items.filter(i => (parseInt(i.gstRate) || 0) > 0).map((i, idx) => {
                      const t = (parseFloat(i.amount) || 0) * (parseInt(i.quantity) || 1);
                      const g = t * (parseInt(i.gstRate) || 0) / 100;
                      return <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', paddingLeft: '10px', fontSize: '11px', color: '#6b7280' }}><span>{i.name || `Item ${idx+1}`} @ {i.gstRate}%</span><span>₹{g.toFixed(2)}</span></div>;
                    })}
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Conv. Fee (2%+18%GST)</span><span>₹{convTotal.toFixed(2)}</span></div>
                    {promo > 0 && <div style={{ display: 'flex', justifyContent: 'space-between', color: '#1a3a2a' }}><span>Promo</span><span>-₹{promo.toFixed(2)}</span></div>}
                    {express > 0 && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Express</span><span>₹{express.toFixed(2)}</span></div>}
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600, borderTop: '1px solid #e5e7eb', paddingTop: '4px', marginTop: '4px', color: '#1a3a2a' }}><span>Total</span><span>₹{grand.toFixed(2)}</span></div>
                  </div>
                );
              })()}
            </div>
          </div>
          <div className={styles['variable-dialog-actions']}>
            <button className={styles['cancel-btn']} onClick={() => setShowPaymentDialog(false)}>
              Cancel
            </button>
            <button
              className={styles['send-template-btn']}
              onClick={sendPaymentMessage}
              disabled={sendingPayment || paymentForm.items.every(i => !i.name.trim() || !parseFloat(i.amount)) || !paymentForm.referenceId || isPayPhoneLocked()}
            >
              {isPayPhoneLocked() ? 'Locked' : sendingPayment ? 'Sending...' : 'Send'}
            </button>
          </div>
        </div>
      )}

      {/* TTS Panel (like Payment — inline above editor) */}
      {showTTSPanel && onSendTTS && (
        <div className={`${styles['variable-dialog']} ${styles['payment-dialog']}`}>
          <div className={styles['variable-dialog-header']}>
            <span>Voice Note (Text-to-Speech)</span>
            <button onClick={() => setShowTTSPanel(false)}>×</button>
          </div>
          <div className={styles['variable-dialog-preview']}>
            Amazon Polly → MP3 audio → S3 → WhatsApp
          </div>
          <div className={styles['variable-dialog-inputs']}>
            <div className={styles['payment-grid']}>
              <div className={`${styles['variable-input-row']} ${styles['full-width']}`}>
                <label>Message *</label>
                <textarea
                  value={ttsText}
                  onChange={e => setTtsText(e.target.value)}
                  placeholder="Type text to convert to speech..."
                  rows={2}
                  style={{ flex: 1, padding: '8px 10px', fontSize: '13px', border: '1px solid var(--border, #e9e9e7)', borderRadius: '6px', resize: 'vertical', fontFamily: 'inherit' }}
                  autoFocus
                />
              </div>
              <div className={styles['variable-input-row']}>
                <label>Language</label>
                <Select ariaLabel="Voice language" value={ttsLanguage}
                  onChange={v => handleTTSLanguageChange(v)}
                  options={ttsLanguageOptions} />
              </div>
              <div className={styles['variable-input-row']}>
                <label>Voice</label>
                <Select ariaLabel="Voice" value={ttsVoiceId}
                  onChange={v => handleTTSVoiceChange(v)}
                  options={ttsVoiceOptions} />
              </div>
            </div>
          </div>
          <div className={styles['variable-dialog-actions']}>
            <button className={styles['cancel-btn']} onClick={() => setShowTTSPanel(false)}>Cancel</button>
            <button className={styles['send-template-btn']} onClick={handleSendTTS} disabled={!ttsText.trim() || ttsSending}>
              {ttsSending ? 'Sending...' : 'Send'}
            </button>
          </div>
        </div>
      )}

      {/* Variables Dropdown */}
      {showVariables && (
        <div className={styles['dropdown-panel']}>
          <div className={styles['dropdown-header']}>
            <span>⊕ Variables</span>
            <button onClick={() => setShowVariables(false)}>×</button>
          </div>
          <div className={styles['dropdown-list']}>
            {VARIABLES.map((variable) => (
              <button key={variable.key} className={styles['dropdown-item']} onClick={() => insertVariable(variable)}>
                <span className={styles['variable-icon']}>{variable.icon}</span>
                <span>{variable.key}</span>
                <span className={styles['variable-label']}>{variable.label}</span>
              </button>
            ))}
          </div>
          <div className={styles['dropdown-hint']}>
            Variables are replaced when sending templates
          </div>
        </div>
      )}

      {/* Formatting Dropdown */}
      {showFormatting && channel === 'whatsapp' && (
        <div className={styles['dropdown-panel']}>
          <div className={styles['dropdown-header']}>
            <span>◈ Formatting</span>
            <button onClick={() => setShowFormatting(false)}>×</button>
          </div>
          <div className={styles['dropdown-list']}>
            <button className={styles['dropdown-item']} onClick={() => wrapSelection('*', '*')}>
              <span className={styles['format-icon']}><strong>B</strong></span>
              <span>Bold</span>
              <span className={styles['format-hint']}>*text*</span>
            </button>
            <button className={styles['dropdown-item']} onClick={() => wrapSelection('_', '_')}>
              <span className={styles['format-icon']}><em>I</em></span>
              <span>Italic</span>
              <span className={styles['format-hint']}>_text_</span>
            </button>
            <button className={styles['dropdown-item']} onClick={() => wrapSelection('~', '~')}>
              <span className={styles['format-icon']}><s>S</s></span>
              <span>Strikethrough</span>
              <span className={styles['format-hint']}>~text~</span>
            </button>
            <button className={styles['dropdown-item']} onClick={() => wrapSelection('```', '```')}>
              <span className={styles['format-icon']}>{'<>'}</span>
              <span>Monospace</span>
              <span className={styles['format-hint']}>```text```</span>
            </button>
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className={styles['editor-toolbar']}>
        {/* Templates Button (WhatsApp only) */}
        {channel === 'whatsapp' && (
          <button
            type="button"
            className={`${styles['toolbar-btn']} ${showTemplates ? styles['active'] : ''}`}
            onClick={() => { setShowTemplates(!showTemplates); setShowVariables(false); setShowFormatting(false); setShowPaymentDialog(false); setShowTTSPanel(false); }}
            title="Templates (can send outside 24h window)"
          >
            <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="#1a3a2a" viewBox="0 0 16 16"><path d="M3 4.5h10a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2m0 1a1 1 0 0 0-1 1v3a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3a1 1 0 0 0-1-1zM1 2a.5.5 0 0 1 .5-.5h13a.5.5 0 0 1 0 1h-13A.5.5 0 0 1 1 2m0 12a.5.5 0 0 1 .5-.5h13a.5.5 0 0 1 0 1h-13A.5.5 0 0 1 1 14"/></svg>
          </button>
        )}

        {/* Payment Button (WhatsApp only) */}
        {channel === 'whatsapp' && selectedContactId && (
          <button
            type="button"
            className={`${styles['toolbar-btn']} ${showPaymentDialog ? styles['active'] : ''}`}
            onClick={() => { 
              if (!showPaymentDialog) {
                // Auto-generate reference ID and use currently selected WABA phone
                setPaymentForm(prev => ({
                  ...prev, 
                  referenceId: generateReferenceId(),
                  phoneNumberId: phoneNumberId || PAYMENT_CONFIG.phoneNumberId,
                }));
              }
              setShowPaymentDialog(!showPaymentDialog); 
              setShowTemplates(false); 
              setShowVariables(false); 
              setShowFormatting(false); 
              setShowTTSPanel(false);
            }}
            title="Send Payment Request (UPI)"
          >
            <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="#1a3a2a" viewBox="0 0 16 16"><path d="M11 5.5a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-2a.5.5 0 0 1-.5-.5z"/><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zm13 2v5H1V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1m-1 9H2a1 1 0 0 1-1-1v-1h14v1a1 1 0 0 1-1 1"/></svg>
          </button>
        )}

        {/* Variables Button */}
        <button
          type="button"
          className={`${styles['toolbar-btn']} ${showVariables ? styles['active'] : ''} ${hasVariables ? styles['has-vars'] : ''}`}
          onClick={() => { setShowVariables(!showVariables); setShowTemplates(false); setShowFormatting(false); setShowPaymentDialog(false); setShowTTSPanel(false); }}
          title="Insert Variable"
        >
          <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="none" stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" viewBox="0 0 24 24"><path d="M5 4C2.5 9 2.5 14 5 20M19 4c2.5 5 2.5 10 0 16M9 9h1c1 0 1 1 2.016 3.527C13 15 13 16 14 16h1"/><path d="M8 16c1.5 0 3-2 4-3.5S14.5 9 16 9"/></svg>
        </button>

        {/* Formatting Button (WhatsApp only) */}
        {channel === 'whatsapp' && (
          <button
            type="button"
            className={`${styles['toolbar-btn']} ${showFormatting ? styles['active'] : ''}`}
            onClick={() => { setShowFormatting(!showFormatting); setShowTemplates(false); setShowVariables(false); setShowPaymentDialog(false); setShowTTSPanel(false); }}
            title="Formatting"
          >
            <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M4 7c0-.932 0-1.398.152-1.765a2 2 0 0 1 1.083-1.083C5.602 4 6.068 4 7 4h10c.932 0 1.398 0 1.765.152a2 2 0 0 1 1.083 1.083C20 5.602 20 6.068 20 7M9 20h6M12 4v16"/></svg>
          </button>
        )}

        {/* Attachment Button */}
        {channel === 'whatsapp' && (
          <button
            type="button"
            className={styles['toolbar-btn']}
            onClick={() => {
              if (onAttachClick) {
                // Use parent's file input
                onAttachClick();
              } else {
                // Fallback: create temporary file input
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = 'image/*,video/*,audio/*,.pdf,.doc,.docx';
                input.onchange = (e) => {
                  const file = (e.target as HTMLInputElement).files?.[0];
                  if (file) {
                    insertAtCursor(`[Attachment: ${file.name}]`);
                  }
                };
                input.click();
              }
            }}
            title="Attach File"
          >
            <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M21 15v1.2c0 1.68 0 2.52-.327 3.162a3 3 0 0 1-1.311 1.311C18.72 21 17.88 21 16.2 21H7.8c-1.68 0-2.52 0-3.162-.327a3 3 0 0 1-1.311-1.311C3 18.72 3 17.88 3 16.2V15m14-7-5-5m0 0L7 8m5-5v12"/></svg>
          </button>
        )}

        {/* TTS Button (WhatsApp only) */}
        {channel === 'whatsapp' && onSendTTS && (
          <button
            type="button"
            className={`${styles['toolbar-btn']} ${showTTSPanel ? styles['active'] : ''}`}
            onClick={() => { setShowTTSPanel(!showTTSPanel); setShowTemplates(false); setShowVariables(false); setShowFormatting(false); setShowPaymentDialog(false); }}
            title="Text-to-Speech (Polly)"
          >
            <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M19 10v2a7 7 0 0 1-7 7m-7-9v2a7 7 0 0 0 7 7m0 0v3m-4 0h8m-4-7a3 3 0 0 1-3-3V5a3 3 0 1 1 6 0v7a3 3 0 0 1-3 3"/></svg>
          </button>
        )}

        {/* Emoji Button (WhatsApp only) */}
        {channel === 'whatsapp' && onEmojiClick && (
          <button
            type="button"
            className={`${styles['toolbar-btn']} ${emojiActive ? styles['active'] : ''}`}
            onClick={onEmojiClick}
            title="Emoji"
          >
            <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M15 9h.01M9 9h.01M22 12c0 5.523-4.477 10-10 10S2 17.523 2 12 6.477 2 12 2s10 4.477 10 10m-6.5-3a.5.5 0 1 1-1 0 .5.5 0 0 1 1 0m-6 0a.5.5 0 1 1-1 0 .5.5 0 0 1 1 0m2.5 8.5c2.5 0 4.5-1.833 4.5-3.5h-9c0 1.667 2 3.5 4.5 3.5"/></svg>
          </button>
        )}

        {/* Interactive List Button (WhatsApp only) */}
        {channel === 'whatsapp' && onInteractiveClick && (
          <button
            type="button"
            className={`${styles['toolbar-btn']} ${interactiveActive ? styles['active'] : ''}`}
            onClick={onInteractiveClick}
            title="Interactive Message (List / Buttons)"
          >
            <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M21 12H9m12-6H9m12 12H9m-4-6a1 1 0 1 1-2 0 1 1 0 0 1 2 0m0-6a1 1 0 1 1-2 0 1 1 0 0 1 2 0m0 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0"/></svg>
          </button>
        )}

        {/* Location Request Button (WhatsApp only) */}
        {channel === 'whatsapp' && onLocationClick && (
          <button
            type="button"
            className={styles['toolbar-btn']}
            onClick={onLocationClick}
            title="Request Location"
          >
            <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M11.5 5h.434c3.048 0 4.571 0 5.15.547a2 2 0 0 1 .586 1.845c-.156.781-1.4 1.66-3.888 3.42l-4.064 2.876c-2.488 1.76-3.732 2.639-3.888 3.42a2 2 0 0 0 .586 1.845c.579.547 2.102.547 5.15.547h.934M8 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0m14 14a3 3 0 1 1-6 0 3 3 0 0 1 6 0"/></svg>
          </button>
        )}

        {/* AI Button */}
        {showAISuggestions && (
          <button
            type="button"
            className={`${styles['toolbar-btn']} ${styles['ai-btn']} ${aiError ? styles['error'] : ''}`}
            onClick={fetchAISuggestions}
            disabled={loadingAI}
            title={aiError || "Suggest a rewrite"}
          >
            {loadingAI ? '...' : <svg width="16" height="16" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path stroke="#1a3a2a" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M13 2 4.093 12.688c-.348.418-.523.628-.525.804a.5.5 0 0 0 .185.397c.138.111.41.111.955.111H12l-1 8 8.907-10.688c.348-.418.523-.628.525-.804a.5.5 0 0 0-.185-.397c-.138-.111-.41-.111-.955-.111H12z"/></svg>}
          </button>
        )}

        <div className={styles['toolbar-spacer']} />

        {/* Character Count */}
        {showCharCount && (
          <span className={`${styles['char-counter']} ${isOverLimit ? styles['over-limit'] : ''}`}>
            {charCount}{maxLength ? `/${maxLength}` : ''}
          </span>
        )}

        {/* Variable indicator */}
        {hasVariables && (
          <span className={styles['var-indicator']} title="Contains variables">
            ⊕ {(value.match(/\{\{\d+\}\}/g) || []).length}
          </span>
        )}
      </div>

      {/* Text Input */}
      <div className={styles['editor-input-wrapper']}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          className={`${styles['editor-textarea']} ${isOverLimit ? styles['over-limit'] : ''}`}
          rows={1}
        />
        {onSend && (
          <button
            type="button"
            className={styles['send-btn']}
            onClick={onSend}
            disabled={disabled || !value.trim() || isOverLimit}
            title="Send (Enter)"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        )}
      </div>

      {/* Help hint */}
      <div className={styles['editor-hint']}>
        {channel === 'whatsapp' && (
          <span>Enter to send · Shift+Enter for new line · *bold* _italic_ ~strike~</span>
        )}
        {channel === 'sms' && (
          <span>SMS: 160 chars = 1 segment · Enter to send</span>
        )}
        {channel === 'email' && (
          <span>Enter to send · Shift+Enter for new line</span>
        )}
      </div>
    </div>
  );
};

export default RichTextEditor;
