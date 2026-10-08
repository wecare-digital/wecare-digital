/**
 * Pay Link - Payment Link Generator
 * Generate shareable payment links for any channel
 */

import React, { useState, useEffect } from 'react';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import Button from '../../../../components/ui/Button';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { PAYMENT_DETAILS } from '../../../../config/constants';

/*
 * BATCH 2f - how long a payment link stays payable. `expiryDays` is a NUMBER, so the option
 * values are the same numbers as strings and `parseInt` does the conversion the native handler
 * already did. Same five choices, same order, same visible text.
 */
const EXPIRY_OPTIONS: SelectOption[] = [
  { value: '1', label: '1 Day' },
  { value: '3', label: '3 Days' },
  { value: '7', label: '7 Days' },
  { value: '15', label: '15 Days' },
  { value: '30', label: '30 Days' },
];

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

const PayLinkPage: React.FC<PageProps> = ({ signOut, user, embedded }) => {
  const [referenceId, setReferenceId] = useState('');
  const [amount, setAmount] = useState<number>(0);
  const [description, setDescription] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [customerEmail, setCustomerEmail] = useState('');
  const [customerPhone, setCustomerPhone] = useState('');
  const [expiryDays, setExpiryDays] = useState<number>(7);
  const [generatedLink, setGeneratedLink] = useState('');
  const [copied, setCopied] = useState(false);

  const [generating, setGenerating] = useState(false);

  const handleGenerateReferenceId = () => {
    // WD-PAY = WECARE.DIGITAL Payment
    const uuid = crypto.randomUUID().replace(/-/g, '').substring(0, 8).toUpperCase();
    setReferenceId(`WD-PAY-${uuid}`);
  };

  useEffect(() => {
    handleGenerateReferenceId();
  }, []);

  const generatePaymentLink = async () => {
    if (amount <= 0) return;
    setGenerating(true);
    try {
      // Build a UPI deep link as the primary payment method
      // Format: upi://pay?pa=<VPA>&pn=<Name>&am=<Amount>&cu=INR&tn=<Note>&tr=<RefId>
      // The payee comes from PAYMENT_DETAILS so it tracks the live WECAREUPI
      // configuration. It used to be a hardcoded @kotak address that no longer
      // matches Meta - a wrong payee here does not fail, it collects elsewhere.
      const upiVpa = PAYMENT_DETAILS.upiVpa;
      const note = encodeURIComponent(description || `Payment ${referenceId}`);
      const payeeName = encodeURIComponent('WECARE.DIGITAL');
      const upiLink = `upi://pay?pa=${upiVpa}&pn=${payeeName}&am=${amount.toFixed(2)}&cu=INR&tn=${note}&tr=${referenceId}`;

      // Share the existing UPI deep link directly; no unimplemented web wrapper.
      setGeneratedLink(upiLink);
    } catch (err) {
      console.error('Link generation error:', err);
    } finally {
      setGenerating(false);
    }
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(generatedLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const content = (
    <>
      <div className="pay-link-page">
        <PageHeader 
          title="Pay Link" 
          subtitle="Generate shareable payment links for any channel"
          icon="link"
        />

        <div className="coming-soon-banner">
          <div className="banner-icon">[ ]</div>
          <div className="banner-content">
            <h3>Coming Soon</h3>
            <p>Payment Link generation via Razorpay API is under development</p>
          </div>
        </div>

        <div className="page-layout">
          <div className="link-form">
            <div className="form-section">
              <h3>Reference ID</h3>
              <div className="ref-row">
                <input type="text" value={referenceId} readOnly />
                <Button variant="secondary" size="sm" onClick={handleGenerateReferenceId}>New</Button>
              </div>
            </div>

            <div className="form-section">
              <h3>Payment Details</h3>
              <div className="form-grid">
                <div className="form-field">
                  <label>Amount (₹) *</label>
                  <input
                    type="number"
                    value={amount || ''}
                    onChange={(e) => setAmount(parseFloat(e.target.value) || 0)}
                    placeholder="0.00"
                    min="1"
                    step="0.01"
                  />
                </div>
                <div className="form-field">
                  {/* The `.form-field` caption is an unassociated label - no `for`, no wrapped
                      control - so it stays and the control takes ariaLabel. `parseInt` is the
                      same call the native handler made on the same string. */}
                  <label>Expiry (Days)</label>
                  <Select
                    ariaLabel="Expiry in days"
                    value={String(expiryDays)}
                    onChange={(v) => setExpiryDays(parseInt(v))}
                    options={EXPIRY_OPTIONS}
                  />
                </div>
                <div className="form-field full-width">
                  <label>Description</label>
                  <input
                    type="text"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Payment for services"
                  />
                </div>
              </div>
            </div>

            <div className="form-section">
              <h3>Customer Details (Optional)</h3>
              <div className="form-grid">
                <div className="form-field">
                  <label>Name</label>
                  <input
                    type="text"
                    value={customerName}
                    onChange={(e) => setCustomerName(e.target.value)}
                    placeholder="Customer Name"
                  />
                </div>
                <div className="form-field">
                  <label>Phone</label>
                  <input
                    type="tel"
                    value={customerPhone}
                    onChange={(e) => setCustomerPhone(e.target.value)}
                    placeholder="+91 XXXXX XXXXX"
                  />
                </div>
                <div className="form-field full-width">
                  <label>Email</label>
                  <input
                    type="email"
                    value={customerEmail}
                    onChange={(e) => setCustomerEmail(e.target.value)}
                    placeholder="customer@email.com"
                  />
                </div>
              </div>
            </div>

            <Button
              variant="primary"
              className="generate-btn"
              onClick={generatePaymentLink}
              disabled={amount <= 0 || generating}
            >
              {generating ? 'Generating...' : 'Generate Payment Link'}
            </Button>
          </div>

          <div className="link-preview">
            <h3>Generated Link</h3>
            <div className="preview-card">
              {generatedLink ? (
                <>
                  <div className="link-display">
                    <input type="text" value={generatedLink} readOnly />
                    <Button variant="secondary" size="sm" onClick={copyToClipboard}>
                      {copied ? 'Copied' : 'Copy'}
                    </Button>
                  </div>
                  <div className="link-details">
                    <div className="detail-row"><span>Amount:</span><span>₹{amount.toFixed(2)}</span></div>
                    <div className="detail-row"><span>Reference:</span><span>{referenceId}</span></div>
                    <div className="detail-row"><span>Expires:</span><span>{expiryDays} days</span></div>
                    {description && <div className="detail-row"><span>Description:</span><span>{description}</span></div>}
                  </div>
                  <div className="share-buttons">
                    <Button variant="secondary" size="sm" className="share-btn">WhatsApp</Button>
                    <Button variant="secondary" size="sm" className="share-btn">Email</Button>
                    <Button variant="secondary" size="sm" className="share-btn">SMS</Button>
                  </div>
                </>
              ) : (
                <div className="empty-state">
                  <div className="empty-icon">--</div>
                  <p>Enter payment details and click Generate to create a payment link</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        .pay-link-page { padding: 20px; max-width: 1100px; margin: 0 auto; }
        .page-header { margin-bottom: 20px; }
        .page-header h1 { font-size: 22px; margin: 0 0 4px 0; }
        .page-header p { color: #4a4a4a; margin: 0; font-size: 14px; }
        
        .coming-soon-banner { display: flex; align-items: center; gap: 16px; background: #f9fafb; padding: 16px 20px; border-radius: 13px; margin-bottom: 20px; border: 1.5px solid #1a3a2a; }
        .banner-icon { font-size: 24px; color: #1a3a2a; }
        .banner-content h3 { margin: 0 0 4px 0; font-size: 16px; color: #1a1a1a; }
        .banner-content p { margin: 0; font-size: 13px; color: #4a4a4a; }
        
        .page-layout { display: grid; grid-template-columns: 1fr 400px; gap: 20px; }
        
        .link-form { background: #fff; border-radius: 13px; padding: 20px; border: 1px solid #e5e5e5; }
        .form-section { margin-bottom: 24px; }
        .form-section h3 { font-size: 14px; margin: 0 0 12px 0; color: #000; font-weight: 600; }
        
        .ref-row { display: flex; gap: 8px; }
        .ref-row input { flex: 1; padding: 10px 12px; border: 1.5px solid #1a3a2a; border-radius: 13px; font-size: 14px; background: #fff; }
        .ref-row input:hover { background: #f9fafb; }
        
        .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .form-field { }
        .form-field.full-width { grid-column: span 2; }
        .form-field label { display: block; font-size: 12px; color: #4a4a4a; margin-bottom: 4px; }
        .form-field input, .form-field select { width: 100%; padding: 10px 12px; border: 1.5px solid #1a3a2a; border-radius: 13px; font-size: 14px; box-sizing: border-box; background: #fff; }
        .form-field input:hover, .form-field select:hover { background: #f9fafb; }
        .form-field input:focus, .form-field select:focus { outline: none; box-shadow: 0 0 0 3px rgba(26, 58, 42, 0.15); background: #fff; }
        
        .generate-btn { width: 100%; }
        
        .link-preview h3 { font-size: 14px; margin: 0 0 10px 0; font-weight: 600; }
        .preview-card { background: #fff; border-radius: 13px; padding: 20px; border: 1.5px solid #1a3a2a; }
        
        .link-display { display: flex; gap: 8px; margin-bottom: 16px; }
        .link-display input { flex: 1; padding: 10px 12px; border: 1.5px solid #1a3a2a; border-radius: 13px; font-size: 14px; background: #f5f5f5; }
        
        .link-details { padding: 12px; background: #f9fafb; border-radius: 10px; margin-bottom: 16px; }
        .detail-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
        .detail-row span:first-child { color: #4a4a4a; }
        .detail-row span:last-child { font-weight: 500; color: #1a1a1a; }
        
        .share-buttons { display: flex; gap: 8px; }
        .share-btn { flex: 1; }
        
        .empty-state { text-align: center; padding: 40px 20px; color: #4a4a4a; }
        .empty-icon { font-size: 24px; margin-bottom: 12px; opacity: 0.5; }
        .empty-state p { margin: 0; font-size: 13px; }
        
        @media (max-width: 800px) {
          .page-layout { grid-template-columns: 1fr; }
          .form-grid { grid-template-columns: 1fr; }
          .form-field.full-width { grid-column: span 1; }
          .share-buttons { flex-direction: column; }
          .share-btn { width: 100%; }
          .link-display { flex-direction: column; }
          .link-display input { width: 100%; }
          .coming-soon-banner { flex-direction: column; text-align: center; }
        }
        @media (max-width: 480px) {
          .pay-link-page { padding: 12px; }
          .link-form { padding: 14px; }
          .ref-row { flex-direction: column; }
        }
      `}</style>
    </>
  );

  if (embedded) return content;

  return (
    <Layout user={user} onSignOut={signOut}>
      {content}
    </Layout>
  );
};

export default PayLinkPage;
